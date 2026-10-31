from app.cost import calculate_cost


def test_cost_calculation():
    assert abs(calculate_cost(4000, 1000, 1.0, 5.0) - 0.009) < 1e-9


def test_cached_tokens_are_priced():
    assert abs(calculate_cost(0, 0, 1.0, 5.0, cached_tokens=1_000_000, cached_price=0.25) - 0.25) < 1e-9
