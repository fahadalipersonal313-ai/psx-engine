"""Return failed health unless the latest core batch completed and is fresh."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
import database as db
from session_calendar import last_completed


def health():
    with db.conn() as c:
        batch = c.execute('SELECT * FROM run_batches ORDER BY started_at DESC, rowid DESC LIMIT 1').fetchone()
        if not batch or batch['status'] != 'complete':
            return {'healthy':False,'reason':'Latest core batch absent or incomplete'}
        rows = c.execute('SELECT symbol,decision_session,signal FROM runs WHERE batch_id=?',(batch['id'],)).fetchall()
    expected = last_completed()
    valid = (len(rows)==batch['expected'] and {r['symbol'] for r in rows}==set(config.STOCKS)
             and all(r['decision_session']==expected for r in rows)
             and any(r['signal']!='No data' for r in rows))
    return {'healthy':valid,'batch_id':batch['id'],'completed_session':expected,
            'unavailable_symbols':[r['symbol'] for r in rows if r['signal']=='No data']}


if __name__=='__main__':
    try:
        status=health()
    except Exception as exc:
        status={'healthy':False,'reason':str(exc)}
    print(json.dumps(status))
    raise SystemExit(0 if status['healthy'] else 1)
