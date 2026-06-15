"""risk_manager.py — Capital protection layer. Runs AFTER scoring and can
veto or downgrade anything. The engine never claims zero loss; it labels
every setup low / medium / high risk and sizes positions so a stopped-out
trade costs at most RISK['max_risk_per_trade_pct'] of capital.
"""

import logging
import config

log = logging.getLogger("risk")


def assess(symbol, technical, sentiment, macro, capital_pkr=1_000_000):
    """Returns dict: risk_level, warnings[], position sizing, veto flags."""
    warnings, vetoes = [], []
    price = technical.get("price")
    stop = technical.get("stop_loss")
    rr = technical.get("headroom_rr")   # REAL room-to-resistance:risk (not the ≈2.0 proj.)

    # ---- hard warnings
    if technical.get("avg_volume") is not None and \
       technical["avg_volume"] < config.RISK["min_avg_daily_volume"]:
        warnings.append(f"ILLIQUID: 20-day avg volume "
                        f"{technical['avg_volume']:,.0f} below "
                        f"{config.RISK['min_avg_daily_volume']:,} — exits may slip badly")
    if technical.get("atr_pct") and technical["atr_pct"] > config.RISK["max_volatility_pct"]:
        warnings.append(f"HIGH VOLATILITY: daily range ≈{technical['atr_pct']:.1f}% — "
                        "gap risk elevated")
    if technical.get("breakdown"):
        warnings.append("TECHNICAL BREAKDOWN below support")
        vetoes.append("breakdown")
    if macro.get("bad_news_flag"):
        warnings.append("NEGATIVE COMPANY NEWS in last 96h: "
                        + "; ".join(t[:70] for t in macro.get("bad_news", [])[:2]))
        vetoes.append("bad_news")
    for f in sentiment.get("flags", []):
        warnings.append(f)
        if "PUMP" in f or "HYPE" in f:
            vetoes.append("manipulation_risk")
    if rr is not None and rr < config.RISK["min_headroom_rr"]:
        warnings.append(f"Thin upside: room-to-resistance:risk {rr} below "
                        f"{config.RISK['min_headroom_rr']} — price near overhead "
                        "resistance, little room before the next ceiling")
        vetoes.append("poor_rr")
    if technical.get("volume_spike") and sentiment.get("score", 50) > 80:
        warnings.append("Volume spike + euphoric sentiment — possible "
                        "manipulation / pump pattern, verify before acting")

    # ---- structural rules (always shown)
    warnings.append("Rule: no leverage, never all-in, max "
                    f"{config.RISK['max_position_pct']}% of capital per stock, "
                    "diversify across sectors")
    warnings.append("Rule: manual confirmation required before any buy order")

    # ---- risk level
    hard = sum(1 for w in warnings if any(k in w for k in
               ("ILLIQUID", "HIGH VOLATILITY", "BREAKDOWN", "NEGATIVE",
                "PUMP", "PANIC")))
    risk_level = "High" if hard >= 2 or vetoes else \
                 "Medium" if hard == 1 else "Low"

    # ---- position sizing (risk-based)
    sizing = None
    if price and stop and price > stop:
        risk_per_share = price - stop
        max_loss = capital_pkr * config.RISK["max_risk_per_trade_pct"] / 100
        shares = int(max_loss / risk_per_share)
        cap_shares = int(capital_pkr * config.RISK["max_position_pct"] / 100 / price)
        shares = max(0, min(shares, cap_shares))
        sizing = {"capital_assumed_pkr": capital_pkr,
                  "max_loss_if_stopped_pkr": round(shares * risk_per_share, 0),
                  "suggested_shares": shares,
                  "position_value_pkr": round(shares * price, 0),
                  "risk_per_share": round(risk_per_share, 2)}

    return {"risk_level": risk_level, "warnings": warnings, "vetoes": vetoes,
            "position_sizing": sizing}
