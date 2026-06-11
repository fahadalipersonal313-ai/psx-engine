"""signal_generator.py — Converts final score + risk assessment into one of:
Strong Buy / Buy / Watch / Hold / Avoid / Exit.

Overrides ALWAYS beat the score:
  * shariah issue            -> Exit (if held) / Avoid
  * technical breakdown      -> Exit / Avoid
  * serious bad news         -> Avoid (or Exit if previously Buy)
  * poor risk/reward or manipulation risk -> downgrade Buy to Watch
"""

import logging
import config
import database as db

log = logging.getLogger("signal")

T = config.SIGNAL_THRESHOLDS


def generate(symbol, final_score, confidence, risk, shariah, technical):
    reasons, override = [], None

    if not shariah["eligible_for_ranking"]:
        override = "Avoid"
        reasons.append("Shariah status unverified — excluded by policy")

    if "breakdown" in risk["vetoes"]:
        prev = db.last_run(symbol)
        override = "Exit" if prev and prev.get("signal") in \
            ("Buy", "Strong Buy", "Hold") else "Avoid"
        reasons.append("Technical breakdown below support")

    if "bad_news" in risk["vetoes"] and override is None:
        override = "Avoid"
        reasons.append("Material negative news — wait for clarity")

    if override:
        return {"signal": override, "reasons": reasons,
                "confidence": min(confidence, 60)}

    # ---- score-based base signal
    if final_score >= T["strong_buy"]:
        base = "Strong Buy"
        reasons.append(f"Final score {final_score} ≥ {T['strong_buy']} with "
                       f"technical {technical['classification']}")
        if technical["classification"] not in ("Strong bullish", "Bullish"):
            base = "Buy"
            reasons.append("Downgraded: score high but technicals not confirming")
    elif final_score >= T["buy"]:
        base = "Buy"; reasons.append(f"Score {final_score} in Buy band 70-80")
    elif final_score >= T["watch"]:
        base = "Watch"; reasons.append(f"Score {final_score} in Watch band 60-70")
    elif final_score >= T["hold"]:
        base = "Hold"; reasons.append(f"Score {final_score} in Hold band 50-60")
    else:
        base = "Avoid"; reasons.append(f"Score {final_score} below 50")

    # ---- soft downgrades
    if base in ("Strong Buy", "Buy"):
        if "poor_rr" in risk["vetoes"]:
            base = "Watch"; reasons.append("Downgraded: risk/reward below minimum")
        elif "manipulation_risk" in risk["vetoes"]:
            base = "Watch"; reasons.append("Downgraded: hype/pump risk — verify first")
        elif risk["risk_level"] == "High":
            base = "Watch"; reasons.append("Downgraded: overall risk level High")
        elif confidence < 45:
            base = "Watch"; reasons.append("Downgraded: confidence below 45% "
                                           "(weak data or poor history)")

    if base in ("Strong Buy", "Buy"):
        reasons.append("Manual confirmation REQUIRED before placing any order")

    return {"signal": base, "reasons": reasons, "confidence": confidence}
