"""Current-session Watch ideas. No writes to daily bars or decision history."""
import concurrent.futures
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

import requests
import config
import database as db
import momentum
import session_calendar as calendar
import shariah_checker
from data_quality import bar_error, source_priority

PATH = Path('intraday_momentum.json')


def detect(symbol, ticks, history, now):
    today = calendar.local_now(now).date().isoformat()
    rows = []
    for tick in ticks:
        ts, price, volume = map(float, tick[:3])
        if not all(math.isfinite(x) for x in (ts, price, volume)) or price <= 0 or volume < 0:
            raise ValueError('Invalid intraday trade')
        at = datetime.fromtimestamp(ts, timezone.utc)
        if at > now:
            raise ValueError('Future intraday trade')
        if calendar.local_now(at).date().isoformat() == today:
            rows.append((at, price, volume))
    if not rows:
        return None
    rows.sort()
    at, price, _ = rows[-1]
    if (now - at).total_seconds() > 1200:
        return None
    prior = [x for x in history if x['date'] < today][-20:]
    if len(prior) != 20 or prior[-1]['date'] != calendar.last_completed(datetime.combine(calendar.local_now(now).date(), datetime.min.time(), calendar.PKT)):
        return None
    if any(bar_error(x) or source_priority(x.get('source')) < 3 or x['volume'] <= 0 for x in prior):
        return None
    if not shariah_checker.check(symbol)['eligible_for_ranking']:
        return None
    if any(abs(b['close'] / a['close'] - 1) > .105 for a, b in zip(prior, prior[1:])):
        return None
    turnover = statistics.median(x['close'] * x['volume'] for x in prior)
    if turnover < momentum.MIN_TURNOVER:
        return None
    gain = (price / prior[-1]['close'] - 1) * 100
    if abs(gain) > 10.5:
        return None  # possible unadjusted corporate action; do not invent a gain
    # Conservative: volume SO FAR must exceed a full day's average. No assumed
    # volume curve, Friday extrapolation, or historical success rate for live calls.
    multiple = sum(x[2] for x in rows) / statistics.mean(x['volume'] for x in prior)
    if gain < momentum.MIN_GAIN_PCT or multiple < momentum.MIN_VOL_MULT:
        return None
    return {'symbol': symbol, 'gain_pct': gain, 'vol_mult': multiple,
            'price': price, 'last_trade': at.isoformat(), 'date': today}


def collect(now=None):
    now = now or datetime.now(timezone.utc)
    day = calendar.local_now(now).date().isoformat()
    result = {'session': day, 'checked_at': now.isoformat(), 'source': 'PSX DPS intraday',
              'checked': 0, 'fresh': 0, 'failed': [], 'items': []}
    with db.conn() as c:
        history = {s: [dict(x) for x in c.execute(
            'SELECT * FROM daily_ohlc WHERE symbol=? AND date<? ORDER BY date DESC LIMIT 20', (s, day))][::-1]
            for s in config.STOCKS}
    def fetch(symbol):
        response = requests.get(config.PSX_INTRADAY_URL.format(symbol=symbol), timeout=15)
        response.raise_for_status()
        ticks = response.json()['data']
        checked = datetime.now(timezone.utc)
        candidate = detect(symbol, ticks, history[symbol], checked)
        last = datetime.fromtimestamp(max(float(t[0]) for t in ticks), timezone.utc) if ticks else None
        fresh = bool(last and calendar.local_now(last).date().isoformat() == day
                     and 0 <= (checked-last).total_seconds() <= 1200)
        return candidate, fresh
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch, s): s for s in config.STOCKS}
        for future in concurrent.futures.as_completed(futures):
            symbol = futures[future]
            try:
                row, fresh = future.result()
                result['checked'] += 1
                result['fresh'] += int(fresh)
                if row:
                    result['items'].append(row)
            except Exception:
                result['failed'].append(symbol)
    result['items'].sort(key=lambda x: -x['gain_pct'])
    PATH.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(f"Intraday scan {day}: {result['checked']}/{len(config.STOCKS)} checked; {len(result['items'])} candidates; {len(result['failed'])} failed")
    return result


def show(st, now=None):
    now = now or datetime.now(timezone.utc)
    st.markdown('### ⚡ Momentum now — current-session watch')
    try:
        data = json.loads(PATH.read_text(encoding='utf-8'))
        age = (now - datetime.fromisoformat(data['checked_at'])).total_seconds()
        if data['session'] != calendar.local_now(now).date().isoformat() or not 0 <= age <= 1200:
            raise ValueError('Capture is old')
    except (OSError, ValueError, KeyError):
        st.info('No fresh current-session scan. Earlier-session stocks are shown separately below.')
        return
    items = [x for x in data['items'] if 0 <= (now - datetime.fromisoformat(x['last_trade'])).total_seconds() <= 1200]
    st.caption(f"Checked {age/60:.0f} minutes ago · {data['checked']}/{len(config.STOCKS)} stocks checked · {data.get('fresh', 0)} with fresh trades · {len(data['failed'])} failed. Updates about every 15 minutes while the loop runs.")
    st.caption('Watch ideas only. Price is up at least 2%; traded volume already exceeds 1.3 times the previous 20-day daily average. These live checks have no measured success rate and can fade. Daily Buy calls still use completed sessions.')
    if items:
        st.dataframe([{'Stock': x['symbol'], 'Rise %': round(x['gain_pct'], 2),
                       'Volume / daily average': round(x['vol_mult'], 2), 'Price': x['price'],
                       'Last trade (PKT)': calendar.local_now(datetime.fromisoformat(x['last_trade'])).strftime('%H:%M:%S')}
                      for x in items], hide_index=True)
    elif not data.get('fresh'):
        st.info('No stocks have fresh current-session trades. Current momentum is unavailable.')
    else:
        st.info('No freshly traded stocks passed these momentum checks.')


if __name__ == '__main__':
    collect()
