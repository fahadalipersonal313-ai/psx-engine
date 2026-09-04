"""event_library.py — every large move in five years, decomposed and remembered.

Detects shocks in the banked daily history, splits each into market / sector /
stock-specific (market_factors), records the setup that preceded it and what
happened afterwards, and stores the lot in `events`.

Why this is the foundation rather than another indicator: 50 symbols x ~1,240
sessions is ~62,000 stock-days, so the shock sample is several times larger than
the engine's entire graded signal history (154 Buys at 3 days). It is also
independent of it — built from price history, not from what the engine happened
to emit.

NOTHING HERE TOUCHES A SIGNAL. It is a library to query and to measure. On this
repo's record every unmeasured input that looked meaningful measured flat or
negative, and the emitted-Buy cohort beat the market 36% while the pool it came
from beat it 63%.

Forward returns are stored EXCESS of the same-day universe median, because a
raw forward return mostly measures the market. That is the same correction the
backtester's grading already applies.
"""

import logging
from datetime import datetime

import numpy as np
import pandas as pd

import config
import market_factors as mf
import corporate_actions as ca

log = logging.getLogger("event_library")

SIGMA_WINDOW = 60          # trailing window for the stock's own volatility
SIGMA_TRIGGER = 2.5        # a move this many sigma is a shock
ABS_FLOOR_PCT = 3.0        # ...and must clear this, so quiet names don't spam
FORWARD_DAYS = (1, 3, 5, 10, 20)
VOL_WINDOW = 20


