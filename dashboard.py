"""dashboard.py — Streamlit dashboard, management-friendly "glimpse" view with a
neon dark theme.

Run:  streamlit run dashboard.py

Top of page (no clicks needed): a status strip (market regime, actionable count,
data health, last updated), a "what changed since last run" line, trade-plan
cards for the actual Buys, and a "high score but NOT a Buy — why" panel. The
book/cash tracking was removed 2026-08-18 at the user's request — they manage
position sizing themselves. Drill-down tabs below hold the full colour-coded
watchlist, the strategy Edge backtest (expectancy / profit
factor / max drawdown / out-of-sample, Tier 2 #8), per-stock charts, history,
news, and reports.
"""

import os
import json
import hmac
import time

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

import config
import database as db
import data_fetcher
import backtester
import news_feed
import momentum
import target_timing

st.set_page_config(page_title="PSX Shariah Engine", layout="wide",
                   page_icon="📈")

# ====================== NEON THEME ========================================
NEON = {"cyan": "#00e5ff", "violet": "#a855f7", "green": "#00ffa3",
        "amber": "#ffd54a", "red": "#ff4d6d", "text": "#e7f0ff",
        "dim": "#9fb3d1"}

# Signal / risk accent colours (neon, high-contrast on the dark background).
NEON_SIG = {"Strong Buy": "#00ffa3", "Buy": "#3ae67f", "Watch": "#ffd54a",
            "Hold": "#9fb3d1", "Avoid": "#ff5d7a", "Exit": "#ff4d6d",
            "No data": "#8aa0c0"}
NEON_RISK = {"Low": "#00ffa3", "Medium": "#ffd54a", "High": "#ff4d6d"}
SIG_RANK = {"Strong Buy": 6, "Buy": 5, "Watch": 4, "Hold": 3, "Avoid": 2,
            "Exit": 1, "No data": 0}
PLOT_LINE = ["#00e5ff", "#a855f7", "#00ffa3", "#ffd54a", "#ff4d6d"]


def _inject_theme():
    st.markdown(
        """
        <style>
        .stApp {
          background:
            radial-gradient(1100px 560px at 10% -12%, rgba(0,229,255,0.13), transparent 60%),
            radial-gradient(1000px 520px at 102% -4%, rgba(168,85,247,0.15), transparent 55%),
            radial-gradient(900px 520px at 50% 118%, rgba(0,255,163,0.10), transparent 55%),
            linear-gradient(180deg,#070b16 0%, #0a1020 48%, #070b16 100%);
          background-attachment: fixed;
        }
        [data-testid="stHeader"] { background: transparent; }
        [data-testid="stToolbar"] { right: 1rem; }
        h1, h2, h3 { color: #eaf6ff !important; letter-spacing:.3px; }
        h1 { text-shadow: 0 0 22px rgba(0,229,255,0.35); }
        h2 { text-shadow: 0 0 16px rgba(0,229,255,0.20); }
        hr { border-color: rgba(0,229,255,0.15) !important; }
        /* glassmorphic bordered containers (tiles, cards) */
        [data-testid="stVerticalBlockBorderWrapper"] {
          background: rgba(16,24,44,0.55);
          border: 1px solid rgba(0,229,255,0.18) !important;
          border-radius: 14px !important;
          box-shadow: 0 8px 30px rgba(0,0,0,0.45), inset 0 0 0 1px rgba(0,229,255,0.03);
          backdrop-filter: blur(7px);
          transition: border-color .2s ease, box-shadow .2s ease;
        }
        [data-testid="stVerticalBlockBorderWrapper"]:hover {
          border-color: rgba(0,229,255,0.40) !important;
          box-shadow: 0 10px 36px rgba(0,0,0,0.5), 0 0 22px -6px rgba(0,229,255,0.5);
        }
        [data-testid="stMetricValue"] {
          color: #00e5ff; text-shadow: 0 0 14px rgba(0,229,255,0.45);
          font-weight: 800;
        }
        [data-testid="stMetricLabel"] { color: #9fb3d1; }
        [data-testid="stMetricDelta"] { color: #00ffa3; }
        /* sidebar */
        [data-testid="stSidebar"] {
          background: linear-gradient(180deg, rgba(11,17,34,0.92), rgba(7,11,22,0.96));
          border-right: 1px solid rgba(0,229,255,0.14);
        }
        /* tabs */
        [data-baseweb="tab-list"] { gap: 6px; border-bottom: 1px solid rgba(0,229,255,0.12); }
        [data-baseweb="tab"] {
          background: rgba(255,255,255,0.03); border-radius: 10px 10px 0 0;
          padding: 7px 15px; color: #cfe0ff;
        }
        [aria-selected="true"][data-baseweb="tab"] {
          background: rgba(0,229,255,0.13);
          box-shadow: inset 0 -2px 0 #00e5ff, 0 0 18px -6px rgba(0,229,255,0.7);
          color: #eaf6ff;
        }
        /* buttons */
        .stButton > button {
          background: linear-gradient(90deg, #00e5ff, #a855f7);
          color: #06101f; font-weight: 700; border: none; border-radius: 10px;
          box-shadow: 0 0 18px -4px rgba(0,229,255,0.6);
        }
        .stButton > button:hover { filter: brightness(1.12); color:#06101f; }
        /* inputs */
        [data-testid="stNumberInput"] input, [data-baseweb="select"] > div {
          background: rgba(10,16,32,0.7) !important;
          border-color: rgba(0,229,255,0.25) !important;
        }
        </style>
        """,
        unsafe_allow_html=True)


# ----------------------------- pills / helpers ----------------------------
def _hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _pill(text, hexc):
    r, g, b = _hex_rgb(hexc)
    return (f'<span style="background:rgba({r},{g},{b},0.13);color:{hexc};'
            f'border:1px solid rgba({r},{g},{b},0.55);border-radius:9px;'
            f'padding:2px 10px;font-size:13px;font-weight:700;white-space:nowrap;'
            f'text-shadow:0 0 7px rgba({r},{g},{b},0.45);'
            f'box-shadow:0 0 12px -3px rgba({r},{g},{b},0.7)">{text}</span>')


def sig_pill(sig):
    return _pill(sig or "—", NEON_SIG.get(sig, "#8aa0c0"))


