"""Print exactly what the mkt_summary download returns -- bytes, not guesses."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests, config
for day in sys.argv[1:] or ["2026-09-29", "2026-09-23"]:
    url = f"https://dps.psx.com.pk/download/mkt_summary/{day}.Z"
    r = requests.get(url, headers=config.REQUEST_HEADERS, timeout=30)
    raw = r.content
    print(f"=== {day}: {r.status_code} | ct={r.headers.get('content-type')} | "
          f"ce={r.headers.get('content-encoding')} | {len(raw)} bytes")
    print("first bytes:", raw[:8])
    print("counts: \\n", raw.count(b"\n"), " \\r", raw.count(b"\r"), " |", raw.count(b"|"))
    print("repr head:", repr(raw[:700]))
    print("repr tail:", repr(raw[-300:]))
