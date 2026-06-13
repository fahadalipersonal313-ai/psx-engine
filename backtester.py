"""backtester.py — Two jobs:

1. OUTCOME TRACKER (the learning loop): for every stored run, fill in real
   prices after the next run, 1, 3, and 7 days, then judge whether the
   signal 'worked'. Buy/Strong Buy works if price moved toward target
   before stop; Avoid/Exit works if price fell. Results feed
   indicator_accuracy and signal_accuracy, which adjust future CONFIDENCE.

2. BACKTEST MODE: replay the EOD history with the technical module to show
   how score-based signals would have behaved. This is in-sample and
   explicitly labelled with overfitting warnings — it is evidence, not proof.
"""

import logging
from datetime import datetime, timedelta

import pandas as pd

import config
import database as db
import data_fetcher
import technical_analyzer

log = logging.getLogger("backtester")


# ---------------------------------------------------------------------------
# Outcome tracking
# ---------------------------------------------------------------------------
def _price_on_or_after(eod, when):
    # EOD timestamps sit at midnight; run_time carries an intraday time. Without
    # normalising, "3 days after a 15:17 run" skips that day's midnight EOD and
    # lands a session late. Compare on calendar date so the horizon is exact.
    sub = eod[eod["date"] >= pd.Timestamp(when).normalize()]
    return float(sub["close"].iloc[0]) if len(sub) else None


def update_outcomes():
    """Fill pending forward prices from real EOD data and grade signals."""
    pend = db.pending_outcomes()
    if not pend:
        return 0
    eod_cache = {}
    updated = 0
    for run in pend:
        sym = run["symbol"]
        if sym not in eod_cache:
            eod_cache[sym], _ = data_fetcher.fetch_eod(sym)
        eod = eod_cache[sym]
        if eod is None:
            continue
        t0 = datetime.fromisoformat(run["run_time"])
        for field, days in (("price_1d", 1), ("price_3d", 3), ("price_7d", 7)):
            if run[field] is None and datetime.now() >= t0 + timedelta(days=days):
                p = _price_on_or_after(eod, t0 + timedelta(days=days))
                if p:
                    db.update_outcome(run["id"], field, p)
                    run[field] = p
                    updated += 1
        # grade once 3-day price exists
        if run["outcome"] is None and run["price_3d"] is not None and run["price"]:
            chg = (run["price_3d"] / run["price"] - 1) * 100
            sig = run["signal"]
            if sig in ("Buy", "Strong Buy"):
                worked = chg > 1.0 and (run["stop_loss"] is None
                                        or run["price_3d"] > run["stop_loss"])
            elif sig in ("Avoid", "Exit"):
                worked = chg < 0
            else:  # Watch / Hold graded loosely on not losing >3%
                worked = chg > -3.0
            db.update_outcome(run["id"], "outcome",
                              "worked" if worked else "failed")
            # credit/blame the dominant section
            b = {"technical": run["technical_score"],
                 "sentiment": run["sentiment_score"],
                 "macro_news": run["macro_news_score"]}
            dominant = max(b, key=lambda k: b[k] or 0)
            db.bump_indicator(dominant, sym, worked)
    log.info("Outcome tracker updated %d fields", updated)
    return updated


# ---------------------------------------------------------------------------
# Historical backtest (technical-only replay; macro/sentiment history is not
# reconstructable honestly, so we do not pretend to backtest it)
# ---------------------------------------------------------------------------
def backtest(symbol, lookback=250, hold_days=5):
    eod, meta = data_fetcher.fetch_eod(symbol)
    if eod is None or len(eod) < 80:
        return {"symbol": symbol, "error": "insufficient history",
                "meta": meta}
    eod = eod.tail(lookback).reset_index(drop=True)
    trades = []
    i = 60
    while i < len(eod) - hold_days:
        window = eod.iloc[: i + 1]
        quote = {"price": float(window["close"].iloc[-1]),
                 "volume": float(window["volume"].iloc[-1])}
        t = technical_analyzer.analyze(symbol, window, quote)
        if t["score"] is not None and t["score"] >= 70 and not t.get("breakdown"):
            entry = quote["price"]
            exit_p = float(eod["close"].iloc[i + hold_days])
            stopped = any(float(eod["close"].iloc[j]) <= t["stop_loss"]
                          for j in range(i + 1, i + hold_days + 1))
            pnl = ((t["stop_loss"] if stopped else exit_p) / entry - 1) * 100
            trades.append({"date": str(eod['date'].iloc[i].date()),
                           "entry": entry, "pnl_pct": round(pnl, 2),
                           "stopped": stopped})
            i += hold_days
        i += 1
    if not trades:
        return {"symbol": symbol, "trades": 0,
                "note": "No qualifying setups in window."}
    wins = [t for t in trades if t["pnl_pct"] > 0]
    return {"symbol": symbol, "trades": len(trades),
            "win_rate_pct": round(len(wins) / len(trades) * 100, 1),
            "avg_pnl_pct": round(sum(t["pnl_pct"] for t in trades)
                                 / len(trades), 2),
            "worst_trade_pct": min(t["pnl_pct"] for t in trades),
            "detail": trades,
            "warning": ("IN-SAMPLE technical-only backtest. Past performance "
                        "≠ future results; small samples overfit easily.")}