def risk_pill(level):
    return _pill(f"{level} risk", NEON_RISK.get(level, "#8aa0c0"))


def news_pill(verdict):
    """Compact news verdict chip. verdict is the dict from news_feed.get(sym)."""
    if not verdict:
        return _pill("📰 no fresh news", "#8aa0c0")
    score = verdict.get("score", 50)
    delta = score - 50  # symmetric around neutral
    direction = verdict.get("direction", "neutral")
    mat = verdict.get("materiality", "normal")
    if direction == "positive":
        clr = NEON["green"]
        arrow = "▲"
    elif direction == "negative":
        clr = NEON["red"]
        arrow = "▼"
    else:
        clr = "#8aa0c0"
        arrow = "●"
    star = " ★" if mat in ("material_positive", "material_negative") else ""
    return _pill(f"📰 {arrow} {delta:+d}{star}", clr)


def _news_window(symbol, nv=None):
    """UNSCORED per-symbol news window for manual cross-verification. Shows the
    auto-fetched last-24h headlines (news_raw_24h.json, refreshed by news.yml on
    a cron — no manual routine). News carries ZERO score weight; this is purely
    so the user can eyeball real, source-linked headlines. Falls back to the
    LLM-judged summary only if it happens to exist."""
    items = news_feed.raw_headlines(symbol, limit=5)
    st.markdown("**📰 News — last 24h (not scored; for your manual check)**")
    if items:
        for it in items:
            pub = it.get("publisher") or "source"
            url, title = it.get("url"), it["title"]
            st.markdown(f"- [{title}]({url}) · _{pub}_" if url
                        else f"- {title} · _{pub}_")
    elif nv and nv.get("summary"):
        st.markdown(f"_{nv['summary']}_")
        for h, u in zip(nv.get("headlines", []), nv.get("sources", [])):
            st.markdown(f"- [{h}]({u})")
    else:
        st.caption("No allowlisted headlines fetched for this symbol in the last "
                   "24h. News never moves the score — this window is informational.")


_GLM_STYLE = {
    "highly_positive": (NEON["green"], "▲▲ highly +ve"),
    "positive":        (NEON["green"], "▲ +ve"),
    "neutral":         ("#8aa0c0",     "● neutral"),
    "negative":        (NEON["red"],   "▼ -ve"),
    "highly_negative": (NEON["red"],   "▼▼ highly -ve"),
}


# Causality is the tag that decides whether news is tradeable at all: only a
# "causal" item has a traceable mechanism to that company's cash flows.
_CAUSAL_STYLE = {"causal": (NEON["cyan"], "⛓ causal"),
                 "correlated": ("#8aa0c0", "≈ correlated"),
                 "noise": ("#8aa0c0", "· noise")}
_HORIZON_LABEL = {"single_session": "1-session", "multi_session": "multi-day",
                  "long_term": "long-term"}


def glm_pill(rating_dict):
    """Compact AI news-rating chip. rating_dict is news_feed.glm_rating(sym)."""
    if not rating_dict:
        return _pill("🤖 AI: —", "#8aa0c0")
    clr, label = _GLM_STYLE.get(rating_dict.get("rating"), ("#8aa0c0", "AI: ?"))
    return _pill(f"🤖 {label}", clr)


def analysis_pills(rating_dict):
    """Causality / horizon / confidence chips. Empty string for the old
    rating shape, so pre-Phase-3 files keep rendering unchanged."""
    if not rating_dict:
        return ""
    bits = []
    cz = rating_dict.get("causality")
    if cz in _CAUSAL_STYLE:
        c, lbl = _CAUSAL_STYLE[cz]
        bits.append(_pill(lbl, c))
    hz = rating_dict.get("horizon")
    if hz in _HORIZON_LABEL:
        bits.append(_pill(_HORIZON_LABEL[hz], "#8aa0c0"))
    conf = rating_dict.get("confidence")
    if isinstance(conf, (int, float)):
        bits.append(_pill(f"conf {conf:.0%}", "#8aa0c0"))
    return " ".join(bits)


_RATING_TEXT = {"highly_positive": "▲▲ highly +ve", "positive": "▲ +ve",
                "neutral": "● neutral", "negative": "▼ -ve",
                "highly_negative": "▼▼ highly -ve"}
_CAUSAL_TEXT = {"causal": "⛓", "correlated": "≈", "noise": "·"}


def news_cell(symbol):
    """Plain-text news read for a dataframe column: rating + causality mark.

    Tables cannot carry HTML, so the pills are compressed to text. "—" means no
    rating for this symbol, which is NOT the same as neutral news — it means the
    analyser had nothing in window to judge.
    """
    rv = news_feed.glm_rating(symbol)
    tag = ""
    if not rv:
        # Fall back to the SECTOR call, which moves this symbol's score just as
        # a company call does. Without it a card shows "—" beside a score that
        # visibly moved. Marked (sec) so it is never read as company news.
        rv, tag = news_feed.sector_rating(symbol), " (sec)"
    if not rv:
        return "—"
    txt = _RATING_TEXT.get(rv.get("rating"), "?")
    mark = _CAUSAL_TEXT.get(rv.get("causality"))
    return f"{txt} {mark}{tag}" if mark else f"{txt}{tag}"


def news_line(symbol, reason=True):
    """Pills + one-clause reason for a symbol, as an HTML fragment. Returns the
    'no rating' pill rather than nothing, so a card never looks as though news
    was checked and came back clean when it was simply never rated."""
    rv = news_feed.glm_rating(symbol)
    prefix = ""
    if not rv:
        rv = news_feed.sector_rating(symbol)
        if rv:
            prefix = _pill(f"🏷 sector: {config.SECTORS.get(symbol.upper())}",
                           "#8aa0c0") + " "
    out = prefix + glm_pill(rv) + (" " + analysis_pills(rv) if rv else "")
    if reason and rv and rv.get("reason"):
        out += (f' <span style="opacity:.75;font-size:12px">'
                f'{str(rv["reason"])[:140]}</span>')
    return out


