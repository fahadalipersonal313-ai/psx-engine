"""dashboard.py — Streamlit dashboard, management-friendly "glimpse" view.

Run:  streamlit run dashboard.py

Top of page (no clicks needed): a status strip (market regime, actionable count,
data health, last updated), a "what changed since last run" line, trade-plan
cards for the actual Buys (with position sizing from your capital), and a
"high score but NOT a Buy — why" panel. Drill-down tabs below hold the full
colour-coded watchlist table, per-stock charts, history, news, and reports.
"""

import os

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

import config
import database as db
import data_fetcher

st.set_page_config(page_title="PSX Shariah Engine", layout="wide")

# ----------------------------- palette / helpers --------------------------
# Light backgrounds + dark text -> readable on BOTH light and dark themes.
SIG_STYLE = {
    "Strong Buy": ("#0a5c40", "#c2efd9"), "Buy": ("#0a5c40", "#d9f2e7"),
    "Watch": ("#7a4e00", "#fbe8c3"), "Hold": ("#444444", "#e6e6e6"),
    "Avoid": ("#962a2a", "#f7d2d2"), "Exit": ("#8a1f1f", "#f4bcbc"),
    "No data": ("#555555", "#e2e2e2"),
}
RISK_STYLE = {"Low": ("#0a5c40", "#d9f2e7"), "Medium": ("#7a4e00", "#fbe8c3"),
              "High": ("#962a2a", "#f7d2d2")}
SIG_RANK = {"Strong Buy": 6, "Buy": 5, "Watch": 4, "Hold": 3, "Avoid": 2,
            "Exit": 1, "No data": 0}


def _pill(text, fg, bg):
    return (f'<span style="background:{bg};color:{fg};padding:2px 10px;'
            f'border-radius:8px;font-size:13px;font-weight:600;'
            f'white-space:nowrap">{text}</span>')


def sig_pill(sig):
    fg, bg = SIG_STYLE.get(sig, ("#555", "#e2e2e2"))
    return _pill(sig or "—", fg, bg)


def risk_pill(level):
    fg, bg = RISK_STYLE.get(level, ("#555", "#e2e2e2"))
    return _pill(f"{level} risk", fg, bg)


def regime_pill(regime):
    if regime == "risk-on":
        return _pill("Risk-on", "#0a5c40", "#c2efd9")
    if regime == "risk-off":
        return _pill("Risk-off", "#8a1f1f", "#f4bcbc")
    return _pill("Unknown", "#555", "#e2e2e2")


def fmt(x, d=2):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"{x:,.{d}f}"


def position_size(price, stop, capital):
    """Replicates risk_manager sizing: cap loss at max_risk_per_trade_pct of
    capital, and the position at max_position_pct."""
    if not price or not stop or price <= stop or capital <= 0:
        return None
    rps = price - stop
    max_loss = capital * config.RISK["max_risk_per_trade_pct"] / 100
    shares = int(max_loss / rps)
    cap_shares = int(capital * config.RISK["max_position_pct"] / 100 / price)
    shares = max(0, min(shares, cap_shares))
    return {"shares": shares, "value": shares * price, "max_loss": shares * rps}


def why_not_buy(reason):
    """Pull the most relevant 'why it isn't a Buy' clause out of main_reason."""
    if not reason:
        return ""
    segs = [s.strip() for s in str(reason).split(";") if s.strip()]
    for kw in ("Downgraded", "breakdown", "negative news", "Shariah", "regime",
               "risk/reward", "manipulation", "confidence", "No usable price"):
        for s in segs:
            if kw.lower() in s.lower():
                return s
    return segs[-1] if segs else ""


def changes_since_last():
    """Symbols whose signal changed vs the previous run cycle."""
    ups, downs = [], []
    for s in config.STOCKS:
        h = db.run_history(s, 2)
        if len(h) >= 2 and h[0]["signal"] != h[1]["signal"]:
            cur, prev = h[0]["signal"], h[1]["signal"]
            (ups if SIG_RANK.get(cur, 0) > SIG_RANK.get(prev, 0) else downs).append(
                (s, prev, cur))
    return ups, downs


def _require_password():
    try:
        pw = st.secrets["DASHBOARD_PASSWORD"]
    except Exception:
        pw = os.environ.get("DASHBOARD_PASSWORD")
    if not pw:
        return
    if st.session_state.get("auth_ok"):
        return
    st.title("🔒 PSX Shariah Engine")
    entered = st.text_input("Enter dashboard password", type="password")
    if entered == pw:
        st.session_state["auth_ok"] = True
        st.rerun()
    elif entered:
        st.error("Incorrect password.")
    st.stop()


# ----------------------------- load ---------------------------------------
_require_password()
db.init_db()

rows = []
for sym in config.STOCKS:
    r = db.last_run(sym)
    if r:
        rows.append(r)
if not rows:
    st.title("PSX Shariah Engine")
    st.warning("No runs stored yet. Run `python main.py run` first.")
    st.stop()

latest = pd.DataFrame(rows).sort_values("final_score", ascending=False,
                                        na_position="last")
