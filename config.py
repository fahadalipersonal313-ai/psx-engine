"""
config.py — Central configuration for the PSX Shariah-Compliant Analysis Engine.

EDIT THIS FILE to change stocks, weights, risk rules, and data sources.
Never hard-code values elsewhere; all modules read from here.
"""

import os

# ---------------------------------------------------------------------------
# 1. STOCK UNIVERSE
# ---------------------------------------------------------------------------
# Default 4 stocks requested by the user:
DEFAULT_STOCKS = ["PSO", "TREET", "FABL", "AIRLINK"]

# 6 additional candidates — chosen ONLY from the officially verified KMI-30
# constituent list (see SHARIAH section below). Diversified across sectors.
# GAL added to complete the full 30 official KMI-30 names (was previously
# missing even though it's in KMI30_VERIFIED).
ADDITIONAL_STOCKS = ["MEBL", "SYS", "LUCK", "FFC", "NRL", "DGKC",
    "OGDC", "PPL", "MARI", "HUBC", "ENGROH", "EFERT", "FCCL", "MLCF",
    "NML", "PAEL", "SEARL", "HCAR", "PRL", "ATRL", "SNGP", "SSGC",
    "SAZEW", "FFL", "CPHL", "GHNI", "GAL"]

# Broader KMI All-Share (Shariah) names — added 2026-06-18, each verified IN the
# official PSX-KMI All Share Islamic Index recomposition (screening 2025-12-31,
# effective 2026-06-05). These are compliant via KMIALLSHR_VERIFIED below (not
# necessarily KMI-30). User-requested batch.
KMIALLSHR_STOCKS = ["KEL", "PIBTL", "TELE", "DCL", "GGL", "BNL", "ILP", "FCL",
    "JVDC", "AGP", "WAVES", "TOMCL", "IMAGE", "SYM", "FCEPL", "KOHC"]
ADDITIONAL_STOCKS += KMIALLSHR_STOCKS

# Extra names beyond the strict KMI-30, compliant via the OTHER_COMPLIANT
# route below (each entry there carries a source + verify note).
EXTRA_STOCKS = ["SLM", "SLGL", "THCCL"]

STOCKS = DEFAULT_STOCKS + ADDITIONAL_STOCKS + EXTRA_STOCKS

SECTORS = {
    "PSO": "Oil Marketing", "TREET": "Diversified/Consumer", "FABL": "Islamic Banking",
    "AIRLINK": "Technology/Telecom Devices", "MEBL": "Islamic Banking",
    "SYS": "Technology/IT Exports", "LUCK": "Cement/Conglomerate",
    "FFC": "Fertilizer", "OGDC": "Oil & Gas Exploration", "MARI": "Oil & Gas Exploration",
    "NRL": "Refinery", "DGKC": "Cement",
    "PPL": "Oil & Gas Exploration", "HUBC": "Power Generation",
    "ENGROH": "Conglomerate", "EFERT": "Fertilizer", "FCCL": "Cement",
    "MLCF": "Cement", "NML": "Textile", "PAEL": "Electrical Goods",
    "SEARL": "Pharmaceuticals", "HCAR": "Auto Assembler", "PRL": "Refinery",
    "ATRL": "Refinery", "SNGP": "Gas Distribution", "SSGC": "Gas Distribution",
    "SAZEW": "Auto Assembler", "FFL": "Food", "CPHL": "Pharmaceuticals",
    "GHNI": "Glass/Holding", "GAL": "Textile/Synthetic Fibre",
    "SLM": "Tyre Manufacturing", "SLGL": "Logistics/Transport",
    "THCCL": "Cement",
    # KMI All-Share batch (2026-06-18)
    "KEL": "Power Generation", "PIBTL": "Logistics/Ports",
    "TELE": "Technology/Telecom", "DCL": "Cement", "GGL": "Glass/Holding",
    "BNL": "Food", "ILP": "Textile", "FCL": "Electrical Goods",
    "JVDC": "Real Estate", "AGP": "Pharmaceuticals", "WAVES": "Electrical Goods",
    "TOMCL": "Food", "IMAGE": "Textile", "SYM": "Technology/IT",
    "FCEPL": "Food", "KOHC": "Cement"}