def whatif_regime_note(actual_regime, assumed_regime, signal):
    """One-line label explaining what the signal WOULD be under an assumed
    regime. Approximation, not a re-run: risk-off soft-downgrades Buy→Watch
    per signal_generator; risk-on relaxes the chase guard and lets some
    regime-downgraded Watches surface as Buys. Actual regime → no note."""
    if not assumed_regime or assumed_regime == actual_regime:
        return ""
    if assumed_regime == "risk-off" and signal in ("Buy", "Strong Buy"):
        return ("🌩 Under **risk-off**: signal would soft-downgrade to Watch "
                "(regime gate) — position size accordingly.")
    if assumed_regime == "risk-on" and signal in ("Buy", "Strong Buy"):
        return "☀ Under **risk-on**: signal holds; chase guard also loosens."
    if assumed_regime == "risk-on" and signal == "Watch":
        return ("☀ Under **risk-on**: if this Watch was regime-downgraded, "
                "it would revert to Buy (check main_reason).")
    return ""


def regime_pill(regime):
    if regime == "risk-on":
        return _pill("● Rising", NEON["green"])
    if regime == "risk-off":
        return _pill("● Falling", NEON["red"])
    return _pill("● Unknown", "#8aa0c0")


def fmt(x, d=2):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    if isinstance(x, float) and x == float("inf"):
        return "∞"
    return f"{x:,.{d}f}"


def price_row(pairs):
    """Entry/Stop/Target strip as plain markdown. NOT st.metric: that widget
    lives in a lazily-imported JS chunk, and a browser holding a cached page
    shell from an earlier Cloud build 404s it ("Importing a module script
    failed") — hiding the three numbers that matter most on a trade card."""
    cells = "".join(
        f'<div style="flex:1;min-width:72px">'
        f'<div style="opacity:.55;font-size:11px;letter-spacing:.4px;'
        f'text-transform:uppercase">{label}</div>'
        f'<div style="font-size:19px;font-weight:700;color:{color}">{value}</div>'
        f'</div>'
        for label, value, color in pairs)
    return (f'<div style="display:flex;gap:10px;margin:8px 0 10px">{cells}</div>')


def neon_fig(fig, height=None):
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(color="#cfe0ff"),
                      margin=dict(l=10, r=10, t=34, b=10),
                      legend=dict(bgcolor="rgba(0,0,0,0)",
                                  bordercolor="rgba(0,229,255,0.15)"))
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.06)", zeroline=False)
    fig.update_yaxes(gridcolor="rgba(255,255,255,0.06)", zeroline=False)
    if height:
        fig.update_layout(height=height)
    return fig


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


# ----------------------------- cached backtests ---------------------------
# fetch_eod hits the network with no cache, so backtests are expensive. Cache
# hard and only run the universe-wide one behind a button.
@st.cache_data(ttl=3600, show_spinner=False)
def bt_symbol(sym, data_version=None):
    return backtester.backtest(sym)


@st.cache_data(ttl=3600, show_spinner=False)
def bt_portfolio(data_version=None):
    return backtester.backtest_portfolio()


def _password_configured():
    try:
        pw = st.secrets["DASHBOARD_PASSWORD"]
    except Exception:
        pw = os.environ.get("DASHBOARD_PASSWORD")
    return pw


def _auto_refresh():
    """Refresh the page; authentication remains in the server session only."""
    secs = int(getattr(config, "DASHBOARD_REFRESH_SECONDS", 300))
    if secs <= 0:
        return
    st.markdown(
        f"<script>setTimeout(function(){{window.parent.location.reload();}},"
        f" {secs * 1000});</script>",
        unsafe_allow_html=True)


def _require_password():
    pw = _password_configured()
    if not pw:
        st.error("Configure DASHBOARD_PASSWORD to access this dashboard.")
        st.stop()
    if 'k' in st.query_params:
        del st.query_params['k']
    if st.session_state.get('auth_until', 0) > time.time():
        return
    st.title("🔒 PSX Shariah Engine")
    entered = st.text_input("Enter dashboard password", type="password")
    if entered and hmac.compare_digest(str(entered), str(pw)):
        st.session_state["auth_until"] = time.time() + 3600
        st.rerun()
    elif entered:
        st.error("Incorrect password.")
    st.stop()


def _inject_compact_css():
    st.markdown(
        """
        <style>
        [data-testid="stVerticalBlockBorderWrapper"] { padding: 2px !important; }
        [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stMarkdownContainer"] p {
          margin-bottom: 2px;
        }
        [data-testid="stMetricValue"] { font-size: 1rem !important; }
        [data-testid="stMetricLabel"] { font-size: 0.72rem !important; }
        h2 { font-size: 1.05rem !important; margin-top: 0.3rem !important; }
        h3, .stMarkdown h3 { font-size: 0.95rem !important; }
        [data-testid="stCaptionContainer"] { font-size: 0.72rem !important; }
        .block-container { padding-top: 1.2rem !important; padding-bottom: 1rem !important; }
        [data-testid="column"] { gap: 0.3rem !important; }
        </style>
        """,
        unsafe_allow_html=True)


# ----------------------------- load ---------------------------------------
_inject_theme()
_require_password()
_auto_refresh()
db.init_db()

rows = []
for sym in config.STOCKS:
    r = db.last_run(sym)
    if r:
        from history_view import explain_run
        r = dict(r)
        r['main_reason'], r['main_risk'] = explain_run(r)
        rows.append(r)
if not rows:
    st.title("PSX Shariah Engine")
    st.warning("No runs stored yet. Run `python main.py run` first.")
    st.stop()

latest = pd.DataFrame(rows).sort_values("final_score", ascending=False,
                                        na_position="last")
for col in ("relative_strength", "market_regime", "buy_zone_low", "buy_zone_high"):
    if col not in latest.columns:
        latest[col] = None

latest_by_symbol = {r["symbol"]: r for r in rows}

regime = (latest["market_regime"].dropna().iloc[0]
          if latest["market_regime"].notna().any() else "unknown")