def _rsi(close, period=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def build(db, symbols=None):
    """Scan the banked history and return a list of event dicts."""
    panel = mf.load_panel(db, symbols)
    if not panel:
        log.warning("no banked history — nothing to scan")
        return []
    close, high, low = panel["close"], panel["high"], panel["low"]
    openp, volume = panel["open"], panel["volume"]
    # A bar that closed at the circuit is frequently unfillable — no counterparty
    # at that price — so it is recorded and excluded from tradeable, never
    # silently treated as an entry you could have taken.
    at_limit = ca.at_limit_mask(panel)
    turn = ca.turnover(panel).shift(1)
    d = mf.decompose(panel)
    ret, market = d["ret"], d["market"]

    # Everything below is shifted so the trigger day never informs its own
    # thresholds or context — the difference between a library and a fitted curve.
    sigma = ret.rolling(SIGMA_WINDOW, min_periods=30).std().shift(1)
    ema50 = close.ewm(span=50, adjust=False).mean().shift(1)
    mom20 = close.pct_change(20).shift(1)
    mom60 = close.pct_change(60).shift(1)
    mkt60 = (1 + market).rolling(60).apply(np.prod, raw=True).shift(1) - 1
    vol_med = volume.rolling(VOL_WINDOW, min_periods=10).median().shift(1)
    rsi = _rsi(close).shift(1)
    tr = pd.concat([(high - low),
                    (high - close.shift()).abs(),
                    (low - close.shift()).abs()]).groupby(level=0).max()
    atr = tr.rolling(14, min_periods=7).mean().shift(1)
    hi52 = close.rolling(250, min_periods=60).max().shift(1)
    lo52 = close.rolling(250, min_periods=60).min().shift(1)

    # Forward EXCESS return: the stock's move minus the universe's, same window.
    fwd = {}
    for n in FORWARD_DAYS:
        stock_fwd = close.shift(-n) / close - 1
        # The benchmark is the SAME-DAY cross-sectional median of n-day forward
        # returns — not the compounded median daily return. Compounding a median
        # daily return understates a real stock's path (a volatility artifact),
        # which put the unconditional baseline at +0.58% / 57% over 5 days and
        # made every event class look profitable. Measured like-for-like the
        # baseline is 0% / 50% by construction, so any edge shown is real edge.
        # .sub(axis=0) is mandatory: `DataFrame - Series` aligns the Series index
        # against COLUMNS, which silently produced all-NaN forward returns.
        fwd[n] = stock_fwd.sub(stock_fwd.median(axis=1), axis=0)

    events = []
    for sym in ret.columns:
        r, sg = ret[sym], sigma[sym]
        trig = (r.abs() >= SIGMA_TRIGGER * sg) & (r.abs() * 100 >= ABS_FLOOR_PCT)
        for dt in r.index[trig.fillna(False)]:
            rv = float(r.loc[dt])
            mc = float(d["mkt_contrib"].at[dt, sym]) if pd.notna(d["mkt_contrib"].at[dt, sym]) else None
            sc = float(d["sec_contrib"].at[dt, sym]) if pd.notna(d["sec_contrib"].at[dt, sym]) else None
            rs_ = float(d["residual"].at[dt, sym]) if pd.notna(d["residual"].at[dt, sym]) else None
            if mc is None or rs_ is None:
                continue                     # no betas yet: not enough history
            cls = mf.classify(rv, mc, sc, rs_)
            if not cls:
                continue

            def g(frame, default=None):
                v = frame.at[dt, sym] if sym in frame.columns else None
                return float(v) if v is not None and pd.notna(v) else default

            c = float(close.at[dt, sym])
            h, l_, o = g(high), g(low), g(openp)
            prev_c = float(close[sym].shift(1).at[dt]) if pd.notna(close[sym].shift(1).at[dt]) else None
            a = g(atr)
            e50, hh, ll = g(ema50), g(hi52), g(lo52)
            vm = g(vol_med)
            m60 = g(mom60)
            k60 = float(mkt60.at[dt]) if pd.notna(mkt60.at[dt]) else None

            ev = {
                "symbol": sym, "date": dt.strftime("%Y-%m-%d"),
                "sector": config.SECTORS.get(sym, "Unknown"),
                "ret_pct": round(rv * 100, 3),
                "sigma_move": round(rv / float(sg.loc[dt]), 2) if sg.loc[dt] else None,
                "direction": "up" if rv > 0 else "down",
                # the decomposition — the whole point of the exercise
                "market_pct": round(mc * 100, 3),
                "sector_pct": round(sc * 100, 3) if sc is not None else None,
                "idio_pct": round(rs_ * 100, 3),
                "cause_class": cls,
                "has_sector_peers": bool(d["has_sector"].at[dt, sym]),
                # the setup that preceded it
                "gap_pct": round((o / prev_c - 1) * 100, 3) if o and prev_c else None,
                "close_position": (round((c - l_) / (h - l_), 3)
                                   if h is not None and l_ is not None and h > l_ else None),
                "range_atr": round((h - l_) / a, 2) if h and l_ and a else None,
                "vol_ratio": round(float(volume.at[dt, sym]) / vm, 2) if vm else None,
                "trend_50_pct": round((c / e50 - 1) * 100, 2) if e50 else None,
                "mom_20_pct": round(float(mom20.at[dt, sym]) * 100, 2) if pd.notna(mom20.at[dt, sym]) else None,
                "rs_60_pct": round((m60 - k60) * 100, 2) if m60 is not None and k60 is not None else None,
                "rsi_14": round(g(rsi), 1) if g(rsi) else None,
                "range_52w_pos": (round((c - ll) / (hh - ll), 3)
                                  if hh is not None and ll is not None and hh > ll else None),
                # tradeability — the difference between a backtest and a trade
                "at_limit": bool(at_limit.at[dt, sym]),
                "turnover_pkr": (round(float(turn.at[dt, sym]))
                                 if pd.notna(turn.at[dt, sym]) else None),
                "tradeable": bool(not at_limit.at[dt, sym]
                                  and pd.notna(turn.at[dt, sym])
                                  and float(turn.at[dt, sym]) >= config.MIN_TURNOVER_PKR),
                # cause label — filled later by research, never invented here
                "cause_label": None, "cause_source": None,
            }
            for n in FORWARD_DAYS:
                v = fwd[n].at[dt, sym]
                ev[f"fwd_{n}d_excess"] = round(float(v) * 100, 3) if pd.notna(v) else None
            events.append(ev)

    log.info("Detected %d events across %d symbols", events and len(events) or 0,
             len(ret.columns))
    return events


def shock_up_today(bars):
    """Did this symbol just print a shock up-move? -> (bool, pct, sigma).

    `bars` are oldest-first daily OHLC dicts. Uses the same trigger as the
    library, and the same one-day shift: the sigma is measured on history
    ENDING YESTERDAY, so today's move never sets its own threshold.
    """
    if not config.SHOCK_UP_DEFER_ENABLED or len(bars) < 32:
        return False, None, None
    closes = pd.Series([b["close"] for b in bars if b.get("close")], dtype=float)
    if len(closes) < 32:
        return False, None, None
    r = closes.pct_change()
    sigma = r.iloc[-(SIGMA_WINDOW + 1):-1].std()
    today = r.iloc[-1]
    if not np.isfinite(sigma) or sigma <= 0 or not np.isfinite(today):
        return False, None, None
    hit = (today >= config.SHOCK_UP_SIGMA * sigma
           and today * 100 >= config.SHOCK_UP_MIN_PCT)
    return bool(hit), round(float(today) * 100, 2), round(float(today / sigma), 2)


def summarise(events):
    """Independence-aware summary. A win rate with no symbol/sector spread is
    the failure measure.py exists to catch, so it is never printed alone."""
    if not events:
        return "no events"
    df = pd.DataFrame(events)
    n_lim = int(df.at_limit.sum()) if "at_limit" in df else 0
    n_ill = int((~df.tradeable.astype(bool)).sum()) - n_lim if "tradeable" in df else 0
    out = [f"{len(df)} events, {df.symbol.nunique()} symbols, "
           f"{df.sector.nunique()} sectors, {df.date.min()} .. {df.date.max()}",
           f"excluded from tradeable: {n_lim} at the circuit limit, "
           f"{max(n_ill, 0)} below PKR {config.MIN_TURNOVER_PKR:,} turnover", ""]
    if "tradeable" in df:
        df = df[df.tradeable.astype(bool)]
        out.append(f"TRADEABLE ONLY: {len(df)} events")
    out.append(f"{'cause':16s}{'dir':6s}{'n':>6s}{'syms':>6s}{'sects':>6s}"
               f"{'med 5d excess':>15s}{'positive':>10s}{'top sym share':>15s}")
    for (cls, dirn), g in df.groupby(["cause_class", "direction"]):
        f5 = g["fwd_5d_excess"].dropna()
        if f5.empty:
            continue
        share = g.symbol.value_counts(normalize=True).iloc[0]
        flag = "" if (len(g) >= 20 and g.symbol.nunique() >= 5
                      and g.sector.nunique() >= 3 and share <= 0.40) else "  NOT TRUSTWORTHY"
        out.append(f"{cls:16s}{dirn:6s}{len(g):6d}{g.symbol.nunique():6d}"
                   f"{g.sector.nunique():6d}{f5.median():14.2f}%"
                   f"{(f5 > 0).mean() * 100:9.0f}%{share * 100:14.0f}%{flag}")
    return "\n".join(out)


def for_symbol(db, symbol, limit=12):
    """One symbol's own shock history, most recent first — what has actually
    moved this stock, and what followed."""
    rows = db.get_events(symbol=symbol, limit=limit)
    if not rows:
        return f"{symbol}: no events detected"
    out = [f"{symbol} — {len(rows)} most recent shocks",
           f"{'date':12s}{'move':>8s}{'cause':>15s}{'mkt':>8s}{'sect':>8s}"
           f"{'idio':>8s}{'fwd5d':>8s}  label"]
    for r in rows:
        f5 = r["fwd_5d_excess"]
        out.append(f"{r['date']:12s}{r['ret_pct']:+7.2f}%{r['cause_class']:>15s}"
                   f"{r['market_pct']:+7.2f}%"
                   f"{(r['sector_pct'] if r['sector_pct'] is not None else 0):+7.2f}%"
                   f"{r['idio_pct']:+7.2f}%"
                   f"{(f'{f5:+.2f}%' if f5 is not None else '—'):>8s}"
                   f"  {r['cause_label'] or ''}")
    return "\n".join(out)


def main():
    import database as db
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    db.init_db()
    import sys
    if len(sys.argv) > 1:
        print(for_symbol(db, sys.argv[1].upper()))
        return
    events = build(db)
    stored = db.save_events(events)
    print(f"detected {len(events)} events, {stored} newly stored\n")
    print(summarise(events))
    print("\nUNMEASURED and wired into nothing. cause_label is NULL until real "
          "research fills it — a cause is never inferred from price alone.")


if __name__ == "__main__":
    main()
