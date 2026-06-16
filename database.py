"""database.py — SQLite storage. Every run, signal, and outcome is recorded
so the engine can learn from history. Nothing is ever fabricated; missing
outcomes stay NULL until real prices arrive."""

import sqlite3
import logging
from datetime import datetime, timedelta
from contextlib import contextmanager

import config

log = logging.getLogger("database")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_time TEXT NOT NULL,
    symbol TEXT NOT NULL,
    price REAL, volume REAL,
    technical_score REAL, sentiment_score REAL, macro_news_score REAL,
    final_score REAL, signal TEXT, confidence REAL,
    stop_loss REAL, target1 REAL, target2 REAL,
    support REAL, resistance REAL, risk_level TEXT,
    shariah_status TEXT, data_quality TEXT,
    main_reason TEXT, main_risk TEXT,
    price_next_run REAL, price_1d REAL, price_3d REAL, price_7d REAL,
    outcome TEXT,             -- 'worked' / 'failed' / NULL (pending)
    tech_flags TEXT,          -- JSON: which sub-indicators were bullish (learning loop)
    conviction_streak INTEGER, -- consecutive runs at the same signal
    confluence INTEGER,       -- 0-4: how many independent signal dimensions agree
    buy_zone_low REAL,        -- pullback buy-zone (band around the 20-EMA)
    buy_zone_high REAL
);
CREATE INDEX IF NOT EXISTS idx_runs_symbol_time ON runs(symbol, run_time);

CREATE TABLE IF NOT EXISTS prices (
    symbol TEXT, ts TEXT, price REAL, volume REAL, source TEXT,
    PRIMARY KEY (symbol, ts)
);

CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at TEXT, source TEXT, title TEXT UNIQUE, link TEXT,
    published TEXT, sentiment REAL, symbols TEXT
);

CREATE TABLE IF NOT EXISTS sentiment_history (
    run_time TEXT, symbol TEXT, score REAL, bullish INTEGER,
    bearish INTEGER, neutral INTEGER, mentions INTEGER, flags TEXT
);

CREATE TABLE IF NOT EXISTS indicator_accuracy (
    indicator TEXT, symbol TEXT, hits INTEGER DEFAULT 0,
    misses INTEGER DEFAULT 0, PRIMARY KEY (indicator, symbol)
);