# run_time is written by the engine as a naive local timestamp, and the cloud
# runs set TZ=Asia/Karachi, so it is already Pakistan wall-clock (PKT, a fixed
# UTC+5 with no DST). Show it as-is and measure age against PKT now — do NOT
# add another +5h (that double-shifted the time and made age go negative).
_latest_pkt = pd.to_datetime(latest["run_time"].max())
_latest_pkt = _latest_pkt.tz_localize("Asia/Karachi") if _latest_pkt.tzinfo is None else _latest_pkt.tz_convert("Asia/Karachi")
last_updated = _latest_pkt.strftime("%m-%d %H:%M") + " PKT"
# Honest staleness flag: the cloud may pause runs (off-hours, weekends, paused
# Action) — in that case signals here describe yesterday's market, not today's.
# Compare against PKT now so the age matches the stored PKT run_time.
_now_pkt = pd.Timestamp.now(tz="Asia/Karachi")
_age_hours = (_now_pkt - _latest_pkt).total_seconds() / 3600
_amber = getattr(config, "DATA_FRESHNESS_AMBER_HOURS", 4)
_red = getattr(config, "DATA_FRESHNESS_RED_HOURS", 24)
if _age_hours >= _red:
    _stale_level, _stale_color, _stale_label = "red", NEON["red"], "STALE"
elif _age_hours >= _amber:
    _stale_level, _stale_color, _stale_label = "amber", NEON["amber"], "aging"
else:
    _stale_level, _stale_color, _stale_label = "fresh", NEON["green"], "fresh"
_last_updated_html = (f'<span style="color:{_stale_color}">{last_updated}</span>'
                      f' <span style="font-size:11px;opacity:.7">'
                      f'({_stale_label}, {_age_hours:.1f}h old)</span>')
good = int((latest["data_quality"] == "good").sum())

# ----------------------------- sidebar ------------------------------------
st.sidebar.header("⚙ Settings")
compact = st.sidebar.toggle("📱 Compact view", value=st.session_state.get("compact", False),
                            help="Denser layout — smaller tiles, fewer clicks, "
                                 "collapsible secondary sections. Good for phones.")
st.session_state["compact"] = compact
if compact:
    _inject_compact_css()
st.sidebar.caption(
    f"Per-trade risk {config.RISK['max_risk_per_trade_pct']}% · max "
    f"{config.RISK['max_position_pct']}% per stock.")
st.sidebar.caption(news_feed.glm_status_line())

# ----------------------------- header + status strip ----------------------
st.title("📈 PSX Shariah Engine — Today")
st.caption("⚠ " + config.DISCLAIMER)
_news_wt = int((config.WEIGHTS.get("sentiment", 0)
                + config.WEIGHTS.get("macro_news", 0)) * 100)
if _news_wt == 0:
    st.caption(f"📰 {news_feed.raw_status_line()} News carries **0% weight** — "
               "headlines are shown per stock for manual cross-verification only, "
               "never moved into the score.")
else:
    st.caption(f"📰 {news_feed.status_line()} News carries {_news_wt}% of the "
               "final score.")


def tile(col, label, value_html, sub=""):
    with col:
        box = st.container(border=True)
        box.markdown(
            f'<div style="font-size:12px;opacity:.65">{label}</div>'
            f'<div style="font-size:20px;font-weight:700;margin:3px 0">{value_html}</div>'
            f'<div style="font-size:12px;opacity:.6">{sub}</div>',
            unsafe_allow_html=True)


# Regime what-if — on the MAIN page (was buried in the sidebar), sitting right
# above the Market-regime tile it drives. Purely a DISPLAY overlay; it never
# re-runs the engine or mutates stored signals.
assumed_regime = None   # what-if control removed; overlay logic below unchanged


# Under an assumed risk-on regime, reverse ONLY the risk-off regime gate: a Watch
# whose reason cites that exact gate was a technical Buy the engine downgraded for
# regime alone, so it surfaces as a Buy. The phrase match is exact, so confluence/
# chase/earnings/rr downgrades are never touched. Buy, never Strong Buy (pre-gate
# tier unknown — take the conservative one).
def _display_signal(sig, reason):
    return sig


latest["display_signal"] = [
    _display_signal(s, mr)
    for s, mr in zip(latest["signal"], latest["main_reason"])]
_whatif_active = bool((latest["display_signal"] != latest["signal"]).any())
buys = latest[latest["display_signal"].isin(["Strong Buy", "Buy"])]
exits = latest[latest["display_signal"] == "Exit"]

st.markdown(
    f'<div style="display:flex;gap:20px;align-items:center;font-size:13px;'
    f'opacity:.8;margin:2px 0 10px">{regime_pill(regime)}'
    f'<span><b>{len(buys)}</b> buys · <b>{len(exits)}</b> exits</span>'
    f'<span>updated {_last_updated_html}</span></div>',
    unsafe_allow_html=True)

# Staleness banner — louder than the tile, only shown when data is past amber.
if _stale_level != "fresh":
    if _stale_level == "red":
        st.error(f"⚠ Data is **{_age_hours:.1f} hours old** (over "
                 f"{_red}h threshold). Signals below reflect the LAST RUN, not "
                 "current market action. Re-run the engine before acting.")
    else:
        st.warning(f"⏳ Data is **{_age_hours:.1f} hours old** — past the {_amber}h "
                   "freshness threshold. Verify quotes manually before acting.")

# ----------------------------- news read (compact) -------------------------
# The per-card pills only render on Buy/Strong Buy cards, and in a risk-off
# market there are none -- so the Claude routine's ratings were invisible
# exactly when the reader most wanted a second opinion. This is the compact
# always-on version: one line per rated symbol, no headline list.
#
# ZERO SCORE WEIGHT, and that is enforced upstream rather than promised here:
# config.WEIGHTS has sentiment and macro_news at 0.0, so a rating cannot move a
# signal. It is shown for manual cross-verification only.
_nr, _nmeta = news_feed.load_glm_ratings()
if _nr and _nmeta.get("status") == "ok":
    st.markdown(f"### 📰 News read — {len(_nr)} symbols")
    st.caption(
        f"From the Claude routine ({_nmeta.get('provider','?')}), "
        f"{_nmeta.get('age_hours', 0):.0f}h old. **Zero score weight** — a rating "
        "never moves a signal. Causal means the story plausibly drives the price; "
        "correlated means it merely coincides. Confidence is the rater's own.")
    _order = {"highly_positive": 0, "positive": 1, "neutral": 2,
              "negative": 3, "highly_negative": 4}
    for _sym in sorted(_nr, key=lambda x: (_order.get(_nr[x].get("rating"), 9), x)):
        _rv = _nr[_sym]
        _why = (_rv.get("reason") or "")[:150]
        # A running story, not a fresh one: some news develops over months, so
        # say how many EARLIER reads this symbol has and what followed the last
        # graded one. Silent when there is no prior read -- a first sighting
        # must never be dressed up as a continuing story.
        _run = ""
        try:
            import news_memory
            _prior = [h for h in news_memory.history_for(_sym, limit=24)
                      if str(h["as_of"]) != str(_nmeta.get("as_of"))]
            if _prior:
                _since = str(_prior[-1]["as_of"])[:10]
                _run = (f' <span style="opacity:.65">· running story: '
                        f'{len(_prior)} earlier read(s) since {_since}')
                _g = next((h for h in _prior if h["outcome_5d"] is not None), None)
                if _g:
                    _run += (f", last graded {str(_g['as_of'])[:10]} "
                             f"{_g['outcome_5d']:+.1f}% vs market at 5d")
                _run += "</span>"
        except Exception:
            _run = ""
        st.markdown(
            f'<div style="margin:2px 0;font-size:13px">'
            f'<b>{_sym}</b> {glm_pill(_rv)} {analysis_pills(_rv)} '
            f'<span style="opacity:.7">{_why}</span>{_run}</div>',
            unsafe_allow_html=True)
    st.divider()
