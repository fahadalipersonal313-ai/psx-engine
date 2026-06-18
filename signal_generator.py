"""signal_generator.py — Converts final score + risk assessment into one of:
Strong Buy / Buy / Watch / Hold / Avoid / Exit.

Overrides ALWAYS beat the score:
  * shariah issue            -> Exit (if held) / Avoid
  * technical breakdown      -> Exit / Avoid
  * serious bad news         -> soft downgrade Buy -> Watch (not a hard Avoid)
  * poor risk/reward or manipulation risk -> downgrade Buy to Watch

Tier 2 additions:
  * Confluence gate  — Strong Buy needs ≥3/4 independent dimensions (trend,
                       momentum, volume, structure); Buy needs ≥2. Below → Watch.
  * Conviction streak — Strong Buy is capped at Buy on its FIRST appearance.
                        A second consecutive Strong Buy run confirms it.

Anti-chase additions (don't buy at the peak):
  * Overextension gate — price too far above EMA20 (or parabolic momentum) steps
                         the signal down one notch: wait for the pullback.
  * Thin-headroom (poor_rr) — REAL room-to-resistance:risk below the minimum
                         (price jammed under a ceiling) → Watch. (Via risk_manager,
                         which now reads technical.headroom_rr, not the ≈2.0 proj R:R.)
  * Pullback entry  — an extended setup held at Watch shows its buy-zone (the
                       20-EMA band); when price later retraces INTO that zone with
                       the uptrend intact, a cooled Watch/Hold is upgraded to Buy
                       (buy the dip, don't chase the peak). Stateless across runs.
  * Earnings blackout — within EARNINGS_BLACKOUT_DAYS of a KNOWN result date, a
                       fresh Buy/Strong Buy is held at Watch (binary event risk).
                       Only acts when a date is known; never invents a blackout.
"""

import logging
import config
import database as db

log = logging.getLogger("signal")

T = config.SIGNAL_THRESHOLDS


def _confluence(technical):
    """0-4: how many independent signal dimensions agree with a bullish trade.

    Four INDEPENDENT dimensions (each captures a different market mechanism):
      1. Trend    — price above its 50-EMA (intermediate trend is up)
      2. Momentum — RSI in healthy zone AND MACD histogram positive (both agree)
      3. Volume   — OBV trending up (smart money accumulating, not distributing)
      4. Structure— price above nearest support AND no breakdown in progress

    A score of 4 means trend, momentum, volume and structure all line up.
    A Buy signal with confluence 1 is a weak coincidence; with 4 it is a real setup.
    """
    price = technical.get("price") or 0
    score, dims = 0, []

    ema50 = technical.get("ema50")
    if ema50 and price > ema50:
        score += 1; dims.append("trend")

    rsi = technical.get("rsi")
    macd_h = technical.get("macd_hist")
    if (rsi is not None and 40 <= rsi <= 74
            and macd_h is not None and macd_h > 0):
        score += 1; dims.append("momentum")

    if technical.get("obv_up"):
        score += 1; dims.append("volume")

    support = technical.get("support")
    if support and price > support and not technical.get("breakdown"):
        score += 1; dims.append("structure")

    return score, dims