-- Real daily OHLC banked from the intraday feed (PSX EOD has no High/Low).
-- Accumulates over time so true ATR/ADX/candles become possible later.
CREATE TABLE IF NOT EXISTS daily_ohlc (
    symbol TEXT, date TEXT, open REAL, high REAL, low REAL,
    close REAL, volume REAL, source TEXT,
    PRIMARY KEY (symbol, date)
);
"""


@contextmanager
def conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db():
    with conn() as c:
        c.executescript(SCHEMA)
        # Lightweight migrations: add newer columns to `runs` if they're missing
        # (CREATE TABLE IF NOT EXISTS won't add columns to a pre-existing table).
        existing = {r[1] for r in c.execute("PRAGMA table_info(runs)")}
        for col, decl in (("relative_strength", "REAL"), ("market_regime", "TEXT"),
                          ("tech_flags", "TEXT"), ("conviction_streak", "INTEGER"),
                          ("confluence", "INTEGER"),
                          ("buy_zone_low", "REAL"), ("buy_zone_high", "REAL")):
            if col not in existing:
                c.execute(f"ALTER TABLE runs ADD COLUMN {col} {decl}")
    log.info("Database initialised at %s", config.DB_PATH)


def save_run(row: dict) -> int:
    cols = ",".join(row.keys())
    ph = ",".join("?" * len(row))
    with conn() as c:
        cur = c.execute(f"INSERT INTO runs ({cols}) VALUES ({ph})",
                        list(row.values()))
        return cur.lastrowid


def save_price(symbol, ts, price, volume, source):
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO prices VALUES (?,?,?,?,?)",
                  (symbol, ts, price, volume, source))


def save_daily_ohlc(symbol, date, o, h, l, c, volume, source):
    """Bank one real daily OHLC bar (from intraday). REPLACE so re-runs on the
    same day refine the high/low as more ticks arrive."""
    with conn() as cx:
        cx.execute("""INSERT OR REPLACE INTO daily_ohlc
            (symbol, date, open, high, low, close, volume, source)
            VALUES (?,?,?,?,?,?,?,?)""",
                   (symbol, date, o, h, l, c, volume, source))


def daily_ohlc_count(symbol=None):
    q = "SELECT COUNT(*) n FROM daily_ohlc"
    args = []
    if symbol:
        q += " WHERE symbol=?"; args.append(symbol)
    with conn() as c:
        return c.execute(q, args).fetchone()["n"]


def get_daily_ohlc(symbol, limit=90):
    """Real banked daily OHLC bars for a symbol, oldest-first (list of dicts:
    date, open, high, low, close, volume). Used for true ATR/ADX once enough
    bars accumulate; empty/short -> caller falls back to the EOD-close proxies."""
    with conn() as c:
        rows = c.execute(
            """SELECT date, open, high, low, close, volume FROM daily_ohlc
               WHERE symbol=? ORDER BY date DESC LIMIT ?""",
            (symbol, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


def save_news(items):
    with conn() as c:
        for it in items:
            c.execute("""INSERT OR IGNORE INTO news
                (fetched_at, source, title, link, published, sentiment, symbols)
                VALUES (?,?,?,?,?,?,?)""",
                (it["fetched_at"], it["source"], it["title"], it["link"],
                 it.get("published"), it.get("sentiment"),
                 ",".join(it.get("symbols", []))))


def recent_news(hours=48, symbol=None):
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    q = "SELECT * FROM news WHERE fetched_at > ?"
    args = [cutoff]
    if symbol:
        q += " AND symbols LIKE ?"
        args.append(f"%{symbol}%")
    with conn() as c:
        return [dict(r) for r in c.execute(q + " ORDER BY fetched_at DESC", args)]


def save_sentiment(run_time, symbol, score, bullish, bearish, neutral,
                   mentions, flags):
    with conn() as c:
        c.execute("INSERT INTO sentiment_history VALUES (?,?,?,?,?,?,?,?)",
                  (run_time, symbol, score, bullish, bearish, neutral,
                   mentions, ",".join(flags)))


def previous_sentiment(symbol):
    with conn() as c:
        r = c.execute("""SELECT score FROM sentiment_history WHERE symbol=?
                         ORDER BY run_time DESC LIMIT 1""", (symbol,)).fetchone()
        return r["score"] if r else None


def last_run(symbol):
    with conn() as c:
        r = c.execute("""SELECT * FROM runs WHERE symbol=?
                         ORDER BY run_time DESC LIMIT 1""", (symbol,)).fetchone()
        return dict(r) if r else None


def run_history(symbol=None, limit=500):
    q = "SELECT * FROM runs"
    args = []
    if symbol:
        q += " WHERE symbol=?"
        args.append(symbol)
    q += " ORDER BY run_time DESC LIMIT ?"
    args.append(limit)
    with conn() as c:
        return [dict(r) for r in c.execute(q, args)]


def pending_outcomes():
    """Runs whose forward prices are not yet fully recorded."""
    with conn() as c:
        return [dict(r) for r in c.execute(
            """SELECT * FROM runs WHERE price_7d IS NULL
               ORDER BY run_time ASC""")]


def update_outcome(run_id, field, value):
    assert field in ("price_next_run", "price_1d", "price_3d", "price_7d",
                     "outcome")
    with conn() as c:
        c.execute(f"UPDATE runs SET {field}=? WHERE id=?", (value, run_id))


def bump_indicator(indicator, symbol, hit: bool):
    with conn() as c:
        c.execute("""INSERT INTO indicator_accuracy (indicator, symbol, hits, misses)
                     VALUES (?,?,?,?)
                     ON CONFLICT(indicator, symbol) DO UPDATE SET
                     hits = hits + ?, misses = misses + ?""",
                  (indicator, symbol, int(hit), int(not hit),
                   int(hit), int(not hit)))


def indicator_stats(symbol=None):
    q = "SELECT * FROM indicator_accuracy"
    args = []
    if symbol:
        q += " WHERE symbol=?"
        args.append(symbol)
    with conn() as c:
        return [dict(r) for r in c.execute(q, args)]


def signal_accuracy(symbol=None):
    """Win rate per signal type from completed runs."""
    q = """SELECT signal, outcome, COUNT(*) n FROM runs
           WHERE outcome IS NOT NULL"""
    args = []
    if symbol:
        q += " AND symbol=?"
        args.append(symbol)
    q += " GROUP BY signal, outcome"
    with conn() as c:
        return [dict(r) for r in c.execute(q, args)]


def signal_streak(symbol):
    """How many consecutive recent runs had the same signal as the most recent run.
    Returns (streak_count, signal_string). streak_count=0 when no history."""
    with conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT signal FROM runs WHERE symbol=? ORDER BY run_time DESC LIMIT 20",
            (symbol,))]
    if not rows:
        return 0, None
    latest = rows[0]["signal"]
    streak = 0
    for r in rows:
        if r["signal"] == latest:
            streak += 1
        else:
            break
    return streak, latest