elif _nmeta.get("status") != "ok":
    st.caption(f"📰 News read unavailable ({_nmeta.get('status')}) — "
               "no rating is shown rather than an old one.")

# --------------------------- momentum burst (top) --------------------------
# Highest-placed panel by request. A burst is one session breaking out of the
# stock's own norm: >=3% on >=1.5x its 20-day volume. Measured before it was
# built — 83% beat at 3d (n=42), 71% at 7d (n=35), independence OK on both.
# A WATCH tier, never a Buy: findings get surfaced, not wired into the score.
try:
    _bursts = momentum.scan()
except Exception:
    _bursts = []
if _bursts:
    # Date the panel by the DATA, not the clock. daily_ohlc holds only COMPLETED
    # sessions — the engine banks the cutoff session's bars and nothing intraday
    # — so momentum.detect reads the last completed session all day. Labelling
    # that "today" made a two-day-old burst read as live.
    _bdate = max((b.get("date") or "") for b in _bursts)
    st.markdown(f"### ⚡ Momentum burst — {len(_bursts)} on {_bdate}")
    _sess = momentum.session_fraction()
    # Provisional is a property of the BARS, not of the wall clock: session_fraction
    # is <1.0 before the open as well as during the session, so keying the "market
    # open" banner off the clock printed "Market open, 0% traded" at 01:00.
    _live = any(b.get("provisional") for b in _bursts)
    _outside = [b["symbol"] for b in _bursts if not b.get("in_measured_cohort", True)]
    _cap = (f"One session ≥{momentum.MIN_GAIN_PCT:g}% on ≥{momentum.MIN_VOL_MULT:g}× "
            f"its {momentum.LOOKBACK}-day average volume, min PKR "
            f"{momentum.MIN_TURNOVER/1e6:.0f}M daily turnover. **Watch tier, not a Buy.**")
    if _outside:
        # Never print the beat rates beside a name the measurement never saw.
        _cap += (f" &nbsp;·&nbsp; ⚠ {', '.join(_outside)} "
                 f"{'is' if len(_outside) == 1 else 'are'} outside the measured "
                 "cohort — no track record for these yet.")
    else:
        _cap += (" &nbsp;·&nbsp; Measured on the original 50 stocks: beat the market "
                 "80% at 3d (n=66), 72% at 7d (n=53).")
    if _live:
        _cap += (f" &nbsp;·&nbsp; ⏳ Live session, {_sess * 100:.0f}% of typical "
                 "volume traded — can still fade.")
    st.caption(_cap)
    _bcols = st.columns(min(len(_bursts), 4))
    for _i, _b in enumerate(_bursts):
        with _bcols[_i % len(_bcols)]:
            _bb = st.container(border=True)
            _bb.markdown(
                f'<div style="display:flex;justify-content:space-between;'
                f'align-items:center"><span style="font-size:17px;font-weight:700">'
                f'{_b["symbol"]}</span>{sig_pill(_b["signal"])}</div>'
                f'<div style="font-size:22px;font-weight:800;color:{NEON["green"]}">'
                f'+{_b["gain_pct"]:.2f}%</div>'
                f'<div style="font-size:12px;opacity:.7">{_b["vol_mult"]:.1f}× volume'
                f'{" pace" if _b.get("provisional") else ""} · {fmt(_b["close"])}</div>'
                + (f'<div style="font-size:11px;color:{NEON["amber"]}">provisional · '
                   f'{_b["session_pct"]}% of session</div>'
                   if _b.get("provisional") else '')
                + f'<div style="font-size:11px;opacity:.6">{_b["sector"]}</div>'
                + (f'<div style="font-size:11px;color:{NEON["cyan"]};font-weight:700">'
                   f'20-day high</div>' if _b["at_high"] else ''),
                unsafe_allow_html=True)
    st.caption("`20-day high` is a tag, not part of the trigger: it scored higher "
               "at 3 days but its 7-day sample was 16 rows and 69% one sector.")
    st.divider()

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
import upward_candidates
st.subheader("Up to 10 stocks with a rising trend")
_upward = upward_candidates.current()
if _upward:
    st.dataframe(pd.DataFrame(_upward), hide_index=True)
else:
    st.info("No stocks currently meet all the upward-trend and momentum checks.")
st.caption("Only stocks with a rising price trend, positive momentum and buying activity qualify. Watch means wait for the Buy rules to pass. Fewer than 10 may qualify.")
if _whatif_active:
    st.info("🔀 **What-if: Assume risk-on** — the market is really risk-off, so "
            "the Buys below are technical signals the engine downgraded to Watch "
            "via the regime gate. Shown as Buys under the assumption only. "
            "Approximation, not a re-run — verify manually before acting.")
action = latest[latest["display_signal"].isin(["Strong Buy", "Buy", "Exit"])]
if action.empty:
    st.info(f"No Buy or Exit signals right now — nothing to act on. "
            f"(Market regime: {regime}.)")
