"""Create and verify a NEW SQLite runtime backup. Source is never modified."""
import argparse
import os
import sqlite3
from pathlib import Path


def backup(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination:
        raise ValueError('Source and destination must differ')
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    src = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Backup integrity check failed')
        tables = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            if src.execute('SELECT COUNT(*) FROM ' + quoted).fetchone()[0] != dst.execute('SELECT COUNT(*) FROM ' + quoted).fetchone()[0]:
                raise ValueError('Backup row count mismatch: ' + table)
    finally:
        src.close(); dst.close()
    return str(destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source'); parser.add_argument('destination')
    args = parser.parse_args()
    print(backup(args.source, args.destination))
