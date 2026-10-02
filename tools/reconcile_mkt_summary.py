"""Does PSX's mkt_summary download agree with the bars we already banked?

CLAUDE.md: reconcile source data before trusting it. For sessions banked from
the old /historical view, fetch the same session from mkt_summary and compare
open/high/low/close/volume for every tracked symbol. Read-only: writes nothing.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import psx_mkt_summary as ms

DAYS = sys.argv[1:] or ["2026-09-22", "2026-09-23"]
FIELDS = ("open", "high", "low", "close", "volume")


def main():
    c = sqlite3.connect(config.DB_PATH)
    total = {f: [0, 0] for f in FIELDS}
    for day in DAYS:
        try:
            bars = {b["symbol"]: b for b in ms.fetch_day(day)}
        except Exception as exc:
            print(f"{day}: FETCH FAILED {type(exc).__name__}: {exc}")
            continue
        print(f"\n=== {day}: {len(bars)} securities in the file")
        miss, diffs = [], []
        for sym in config.STOCKS:
            row = c.execute("SELECT open,high,low,close,volume,source FROM daily_ohlc "
                            "WHERE symbol=? AND date=?", (sym, day)).fetchone()
            if row is None:
                continue
            b = bars.get(sym)
            if b is None:
                miss.append(sym)
                continue
            for f, ours in zip(FIELDS, row[:5]):
                theirs = b[f]
                total[f][1] += 1
                tol = 0.5 if f == "volume" else 0.011
                if ours is not None and theirs is not None and abs(ours - theirs) <= tol:
                    total[f][0] += 1
                else:
                    diffs.append((sym, f, ours, theirs))
        print(f"    tracked symbols missing from the file: {miss or 'none'}")
        for d in diffs[:15]:
            print(f"    DIFF {d[0]:7s} {d[1]:6s} ours={d[2]} file={d[3]}")
        if len(diffs) > 15:
            print(f"    ... {len(diffs) - 15} more differences")
    print("\n=== AGREEMENT")
    for f, (ok, n) in total.items():
        print(f"    {f:6s} {ok}/{n}" + (f"  ({ok / n * 100:.1f}%)" if n else ""))
    print("\n=== sample, newest published session")
    for day in ("2026-09-29",):
        b = {x["symbol"]: x for x in ms.fetch_day(day)}
        for s in ("OGDC", "PSO", "HUBC", "LUCK", "MEBL"):
            print(f"    {day} {s}: {b.get(s)}")


if __name__ == "__main__":
    main()