elif compact:
    st.caption("Manual confirmation required before any order. Toggle off "
               "**Compact view** for full trade-plan cards.")
    act_show = action[["symbol", "display_signal", "price", "stop_loss", "target1",
                       "confidence", "relative_strength"]].copy()
    act_show["news"] = [news_cell(s) for s in action["symbol"]]
    act_show.columns = ["Symbol", "Signal", "Price", "Stop", "Target", "Quality",
                        "RS", "News"]
    st.dataframe(
        act_show.style
        .map(lambda v: f"color:{NEON_SIG.get(v, '')};font-weight:700", subset=["Signal"])
        .format({"Price": "{:.2f}", "Stop": "{:.2f}", "Target": "{:.2f}",
                 "Quality": "{:.0f}", "RS": "{:.0f}"}, na_rep="—"),
        width="stretch", hide_index=True)
else:
    st.caption("Manual confirmation required before any order. Position sizing "
               "is yours to manage.")
    cards = list(action.iterrows())
    for i in range(0, len(cards), 2):
        cols = st.columns(2)
        for col, (_, r) in zip(cols, cards[i:i + 2]):
            with col:
                box = st.container(border=True)
                disp = r["display_signal"]
                sec = config.SECTORS.get(r["symbol"], "")
                box.markdown(
                    f'<div style="display:flex;justify-content:space-between;'
                    f'align-items:center">'
                    f'<div><span style="font-size:20px;font-weight:700">'
                    f'{r["symbol"]}</span> '
                    f'<span style="opacity:.6;font-size:13px">{sec}</span></div>'
                    f'{sig_pill(disp)}</div>',
                    unsafe_allow_html=True)
                box.markdown(price_row([
                    ("Entry", fmt(r["price"]), "#e8f0ff"),
                    ("Stop", fmt(r["stop_loss"]), NEON["red"]),
                    ("Target", fmt(r["target1"]), NEON["green"]),
                ]), unsafe_allow_html=True)
                # Structure the trade sits inside. Stop and target alone do not
                # say whether the level beneath is one price has actually
                # defended, which is what decides where the stop belongs.
                _lv = [("Support", r.get("support")), ("Resistance", r.get("resistance")),
                       ("Target 2", r.get("target2"))]
                _lv = [(k, v) for k, v in _lv if pd.notna(v)]
                if _lv:
                    box.markdown(
                        '<div style="display:flex;gap:18px;margin:2px 0 4px;'
                        'font-size:12px;opacity:.72">'
                        + "".join(f'<span>{k} <b style="opacity:.95">{fmt(v)}</b></span>'
                                  for k, v in _lv)
                        + '</div>', unsafe_allow_html=True)
                # Measured, not projected. distance/ATR would read ~4 sessions
                # for a target this name historically took 12 to reach, and
                # would hide that it arrived under half the time.
                try:
                    _eta = target_timing.estimate(r["symbol"], r["price"], r["target1"])
                except Exception:
                    _eta = None
                if _eta and _eta["typical_sessions"]:
                    _hr = _eta["hit_rate"] * 100
                    _col = NEON["green"] if _hr >= 55 else (
                        NEON["amber"] if _hr >= 40 else NEON["red"])
                    box.markdown(
                        f'<div style="font-size:12px;opacity:.8;margin-bottom:2px">'
                        f'🕒 <b>~{_eta["typical_sessions"]} sessions</b> to target '
                        f'<span style="opacity:.6">({_eta["distance_pct"]:+.1f}%,'
                        f' {_eta["k_atr"]:.1f}×ATR)</span> · reached '
                        f'<b style="color:{_col}">{_hr:.0f}%</b> of the time '
                        f'<span style="opacity:.6">in {_eta["attempts"]:,} past '
                        f'attempts, {_eta["horizon"]}-session limit</span></div>',
                        unsafe_allow_html=True)
                bzl, bzh = r.get("buy_zone_low"), r.get("buy_zone_high")
                if pd.notna(bzl) and pd.notna(bzh):
                    box.markdown(
                        f'<span style="background:rgba(0,255,163,0.14);'
                        f'color:{NEON["green"]};padding:2px 8px;border-radius:6px;'
                        f'font-size:13px;font-weight:700">🎯 Buy-zone '
                        f'{bzl:.2f}–{bzh:.2f}</span> '
                        f'<span style="opacity:.6;font-size:12px">pullback to '
                        f'{config.PULLBACK_EMA_SPAN}-EMA</span>', unsafe_allow_html=True)
                rs = r.get("relative_strength")
                rs_txt = f"RS {rs:.0f}" if pd.notna(rs) else "RS —"
                box.markdown(
                    f'{risk_pill(r["risk_level"])} &nbsp; '
                    f'<span style="opacity:.75;font-size:13px">conf '
                    f'{fmt(r["confidence"], 0)}/100 quality · {rs_txt} · '
                    f'R:R {fmt((r["target1"] - r["price"]) / (r["price"] - r["stop_loss"]), 1) if r["price"] and r["stop_loss"] and r["price"] > r["stop_loss"] else "—"}'
                    f'</span>',
                    unsafe_allow_html=True)
                nv = news_feed.get(r["symbol"])
                gv = news_feed.glm_rating(r["symbol"])
                box.markdown(news_pill(nv) + " " + glm_pill(gv) + " " +
                             analysis_pills(gv) +
                             (f' <span style="opacity:.75;font-size:12px">'
                              f'{nv["summary"][:120]}</span>' if nv else ''),
                             unsafe_allow_html=True)
                if gv and gv.get("reason"):
                    box.caption(f"🤖 AI: {gv['reason']}")
                if disp != r["signal"]:
                    box.warning("🔀 What-if (assume risk-on): engine's REAL signal "
                                "is **Watch** — downgraded by the risk-off regime "
                                "gate. Verify manually before acting.")
                else:
                    _wf = whatif_regime_note(regime, assumed_regime, r["signal"])
                    if _wf:
                        box.markdown(_wf)
                box.caption(str(r["main_reason"])[:240])
                with box.expander("📋 Full detail"):
                    st.write("**Full reason:**", r["main_reason"])
                    st.write("**Main risk:**", r["main_risk"])
                    st.write("**Shariah:**", r["shariah_status"], " · "
                             "**Market regime:**", r.get("market_regime") or "—")
                    st.write("**Support / Resistance:**",
                             f"{fmt(r.get('support'))} / {fmt(r.get('resistance'))}")
                    bzl2, bzh2 = r.get("buy_zone_low"), r.get("buy_zone_high")
                    if pd.notna(bzl2) and pd.notna(bzh2):
                        st.write(f"**Buy-zone ({config.PULLBACK_EMA_SPAN}-EMA pullback):**",
                                 f"{bzl2:.2f}–{bzh2:.2f}")
                    _news_window(r["symbol"], nv)
                    st.caption("For the price/volume chart and a per-stock "
                               "backtest, open the 📈 Stock detail tab.")

