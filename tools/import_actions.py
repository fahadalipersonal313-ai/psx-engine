"""Import explicitly sourced action terms; never derive factors from prices."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
import database as db
from corporate_actions import valid_action


def import_actions(path):
    rows = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(rows, list) or any(not valid_action(a) or not a.get('symbol') for a in rows):
        raise ValueError('Every action requires symbol, kind, ex_date, known_at, source, verified=true, positive price and explicit volume factors')
    with db.conn() as c:
        for a in rows:
            old = c.execute('SELECT * FROM corporate_actions WHERE symbol=? AND ex_date=?', (a['symbol'], a['ex_date'])).fetchone()
            if old and old['verified']:
                if any(old[k] != a[k] for k in ('factor','volume_factor','kind','known_at','source')):
                    raise ValueError('Verified action already exists with different terms; reconcile explicitly')
                continue
            cols = ('symbol','ex_date','kind','factor','volume_factor','source','known_at','verified')
            c.execute('INSERT INTO corporate_actions (' + ','.join(cols) + ') VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(symbol,ex_date) DO UPDATE SET kind=excluded.kind,factor=excluded.factor,volume_factor=excluded.volume_factor,source=excluded.source,known_at=excluded.known_at,verified=excluded.verified',tuple(a[k] for k in cols))
    return len(rows)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file'); parser.add_argument('--database',required=True)
    args=parser.parse_args()
    config.DB_PATH=args.database; db.init_db()
    print(import_actions(args.file))
