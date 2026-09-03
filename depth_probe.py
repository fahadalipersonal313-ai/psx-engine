"""depth_probe.py — READ-ONLY: does PSX publish market depth without a login?

The engine's one measured lead indicator is CMF, which is a crude, after-the-fact
proxy for buying pressure. A real order book is the direct, pre-trade version of
that signal — but only worth building if it is PUBLIC. An authenticated broker
terminal is out: CLAUDE.md's rule is public PSX endpoints and public RSS only.

Writes nothing, parses nothing into the engine. Must run on a runner — the
sandbox has no egress and cannot reach dps.psx.com.pk at all.

Paths below are GUESSES. That is the entire point: the historical High/Low
endpoint was found this way, and the one time markup was assumed instead of
observed it produced the reverted Mettis date bug.
"""
import sys, re, json, requests, config, ssl_compat

TIMEOUT, SNIP = 25, 500
HDRS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"),
        "Referer": "https://dps.psx.com.pk/",
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "X-Requested-With": "XMLHttpRequest"}
# Words that would appear on a real depth table but not on a plain quote page.
DEPTH_WORDS = ("bid", "ask", "offer", "depth", "orderbook", "order book",
               "buy qty", "sell qty", "quantity", "orders")


def look(name, url, method="GET", **kw):
    print(f"\n=== {name} ===\n{method} {url}")
    try:
        r = (requests.post if method == "POST" else requests.get)(
            url, timeout=TIMEOUT, headers=HDRS, **kw)
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        return
    print(f"  HTTP {r.status_code} | {r.headers.get('Content-Type','?')} | {len(r.content)} bytes")
    if r.status_code != 200:
        print(f"  body: {r.text[:160]!r}")
        return
    low = r.text.lower()
    found = [w for w in DEPTH_WORDS if w in low]
    print(f"  depth words present: {found}")
    rows = len(re.findall(r"<tr\b", r.text, re.I))
    if rows:
        print(f"  <tr> rows: {rows}")
    try:
        print(f"  JSON: {json.dumps(r.json())[:SNIP]}")
    except Exception:
        # Show any table that mentions bid/ask, not the page head.
        m = re.search(r"<table[^>]*>.{0,%d}" % SNIP, r.text, re.S | re.I)
        print(f"  table: {m.group(0)[:SNIP]!r}" if m else f"  head: {r.text[:200]!r}")


def main():
    ssl_compat.enable()
    sym = (sys.argv[1] if len(sys.argv) > 1 else "NRL").upper()
    b = config.PSX_DPS_BASE
    print(f"Probing for a PUBLIC order book / market depth ({sym}). Nothing is written.")
    for path in (f"/orderbook/{sym}", f"/depth/{sym}", f"/market-depth/{sym}",
                 f"/timeseries/depth/{sym}", f"/quote/{sym}", f"/marketwatch/{sym}"):
        look(f"DPS {path}", b + path)
    # Known-good pages: does either already CARRY depth we simply never parsed?
    look("DPS company page (known 200 — scan for depth)", config.PSX_COMPANY_URL.format(symbol=sym))
    look("DPS market watch", b + "/market-watch")
    look("PSX main site depth", f"https://www.psx.com.pk/market-summary/")
    print("\n---\nA hit = HTTP 200 whose 'depth words' include bid AND ask, with rows.\n"
          "Paste the winning snippet back before any parser is written.")


if __name__ == "__main__":
    main()