# ---------------------------------------------------------------------------
# 2. SHARIAH COMPLIANCE — VERIFIED SOURCE OF TRUTH
# ---------------------------------------------------------------------------
# Official KMI-30 constituents per PSX re-composition notification,
# screening date 2025-12-31, effective 2026-05-25.
# Source: PSX notification (dps.psx.com.pk/download/attachment/277332-1.pdf),
# reported by Mettis Global, 2026-05-18.
# IMPORTANT: KMI-30 is recomposed semi-annually. Re-verify this list every
# 6 months. The engine warns when the verification date is older than
# SHARIAH_STALE_DAYS.
KMI30_VERIFIED = {
    "AIRLINK", "ATRL", "CPHL", "DGKC", "EFERT", "ENGROH", "FCCL", "FFC", "FFL",
    "GAL", "GHNI", "HCAR", "HUBC", "LUCK", "MARI", "MEBL", "MLCF", "NML", "NRL",
    "OGDC", "PAEL", "PPL", "PRL", "PSO", "SAZEW", "SEARL", "SNGP", "SSGC",
    "SYS", "TREET",
}
KMI30_VERIFICATION_DATE = "2026-05-25"   # effective date of recomposition
KMI30_SOURCE = "PSX KMI-30 recomposition notice (screening 2025-12-31)"
SHARIAH_STALE_DAYS = 200  # warn if verification older than this

# Broader KMI All-Share (Shariah) constituents — every symbol here was confirmed
# present and "Compliant" in the official PSX-KMI All Share Islamic Index
# recomposition notice (screening accounts 2025-12-31, effective 2026-06-05).
# These are shariah-compliant and ELIGIBLE for ranking even though they are not
# in the tighter KMI-30. Re-verify at the next recomposition (semi-annual).
# Source: psx.com.pk KMI-ALL-Share-Recomposition-Notice.pdf (verified 2026-06-18).
KMIALLSHR_VERIFIED = {
    "KEL", "PIBTL", "TELE", "DCL", "GGL", "BNL", "ILP", "FCL", "JVDC", "AGP",
    "WAVES", "TOMCL", "IMAGE", "SYM", "FCEPL", "KOHC",
}
KMIALLSHR_VERIFICATION_DATE = "2026-06-05"   # effective date of recomposition
KMIALLSHR_SOURCE = "PSX-KMI All Share recomposition notice (screening 2025-12-31)"

# Stocks compliant via another verified route (not in KMI-30 top-30 ranking
# but shariah compliant per company structure). Each entry MUST carry a
# reason and a manual re-check note. Anything not in KMI30_VERIFIED or here
# is marked "Needs manual verification" and EXCLUDED from the top-10 ranking.
OTHER_COMPLIANT = {
    "FABL": {
        "reason": ("Faysal Bank converted to a full-fledged Islamic bank "
                   "(conversion completed Jan 2023); operates under SBP Islamic "
                   "banking licence."),
        "verify_note": ("Confirm continued inclusion in PSX KMI All Share Index "
                        "and SECP shariah-compliant securities list each quarter."),
    },
    "SLM": {
        "reason": ("Service Long March Tyres Ltd. — deemed Shariah compliant under "
                   "the KMI All Share Index screening criteria and included in the "
                   "PSX-KMI All Share Islamic Index on listing (PSX, June 2026)."),
        "verify_note": ("Newly listed (15 Jun 2026) — confirm continued inclusion in "
                        "the PSX-KMI All Share Islamic Index each semi-annual "
                        "recomposition."),
    },
    "SLGL": {
        "reason": ("Secure Logistics-Trax Group Ltd. — reported as Shariah "
                   "compliant per PSX documentation (transport/logistics sector, "
                   "no interest-based core business)."),
        "verify_note": ("Source was a secondary aggregator, not the primary PSX "
                        "KMI All Share notice PDF — confirm against the latest "
                        "PSX-KMI All Share Islamic Index recomposition notice "
                        "before relying on this."),
    },
    "THCCL": {
        "reason": ("Thatta Cement Company Ltd. — cement sector, a sector where "
                   "most PSX names pass KMI screening (cf. DGKC/FCCL/MLCF already "
                   "in KMI30_VERIFIED)."),
        "verify_note": ("Not independently confirmed against the primary PSX-KMI "
                        "All Share Islamic Index notice — verify before relying on "
                        "this for trading decisions."),
    },
}