for col in ("relative_strength", "market_regime"):
    if col not in latest.columns:
        latest[col] = None

regime = (latest["market_regime"].dropna().iloc[0]
          if latest["market_regime"].notna().any() else "unknown")
last_updated = str(latest["run_time"].max())[:16]
buys = latest[latest["signal"].isin(["Strong Buy", "Buy"])]
exits = latest[latest["signal"] == "Exit"]
good = int((latest["data_quality"] == "good").sum())

# ----------------------------- sidebar ------------------------------------
st.sidebar.header("Settings")
capital = st.sidebar.number_input("Your capital (PKR)", min_value=0,
                                  value=1_000_000, step=50_000, format="%d")
st.sidebar.caption(
    f"Position sizing risks {config.RISK['max_risk_per_trade_pct']}% of capital "
    f"per trade, max {config.RISK['max_position_pct']}% in one stock.")
st.sidebar.caption("Tip: set this to what you'd actually deploy — the Buy cards "
                   "size each position to it.")

# ----------------------------- header + status strip ----------------------
st.title("PSX Shariah Engine — Today")
st.caption("⚠ " + config.DISCLAIMER)


def tile(col, label, value_html, sub=""):
    with col:
        box = st.container(border=True)
        box.markdown(
            f'<div style="font-size:12px;opacity:.65">{label}</div>'
            f'<div style="font-size:20px;font-weight:700;margin:3px 0">{value_html}</div>'
            f'<div style="font-size:12px;opacity:.6">{sub}</div>',
            unsafe_allow_html=True)


t1, t2, t3, t4, t5 = st.columns(5)
tile(t1, "Market regime", regime_pill(regime),
     f"benchmark {config.BENCHMARK_INDEX}")
tile(t2, "Actionable now", f"{len(buys)} buys",
     f"{len(exits)} exits" if len(exits) else "no exits")
top = buys.iloc[0]["symbol"] if not buys.empty else "—"
tile(t3, "Top pick", top,
     f"score {buys.iloc[0]['final_score']:.0f}" if not buys.empty else "no buys")
tile(t4, "Data health", f"{good} / {len(latest)}",
     "stocks with good data")
tile(t5, "Last updated", last_updated[5:], "reboot app if stale")

# ----------------------------- what changed -------------------------------
ups, downs = changes_since_last()
if ups or downs:
    parts = []
    for s, p, c in ups:
        parts.append(f"🔼 **{s}** {p}→{c}")
    for s, p, c in downs:
        parts.append(f"🔽 **{s}** {p}→{c}")
    st.markdown("**Since last run:** " + " · ".join(parts))
else:
    st.caption("No signal changes since the last run.")

st.divider()

# ----------------------------- ACTION TODAY -------------------------------
st.subheader("🎯 Action today")
action = latest[latest["signal"].isin(["Strong Buy", "Buy", "Exit"])]
if action.empty:
    st.info(f"No Buy or Exit signals right now — nothing to act on. "
            f"(Market regime: {regime}.)")
else:
    st.caption("Manual confirmation required before any order. Position sizes "
               f"use your capital (PKR {capital:,}).")
    cards = list(action.iterrows())
    for i in range(0, len(cards), 2):
        cols = st.columns(2)
        for col, (_, r) in zip(cols, cards[i:i + 2]):
            with col:
                box = st.container(border=True)
                sec = config.SECTORS.get(r["symbol"], "")
                box.markdown(
                    f'<div style="display:flex;justify-content:space-between;'
                    f'align-items:center">'
                    f'<div><span style="font-size:20px;font-weight:700">'
                    f'{r["symbol"]}</span> '
                    f'<span style="opacity:.6;font-size:13px">{sec}</span></div>'
                    f'{sig_pill(r["signal"])}</div>', unsafe_allow_html=True)
                a, b, c = box.columns(3)
                a.metric("Entry", fmt(r["price"]))
                b.metric("Stop", fmt(r["stop_loss"]))
                c.metric("Target", fmt(r["target1"]))
                ps = position_size(r["price"], r["stop_loss"], capital)
                if ps and ps["shares"] > 0:
                    box.markdown(
                        f'🧮 Buy **{ps["shares"]:,} shares** · ≈PKR '
                        f'{ps["value"]:,.0f} · max loss if stopped **PKR '
                        f'{ps["max_loss"]:,.0f}**')
                rs = r.get("relative_strength")
                rs_txt = f"RS {rs:.0f}" if pd.notna(rs) else "RS —"
                box.markdown(
                    f'{risk_pill(r["risk_level"])} &nbsp; '
                    f'<span style="opacity:.75;font-size:13px">conf '
                    f'{fmt(r["confidence"], 0)}% · {rs_txt} · '
                    f'R:R {fmt((r["target1"] - r["price"]) / (r["price"] - r["stop_loss"]), 1) if r["price"] and r["stop_loss"] and r["price"] > r["stop_loss"] else "—"}</span>',
                    unsafe_allow_html=True)
                box.caption(str(r["main_reason"])[:240])

# ----------------------------- WHY NOT A BUY ------------------------------
why = latest[(latest["final_score"] >= config.SIGNAL_THRESHOLDS["buy"]) &
             (~latest["signal"].isin(["Strong Buy", "Buy"]))]
