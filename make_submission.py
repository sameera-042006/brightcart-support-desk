#!/usr/bin/env python
"""Builds the final submission folder in the course's required structure (guide section 41).

  python make_submission.py --name "Your Name" --reg 2023000000 --course "CSE-AIML" \
        --url https://your-api.onrender.com --repo https://github.com/you/repo --zip

Run it AFTER the evaluation (python run_eval.py) so results and the cost workbook exist. It:
  * generates 01, 02 and 10 as PDFs (needs: pip install reportlab),
  * copies code, tests, data, Dockerfile and README into the numbered folders,
  * copies results/evaluation_results.csv and builds 09_Cost_Analysis.xlsx,
  * records the git commit hash and the reproducibility table,
  * scans everything for leaked API keys and ABORTS if one is found,
  * prints which of the 14 items are present and which are still missing.
Run make_report.py first (writes docs/14_Final_Report.pdf); put screenshots in screenshots/.
"""
import argparse
import datetime as dt
import hashlib
import importlib.metadata as md
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
MARKER = ".made_by_make_submission"
SKIP_DIRS = {".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache", "runs", "results", "submission",
             "node_modules", ".idea", ".vscode"}
SKIP_FILES = {".env", ".DS_Store"}
SKIP_SUFFIX = {".pyc", ".zip"}
TEXT_SUFFIX = {".py", ".md", ".txt", ".json", ".yml", ".yaml", ".html", ".csv", ".toml", ".cfg", ".ini", ".example", ""}
SECRET_PATTERNS = [
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("assigned secret", re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\b\s*[=:]\s*[\"']?[A-Za-z0-9_\-]{24,}[\"']?")),
]


def sh(cmd, cwd=ROOT):
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception:
        return ""


def ignore(_dir, names):
    return [n for n in names if n in SKIP_DIRS or n in SKIP_FILES or pathlib.Path(n).suffix in SKIP_SUFFIX
            or n == "09_Cost_Analysis.xlsx"]


def copy_into(src: pathlib.Path, dst: pathlib.Path):
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)
    return True


def scan_for_secrets(folder: pathlib.Path):
    hits = []
    for p in folder.rglob("*"):
        if not p.is_file() or p.suffix not in TEXT_SUFFIX or p.stat().st_size > 2_000_000:
            continue
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        for name, rx in SECRET_PATTERNS:
            for m in rx.finditer(text):
                hits.append((str(p.relative_to(folder)), name, m.group(0)[:6] + "..."))
    return hits


def digest(paths):
    h = hashlib.sha256()
    for p in sorted(paths):
        if p.is_file():
            h.update(p.name.encode()); h.update(p.read_bytes())
    return h.hexdigest()[:16]


def env_value(key):
    if os.getenv(key):
        return os.getenv(key)
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(errors="ignore").splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].split("#")[0].strip().strip("\"'")
    return ""


