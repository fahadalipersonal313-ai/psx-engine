"""Small first-paint cache for the Streamlit dashboard.

The SQLite database remains authoritative history. This snapshot contains only
the latest completed run per tracked symbol so a reboot does not need to open
and query the large DB before rendering.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
import config
import database as db

PATH = Path("dashboard_snapshot.json")

def build():
    rows = []
    for sym in config.STOCKS:
        r = db.last_run(sym)
        if r:
            import research_guard
            try:
                r["research_guard"] = research_guard.check(r)
            except Exception as exc:
                r["research_guard"] = {"valid": False, "checks": ["Research input audit failed: " + type(exc).__name__]}
            rows.append(r)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": rows,
    }
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, default=str, separators=(",", ":")), encoding="utf-8")
    tmp.replace(PATH)
    # Small read-only measurements use the same banked completed-session data.
    import research_comparisons
    comparisons=research_comparisons.build()
    measured=Path("research_comparisons.json")
    pending=measured.with_suffix(".tmp")
    pending.write_text(json.dumps(comparisons,allow_nan=False,ensure_ascii=False),encoding="utf-8")
    pending.replace(measured)
    return payload

if __name__ == "__main__":
    p = build()
    print(f"dashboard snapshot: {len(p['rows'])} symbols at {p['generated_at']}")
