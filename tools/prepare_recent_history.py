"""Prepare official history and a dated list of KMI All Share stocks below PKR 50.

Run against an isolated database copy before publishing it.
"""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
import config
import database as db
import psx_historical
import psx_market_watch
import ssl_compat
from data_quality import bar_error


def prepare(path, output):
    if Path(path).resolve() == (Path(__file__).resolve().parents[1] / 'psx_engine.db'):
        raise ValueError('Prepare an isolated database copy first')
    ssl_compat.enable()
    config.DB_PATH = str(path)
    session = requests.Session()
    response = session.get(psx_market_watch.URL, headers=psx_market_watch.HEADERS, timeout=30)
    response.raise_for_status()
    names, rows = psx_market_watch.parse(response.text)
    if not {'listed', 'symbol', 'close', 'sector'}.issubset(names):
        raise ValueError('PSX membership columns missing')
    selected = [r for r in rows if 'KMIALLSHR' in r['listed']
                and 0 < float(r['close']) < 50]
    for row in selected:
        row['display_symbol'] = row['symbol']
        row['symbol'] = row['symbol'].split()[0]
    if not selected:
        raise ValueError('No verified lower-price stocks returned')
    symbols = sorted({s.split()[0] for s in config.STOCKS} | {r['symbol'] for r in selected})
    # 42 sessions to form each signal, followed by one month of dates to test.
    dates = [r['date'] for r in db.get_eod_history(config.BENCHMARK_INDEX, 64)]
    written = 0
    for day in dates:
        for attempt in range(3):
            try:
                bars = psx_historical.fetch_day(day, session)
                if not bars:
                    raise ValueError('No official rows for benchmark session ' + day)
                break
            except (requests.RequestException, ValueError):
                if attempt == 2:
                    raise
                time.sleep(2)
        for b in bars:
            b['symbol'] = b['symbol'].split()[0]
            if b['symbol'] not in symbols or bar_error(dict(b, date=day)):
                continue
            with db.conn() as c:
                old = c.execute('SELECT * FROM daily_ohlc WHERE symbol=? AND date=?', (b['symbol'], day)).fetchone()
                if old and old['source'] != psx_historical.SOURCE:
                    c.execute('INSERT INTO quarantined_bars(symbol,date,payload,reason) VALUES (?,?,?,?)',
                              (b['symbol'], day, json.dumps(dict(old)), 'Preserved before history repair'))
            written += db.save_hl_bar(b['symbol'], day, b['open'], b['high'], b['low'], b['close'], b['volume'], psx_historical.SOURCE, True)
        print(day, 'written', written, flush=True)
        time.sleep(.2)
    from session_calendar import local_now
    payload = {'verified_on': local_now().date().isoformat(), 'price_limit_pkr': 50,
               'source': psx_market_watch.URL, 'price_date': dates[-1],
               'stocks': selected, 'history_start': dates[0], 'history_end': dates[-1]}
    Path(output).write_text(json.dumps(payload, indent=2), encoding='utf-8')
    print('Selected', len(selected), 'lower-price stocks;', len(symbols), 'total symbols', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    prepare(args.database, args.output)
