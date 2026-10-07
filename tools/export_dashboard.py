"""Build the psx-dashboard deployment tree from psx-engine's dashboard code.

The live app (psx-engine.streamlit.app) deploys from the separate
fahadalipersonal313-ai/psx-dashboard repository. Copying files there by hand
let it drift twice (2026-09-28 -> 10-02 it still said KMI30/v7 and crashed on
Stock detail; 10-04 it gained a research layer the engine no longer has).
This makes the copy one repeatable step:

    python tools/export_dashboard.py /path/to/psx-dashboard

Two deliberate differences from psx-engine's dashboard.py:
  * runtime_bootstrap.prepare() runs first (the deployment downloads its
    database and news files from runtime-state at start-up);
  * no password gate: public access was confirmed by the owner for this app
    (psx-dashboard commit 3c7905b).
Everything else is psx-engine's code, so the two cannot disagree.

Writes into the target working tree only; review `git diff` there before
committing. Never touches runtime data (that is downloaded, not committed).
"""
import ast
import shutil
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
TARGET_OWNED = {"runtime_bootstrap.py", "test_dashboard_public_access.py"}
TESTS = ["test_remote_cache.py", "test_remote_data.py", "test_news_desk.py",
         "test_news_review_panel.py"]
DATA = ["data_lower_price_stocks.json", "data_stock_sectors.json"]
# Retired 2026-10-07 (engine simplified to technical analysis + news review).
RETIRED = [".github/workflows/candle-research.yml", "requirements-research.txt",
           "docs/RESEARCH_CONTEXT.md", "docs/candle-research", "skills/psx-candle-research"]

SMOKE = """name: Dashboard smoke test
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09
      - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1
        with: {python-version: '3.11', cache: pip}
      - run: pip install -r requirements.txt
      - name: Compile, import every dashboard module, run the tests
        run: |
          python -m py_compile *.py
          python -c "import %(mods)s; print('dashboard imports OK')"
          python -m unittest %(tests)s -q
"""


def public_bootstrapped(src):
    """psx-engine dashboard.py -> deployment dashboard.py."""
    src = src.replace("import json\n", "import json\nimport runtime_bootstrap\nruntime_bootstrap.prepare()\n", 1)
    src = src.replace("import hmac\n", "", 1)
    for name in ("_password_configured", "_require_password"):
        start = src.index(f"\ndef {name}(") + 1
        end = src.index("\ndef ", start) + 1
        src = src[:start] + src[end:]
    call = "_require_password()\n"
    assert src.count(call) == 1, "password call site changed; update the exporter"
    src = src.replace(call, '# Public access confirmed by the owner (psx-dashboard 3c7905b).\n'
                            'if "k" in st.query_params:\n    del st.query_params["k"]\n', 1)
    for banned in ("DASHBOARD_PASSWORD", "_require_password", "hmac"):
        assert banned not in src, banned
    assert "runtime_bootstrap.prepare()" in src
    return src


def closure(root_sources, available):
    """Engine modules reachable by import from the given sources."""
    need, todo = set(), list(root_sources)
    while todo:
        tree = ast.parse(todo.pop())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            for mod in names:
                if mod in available and mod not in need:
                    need.add(mod)
                    todo.append((ENGINE / f"{mod}.py").read_text(encoding="utf-8"))
    return need


def export(target):
    target = Path(target).resolve()
    assert (target / "runtime_bootstrap.py").exists(), f"{target} is not a psx-dashboard checkout"
    dashboard = public_bootstrapped((ENGINE / "dashboard.py").read_text(encoding="utf-8"))
    available = {p.stem for p in ENGINE.glob("*.py")} - {"dashboard"}
    roots = [dashboard] + [(ENGINE / t).read_text(encoding="utf-8") for t in TESTS]
    modules = closure(roots, available)
    (target / "dashboard.py").write_text(dashboard, encoding="utf-8")
    copied = sorted(modules) + [t[:-3] for t in TESTS]
    for mod in copied:
        shutil.copy2(ENGINE / f"{mod}.py", target / f"{mod}.py")
    for name in DATA:
        shutil.copy2(ENGINE / name, target / name)
    keep = {f"{m}.py" for m in copied} | TARGET_OWNED | {"dashboard.py"}
    removed = []
    for path in sorted(target.glob("*.py")):
        if path.name not in keep:
            path.unlink()
            removed.append(path.name)
    for rel in RETIRED:
        path = target / rel
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(rel + "/")
        elif path.exists():
            path.unlink()
            removed.append(rel)
    tests = [t[:-3] for t in TESTS] + ["test_dashboard_public_access"]
    smoke = SMOKE % {"mods": ", ".join(sorted(modules | {"runtime_bootstrap"})),
                     "tests": " ".join(tests)}
    (target / ".github/workflows/smoke.yml").write_text(smoke, encoding="utf-8")
    print(f"dashboard.py + {len(copied)} modules/tests copied; removed {len(removed)}:")
    for name in removed:
        print("  -", name)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    export(sys.argv[1])
