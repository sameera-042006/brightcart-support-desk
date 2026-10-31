import pytest

pytest.importorskip("reportlab")
import make_submission as ms  # noqa: E402


def test_builds_structure_and_pdfs(tmp_path):
    out = tmp_path / "sub"
    assert ms.main(["--out", str(out), "--name", "Test Student", "--reg", "123", "--url", "https://x.example"]) == 0
    for pdf in ("01_Problem_Statement.pdf", "02_System_Architecture.pdf", "10_Deployment_Guide.pdf"):
        assert (out / pdf).read_bytes().startswith(b"%PDF") and (out / pdf).stat().st_size > 5000
    assert (out / "11_Dockerfile").exists() and (out / "12_README.md").exists()
    assert (out / "04_MCP_Server" / "mcp_server" / "tools.py").exists()
    assert (out / "07_Test_Cases" / "test_cases.json").exists()
    txt = (out / "13_Demo_Video_or_Link.txt").read_text()
    assert "https://x.example/health" in txt


def test_env_file_and_outputs_are_never_copied(tmp_path):
    out = tmp_path / "sub"
    ms.main(["--out", str(out)])
    names = {p.name for p in out.rglob("*")}
    assert ".env" not in names and "runs" not in names and "__pycache__" not in names


def test_secret_scan_detects_keys(tmp_path):
    (tmp_path / "a.py").write_text('KEY = "AIza' + "A" * 35 + '"\n')
    (tmp_path / "b.txt").write_text("LLM_API_KEY=replace_me\nMCP_AUTH_TOKEN=\n")
    hits = ms.scan_for_secrets(tmp_path)
    assert len(hits) == 1 and hits[0][0] == "a.py"


def test_refuses_to_overwrite_foreign_folder(tmp_path):
    (tmp_path / "keep.txt").write_text("mine")
    assert ms.main(["--out", str(tmp_path)]) == 2 and (tmp_path / "keep.txt").exists()