def _why_not_buy_section():
    why = latest[(latest["final_score"] >= config.SIGNAL_THRESHOLDS["buy"]) &
                 (~latest["signal"].isin(["Strong Buy", "Buy"]))]
    if why.empty:
        return
    st.caption("These scored in Buy range but a safety rule held them back. "
               "No need to dig — the reason is shown.")
    for _, r in why.iterrows():
        st.markdown(
            f'{sig_pill(r["signal"])} &nbsp;**{r["symbol"]}** '
            f'(score {r["final_score"]:.0f}) — '
            f'<span style="opacity:.8">{why_not_buy(r["main_reason"])}</span>'
            f'<br>{news_line(r["symbol"])}',
            unsafe_allow_html=True)


def _early_watch_section():
    ew = latest[latest.get("early_watch").fillna(0) == 1] if "early_watch" in latest.columns \
        else latest.iloc[0:0]
    if ew.empty:
        st.caption("No early-watch names right now. This tier only fires on real "
                   "money-flow build-up (CMF) below the Buy band.")
        return
    st.caption("Lead-time tier: money flow building BEFORE the score confirms. "
               "NOT a buy signal — it exists so a move can be prepared for "
               "instead of chased. Graded on the 7-day horizon; treat as "
               "unproven until that history accumulates.")
    for _, r in ew.sort_values("cmf", ascending=False).iterrows():
        st.markdown(
            f'<span style="background:rgba(122,162,255,0.16);color:#7aa2ff;'
            f'padding:2px 8px;border-radius:6px;font-size:12px;font-weight:700">'
            f'🔭 EARLY</span> &nbsp;**{r["symbol"]}** · price {fmt(r["price"])} · '
            f'score {fmt(r["final_score"], 0)} · CMF {fmt(r.get("cmf"), 2)} · '
            f'RS {fmt(r.get("relative_strength"), 0)}'
            f'<br><span style="opacity:.75;font-size:13px">'
            f'{r.get("early_reason") or ""}</span>'
            f'<br>{news_line(r["symbol"])}',
            unsafe_allow_html=True)




# ----------------------------- tabs (drill-down) ---------------------------
# Restored on request. They sit BELOW Action today and Momentum burst, which
# stay where they are: the tabs are drill-down, not the front page.
st.divider()

(tab_watch, tab_edge, tab_stock, tab_hist,
 tab_news, tab_reports) = st.tabs(
    ["📋 Watchlist", "🧪 Past results", "🔍 Stock detail",
     "📈 History", "📰 News", "📋 Reports"])

with tab_watch:
    st.caption("Full ranking — colour-coded. Sort by clicking a column header.")
    show = latest[["symbol", "final_score", "relative_strength", "signal",
                   "risk_level", "confidence", "price", "stop_loss", "target1",
                   "buy_zone_low", "buy_zone_high",
                   "data_quality", "shariah_status"]].copy()
    show["buy_zone"] = [f"{lo:.2f}–{hi:.2f}" if pd.notna(lo) and pd.notna(hi) else "—"
                        for lo, hi in zip(show["buy_zone_low"], show["buy_zone_high"])]
    show = show.drop(columns=["buy_zone_low", "buy_zone_high"])
    show["news"] = [news_cell(s) for s in show["symbol"]]
    show.columns = ["Symbol", "Score", "Market strength", "Signal", "Risk", "Quality",
                    "Price", "Stop", "Target", "Data", "Shariah", "Buy-zone",
                    "News"]

    def _sig_css(v):
        c = NEON_SIG.get(v)
        if not c:
            return ""
        r, g, b = _hex_rgb(c)
        return f"background-color:rgba({r},{g},{b},0.16);color:{c};font-weight:700"

    def _risk_css(v):
        c = NEON_RISK.get(v)
        if not c:
            return ""
        r, g, b = _hex_rgb(c)
        return f"background-color:rgba({r},{g},{b},0.16);color:{c};font-weight:700"

    styled = (show.style
              .map(_sig_css, subset=["Signal"])
              .map(_risk_css, subset=["Risk"])
              .format({"Score": "{:.1f}", "Market strength": "{:.0f}", "Quality": "{:.0f}",
                       "Price": "{:.2f}", "Stop": "{:.2f}", "Target": "{:.2f}"},
                      na_rep="—"))
    st.dataframe(styled, width="stretch", hide_index=True, height=560)

    # The two panels the trim orphaned: their functions survived with no caller,
    # so they rendered nowhere. They belong with the full ranking rather than on
    # the front page, which is what pushed them off it.
    st.divider()
    st.subheader("⚠ High score, but NOT a Buy — here's why")
    _why_not_buy_section()
    st.divider()
    st.subheader("🔭 Early watch — building before the Buy band")
    _early_watch_section()

with tab_edge:
    st.subheader("How past Buy signals performed")
    st.caption("Checks all tracked stocks against verified daily prices. This "
               "measures software behaviour on past bars — it is not a forecast "
               "and not a profitability claim.")
    if st.button("Check past signals for all stocks"):
        with st.spinner("Checking past prices for all stocks..."):
            res = bt_portfolio(os.stat(config.DB_PATH).st_mtime_ns)
        import history_view
        history_view.show(st, res)

