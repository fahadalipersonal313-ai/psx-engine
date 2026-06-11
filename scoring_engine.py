"""scoring_engine.py — Blends the section scores into a final 0-100 score and
a confidence percentage.

Weights are configurable in config.WEIGHTS (currently technical-first:
technical 0.65 / macro_news 0.20 / sentiment 0.15). Learning adjusts
CONFIDENCE, not weights: if a stock's past signals keep failing, confidence
drops; if they keep working, it rises modestly. Small samples are flagged as
overfitting risk and barely move confidence. The weak-section confidence
penalty is weight-aware, so a minor section can't dominate confidence.
"""

import logging

import config
import database as db

log = logging.getLogger("scoring")


def historical_confidence_adjust(symbol):
    """Return (adjustment in percentage points, note)."""
    rows = db.signal_accuracy(symbol)
    wins = sum(r["n"] for r in rows if r["outcome"] == "worked")
    losses = sum(r["n"] for r in rows if r["outcome"] == "failed")
    total = wins + losses
    if total == 0:
        return 0.0, "No completed signal history yet — base confidence."
    win_rate = wins / total
    if total < 10:
        # tiny sample: cap influence, warn about overfitting
        adj = (win_rate - 0.5) * 8
        return round(adj, 1), (f"Only {total} completed signals — small sample, "
                               "OVERFITTING RISK; history given little weight.")
    adj = (win_rate - 0.5) * 30          # max ±15 points
    return round(max(-15, min(15, adj)), 1), \
        f"History: {wins}W/{losses}L (win rate {win_rate:.0%}) over {total} signals."


def compute(symbol, macro, sentiment, technical):
    w = config.WEIGHTS
    final = round(w["macro_news"] * macro["score"]
                  + w["sentiment"] * sentiment["score"]
                  + w["technical"] * technical["score"], 1)

    # ---- data quality
    weak = []
    if macro.get("low_confidence"): weak.append("macro/news")
    if sentiment.get("low_confidence"): weak.append("sentiment")
    if technical.get("low_confidence"): weak.append("technical")
    data_quality = "good" if not weak else ("weak: " + ", ".join(weak))

    # ---- confidence
    confidence = 70.0
    # Weight-aware penalty: a weak section dents confidence in proportion to how
    # much it actually drives the score. With the technical-first weights, a
    # quiet/empty news section barely matters, while weak technicals (the core)
    # matter most. (Old behaviour was a flat 12 pts per weak section.)
    _key = {"macro/news": "macro_news", "sentiment": "sentiment",
            "technical": "technical"}
    confidence -= sum(36 * w.get(_key.get(s, s), 0) for s in weak)
    # agreement bonus: all three sections pointing the same way
    scores = [macro["score"], sentiment["score"], technical["score"]]
    if max(scores) - min(scores) < 15:
        confidence += 8
    adj, hist_note = historical_confidence_adjust(symbol)
    confidence = round(max(10, min(95, confidence + adj)), 1)

    return {"final_score": final, "confidence": confidence,
            "data_quality": data_quality, "weak_sections": weak,
            "history_note": hist_note,
            "breakdown": {"macro_news": macro["score"],
                          "sentiment": sentiment["score"],
                          "technical": technical["score"],
                          "weights": w}}
