"""corporate_actions.py — find the splits and bonus issues hiding as crashes.

PSX serves UNADJUSTED prices, so a 1:6 bonus arrives in the data as a -14.3%
"loss" and a 1:10 split as -88%. Left alone these become the largest
"idiosyncratic shocks" in the event library, and they poison every long-horizon
return, drawdown and volatility computed across them.

Detection rests on an exchange rule rather than a guess: **PSX runs a +-10%
circuit breaker** (confirmed live — NRL prev close 517.58, limits 465.82 /
569.34, exactly +-10%). A single-session move beyond that is mechanically
impossible in ordinary trading, so it is a corporate action, a data error, or a
resumption after suspension.

The two directions are NOT symmetric, and treating them alike would be wrong:
  * DOWN beyond the limit -> a bonus, split or rights issue. All of them cut the
    price. Adjust.
  * UP beyond the limit -> ambiguous. Newly listed scrips trade without a circuit
    for their first sessions, some scrips carry narrower limits, and a
    resumption after suspension can gap up. Never adjusted; only flagged, so a
    real event is not silently rewritten.

Raw prices are never modified. Actions are stored and the adjustment is applied
ON READ, so the exchange's own record stays intact and any mistake here is
reversible.
"""

import logging

import numpy as np
import pandas as pd

import config

log = logging.getLogger("corporate_actions")

LIMIT_PCT = getattr(config, "CIRCUIT_LIMIT_PCT", 10.0)
DETECT_PCT = LIMIT_PCT + 0.5          # small buffer over the circuit
LIMIT_TOL = 0.3                       # "at the limit" band, for flagging


def detect(panel):
    """-> list of {symbol, ex_date, ratio, factor, kind}.

    `ratio` is close_after / close_before. `factor` is what historical prices
    must be MULTIPLIED by to sit on the post-action scale.
    """
    close = panel["close"]
    r = close.pct_change() * 100
    out = []
    for sym in close.columns:
        s = r[sym].dropna()
        for dt, pct in s[s.abs() > DETECT_PCT].items():
            ratio = 1 + pct / 100
            out.append({
                "symbol": sym, "ex_date": dt.strftime("%Y-%m-%d"),
                "ratio": round(float(ratio), 6),
                "factor": round(float(ratio), 6) if pct < 0 else None,
                # An implied 7/6 or 10/9 is the fingerprint of a 1:6 or 10%
                # bonus; it is recorded for eyeballing, never used to decide.
                "implied": round(1 / float(ratio), 4),
                "kind": "price_cut" if pct < 0 else "unexplained_gap_up",
                "pct": round(float(pct), 3),
            })
    log.info("Detected %d beyond-circuit moves (%d adjustable price cuts)",
             len(out), sum(1 for a in out if a["factor"]))
    return out


def adjust(panel, actions):
    """Back-adjust prices for every detected price cut. Returns a NEW panel.

    Prices before an ex-date are multiplied by the ratio so the series is
    continuous on today's scale; volume is divided by it, because a split
    multiplies the share count and raw historical volume would otherwise look
    artificially small. Only `price_cut` actions are applied — an unexplained
    gap up is left exactly as the exchange reported it.
    """
    if not actions:
        return panel
    close = panel["close"]
    factors = pd.DataFrame(1.0, index=close.index, columns=close.columns)
    applied = 0
    for a in actions:
        if not a["factor"] or a["symbol"] not in close.columns:
            continue
        ex = pd.Timestamp(a["ex_date"])
        # everything strictly BEFORE the ex-date moves onto the new scale
        factors.loc[factors.index < ex, a["symbol"]] *= a["factor"]
        applied += 1
    out = {}
    for field in ("open", "high", "low", "close"):
        out[field] = panel[field] * factors
    out["volume"] = panel["volume"] / factors
    log.info("Applied %d price-cut adjustments", applied)
    return out


def at_limit_mask(panel):
    """True where the session closed at the circuit limit. Those bars are often
    unfillable — there is frequently no counterparty — so a signal generated on
    one is not a trade you could have taken."""
    r = panel["close"].pct_change() * 100
    return (r.abs() >= LIMIT_PCT - LIMIT_TOL) & (r.abs() <= LIMIT_PCT + LIMIT_TOL)


def turnover(panel, window=20):
    """Rolling median daily turnover in PKR — the only honest read on whether a
    name is tradeable at a given size."""
    return (panel["close"] * panel["volume"]).rolling(window, min_periods=10).median()


def main():
    import database as db
    import market_factors as mf
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    db.init_db()
    panel = mf.load_panel(db, adjust=False)
    actions = detect(panel)
    stored = db.save_corporate_actions(actions)
    cuts = [a for a in actions if a["factor"]]
    print(f"detected {len(actions)} beyond-circuit moves, {stored} newly stored")
    print(f"  adjustable price cuts : {len(cuts)}")
    print(f"  unexplained gap-ups   : {len(actions) - len(cuts)} (flagged, NOT adjusted)\n")
    print(f"{'symbol':8s}{'ex_date':12s}{'move':>9s}{'implied':>9s}  note")
    for a in sorted(cuts, key=lambda x: x["pct"])[:15]:
        print(f"{a['symbol']:8s}{a['ex_date']:12s}{a['pct']:8.2f}%{a['implied']:9.3f}  "
              f"{'~' + str(round(a['implied'], 2)) + 'x shares'}")
    lim = at_limit_mask(panel)
    print(f"\nbars closing AT the +-{LIMIT_PCT}% circuit: {int(lim.sum().sum()):,} "
          f"of {int(panel['close'].notna().sum().sum()):,}")


if __name__ == "__main__":
    main()
