"""Reconcile suspect bars on an explicit runtime database, preserving originals.

Usage: python tools/reconcile_data.py --database PATH [--apply --max-dates 10]
Run migrate_runtime.py first. Never use the tracked database for reconciliation.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
import database as db
from data_quality import bar_error, source_priority


def candidates(path):
    with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True) as c:
        c.row_factory = sqlite3.Row
        return [dict(row) for row in c.execute('SELECT * FROM daily_ohlc ORDER BY date,symbol')
                if bar_error(dict(row)) or source_priority(row['source']) < 3]


def reconcile(path, max_dates=10):
    import psx_historical
    from session_calendar import last_completed
    if Path(path).resolve() == Path(config.BASE_DIR, 'psx_engine.db').resolve():
        raise ValueError('Use a verified backup at a separate runtime path')
    cutoff = last_completed()
    suspect = [b for b in candidates(path) if b['date'] <= cutoff]
    config.DB_PATH = str(path)
    db.init_db()
    dates = sorted({b['date'] for b in suspect}, reverse=True)[:max_dates]
    written = 0
    for day in dates:
        fetched = psx_historical.fetch_day(day)
        source_rows = {b['symbol']: b for b in fetched}
        with db.conn() as c:
            for old in [b for b in suspect if b['date'] == day]:
                new = source_rows.get(old['symbol'])
                if new is None:
                    continue  # absent is not evidence of a zero/flat replacement
                candidate = dict(new, date=day)
                if bar_error(candidate):
                    continue
                c.execute('INSERT INTO quarantined_bars(symbol,date,payload,reason) VALUES (?,?,?,?)',
                          (old['symbol'], day, json.dumps(old), 'Preserved before official reconciliation'))
        for old in [b for b in suspect if b['date'] == day]:
            new = source_rows.get(old['symbol'])
            if new:
                written += db.save_hl_bar(old['symbol'], day, new['open'], new['high'], new['low'], new['close'], new['volume'], psx_historical.SOURCE, True)
    return {'dates_requested': len(dates), 'bars_written': written, 'remaining_suspect': len(candidates(path))}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--max-dates', type=int, default=10)
    args = parser.parse_args()
    if args.apply:
        print(json.dumps(reconcile(args.database, args.max_dates), indent=2))
    else:
        rows = candidates(args.database)
        print(json.dumps({'suspect_bars': len(rows), 'dates': sorted({b['date'] for b in rows})}, indent=2))
