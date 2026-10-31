from mcp_server import tools


def test_mcp_tools_exist(client):
    names = client.list_tools()
    for t in ("search_policy", "get_order", "check_return_eligibility", "calculator", "create_escalation",
              "save_evidence"):
        assert t in names


def test_get_order_contract(client):
    o = client.get_order("ORD-1007")
    assert o.status == "delivered" and [(i.name, i.quantity) for i in o.items] == [("T-Shirt", 3), ("Jeans", 1)]
    assert client.get_order("ORD-9999").error == "not_found"
    assert client.get_order("rm -rf /").error == "invalid_order_id"


def test_eligibility_rules(client):
    e = client.check_return_eligibility
    assert e("ORD-1001").eligible and e("ORD-1001").reason_code == "within_window"
    assert not e("ORD-1002").eligible and e("ORD-1002").reason_code == "window_expired"
    assert e("ORD-1002").days_since_delivery == 77
    assert not e("ORD-1003").eligible and e("ORD-1003").reason_code == "not_delivered"
    assert not e("ORD-1004").eligible and e("ORD-1004").warranty_active
    assert e("ORD-1006").reason_code == "gift_card_non_returnable"
    assert e("ORD-1007").full_order_refund_usd == 115.50
    d = e("ORD-1008")
    assert d.eligible and d.reason_code == "damaged_item" and d.full_order_refund_usd == 96.50   # shipping refunded


def test_reference_date_is_configurable(monkeypatch):
    monkeypatch.setenv("SHOP_TODAY", "2026-12-01")           # 42 days after ORD-1001 delivery
    assert tools.check_return_eligibility("ORD-1001")["reason_code"] == "window_expired"


def test_policy_search(client):
    r = client.search_policy("standard shipping")
    assert {h.source for h in r.results} >= {"shipping_standard_a", "shipping_standard_b"}
    assert client.search_policy("student discount").results == []
    assert client.search_policy("price match amazon").results == []


def test_calculator(client):
    assert client.calculator("3*18.5")["result"] == 55.5
    for bad in ("__import__('os').system('ls')", "open('x')", "2**10000", "1/0", "a+b"):
        assert "error" in tools.calculator(bad)


def test_create_escalation_and_path_traversal(client):
    assert client.create_escalation("20261031-100000-abc123", "test", "summary")["ticket_ref"] == "ESC-ABC123"
    assert tools.create_escalation("../../etc/passwd", "x", "y")["created"] is False
    assert tools.save_evidence("../../etc/passwd", {"x": 1})["saved"] is False


def test_corpus_contains_conflict_and_injection_docs():
    assert {"shipping_standard_a", "shipping_standard_b"} <= set(tools.POLICIES)
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in tools.POLICIES["promotions_faq"]["text"]