# ---------------------------------------------------------------------------
# 3. SCORING WEIGHTS (fixed per spec; change only deliberately)
# ---------------------------------------------------------------------------
# Technical + fundamentals only. News/sentiment weight is ZERO (news judged to be
# noise) — both sections are still COMPUTED for display and to drive the bad-news
# SAFETY override in risk_manager, but they no longer move the score.
# Must sum to 1.0.
# Tier B: macro is anchor-informed (rates/CPI/reserves — see
# macro_news_analyzer._anchor_score). The `sentiment` slot now carries AUTHENTIC
# news: a daily Claude routine writes news_signals.json (LLM-judged headlines
# with source URLs); sentiment_analyzer reads it (VADER RSS is the fallback when
# the file is stale/missing). Technical stays dominant. Zero a slot to disable it.
WEIGHTS = {"technical": 0.45, "fundamentals": 0.20,
           "macro_news": 0.15, "sentiment": 0.20}

SIGNAL_THRESHOLDS = {   # final score -> base signal (before risk overrides)
    "strong_buy": 80, "buy": 70, "watch": 60, "hold": 50,
}

# Hysteresis dead-band around the SIGNAL_THRESHOLDS. A raw score grazing a
# threshold (e.g. 69.5 vs 70.5) shouldn't flip Buy↔Watch run-to-run — that's
# scoring noise, not signal. Once a stock is at level X, its final_score must
# cross the next threshold by at least this many points BEFORE flipping. Same
# pattern as the existing conviction-streak gate (which requires Strong Buy to
# confirm), but applied to band edges. Set to 0 to disable.
HYSTERESIS_BAND = 2

# ---------------------------------------------------------------------------
# 3b. MARKET REGIME & RELATIVE STRENGTH (Tier 2)
# ---------------------------------------------------------------------------
# Benchmark index for the regime gate + relative-strength ranking. PSX DPS
# serves index EOD at the same /timeseries/eod/{symbol} endpoint as stocks.
# KMI30 = the Shariah index matching this engine's universe (KSE100 = broad
# market). Confirmed live 2026-06-14: KSE100, KMI30, KSE30, ALLSHR, KMIALLSHR.
BENCHMARK_INDEX = "KMI30"
REGIME_EMA_SPAN = 50           # index must be above this EMA for a "risk-on" market
REGIME_GATE_ENABLED = True     # in a risk-off market, soften Buy/Strong Buy -> Watch
# Relative strength: stock return minus index return over these trading-day
# windows, blended (recent weighted a touch less than the 3-/6-month trend).
RS_LOOKBACKS = {"1m": 21, "3m": 63, "6m": 126}
RS_WEIGHTS = {"1m": 0.25, "3m": 0.40, "6m": 0.35}
RS_POINTS = 15                 # relative strength's contribution to the technical score
# True ATR/ADX activate once this many REAL daily OHLC bars (banked from intraday
# H/L) exist for a symbol; below this the engine uses the close-based proxies.
# Banking started ~2026-06-12, so true values switch on automatically in early July.
MIN_OHLC_BARS_FOR_TRUE = 16

# Fundamentals table (manually maintained — the engine NEVER invents these).
# Fill per symbol from the latest audited quarterly/annual report. Any symbol
# left out scores a neutral 50 and is flagged low-confidence (see
# fundamentals_analyzer.py). Keys (all optional): pe, eps_growth (%), roe (%),
# de (debt/equity), div_yield (%).
FUNDAMENTALS_AS_OF = ""   # e.g. "2026-03-31 (Q3 FY26)"; blank = not yet filled
FUNDAMENTALS = {
    # "PSO": {"pe": 4.2, "eps_growth": 12, "roe": 18, "de": 0.6, "div_yield": 7},
}

