"""Prove a published archive restores, against a COPY of the live database.

A restore that has never been exercised is not a restore. CI downloads the asset
it actually published — not the local file it just wrote — and replays it here,
so a truncated upload or a bad content type fails the run instead of being
discovered the day someone needs the history back.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

archive_path, db_copy = sys.argv[1], sys.argv[2]
config.DB_PATH = db_copy          # never the tracked database

import archive  # noqa: E402  (must follow the DB_PATH override)

check = archive.verify(archive_path)
if not check["ok"]:
    print(f"::error::published asset failed verification: {check}")
    raise SystemExit(1)
print(f"published asset verifies: {check['decisions']} decisions, "
      f"{check['snapshots']} snapshots, digest {check['recomputed'][:16]}")
print("restored into a copy:", archive.restore(archive_path))