with tab_stock:
    sym = st.selectbox("Stock", config.STOCKS)
    r = db.last_run(sym)
    if r:
        from history_view import explain_run
        r = dict(r)
        r['main_reason'], r['main_risk'] = explain_run(r)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Signal", r["signal"], f"{fmt(r['confidence'], 0)}/100 quality")
        c2.metric("Final score", fmt(r["final_score"], 1))
        c3.metric("Strength versus market", fmt(r.get("relative_strength"), 0))
        c4.metric("Price", fmt(r["price"]))
        c5.metric("Risk", r["risk_level"])
        st.write("**Why:**", r["main_reason"])
        st.write("**Main risk:**", r["main_risk"])
        st.write("**Shariah:**", r["shariah_status"], " · **Market direction:**",
                 {'risk-on': 'Rising', 'risk-off': 'Falling'}.get(r.get("market_regime"), 'Unknown'))
        # The news read for this symbol, including the story so far when there
        # is one -- silent when this is a first sighting.
        st.markdown(news_line(sym), unsafe_allow_html=True)
        try:
            import news_memory
            _thread = news_memory.thread_summary(sym)
            if _thread:
                with st.expander("📰 Story so far — every earlier read on this stock"):
                    st.code(_thread, language=None)
        except Exception:
            pass
        _news_window(sym, news_feed.get(sym))

    # Banked bars FIRST. daily_ohlc is the same completed-session history the
    # strategy reads, it is already local, and it cannot stall. The live EOD
    # call is only a top-up: when the feed is down -- which has happened twice
    # -- it used to block the whole page here, so the tabs below never painted.
    eod, meta = None, {}
    _bars = db.get_daily_ohlc(sym, limit=config.FEATURE_HISTORY_LIMIT)
    if _bars:
        eod = pd.DataFrame(_bars)[["date", "close", "volume"]]
        meta = {"source": "banked daily bars (completed sessions)",
                "as_of": eod["date"].max()}
    else:
        try:
            eod, meta = data_fetcher.fetch_eod(sym)
        except Exception as exc:
            eod, meta = None, {"warning": f"No banked bars and the live feed "
                                          f"is unreachable: {exc}"}
    if eod is not None:
        eod = eod.sort_values('date').tail(config.FEATURE_HISTORY_LIMIT)
        st.caption(f"Source: {meta['source']} (as of {meta['as_of']})")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=eod["date"], y=eod["close"], name="Close",
                                 line=dict(color=NEON["cyan"], width=2)))
        fig.add_trace(go.Scatter(x=eod["date"], y=eod["close"].ewm(span=20).mean(),
                                 name="Short price trend (20 days)",
                                 line=dict(color=NEON["amber"], dash="dot")))
        fig.add_trace(go.Scatter(x=eod["date"], y=eod["close"].ewm(span=40).mean(),
                                 name="Slower price trend (40 days)",
                                 line=dict(color=NEON["violet"], dash="dash")))
        if r:
            for lvl, nm, clr in ((r["support"], "Support", NEON["green"]),
                                 (r["resistance"], "Resistance", NEON["red"]),
                                 (r["stop_loss"], "Stop", NEON["red"])):
                if lvl:
                    fig.add_hline(y=lvl, line_dash="dot", line_color=clr,
                                  annotation_text=nm,
                                  annotation_font_color=clr)
        fig.update_layout(title=f"{sym} — price & moving averages")
        st.plotly_chart(neon_fig(fig, height=420), width="stretch")
        volf = go.Figure(go.Bar(x=eod["date"], y=eod["volume"], name="Volume",
                                marker=dict(color="rgba(0,229,255,0.5)")))
        volf.update_layout(title="Volume")
        st.plotly_chart(neon_fig(volf, height=220), width="stretch")
    else:
        st.error(meta.get("warning", "No price data."))

    with st.expander("How past Buy signals performed"):
        if st.button(f"Check past signals for {sym}", key="bt_one"):
            res = bt_symbol(sym, os.stat(config.DB_PATH).st_mtime_ns)
            import history_view
            history_view.show(st, res)

with tab_hist:
    sym = st.selectbox("Stock ", config.STOCKS, key="hist")
    hist = pd.DataFrame(db.run_history(sym, 300))
    if len(hist):
        hist["run_time"] = pd.to_datetime(hist["run_time"], utc=True, format="mixed")
        cols = [c for c in ["final_score", "technical_score", "relative_strength"]
                if c in hist.columns]
        st.line_chart(hist.set_index("run_time")[cols])
        st.caption("The score is a guide, not a chance of profit. Older results "
                   "compare the stock with the market.")
        st.subheader("Signal history")
        st.dataframe(hist[["run_time", "signal", "confidence", "price", "outcome"]],
                     width="stretch", hide_index=True)
    else:
        st.info("No run history stored for this stock yet.")

with tab_news:
    st.caption("Every headline gathered from approved publishers, banked and "
               "kept. Unrated and unscored — the rated read is the panel at "
               "the top. This is the record a new story is judged against.")
    _win = st.radio("Window", [3, 7, 30, 365], index=1, horizontal=True,
                    format_func=lambda d: {3: "3 days", 7: "7 days",
                                           30: "30 days", 365: "1 year"}[d],
                    key="news_win")
    _items = db.recent_news(_win * 24)
    _total = len(_items)
    if not _items:
        # Distinguish "nothing published" from "nothing ingested" -- the second
        # is a broken pipeline and used to look exactly like the first.
        with db.conn() as _c:
            _last = _c.execute("SELECT MAX(fetched_at) FROM news").fetchone()[0]
        if _last:
            st.warning(f"No headlines in the last {_win} day(s). The newest "
                       f"banked headline is from {str(_last)[:16]} — if that is "
                       f"old, the news fetch has stopped running.")
        else:
            st.warning("No headlines banked at all. The news fetch is not "
                       "reaching the database.")
    else:
        st.caption(f"{_total} headlines · newest {str(_items[0]['fetched_at'])[:16]}")
        for n in _items[:120]:
            tag = f" `[{n['symbols']}]`" if n["symbols"] else ""
            _link = n["link"] or ""
            _title = f"[{n['title']}]({_link})" if _link else n["title"]
            st.markdown(f"- `{str(n['fetched_at'])[:10]}` **{n['source']}** — "
                        f"{_title}{tag}")
        if _total > 120:
            st.caption(f"Showing the newest 120 of {_total}.")

with tab_reports:
    if os.path.isdir(config.REPORT_DIR):
        files = sorted(os.listdir(config.REPORT_DIR), reverse=True)[:10]
        pick = st.selectbox("Saved reports", files) if files else None
        if pick:
            with open(os.path.join(config.REPORT_DIR, pick), encoding="utf-8") as f:
                st.markdown(f.read())
        elif not files:
            st.info("No reports saved yet.")
    else:
        st.info("No reports saved yet.")
