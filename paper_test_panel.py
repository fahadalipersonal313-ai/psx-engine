"""Trading-desk panel for the paper-trading forward test (Turn-Confirmation Theory).

Reads state/status.json from the `paper-trading` branch, written by its own
trader after every run (see docs/PAPER_TRADING.md). Display only: the test has
zero weight in the engine's signals and never places a real order. Missing or
unreadable status shows as such; nothing is filled in.
"""
from datetime import date

STATUS_FILE = "state/status.json"
BRANCH = "paper-trading"
REVIEW_AFTER = 30   # closed trades before the forward result is judged


def fetch_status(get=None):
    import remote_data
    return remote_data.fetch_json(STATUS_FILE, branch=BRANCH, ttl=300, get=get, timeout=4)


def _day(text):
    try:
        return date.fromisoformat(str(text)[:10]).strftime("%d %b %Y").lstrip("0")
    except ValueError:
        return str(text or "unknown")


def _n(x, d=0):
    return "—" if x is None else f"{x:,.{d}f}"


def summarize(status):
    """status.json -> plain-language pieces for the dashboard, or None when unavailable."""
    if not status or not status.get("last_scan"):
        return None
    scan = status["last_scan"]; g = scan.get("gates") or {}
    out = {"through": _day(status.get("official_through")), "updated": status.get("updated_pkt", "")[:16].replace("T", " ")}
    out["gate1"] = dict(
        open=bool(g.get("gate1_open")), title="Market bounce",
        value=f"{'Open' if g.get('gate1_open') else 'Closed'}",
        text=(f"KSE-100 {_n(g.get('kse100'))} is {_n(g.get('bounce_pct'), 1)}% above its 20-day low of {_n(g.get('low20'))}. "
              f"Opens at a close of {_n(g.get('gate1_level'))} or higher (3% above that low)."))
    prev = g.get("breadth_prev")
    out["gate2"] = dict(
        open=bool(g.get("gate2_open")), title="More stocks rising",
        value=f"{'Open' if g.get('gate2_open') else 'Closed'}",
        text=(f"{_n(g.get('breadth'))}% of Shariah stocks are above their 20-day average, against "
              f"{_n(prev)}% five sessions earlier ({_day(g.get('breadth_prev_date'))}). Opens when the share is higher."
              if prev is not None else "Not enough breadth history yet."))
    both = out["gate1"]["open"] and out["gate2"]["open"]
    orders = status.get("orders") or []
    out["verdict"] = (f"Both gates open: {len(orders)} paper order(s) wait for the next official open." if both else
                      "At least one gate is closed, so the paper test buys nothing. Signals are only logged.")
    kind = {"B": "52-week-high breakout", "A": "Washout bounce (research only)"}
    out["signals"] = [{"Stock": s["sym"], "List": s.get("list", ""), "Setup": kind.get(s.get("book"), s.get("book")),
                       "Close": s.get("signal_close"), "Stop": s.get("stop"),
                       "Risk %": round(100 * (1 - s["stop"] / s["signal_close"]), 1) if s.get("signal_close") else None}
                      for s in scan.get("signals") or []]
    out["orders"] = [{"Stock": o["sym"], "Setup": kind.get(o.get("book"), o.get("book")), "Signal close": o.get("signal_close"),
                      "Stop": o.get("stop"), "Won't buy above": round(o["signal_close"] + 0.3 * o["atr"], 2)}
                     for o in orders]
    out["positions"] = [{"Stock": p["sym"], "Setup": kind.get(p.get("book"), p.get("book")), "Bought": _day(p.get("entry_date")),
                         "Entry": p.get("entry"), "Stop now": p.get("stop"), "Last close": p.get("last_close"),
                         "Sessions held": p.get("days"), "Shares": p.get("shares")}
                        for p in status.get("positions") or []]
    c = status.get("closed") or {}
    n = c.get("n") or 0
    out["closed"] = ("No paper trade has closed yet." if not n else
                     f"{n} closed: total {c['total_R']:+.2f}R, profit factor {c['pf'] if c.get('pf') is not None else 'n/a'}, "
                     f"{c['win_pct']}% winners, Rs {c.get('pnl_rs', 0):+,} on Rs 1,000,000 paper capital.")
    out["closed"] += (f" The result is judged after {REVIEW_AFTER} closed trades." if n < REVIEW_AFTER else "")
    live = status.get("live") or {}
    out["live"] = (f"Live KSE-100 {_n(live.get('kse100'))} (TradingView, delayed, not official; informational)."
                   if live.get("ok") and live.get("kse100") else "")
    note = status.get("official_note") or ""
    out["problem"], out["problem_detail"] = "", ""
    if note.startswith("OFFICIAL DATA UNAVAILABLE"):
        out["problem"] = ("On its last check the paper test could not read PSX's official end-of-day file, so it changed "
                          "nothing and is waiting. The figures below are from the last session it did read.")
    elif note.startswith("HISTORY GAP"):
        out["problem"] = ("The paper test stopped because a trading session seems to be missing from its history. "
                          "It changes nothing until that is fixed.")
    if out["problem"]:
        out["problem_detail"] = note
    return out


def render(st, status, tile):
    s = summarize(status)
    st.subheader("Market turn check (paper test)")
    if s is None:
        st.caption("The paper test's status is not available right now.")
        return
    st.caption(f"Paper test only: no real orders, and it does not change the signals above. "
               f"Official PSX data through {s['through']} · checked {s['updated']} PKT.")
    if s["problem"]:
        st.warning(s["problem"])
        st.caption("Technical detail: " + s["problem_detail"])
    c1, c2 = st.columns(2)
    for col, g in ((c1, s["gate1"]), (c2, s["gate2"])):
        colour = "#22c55e" if g["open"] else "#f59e0b"
        tile(col, g["title"], f'<span style="color:{colour}">{g["value"]}</span>', g["text"])
    st.markdown(f"**{s['verdict']}**")
    if s["live"]:
        st.caption(s["live"])
    if s["signals"]:
        st.caption("Setups found at the last official close:")
        st.dataframe(s["signals"], hide_index=True, use_container_width=True)
    if s["orders"]:
        st.caption("Paper orders for the next official open:")
        st.dataframe(s["orders"], hide_index=True, use_container_width=True)
    if s["positions"]:
        st.caption("Open paper positions:")
        st.dataframe(s["positions"], hide_index=True, use_container_width=True)
    st.caption(s["closed"])
