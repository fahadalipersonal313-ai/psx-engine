"""Additional current-research gates without revising historical v8 outcomes."""
from datetime import date, timedelta
import database as db
import corporate_actions
import config
import session_calendar as cal


def check(row, now=None):
    now=cal.local_now(now)
    result={'valid':False,'checks':[],'session_basis':'Independent dated PSX exchange calendar, cross-checked against banked market-wide dates'}
    result['binding']={k:row.get(k) for k in ('symbol','decision_session','strategy_version','config_hash','snapshot_hash')}
    symbol=row['symbol'];cutoff=row.get('decision_session')
    if not cutoff:
        result['checks'].append('No decision session');return result
    bars=db.get_daily_ohlc(symbol,config.FEATURE_HISTORY_LIMIT)
    dates=[str(x['date']) for x in bars if str(x['date']) <= cutoff][-config.FEATURE_HISTORY_LIMIT:]
    if len(dates)!=config.FEATURE_HISTORY_LIMIT:
        result['checks'].append('Insufficient completed-session history')
    with db.conn() as c:
        expected=[x[0] for x in c.execute('SELECT DISTINCT date FROM daily_ohlc WHERE date<=? ORDER BY date DESC LIMIT ?',
                                         (cutoff,config.FEATURE_HISTORY_LIMIT))][::-1]
    import research_calendar
    try:
        independently_expected=research_calendar.expected(cutoff,config.FEATURE_HISTORY_LIMIT)
        if expected != independently_expected:
            result['checks'].append('Market-wide history differs from independent exchange-session calendar')
    except ValueError as exc:
        result['checks'].append(str(exc))
    result['calendar_sources']=research_calendar.SOURCES
    result['calendar_verified_at']=research_calendar.VERIFIED_AT
    if dates!=expected:
        result['checks'].append('Stock history omits a banked market session')
    benchmark=[str(x['date']) for x in db.get_eod_history(config.BENCHMARK_INDEX,config.FEATURE_HISTORY_LIMIT) if str(x['date'])<=cutoff]
    if benchmark!=expected:
        result['checks'].append('Benchmark history omits a banked market session')
    for action in db.get_corporate_actions(symbol):
        try:
            ex=date.fromisoformat(str(action['ex_date'])[:10]).isoformat()
            if dates and (ex <= dates[0] or ex > now.date().isoformat()):
                continue
            known=date.fromisoformat(str(action['known_at'])[:10]).isoformat()
            if known<=now.date().isoformat() and dates and dates[0]<ex<=now.date().isoformat():
                if not corporate_actions.valid_action(action):
                    result['checks'].append('Known unresolved corporate action '+ex)
                elif ex>cutoff:
                    result['checks'].append('Corporate action occurred after technical decision; regenerate levels')
        except (ValueError,TypeError,KeyError):
            result['checks'].append('Malformed corporate action evidence')
    result['valid']=not result['checks']
    result['checked_at']=now.isoformat()
    return result
