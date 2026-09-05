"""Select up to ten current stocks with an intact upward trend and momentum."""
import json
import config
from data_quality import finite, valid_levels


def qualifies(decision):
    t = decision.get('technical', {})
    keys = ('price', 'ema10', 'ema20', 'ema40', 'rsi', 'macd_hist',
            'momentum_20d', 'relative_strength', 'cmf', 'avg_volume')
    if not all(finite(t.get(k)) for k in keys):
        return False
    return (decision['signal']['signal'] in ('Buy', 'Strong Buy', 'Watch')
            and decision.get('snapshot', {}).get('eligible', False)
            and t['price'] > t['ema10'] > t['ema20'] > t['ema40']
            and 50 <= t['rsi'] <= 70 and t['macd_hist'] > 0
            and t['momentum_20d'] > 0 and t['relative_strength'] >= 55
            and t['cmf'] > 0 and t['avg_volume'] >= config.RISK['min_avg_daily_volume']
            and not t.get('breakdown') and not t.get('extended')
            and valid_levels(t['price'], t.get('stop_loss'), t.get('target1'), t.get('target2')))


def current():
    import database as db
    import decision_engine
    from session_calendar import last_completed
    with db.conn() as c:
        rows = c.execute('SELECT payload FROM decisions WHERE session=? AND version=? AND config_hash=?',
                         (last_completed(), config.STRATEGY_VERSION,
                          decision_engine.digest(decision_engine.contract()))).fetchall()
    decisions = [json.loads(r['payload']) for r in rows]
    selected = sorted((d for d in decisions if qualifies(d)),
                      key=lambda d: d['scoring']['final_score'], reverse=True)[:10]
    return [{'Stock': d['symbol'], 'Price': d['technical']['price'],
             'Signal': d['signal']['signal'], 'Target': d['technical']['target1'],
             'Loss limit': d['technical']['stop_loss'],
             'Why it qualifies': 'Price trend rising, momentum positive, buying activity positive'}
            for d in selected]