# ---------------------------------------------------------------------------
# 4. RISK MANAGEMENT
# ---------------------------------------------------------------------------
RISK = {
    "max_risk_per_trade_pct": 1.5,     # % of total capital risked per trade
    "max_position_pct": 15.0,          # never put more than this % in one stock
    "min_risk_reward": 2.0,            # reject setups below 2:1 (projected-target R:R)
    "min_headroom_rr": 1.5,            # real room-to-resistance : risk; below -> thin
                                       # upside (price jammed under a ceiling) -> Watch
    "min_headroom_rr_riskon_floor": 1.1,# FLOOR for the risk-on relaxation of the
                                       # headroom-RR threshold. In a confirmed bull
                                       # most stocks sit close to recent highs (price
                                       # near "resistance" is the leadership default),
                                       # so requiring 1.5x headroom would mute the
                                       # whole leadership group. Threshold ramps DOWN
                                       # from min_headroom_rr (neutral / flat tape) to
                                       # this floor (strong rally). Set to 1.5 to
                                       # disable risk-on relaxation.
    "headroom_rr_riskon_full_pct": 8.0, # Rally strength (benchmark % above its 50-EMA)
                                       # at which the headroom threshold reaches its
                                       # floor. Linear ramp between the two.
    "max_extension_pct": 11.0,         # price > this % above EMA20 -> extended (chase).
                                       # %-based, not ATR: the EOD ATR proxy understates
                                       # true range, which inflated ATR-normalised distance.
    "max_extension_momentum_pct": 22.0,# 20-day momentum above this% -> parabolic/extended
    "extension_riskon_multiplier": 1.8,# CEILING for the risk-on chase-guard widening.
                                       # In a confirmed risk-on rally "above EMA20" is
                                       # the market's DEFAULT state, so the chase guard
                                       # widens UP TO this factor (≈20% above EMA20 /
                                       # ≈40% 20-day momentum). The actual widening scales
                                       # with rally strength (see _full_pct below). Set to
                                       # 1.0 to keep the guard regime-neutral (old behaviour).
    "extension_riskon_full_pct": 8.0,  # Rally strength (benchmark % above its 50-EMA) at
                                       # which the chase guard reaches its full widening.
                                       # The multiplier ramps linearly from 1.0 when the
                                       # index just crosses above its EMA (mild rally) to
                                       # the ceiling above when the index is this far above
                                       # it (strong, confirmed bull) — so a shaky breakout
                                       # loosens the guard only a little, a powerful trend
                                       # loosens it fully.
    "default_stop_atr_mult": 2.0,      # stop loss = entry - 2*ATR (or support)
    "min_avg_daily_volume": 100_000,   # below this -> illiquid warning
    "max_volatility_pct": 6.0,         # daily ATR% above this -> high risk
    "no_leverage": True,
    "manual_confirmation_required": True,
}

# ---------------------------------------------------------------------------
# 4b. PORTFOLIO-LEVEL RISK (Tier 2 #9)
# ---------------------------------------------------------------------------
# Per-trade sizing (above) caps the damage from ONE position. These caps apply
# ACROSS every open/recommended Buy at once, because the real account-killer is
# correlated risk: ten "safe" 1.5% trades that all gap down together, or a book
# that is 80% cement. The engine sizes each Buy, then admits them greedily by
# score until a cap binds — the rest are flagged "defer", never silently dropped.
PORTFOLIO_RISK = {
    "max_portfolio_heat_pct": 6.0,    # total capital at risk if EVERY open stop fills at once
    "max_sector_exposure_pct": 30.0,  # max % of capital deployed into any one sector
    "max_open_positions": 8,          # practical cap on concurrent positions
}

# ---------------------------------------------------------------------------
# 4c. BACKTEST METRICS (Tier 2 #8)
# ---------------------------------------------------------------------------
# The backtest replays EOD history with the technical module and now reports the
# metrics that actually predict whether an edge is real and tradeable:
#   * expectancy   — average PKR/%, per trade, you can expect (the north star)
#   * profit_factor— gross profit / gross loss (>1.5 = healthy, <1 = bleeding)
#   * max_drawdown — worst peak-to-trough equity dip (can you stomach it?)
#   * walk-forward — metrics on a held-out OUT-OF-SAMPLE tail + rolling folds,
#                    so an edge that only exists in-sample is exposed as overfit.
BACKTEST = {
    "lookback": 250,            # trading days of history to replay
    "hold_days": 5,            # bars held per trade (exit or stop)
    "entry_score": 70,         # technical score threshold to open a backtest trade
    "oos_fraction": 0.30,      # final fraction of the window held out (out-of-sample)
    "walk_forward_folds": 4,   # rolling walk-forward folds for robustness
}

# ---------------------------------------------------------------------------
# 5. DATA SOURCES (public, no login, no protection bypass)
# ---------------------------------------------------------------------------
PSX_DPS_BASE = "https://dps.psx.com.pk"
PSX_INTRADAY_URL = PSX_DPS_BASE + "/timeseries/int/{symbol}"
PSX_EOD_URL = PSX_DPS_BASE + "/timeseries/eod/{symbol}"
PSX_COMPANY_URL = PSX_DPS_BASE + "/company/{symbol}"

