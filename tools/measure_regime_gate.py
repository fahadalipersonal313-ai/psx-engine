"""Re-measure the regime gate at the v5/v6/v7 30-session horizon.

Method is deliberately the SAME as the 2026-09-05 audit (dfba5ee), because the
point is comparability:

  - ABSOLUTE returns, not the same-day cross-sectional excess used elsewhere.
    A market-wide rule is differenced away exactly by a same-day benchmark.
  - The regime proxy is an equal-weight index of our own names (KMI30 is not
    stored historically), compounded from the MEAN daily return. Compounding
    the MEDIAN was the bug that produced the first, wrong answer.
  - Reported at BOTH the trade level and the session level. The session is the
    independent unit, but collapsing each session to one number weights a quiet
    3-candidate day the same as a busy 40-candidate day, which is what reversed
    the original result. Both are printed so the trade-off is visible.

Only the horizon differs: 10 sessions then, 30 now.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import config
import database as db

HORIZONS = (10, 30)


def panel():
    close, high, low, vol = {}, {}, {}, {}
    for s in config.STOCKS:
        bars = db.get_daily_ohlc(s, limit=100000)
        if len(bars) < 300:
            continue
        idx = [b["date"] for b in bars]
        close[s] = pd.Series([b["close"] for b in bars], index=idx, dtype=float)
        high[s] = pd.Series([b["high"] for b in bars], index=idx, dtype=float)
        low[s] = pd.Series([b["low"] for b in bars], index=idx, dtype=float)
        vol[s] = pd.Series([b["volume"] for b in bars], index=idx, dtype=float)
    f = lambda d: pd.DataFrame(d).sort_index()
    return f(close), f(high), f(low), f(vol)


def main():
    C, H, L, V = panel()
    print(f"panel: {C.shape[1]} symbols x {C.shape[0]} sessions "
          f"({C.index[0]} -> {C.index[-1]})")

    # --- regime proxy: equal-weight index, MEAN daily return, compounded -----
    ret = C.pct_change()
    idx_level = (1 + ret.mean(axis=1)).cumprod()
    ema = idx_level.ewm(span=config.REGIME_EMA_SPAN, adjust=False).mean()
    regime = pd.Series(np.where(idx_level >= ema, "risk-on", "risk-off"),
                       index=idx_level.index)
    regime.iloc[:config.REGIME_EMA_SPAN] = "unknown"      # not enough history
    vc = regime.value_counts()
    print(f"sessions: risk-on {vc.get('risk-on', 0)}, "
          f"risk-off {vc.get('risk-off', 0)}, unknown {vc.get('unknown', 0)}")

    # --- entry definition: the technical core the gate sits in front of -----
    e10 = C.ewm(span=10, adjust=False).mean()
    e20 = C.ewm(span=20, adjust=False).mean()
    e40 = C.ewm(span=40, adjust=False).mean()
    trend = (e10 > e20) & (e20 > e40) & (e40 > e40.shift(5))
    mom = C.pct_change(10) > 0

    # Chaikin money flow (20), the BUY_MIN_CMF input
    rng = (H - L).replace(0, np.nan)
    mfm = ((C - L) - (H - C)) / rng
    mfv = mfm * V
    cmf = mfv.rolling(20).sum() / V.rolling(20).sum().replace(0, np.nan)

    # v6 liquidity floor: median 20-day PKR turnover
    turnover = (C * V).rolling(20).median()

    entry = (trend & mom & (cmf >= config.BUY_MIN_CMF)
             & (turnover >= config.MIN_TURNOVER_PKR))
    print(f"entry rule: EMA10>20>40 rising, 10d momentum>0, "
          f"CMF>={config.BUY_MIN_CMF}, turnover>={config.MIN_TURNOVER_PKR:,.0f}")

    rows = []
    dates = list(C.index)
    for h in HORIZONS:
        fwd = C.shift(-h) / C - 1                       # ABSOLUTE forward return
        sel = entry & fwd.notna()
        for i, d in enumerate(dates):
            r = regime.iloc[i]
            if r == "unknown":
                continue
            picks = sel.columns[sel.iloc[i].values]
            if len(picks) == 0:
                continue
            vals = fwd.iloc[i][picks].astype(float)
            vals = vals[np.isfinite(vals)]
            if vals.empty:
                continue
            for sym, v in vals.items():
                rows.append((h, d, r, sym, float(v) * 100))

    df = pd.DataFrame(rows, columns=["h", "date", "regime", "symbol", "ret"])
    if df.empty:
        print("no entries — cannot measure")
        return

    for h in HORIZONS:
        sub = df[df.h == h]
        print(f"\n=== horizon {h} sessions "
              f"{'(v4 contract, comparable to 2026-09-05)' if h == 10 else '(v5/v6/v7 contract)'}")
        print(f"{'regime':10s}{'trades':>8s}{'sessions':>10s}{'mean%':>9s}"
              f"{'median%':>9s}{'p90%':>8s}{'win%':>7s}{'sess-mean%':>12s}")
        for r in ("risk-on", "risk-off"):
            s = sub[sub.regime == r]
            if s.empty:
                continue
            # session level: collapse each session to the mean of its candidates
            sess = s.groupby("date")["ret"].mean()
            print(f"{r:10s}{len(s):8d}{sess.size:10d}{s.ret.mean():9.2f}"
                  f"{s.ret.median():9.2f}{s.ret.quantile(0.9):8.2f}"
                  f"{(s.ret > 0).mean() * 100:7.1f}{sess.mean():12.2f}")
        on = sub[sub.regime == "risk-on"].ret
        off = sub[sub.regime == "risk-off"].ret
        if len(on) and len(off):
            print(f"  risk-on minus risk-off: trade mean "
                  f"{on.mean() - off.mean():+.2f}pp | opportunity ratio "
                  f"{len(on) / max(len(off), 1):.1f}x")
    downside_and_years(df)


def downside_and_years(df):
    """The 2026-09-05 audit turned on a trade-off: risk-off marginally safer on
    drawdown, risk-on more profitable. Check whether that still holds at 30."""
    for h in HORIZONS:
        sub = df[df.h == h]
        print(f"\n--- downside, horizon {h}")
        print(f"{'regime':10s}{'p10%':>8s}{'p25%':>8s}{'worst%':>9s}{'<-10%':>8s}")
        for r in ("risk-on", "risk-off"):
            s = sub[sub.regime == r].ret
            if s.empty:
                continue
            print(f"{r:10s}{s.quantile(0.10):8.2f}{s.quantile(0.25):8.2f}"
                  f"{s.min():9.2f}{(s < -10).mean() * 100:8.1f}")
    sub = df[df.h == 30].copy()
    sub["year"] = sub.date.str[:4]
    print("\n--- 30-session mean by year (trades in brackets)")
    print(f"{'year':6s}{'risk-on':>18s}{'risk-off':>18s}")
    for y, g in sub.groupby("year"):
        on, off = g[g.regime == "risk-on"].ret, g[g.regime == "risk-off"].ret
        f = lambda s: f"{s.mean():7.2f} ({len(s):5d})" if len(s) else f"{'—':>14s}"
        print(f"{y:6s}{f(on):>18s}{f(off):>18s}")


if __name__ == "__main__":
    main()
