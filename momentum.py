"""momentum.py — Momentum-burst detector.

A burst is one session that breaks out of a stock's own recent behaviour: a
large single-day advance carried by volume well above its 20-day norm. It is
computed from `daily_ohlc` (real H/L/C bars), so it needs no extra fetch and
adds no write path to `full_run`.

MEASURED before it was built (2026-08-17, day-deduped, forward move vs the
same-day cohort median, independence-checked via measure.py):

    burst (>=3% on >=1.5x volume)   3d  n=42  beat 83.3%  excess +2.54%
                                    7d  n=35  beat 71.4%  excess +1.92%
      spread 26 symbols / 14 sectors (3d), 24 / 13 (7d) — independence OK

Both horizons agree and neither is one sector's rally, which is more than can be
said for most ideas tried on this data (score velocity 45%, OBV divergence
negative, accumulation heuristics no edge).

The stricter variant that ALSO requires a 20-day closing high scored 91.3% at
3 days, but its 7-day sample is 16 rows and 69% one sector — so `at_high` is
carried as a TAG, not part of the trigger. Do not promote it without more data.

This is a WATCH tier, not a signal. It never becomes a Buy: the audit in
CLAUDE.md showed the gate layer selecting the worst subset of a pool that had
edge, so new findings are surfaced, not wired into the score.
"""

import logging

import config
import database as db

log = logging.getLogger("momentum")

MIN_GAIN_PCT = 3.0      # single-session advance
MIN_VOL_MULT = 1.5      # vs the 20-day average volume
LOOKBACK = 20           # window for the volume norm and the high tag


def _series(symbol, limit=60):
    with db.conn() as c:
        rows = [dict(r) for r in c.execute(
            """SELECT date, close, volume FROM daily_ohlc
               WHERE symbol=? ORDER BY date DESC LIMIT ?""", (symbol, limit))]
    return list(reversed(rows))


def detect(symbol):
    """Burst dict for the most recent bar, or None. Never raises on thin data."""
    s = _series(symbol)
    if len(s) < LOOKBACK + 2:
        return None
    last, prev = s[-1], s[-2]
    if not (last["close"] and prev["close"] and last["volume"]):
        return None
    gain = (last["close"] / prev["close"] - 1) * 100
    window = s[-(LOOKBACK + 1):-1]
    vols = [b["volume"] for b in window if b["volume"]]
    if not vols:
        return None
    vavg = sum(vols) / len(vols)
    mult = last["volume"] / vavg if vavg else 0
    if gain < MIN_GAIN_PCT or mult < MIN_VOL_MULT:
        return None
    highs = [b["close"] for b in window if b["close"]]
    return {"symbol": symbol, "date": last["date"], "gain_pct": gain,
            "vol_mult": mult, "close": last["close"],
            # Stronger at 3 days but unconfirmed at 7 — a tag, not a trigger.
            "at_high": bool(highs and last["close"] >= max(highs))}


def scan(symbols=None):
    """Bursts across the universe, strongest advance first."""
    out = []
    for sym in (symbols or config.STOCKS):
        try:
            b = detect(sym)
        except Exception as e:                      # never break a caller
            log.warning("burst scan failed for %s: %s", sym, e)
            continue
        if b:
            latest = db.last_run(sym)
            b["signal"] = (latest or {}).get("signal")
            b["final_score"] = (latest or {}).get("final_score")
            b["sector"] = config.SECTORS.get(sym, "")
            out.append(b)
    return sorted(out, key=lambda x: -x["gain_pct"])