# Public RSS feeds for news + sentiment (respecting robots/ToS — RSS is
# explicitly published for consumption).
NEWS_FEEDS = [
    ("Business Recorder", "https://www.brecorder.com/feeds/latest-news"),
    ("Dawn Business", "https://www.dawn.com/feeds/business"),
    ("The News Business", "https://www.thenews.com.pk/rss/1/8"),
    ("Tribune Business", "https://tribune.com.pk/feed/business"),
    # Profit (profit.pakistantoday.com.pk/feed) and Mettis (mettisglobal.news/rss)
    # were removed 2026-06-11: both feed URLs now return HTTP 404.
]

REQUEST_TIMEOUT = 15
REQUEST_HEADERS = {"User-Agent": "PSX-Research-Engine/1.0 (personal research tool)"}

# Drop any news headline whose PUBLISH date is older than this many days, so
# stale/irrelevant articles can't pollute scoring (filters on real publish
# date, not fetch time).
NEWS_MAX_AGE_DAYS = 3

# Per-company PUBLIC news/sentiment via Google News RSS search (login-free,
# published for consumption). Each query is scoped to the company so the
# sentiment module gets real per-symbol mentions instead of market-wide noise.
GOOGLE_NEWS_RSS = ("https://news.google.com/rss/search?q={query}"
                   "+when:2d&hl=en-PK&gl=PK&ceid=PK:en")
COMPANY_NEWS_QUERY = {
    "PSO": "Pakistan State Oil",
    "TREET": "Treet Corporation Pakistan",
    "FABL": "Faysal Bank",
    "AIRLINK": "Air Link Communication Pakistan",
    "MEBL": "Meezan Bank",
    "SYS": "Systems Limited Pakistan",
    "LUCK": "Lucky Cement",
    "FFC": "Fauji Fertilizer Company",
    "NRL": "National Refinery Limited Pakistan",
    "DGKC": "DG Khan Cement",
    "OGDC": "Oil and Gas Development Company Pakistan",
    "MARI": "Mari Petroleum Energies","PPL": "Pakistan Petroleum", "HUBC": "Hub Power Company",
    "ENGROH": "Engro Holdings", "EFERT": "Engro Fertilizers",
    "FCCL": "Fauji Cement", "MLCF": "Maple Leaf Cement", "NML": "Nishat Mills",
    "PAEL": "Pak Elektron", "SEARL": "Searle Company Pakistan",
    "HCAR": "Honda Atlas Cars", "PRL": "Pakistan Refinery",
    "ATRL": "Attock Refinery", "SNGP": "Sui Northern Gas",
    "SSGC": "Sui Southern Gas", "SAZEW": "Sazgar Engineering",
    "FFL": "Fauji Foods", "CPHL": "Citi Pharma",
    # KMI All-Share batch (2026-06-18)
    "KEL": "K-Electric", "PIBTL": "Pakistan International Bulk Terminal",
    "TELE": "Telecard Pakistan", "DCL": "Dewan Cement",
    "GGL": "Ghani Global Holdings", "BNL": "Bunnys Limited Pakistan",
    "ILP": "Interloop Limited", "FCL": "Fast Cables Pakistan",
    "JVDC": "Javedan Corporation Naya Nazimabad", "AGP": "AGP Limited pharma Pakistan",
    "WAVES": "Waves Corporation Pakistan", "TOMCL": "The Organic Meat Company Pakistan",
    "IMAGE": "Image Pakistan Limited", "SYM": "Symmetry Group Pakistan",
    "FCEPL": "FrieslandCampina Engro Foods", "KOHC": "Kohat Cement"
}

# ---------------------------------------------------------------------------
# 6. MACRO INPUTS — manually maintained (update from SBP/PBS releases).
#    The engine also scores macro news automatically; these anchors give it
#    a baseline. Each carries an as_of date; stale values trigger warnings.
# ---------------------------------------------------------------------------
MACRO_ANCHORS = {
    "policy_rate_pct":   {"value": 11.5,   "as_of": "2026-04-27", "source": "SBP MPC (raised +100bps to 11.5%)"},
    "cpi_yoy_pct":       {"value": 11.7,   "as_of": "2026-05-31", "source": "PBS (May 2026 CPI YoY)"},
    "usd_pkr":           {"value": 278.75, "as_of": "2026-06-14", "source": "Interbank"},
    "fx_reserves_usd_bn":{"value": 17.22,  "as_of": "2026-06-05", "source": "SBP-held reserves"},
}
MACRO_STALE_DAYS = 45

