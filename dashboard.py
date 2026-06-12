"""dashboard.py — Streamlit dashboard.

Run:  streamlit run dashboard.py
Shows top-10 ranking, per-stock detail, score/signal history, price & volume
charts, sentiment trend, news, and risk warnings.
"""

import os

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

import config
import database as db
import data_fetcher

st.set_page_config(page_title="PSX Shariah Engine", layout="wide")


def _require_password():
    """Gate the dashboard behind a password from Streamlit secrets / env.

    If no password is configured (local dev), the dashboard is open. On
    Streamlit Cloud, set DASHBOARD_PASSWORD in the app's Secrets to protect it.
    """
    try:
        pw = st.secrets["DASHBOARD_PASSWORD"]
    except Exception:
        pw = os.environ.get("DASHBOARD_PASSWORD")
    if not pw:
        return  # no password set -> open (local use)
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


_require_password()
db.init_db()

st.title("PSX Shariah-Compliant Analysis Engine")
st.caption("⚠ " + config.DISCLAIMER)

# ---------------- latest run table ----------------
rows = []
for sym in config.STOCKS:
    r = db.last_run(sym)
    if r:
        rows.append(r)
if not rows:
    st.warning("No runs stored yet. Run `python main.py run` first.")
    st.stop()

latest = pd.DataFrame(rows)
latest = latest.sort_values("final_score", ascending=False)

st.caption(f"🕒 Latest data: {latest['run_time'].max()}  ·  "
           f"if this looks old, reboot the app (Manage app → Reboot).")

tab_rank, tab_stock, tab_history, tab_news, tab_reports = st.tabs(
    ["🏆 Ranking", "🔍 Stock detail", "📈 History", "📰 News", "📋 Reports"])

with tab_rank:
    st.subheader(f"Latest ranking ({len(latest)} stocks)")
    cols = ["symbol", "shariah_status", "final_score", "macro_news_score",
            "sentiment_score", "technical_score", "price", "support",
            "resistance", "stop_loss", "target1", "risk_level", "signal",
            "confidence", "data_quality", "run_time"]
    st.dataframe(latest[cols], use_container_width=True, hide_index=True)
    for _, r in latest.iterrows():
        if r["risk_level"] == "High" or "weak" in str(r["data_quality"]):
            st.warning(f"{r['symbol']}: risk={r['risk_level']}, "
                       f"data={r['data_quality']} — {r['main_risk']}")

with tab_stock:
    sym = st.selectbox("Stock", config.STOCKS)
    r = db.last_run(sym)
    if r:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Signal", r["signal"], f"{r['confidence']}% conf")
        c2.metric("Final score", r["final_score"])
        c3.metric("Price", r["price"])
        c4.metric("Risk", r["risk_level"])
        st.write("**Why:**", r["main_reason"])
        st.write("**Main risk:**", r["main_risk"])
        st.write("**Shariah:**", r["shariah_status"])

    eod, meta = data_fetcher.fetch_eod(sym)
    if eod is not None:
        st.caption(f"Source: {meta['source']} (as of {meta['as_of']})")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=eod["date"], y=eod["close"], name="Close"))
        fig.add_trace(go.Scatter(x=eod["date"],
                                 y=eod["close"].ewm(span=20).mean(),
                                 name="EMA20", line=dict(dash="dot")))
        fig.add_trace(go.Scatter(x=eod["date"],
                                 y=eod["close"].ewm(span=50).mean(),
                                 name="EMA50", line=dict(dash="dash")))
        if r:
            for lvl, nm in ((r["support"], "Support"),
                            (r["resistance"], "Resistance"),
                            (r["stop_loss"], "Stop")):
                if lvl:
                    fig.add_hline(y=lvl, line_dash="dot",
                                  annotation_text=nm)
        st.plotly_chart(fig, use_container_width=True)
        vfig = go.Figure(go.Bar(x=eod["date"], y=eod["volume"], name="Volume"))
        st.plotly_chart(vfig, use_container_width=True)
    else:
        st.error(meta.get("warning", "No price data."))

with tab_history:
    sym = st.selectbox("Stock ", config.STOCKS, key="hist")
    hist = pd.DataFrame(db.run_history(sym, 300))
    if len(hist):
        hist["run_time"] = pd.to_datetime(hist["run_time"])
        st.line_chart(hist.set_index("run_time")[
            ["final_score", "technical_score", "sentiment_score",
             "macro_news_score"]])
        st.subheader("Signal history")
        st.dataframe(hist[["run_time", "signal", "confidence", "price",
                           "outcome"]], use_container_width=True,
                     hide_index=True)
        with db.conn() as c:
            srows = [dict(x) for x in c.execute(
                """SELECT run_time, score FROM sentiment_history
                   WHERE symbol=? ORDER BY run_time""", (sym,))]
        if srows:
            sdf = pd.DataFrame(srows)
            sdf["run_time"] = pd.to_datetime(sdf["run_time"])
            st.subheader("Sentiment trend")
            st.line_chart(sdf.set_index("run_time")["score"])

with tab_news:
    news = db.recent_news(72)
    for n in news[:40]:
        tag = f" `[{n['symbols']}]`" if n["symbols"] else ""
        st.markdown(f"- **{n['source']}** — {n['title']}{tag}")

with tab_reports:
    import os
    if os.path.isdir(config.REPORT_DIR):
        files = sorted(os.listdir(config.REPORT_DIR), reverse=True)[:10]
        pick = st.selectbox("Saved reports", files) if files else None
        if pick:
            with open(os.path.join(config.REPORT_DIR, pick),
                      encoding="utf-8") as f:
                st.markdown(f.read())
    else:
        st.info("No reports saved yet.")