def repro_table(args, commit, dirty):
    def ver(pkg):
        try:
            return md.version(pkg)
        except md.PackageNotFoundError:
            return "not installed"
    req = ROOT / "requirements.txt"
    lock = ROOT / "requirements.lock.txt"
    return [
        ("Code", commit + ("  (UNCOMMITTED CHANGES PRESENT)" if dirty else "")),
        ("Repository", args.repo or "(add with --repo)"),
        ("Python", platform.python_version()),
        ("Dependencies", "requirements.txt" + (" and requirements.lock.txt" if lock.exists() else " (run pip freeze > requirements.lock.txt and rerun)")),
        ("LLM (exact model name)", env_value("MODEL_NAME") or "(set MODEL_NAME in .env)"),
        ("Pricing page and date checked", env_value("PRICING_DATE_CHECKED") or "(set PRICING_DATE_CHECKED in .env)"),
        ("MCP SDK version", ver("mcp")),
        ("Dataset (corpus + orders) hash", digest(list((ROOT / "data" / "documents").glob("*.txt")) + [ROOT / "data" / "sources.json", ROOT / "data" / "orders.json"])),
        ("Test cases hash", digest([ROOT / "data" / "test_cases.json"])),
        ("Deployment", f"{args.provider}; {args.url or '(add with --url)'}; checked {dt.date.today().isoformat()}"),
        ("Hardware", "None needed; model is a hosted API"),
    ]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default=""); ap.add_argument("--reg", default=""); ap.add_argument("--course", default="")
    ap.add_argument("--url", default="", help="deployed API URL"); ap.add_argument("--repo", default="", help="GitHub repository URL")
    ap.add_argument("--video", default="", help="demo video link"); ap.add_argument("--provider", default="Render (free Docker web service, single container)")
    ap.add_argument("--commit", default="", help="override the git commit hash")
    ap.add_argument("--out", default=str(ROOT / "submission")); ap.add_argument("--zip", action="store_true")
    args = ap.parse_args(argv)

    try:
        import docgen
        import reportlab  # noqa: F401
    except ImportError:
        print("reportlab is needed for the PDFs:  pip install reportlab"); return 2

    out = pathlib.Path(args.out).resolve()
    if out.exists():
        if (out / MARKER).exists():
            shutil.rmtree(out)
        elif any(out.iterdir()):
            print(f"Refusing to overwrite {out}: it was not created by this script. Choose another --out."); return 2
    out.mkdir(parents=True, exist_ok=True); (out / MARKER).write_text("generated; safe to delete\n")

    warnings = []
    commit = args.commit or sh(["git", "rev-parse", "HEAD"])
    dirty = bool(sh(["git", "status", "--porcelain"])) if commit else False
    if not commit:
        commit = "(not a git repository yet: git init, commit, then rerun)"; warnings.append("No git commit hash found.")
    elif dirty:
        warnings.append("There are uncommitted changes, so the commit hash does not describe exactly this code. Commit first.")
    if not args.url:
        warnings.append("No --url given: the deployed URL is missing from 10 and 13.")

    # numbered folders -------------------------------------------------------------------------
    copy_into(ROOT, out / "03_Source_Code")
    copy_into(ROOT / "mcp_server", out / "04_MCP_Server" / "mcp_server")
    copy_into(ROOT / "screenshots", out / "04_MCP_Server" / "screenshots")
    copy_into(ROOT / "app" / "mcp_client", out / "05_MCP_Client" / "mcp_client")
    copy_into(ROOT / "tests" / "test_mcp_contract.py", out / "05_MCP_Client" / "test_mcp_contract.py")
    for sub in ("agents", "schemas", "static"):
        copy_into(ROOT / "app" / sub, out / "06_Agent_Implementation" / "app" / sub)
    for f in ("gate.py", "orchestrator.py", "baseline.py", "llm.py", "cost.py", "logging_utils.py", "main.py"):
        copy_into(ROOT / "app" / f, out / "06_Agent_Implementation" / "app" / f)
    runs = sorted((ROOT / "runs").glob("2*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
    for r in runs:
        copy_into(r, out / "06_Agent_Implementation" / "sample_run_logs" / r.name)
    for f in ("test_cases.json", "orders.json", "sources.json"):
        copy_into(ROOT / "data" / f, out / "07_Test_Cases" / f)
    copy_into(ROOT / "data" / "documents", out / "07_Test_Cases" / "documents")
    copy_into(ROOT / "tests", out / "07_Test_Cases" / "tests")

    # results ------------------------------------------------------------------------------------
    res = ROOT / "results" / "evaluation_results.csv"
    if res.exists():
        shutil.copy2(res, out / "08_Evaluation_Results.csv")
        if (ROOT / "results" / "cost_log.csv").exists():
            subprocess.run([sys.executable, "make_cost_report.py"], cwd=ROOT, capture_output=True, timeout=120)
            x = ROOT / "09_Cost_Analysis.xlsx"
            if x.exists():
                shutil.move(str(x), out / "09_Cost_Analysis.xlsx")
    for extra in ("comparison.md", "summary.json"):
        copy_into(ROOT / "results" / extra, out / "03_Source_Code" / "results" / extra)

    # documents ----------------------------------------------------------------------------------
    meta = {"name": args.name, "reg": args.reg, "course": args.course, "date": dt.date.today().strftime("%d %B %Y")}
    docgen.problem_statement(str(out / "01_Problem_Statement.pdf"), meta)
    docgen.architecture(str(out / "02_System_Architecture.pdf"), meta)
    docgen.deployment_guide(str(out / "10_Deployment_Guide.pdf"), meta, repro_table(args, commit, dirty))
    shutil.copy2(ROOT / "Dockerfile", out / "11_Dockerfile")
    shutil.copy2(ROOT / "README.md", out / "12_README.md")
    (out / "13_Demo_Video_or_Link.txt").write_text(
        f"Project: BrightCart Support Desk (multi-agent ticket resolution with MCP)\n"
        f"Deployed URL: {args.url or '(add with --url)'}\n"
        f"Health check: {(args.url.rstrip('/') + '/health') if args.url else '(add with --url)'}\n"
        f"Demo video: {args.video or '(add a link with --video)'}\n"
        f"Repository: {args.repo or '(add with --repo)'}\n"
        f"Commit hash: {commit}\n"
        f"Deployment date: {dt.date.today().isoformat()}\n")
    report = ROOT / "docs" / "14_Final_Report.pdf"
    if report.exists():
        shutil.copy2(report, out / "14_Final_Report.pdf")

    # safety: never ship a leaked key ----------------------------------------------------------
    hits = scan_for_secrets(out)
    if hits:
        print("\nSTOPPED: possible secrets found. Remove them, revoke the key, and rerun.")
        for f, kind, snip in hits:
            print(f"  {f}: {kind} ({snip})")
        shutil.rmtree(out)
        return 3

    # checklist ----------------------------------------------------------------------------------
    items = ["01_Problem_Statement.pdf", "02_System_Architecture.pdf", "03_Source_Code", "04_MCP_Server", "05_MCP_Client",
             "06_Agent_Implementation", "07_Test_Cases", "08_Evaluation_Results.csv", "09_Cost_Analysis.xlsx",
             "10_Deployment_Guide.pdf", "11_Dockerfile", "12_README.md", "13_Demo_Video_or_Link.txt", "14_Final_Report.pdf"]
    hint = {"08_Evaluation_Results.csv": "run: python run_eval.py", "09_Cost_Analysis.xlsx": "run: python run_eval.py",
            "14_Final_Report.pdf": "run: python make_report.py (after run_eval.py)"}
    print(f"\nSubmission folder: {out}\n")
    missing = 0
    for it in items:
        ok = (out / it).exists()
        missing += not ok
        print(f"  [{'x' if ok else ' '}] {it}" + ("" if ok else f"   <- MISSING: {hint.get(it, '')}"))
    if not (out / "04_MCP_Server" / "screenshots").exists():
        warnings.append("No screenshots/ folder: add MCP Inspector / tool-call screenshots as evidence for the MCP marks.")
    if not runs:
        warnings.append("No run logs found in runs/: run a few tickets first so sample logs are included.")
    for w in warnings:
        print(f"\n  WARNING: {w}")
    if args.zip:
        z = pathlib.Path(str(out) + ".zip")
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(out.rglob("*")):
                if p.is_file() and p.name != MARKER:
                    zf.write(p, p.relative_to(out.parent))
        print(f"\nZip written: {z}")
    print(f"\n{14 - missing}/14 items present." + ("" if not missing else " Fix the missing items and rerun."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