# Earnings-date awareness: within this many days BEFORE a known result/board-
# meeting date, a fresh Buy/Strong Buy is held at Watch (binary event risk). Only
# acts when a date is KNOWN — from EARNINGS_DATES below, or an optional
# "earnings_date" field the news routine adds to news_signals.json. Unknown =
# no effect (never fabricates a blackout).
EARNINGS_BLACKOUT_DAYS = 5
EARNINGS_DATES = {}          # manual override, e.g. {"LUCK": "2026-07-28"}

# ---------------------------------------------------------------------------
# 7. SCHEDULING
# ---------------------------------------------------------------------------
RUN_INTERVAL_MINUTES = 15
# Dashboard staleness flagging — when the latest run is older than these
# thresholds (in hours, PKT), the "Last updated" tile shifts amber then red and
# a banner warns the user that signals may not reflect current price action.
# Honest-by-design: better to flag stale than to let it pass as fresh.
DATA_FRESHNESS_AMBER_HOURS = 4
DATA_FRESHNESS_RED_HOURS = 24
MARKET_OPEN = "09:15"     # PSX regular session (Mon-Thu 09:32-15:30 approx;
MARKET_CLOSE = "15:45"    # Fri split session). Slightly widened window.
MARKET_DAYS = [0, 1, 2, 3, 4]          # Mon..Fri
MORNING_REPORT_TIME = "09:00"
EVENING_REPORT_TIME = "21:00"
TIMEZONE = "Asia/Karachi"

# ---------------------------------------------------------------------------
# 8. STORAGE / LOGGING
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "psx_engine.db")
LOG_PATH = os.path.join(BASE_DIR, "engine.log")
REPORT_DIR = os.path.join(BASE_DIR, "reports_out")

# Authentic news feed — produced by the daily Claude news routine (see
# news_routine.md). news_signals.json holds per-symbol LLM-judged news verdicts
# with source URLs. The engine reads it via news_feed.py; if the file is missing
# or older than NEWS_SIGNALS_MAX_AGE_HOURS, it falls back to RSS/VADER scoring.
NEWS_SIGNALS_PATH = os.path.join(BASE_DIR, "news_signals.json")
# Your real holdings + ready cash (read by portfolio_advisor for the dashboard's
# Portfolio tab). Edit portfolio.json or the dashboard table to keep it current.
PORTFOLIO_PATH = os.path.join(BASE_DIR, "portfolio.json")
NEWS_SIGNALS_MAX_AGE_HOURS = 24          # strict 24h window per user spec; weekend gap means Mon's run starts neutral until refresh
# Authentic-or-neutral policy: when there is NO fresh authentic verdict for a
# stock, treat its news as NEUTRAL rather than keyword-scoring noisy RSS with
# VADER. Set True only to restore the old VADER fallback. False means news moves
# a signal ONLY when there is real, sourced news.
NEWS_FALLBACK_VADER = False
# Only these sources count as authentic for the news routine (no social/rumor).
# Narrowed to 3 desks (2026-06-14) to keep the routine token-frugal — the first
# full run naturally used only Mettis + BR anyway.
NEWS_SOURCE_ALLOWLIST = [
    "brecorder.com",                     # Business Recorder
    "dawn.com",                          # Dawn Business
    "mettisglobal.news",                 # Mettis Global
    "profit.pakistantoday.com.pk",       # Profit Pakistan Today
    "news.google.com",                   # Google News RSS aggregator (per-symbol)
]
EXCEL_DIR = REPORT_DIR

# ---------------------------------------------------------------------------
# 9. NOTIFICATIONS / EMAIL  (secrets come from the ENVIRONMENT — never commit
#    them. On the cloud these are injected from GitHub Actions Secrets.)
# ---------------------------------------------------------------------------
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")                  # sending Gmail address
SMTP_APP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD")  # 16-char app password
EMAIL_TO = os.environ.get("EMAIL_TO")                    # recipient address
# How often to email: "actionable" (default) emails only when a Buy/Strong Buy/
# Exit appears — avoids spamming you every 10 minutes; "always" = every run;
# "off" = never.
EMAIL_MODE = os.environ.get("EMAIL_MODE", "actionable")
ACTIONABLE_SIGNALS = {"Strong Buy", "Buy", "Exit"}

# Dashboard view password (set in Streamlit Cloud secrets; falls back to env).
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD")

DISCLAIMER = (
    "This tool is decision support, NOT financial advice. No system can "
    "guarantee profit or zero loss. Setups are labelled low/medium/high risk. "
    "Always confirm manually before trading and never risk money you cannot "
    "afford to lose."
)