if not why.empty:
    st.subheader("⚠ High score, but NOT a Buy — here's why")
    st.caption("These scored in Buy range but a safety rule held them back. "
               "No need to dig — the reason is shown.")
    for _, r in why.iterrows():
        st.markdown(
            f'{sig_pill(r["signal"])} &nbsp;**{r["symbol"]}** '
            f'(score {r["final_score"]:.0f}) — '
            f'<span style="opacity:.8">{why_not_buy(r["main_reason"])}</span>',
            unsafe_allow_html=True)

st.divider()

# ----------------------------- tabs (drill-down) --------------------------
tab_watch, tab_stock, tab_hist, tab_news, tab_reports = st.tabs(
    ["📋 Watchlist", "🔍 Stock detail", "📈 History", "📰 News", "📋 Reports"])

with tab_watch:
    st.caption("Full ranking — colour-coded. Sort by clicking a column header.")
    show = latest[["symbol", "final_score", "relative_strength", "signal",
                   "risk_level", "confidence", "price", "stop_loss", "target1",
                   "data_quality", "shariah_status"]].copy()
    show.columns = ["Symbol", "Score", "RS", "Signal", "Risk", "Conf%",
                    "Price", "Stop", "Target", "Data", "Shariah"]

    def _sig_css(v):
        fg, bg = SIG_STYLE.get(v, ("inherit", "transparent"))
        return f"background-color:{bg};color:{fg};font-weight:600"

    def _risk_css(v):
        fg, bg = RISK_STYLE.get(v, ("inherit", "transparent"))
        return f"background-color:{bg};color:{fg};font-weight:600"

    styled = (show.style
              .map(_sig_css, subset=["Signal"])
              .map(_risk_css, subset=["Risk"])
              .format({"Score": "{:.1f}", "RS": "{:.0f}", "Conf%": "{:.0f}",
                       "Price": "{:.2f}", "Stop": "{:.2f}", "Target": "{:.2f}"},
                      na_rep="—"))
    st.dataframe(styled, width="stretch", hide_index=True, height=560)

with tab_stock:
    sym = st.selectbox("Stock", config.STOCKS)
    r = db.last_run(sym)
    if r:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Signal", r["signal"], f"{fmt(r['confidence'], 0)}% conf")
        c2.metric("Final score", fmt(r["final_score"], 1))
        c3.metric("Rel. strength", fmt(r.get("relative_strength"), 0))
        c4.metric("Price", fmt(r["price"]))
        c5.metric("Risk", r["risk_level"])
        st.write("**Why:**", r["main_reason"])
        st.write("**Main risk:**", r["main_risk"])
        st.write("**Shariah:**", r["shariah_status"], " · **Market regime:**",
                 r.get("market_regime") or "—")

    eod, meta = data_fetcher.fetch_eod(sym)
    if eod is not None:
        st.caption(f"Source: {meta['source']} (as of {meta['as_of']})")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=eod["date"], y=eod["close"], name="Close"))
        fig.add_trace(go.Scatter(x=eod["date"], y=eod["close"].ewm(span=20).mean(),
                                 name="EMA20", line=dict(dash="dot")))
        fig.add_trace(go.Scatter(x=eod["date"], y=eod["close"].ewm(span=50).mean(),
                                 name="EMA50", line=dict(dash="dash")))
        if r:
            for lvl, nm in ((r["support"], "Support"), (r["resistance"], "Resistance"),
                            (r["stop_loss"], "Stop")):
                if lvl:
                    fig.add_hline(y=lvl, line_dash="dot", annotation_text=nm)
        st.plotly_chart(fig, width="stretch")
        st.plotly_chart(go.Figure(go.Bar(x=eod["date"], y=eod["volume"],
                                          name="Volume")), width="stretch")
    else:
        st.error(meta.get("warning", "No price data."))

with tab_hist:
    sym = st.selectbox("Stock ", config.STOCKS, key="hist")
    hist = pd.DataFrame(db.run_history(sym, 300))
    if len(hist):
        hist["run_time"] = pd.to_datetime(hist["run_time"])
        cols = [c for c in ["final_score", "technical_score", "relative_strength"]
                if c in hist.columns]
        st.line_chart(hist.set_index("run_time")[cols])
        st.subheader("Signal history")
        st.dataframe(hist[["run_time", "signal", "confidence", "price", "outcome"]],
                     width="stretch", hide_index=True)

with tab_news:
    for n in db.recent_news(72)[:40]:
        tag = f" `[{n['symbols']}]`" if n["symbols"] else ""
        st.markdown(f"- **{n['source']}** — {n['title']}{tag}")

with tab_reports:
    if os.path.isdir(config.REPORT_DIR):
        files = sorted(os.listdir(config.REPORT_DIR), reverse=True)[:10]
        pick = st.selectbox("Saved reports", files) if files else None
        if pick:
            with open(os.path.join(config.REPORT_DIR, pick), encoding="utf-8") as f:
                st.markdown(f.read())
    else:
        st.info("No reports saved yet.")