def generate(symbol, final_score, confidence, risk, shariah, technical,
             regime=None, prev_signal=None, prev_streak=0, days_to_earnings=None,
             regime_pct_above=None):
    """Generate a trading signal.

    prev_signal / prev_streak: the most recent stored signal and how many
    consecutive runs it has held. Used by the conviction streak gate.
    """
    reasons, override = [], None

    # No usable price this run -> not analysable. Emit an explicit "No data"
    # signal so a fetch failure can never masquerade as a Hold/Watch with a
    # bogus 0.00 price/stop/target sitting in the ranking.
    price = technical.get("price")
    if not price or price <= 0:
        return {"signal": "No data",
                "reasons": ["No usable price for this symbol this run — "
                            "excluded from ranking until the feed returns."],
                "confidence": 0, "confluence": 0, "confluence_dims": [],
                "streak": 1}

    if not shariah["eligible_for_ranking"]:
        override = "Avoid"
        reasons.append("Shariah status unverified — excluded by policy")

    if "breakdown" in risk["vetoes"]:
        prev = db.last_run(symbol)
        override = "Exit" if prev and prev.get("signal") in \
            ("Buy", "Strong Buy", "Hold") else "Avoid"
        reasons.append("Technical breakdown below support")

    if override:
        streak = (prev_streak + 1) if prev_signal == override else 1
        return {"signal": override, "reasons": reasons,
                "confidence": min(confidence, 60),
                "confluence": 0, "confluence_dims": [], "streak": streak}

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

    # ---- Hysteresis dead-band: a raw score grazing a band edge (e.g. 70.3 one
    # run, 69.7 the next) shouldn't flip the signal — that's scoring noise, not
    # a real change. Require crossing the threshold by HYSTERESIS_BAND points
    # before changing direction. Only acts on one-notch transitions; multi-notch
    # moves and hard vetoes (breakdown/shariah) bypass it. Applied BEFORE the
    # streak/confluence/chase gates so those still operate normally on top.
    _band = getattr(config, "HYSTERESIS_BAND", 0)
    if _band > 0 and prev_signal in ("Strong Buy", "Buy", "Watch", "Hold", "Avoid"):
        _RANK = {"Strong Buy": 4, "Buy": 3, "Watch": 2, "Hold": 1, "Avoid": 0}
        _pr, _br = _RANK.get(prev_signal), _RANK.get(base)
        _thr = {"Strong Buy": T["strong_buy"], "Buy": T["buy"],
                "Watch": T["watch"], "Hold": T["hold"]}
        if _pr is not None and _br is not None and abs(_pr - _br) == 1:
            if _pr > _br:
                # one-notch DOWNGRADE — only flip if score is decisively below
                # the threshold the previous signal sat above
                _t = _thr.get(prev_signal)
                if _t is not None and final_score >= _t - _band:
                    base = prev_signal
                    reasons.append(
                        f"Hysteresis: score {final_score} within {_band}-pt "
                        f"dead-band of {prev_signal} threshold ({_t}) — held at "
                        f"{prev_signal} until a decisive break")
            else:
                # one-notch UPGRADE — require clearing the new threshold by the
                # band, not just grazing it (avoids flapping the other way)
                _t = _thr.get(base)
                if _t is not None and final_score < _t + _band:
                    base = prev_signal
                    reasons.append(
                        f"Hysteresis: score {final_score} only just clears the "
                        f"{base} threshold ({_t}) — held at {prev_signal} until "
                        f"it breaks {_t + _band}+")

    # ---- Tier 2: streak gate (before confluence so we check intent, not result)
    # A new Strong Buy on its first appearance is held at Buy — the market has
    # to CONFIRM it on the next run. This prevents chasing a one-run spike.
    if base == "Strong Buy" and prev_signal != "Strong Buy":
        base = "Buy"
        reasons.append("Downgraded Strong Buy→Buy: first run at this level — "
                       "needs one more consecutive confirmation")

    # ---- Tier 2: confluence gate
    # Each of the 4 dimensions (trend/momentum/volume/structure) captures an
    # independent market mechanism. Requiring agreement across dimensions cuts
    # false positives from setups that score well on one dimension alone.
    confluence, conf_dims = _confluence(technical)
    if base == "Strong Buy" and confluence < 3:
        base = "Buy"
        missing = [d for d in ("trend", "momentum", "volume", "structure")
                   if d not in conf_dims]
        reasons.append(f"Downgraded Strong Buy→Buy: confluence {confluence}/4 "
                       f"(missing: {', '.join(missing)})")
    elif base == "Buy" and confluence < 2:
        base = "Watch"
        reasons.append(f"Downgraded Buy→Watch: confluence {confluence}/4 — "
                       "requires at least 2 dimensions (trend/momentum/volume/"
                       "structure) to agree before acting")

    # ---- Overextension (chase) guard: don't buy a stretched, parabolic move at
    # the peak — that's where profit-takers hand you the bag. Far above EMA20 or
    # very high 20-day momentum steps the signal down one notch and tells the user
    # to wait for the pullback the profit-taking creates. (The "thin room to
    # resistance" case is handled by the poor_rr veto in the soft downgrades.)
    _zlo, _zhi = technical.get("buy_zone_low"), technical.get("buy_zone_high")
    _zone = f" Buy-zone PKR {_zlo}–{_zhi} (pullback to 20-EMA)." if _zlo and _zhi else ""
    # Regime-aware chase guard. In a broad rally most names sit well above their
    # 20-EMA — treating that as "extended" would downgrade the whole leadership
    # group to Watch and make the engine miss the move. So in a confirmed risk-on
    # regime the chase thresholds widen (×extension_riskon_multiplier); only a
    # genuinely parabolic move is still stepped down. In neutral/risk-off the
    # guard stays tight. (technical['extended'] keeps its strict definition for the
    # buy-zone/accumulation logic; only the SIGNAL action adapts here.)
    _ext_pct = technical.get("ext_pct")
    _mom = technical.get("momentum_20d")
    # The widening scales with RALLY STRENGTH: ramp the multiplier linearly from
    # 1.0 (index just crossed above its 50-EMA — a shaky breakout, loosen barely)
    # up to the configured ceiling (index _full_pct above its EMA — a strong,
    # confirmed bull, loosen fully). A mild rally relaxes the guard a little; a
    # powerful one relaxes it a lot.
    _mult = 1.0
    if regime == "risk-on":
        _ceil = config.RISK.get("extension_riskon_multiplier", 1.0)
        _full = config.RISK.get("extension_riskon_full_pct", 8.0) or 8.0
        _strength = 1.0 if regime_pct_above is None else \
            max(0.0, min(1.0, regime_pct_above / _full))
        _mult = 1.0 + (_ceil - 1.0) * _strength
    _ext_lim = config.RISK["max_extension_pct"] * _mult
    _mom_lim = config.RISK["max_extension_momentum_pct"] * _mult
    _chase = ((_ext_pct is not None and _ext_pct > _ext_lim)
              or (_mom is not None and _mom > _mom_lim))
    _relaxed = (f" (chase guard ×{_mult:.2f} for risk-on rally)"
                if _mult > 1.0 else "")
    if _chase:
        if base == "Strong Buy":
            base = "Buy"; reasons.append(
                f"Downgraded Strong Buy→Buy: extended {_ext_pct}% "
                f"above EMA20{_relaxed} — chase risk, a pullback entry is safer.{_zone}")
        elif base == "Buy":
            base = "Watch"; reasons.append(
                f"Downgraded Buy→Watch: price extended above EMA20 (chase risk{_relaxed}) "
                f"— wait for a pullback before acting.{_zone}")

    # ---- soft downgrades (earnings, regime, risk, news, confidence)
    _earnings_soon = (days_to_earnings is not None
                      and 0 <= days_to_earnings <= config.EARNINGS_BLACKOUT_DAYS)
    _vetoed = False
    if base in ("Strong Buy", "Buy"):
        if _earnings_soon:
            base = "Watch"; _vetoed = True; reasons.append(
                f"Downgraded: earnings/result due in ~{days_to_earnings}d — binary "
                "event risk, don't open a fresh position into the announcement")
        elif config.REGIME_GATE_ENABLED and regime == "risk-off":
            base = "Watch"; _vetoed = True; reasons.append(
                f"Downgraded: market regime risk-off ({config.BENCHMARK_INDEX} below "
                f"its {config.REGIME_EMA_SPAN}-EMA) — don't buy into a falling market")
        elif "poor_rr" in risk["vetoes"]:
            base = "Watch"; _vetoed = True; reasons.append("Downgraded: risk/reward below minimum")
        elif "manipulation_risk" in risk["vetoes"]:
            base = "Watch"; _vetoed = True; reasons.append("Downgraded: hype/pump risk — verify first")
        elif "bad_news" in risk["vetoes"]:
            base = "Watch"; _vetoed = True; reasons.append("Downgraded: material negative news — "
                                           "verify the headline before acting")
        elif risk["risk_level"] == "High":
            base = "Watch"; _vetoed = True; reasons.append("Downgraded: overall risk level High")
        elif confidence < 45:
            base = "Watch"; _vetoed = True; reasons.append("Downgraded: confidence below 45% "
                                           "(weak data or poor history)")

    # ---- Pullback-entry upgrade (the safer entry), applied LAST so it is the
    # clean final word: turn a cooled-off Watch/Hold into a Buy when an established
    # uptrend has retraced into its 20-EMA buy-zone (the dip profit-takers create)
    # with structure intact. Stateless: once an extended name pulls back into the
    # zone, `extended` clears and pullback_ready turns True. Skipped when any real
    # veto fired above (regime/rr/news/manip/risk/confidence) so we never upgrade
    # into a known problem or print a self-contradicting reason.
    if (base in ("Watch", "Hold") and not _vetoed and not _earnings_soon
            and technical.get("pullback_ready") and confluence >= 2
            and not (config.REGIME_GATE_ENABLED and regime == "risk-off")
            and "poor_rr" not in risk["vetoes"]
            and "bad_news" not in risk["vetoes"]
            and "manipulation_risk" not in risk["vetoes"]
            and risk["risk_level"] != "High" and confidence >= 45):
        base = "Buy"
        reasons.append(f"Pullback entry: retraced into the 20-EMA buy-zone "
                       f"(PKR {_zlo}–{_zhi}) with the uptrend intact — lower-risk "
                       "entry than chasing the breakout.")

    if base in ("Strong Buy", "Buy"):
        reasons.append("Manual confirmation REQUIRED before placing any order")

    current_streak = (prev_streak + 1) if prev_signal == base else 1
    return {"signal": base, "reasons": reasons, "confidence": confidence,
            "confluence": confluence, "confluence_dims": conf_dims,
            "streak": current_streak,
            "buy_zone_low": technical.get("buy_zone_low"),
            "buy_zone_high": technical.get("buy_zone_high")}
