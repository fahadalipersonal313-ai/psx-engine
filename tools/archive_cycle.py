"""Pick a cutoff, export, verify, purge, vacuum. Used by archive.yml.

Kept out of the workflow so the logic is testable and readable rather than
embedded in YAML, and so a human can run exactly what CI runs.

Refuses to purge anything the archive cannot reproduce: main.archive's contract
is export -> verify -> purge and this only reaches purge through it.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import archive
import database as db


def pick_cutoff(keep):
    """The session that becomes the archive boundary, or None when there is
    genuinely nothing older than the retention window."""
    with db.conn() as c:
        sessions = [r[0] for r in c.execute(
            "SELECT DISTINCT session FROM decisions ORDER BY session DESC")]
    return sessions[keep] if len(sessions) > keep else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=30,
                    help="sessions to keep live; older ones are archived")
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--dry-run", action="store_true",
                    help="export and verify, but never purge")
    args = ap.parse_args()

    db.init_db()
    cutoff = pick_cutoff(args.keep)
    if not cutoff:
        print(f"::notice::fewer than {args.keep} stored sessions — nothing to archive")
        print("DID=0")
        return 0

    out = os.path.join(args.out_dir, f"decisions-before-{cutoff}.db")
    man = archive.export(cutoff, out)
    print(f"exported {man['decisions']} decisions + {man['snapshots']} snapshots "
          f"-> {out} ({man['bytes'] / 1e6:.1f} MB)")

    chk = archive.verify(out, man)
    if not chk["ok"]:
        print(f"::error::archive failed verification: {chk}")
        return 1
    print(f"verified {chk['recomputed'][:16]} ({chk['decisions']} decisions)")

    if args.dry_run:
        print("dry run — not purging")
        print(f"DID=1\nNAME={os.path.basename(out)}\nCUTOFF={cutoff}")
        return 0

    before = os.path.getsize(db_path := __import__("config").DB_PATH)
    res = archive.purge(out, cutoff)
    if not res.get("verified"):
        print(f"::error::purge refused: {res}")
        return 1
    print(f"purged {res['purged']} decisions, {res['snapshots_purged']} snapshots")

    import sqlite3
    con = sqlite3.connect(db_path); con.execute("VACUUM"); con.close()
    print(f"database {before / 1e6:.1f} MB -> {os.path.getsize(db_path) / 1e6:.1f} MB")
    print(f"DID=1\nNAME={os.path.basename(out)}\nCUTOFF={cutoff}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
