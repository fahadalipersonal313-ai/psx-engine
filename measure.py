"""measure.py — Cohort measurement with an INDEPENDENCE report attached.

Every win rate this repo has ever trusted came from splitting stored rows into
a cohort and comparing forward moves to the same-day universe median. The
failure mode that survived all of it: a cohort can look spectacular while being
one event counted many times.

Worked example (2026-08-17): candidates with a stretched RSI beat the market
94% over 3 days and 100% over 7, median excess +8.71%. The bucket was 17 rows
drawn from TWO symbols (PRL, NRL), both refineries, over 13 overlapping days of
one policy rally. Not an edge — one trade, replayed.

So `cohort()` never returns a win rate on its own. It returns the win rate WITH
distinct symbols, distinct sectors, the largest single-symbol share and the date
span, plus a verdict that says out loud when the sample is too concentrated to
mean anything.

Day-dedupe is mandatory and automatic: 15-min polling inflates raw counts ~20x.
"""

import statistics as st

import config
import database as db

# A cohort needs at least this much spread before its win rate is worth reading.
MIN_ROWS = 20
MIN_SYMBOLS = 5
MIN_SECTORS = 3
MAX_SYMBOL_SHARE = 0.40      # no single symbol may be >40% of the sample
MAX_SECTOR_SHARE = 0.60


def load(day_dedupe=True):
    """Stored rows with a forward price, one per symbol per day."""
    with db.conn() as c:
        rows = [dict(r) for r in c.execute(
            """SELECT run_time, symbol, final_score, relative_strength, cmf,
                      confluence, tech_flags, signal, price, price_3d, price_7d
               FROM runs WHERE strategy_version IS NULL AND price IS NOT NULL ORDER BY run_time DESC, id DESC""")]
    if not day_dedupe:
        return rows
    seen = {}
    for r in rows:
        seen.setdefault((r["symbol"], r["run_time"][:10]), r)
    return list(seen.values())


def _cohort_median(rows, days):
    """Same-day median forward move across the whole universe — the benchmark a
    cohort has to beat. Controls for the market regime."""
    key = f"price_{days}d"
    by = {}
    for r in rows:
        if r.get(key) and r.get("price"):
            by.setdefault(r["run_time"][:10], []).append(r[key] / r["price"] - 1)
    return {d: st.median(v) for d, v in by.items() if len(v) >= 5}


def independence(sub):
    """How many genuinely separate bets is this sample? Returns the counts plus
    a list of reasons the sample cannot support a conclusion."""
    n = len(sub)
    syms = [r["symbol"] for r in sub]
    secs = [config.SECTORS.get(s, "Unknown") for s in syms]
    days = sorted({r["run_time"][:10] for r in sub})
    top_sym = max((syms.count(s) for s in set(syms)), default=0)
    top_sec = max((secs.count(s) for s in set(secs)), default=0)
    warnings = []
    if n < MIN_ROWS:
        warnings.append(f"only {n} rows (want >= {MIN_ROWS})")
    if len(set(syms)) < MIN_SYMBOLS:
        warnings.append(f"only {len(set(syms))} distinct symbols "
                        f"(want >= {MIN_SYMBOLS})")
    if len(set(secs)) < MIN_SECTORS:
        warnings.append(f"only {len(set(secs))} distinct sectors "
                        f"(want >= {MIN_SECTORS})")
    if n and top_sym / n > MAX_SYMBOL_SHARE:
        warnings.append(f"one symbol is {top_sym / n:.0%} of the sample")
    if n and top_sec / n > MAX_SECTOR_SHARE:
        warnings.append(f"one sector is {top_sec / n:.0%} of the sample")
    if len(days) > 1:
        span = (days[-1], days[0])
        # Consecutive days with a 3/7-day forward window overlap heavily, so
        # neighbouring rows are re-measuring the same move.
        if len(days) > 3 and len(set(syms)) < MIN_SYMBOLS:
            warnings.append("consecutive days on few symbols — forward windows "
                            "overlap, so rows are not independent")
    return {"n": n, "symbols": len(set(syms)), "sectors": len(set(secs)),
            "days": len(days), "span": (days[0], days[-1]) if days else None,
            "top_symbol_share": (top_sym / n) if n else 0,
            "top_sector_share": (top_sec / n) if n else 0,
            "warnings": warnings,
            "trustworthy": not warnings}


def cohort(sub, universe, days=3):
    """Beat rate + median excess vs the same-day universe median, WITH the
    independence report. Never returns a bare win rate."""
    med = _cohort_median(universe, days)
    key = f"price_{days}d"
    ex, used = [], []
    for r in sub:
        d = r["run_time"][:10]
        if r.get(key) and r.get("price") and d in med:
            ex.append((r[key] / r["price"] - 1) - med[d])
            used.append(r)
    ind = independence(used)
    if not ex:
        return {"days": days, "n": 0, "beat_pct": None, "median_excess_pct": None,
                "independence": ind}
    return {"days": days, "n": len(ex),
            "beat_pct": sum(1 for e in ex if e > 0) / len(ex) * 100,
            "median_excess_pct": st.median(ex) * 100,
            "independence": ind}


def render(label, res):
    ind = res["independence"]
    if not res["n"]:
        return f"{label}: no gradable rows."
    head = (f"{label}\n"
            f"  {res['days']}d: n={res['n']}  beat {res['beat_pct']:.1f}%  "
            f"median excess {res['median_excess_pct']:+.2f}%\n"
            f"  spread: {ind['symbols']} symbols, {ind['sectors']} sectors, "
            f"{ind['days']} days"
            + (f" ({ind['span'][0]} .. {ind['span'][1]})" if ind["span"] else ""))
    if ind["warnings"]:
        head += "\n  NOT TRUSTWORTHY — " + "; ".join(ind["warnings"])
        head += "\n  Treat this as one event replayed, not an edge."
    else:
        head += "\n  independence OK"
    return head
