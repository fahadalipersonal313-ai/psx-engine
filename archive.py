"""archive.py — move settled decision history to a durable file, verifiably.

The tracked database is committed on every 15-minute cycle, so its size is a
per-push cost. `decisions` + `decision_snapshots` are the unbounded part: 0.67 MB
per 60-symbol session, roughly 14 MB a month, against GitHub's 100 MB hard limit.
Compression bought headroom; it did not stop the growth.

These rows are immutable audit records, so they are ARCHIVED, never discarded.
The order is deliberate and is the whole point of the module:

    export  ->  verify  ->  purge

`purge` refuses to delete anything the archive cannot reproduce byte-for-byte.
A restore is not a hope, it is checked before the live rows go away, which is the
"durable destination and a verified restore" the operating constraints ask for.

Snapshots are shared: several decisions can point at one snapshot_hash. A
snapshot is only archived and purged when NO retained decision still references
it, otherwise a live row would be left pointing at nothing.

The archive is a plain SQLite file. It restores with `python main.py restore
<path>` and needs no code from this repo to read -- a format that outlives the
tool is part of being durable.
"""

import os
import sqlite3

import database as db
from decision_engine import digest

TABLES = ("decisions", "decision_snapshots")


def _rows(c, sql, args=()):
    return [tuple(r) for r in c.execute(sql, args)]


def manifest(decisions, snapshots):
    """Content digest of everything the archive claims to hold."""
    return {"decisions": len(decisions), "snapshots": len(snapshots),
            "digest": digest([sorted(str(r) for r in decisions),
                              sorted(str(r) for r in snapshots)])}


def export(cutoff_session, out_path):
    """Write every decision strictly older than `cutoff_session` to `out_path`.

    Nothing is deleted here. Returns the manifest the verify step re-derives.
    """
    with db.conn() as c:
        decisions = _rows(c, "SELECT * FROM decisions WHERE session < ?", (cutoff_session,))
        keep_hashes = {r[0] for r in _rows(
            c, "SELECT DISTINCT snapshot_hash FROM decisions WHERE session >= ?",
            (cutoff_session,)) if r[0]}
        moving = {r[4] for r in decisions if r[4]}
        orphans = sorted(moving - keep_hashes)
        snapshots = []
        for i in range(0, len(orphans), 400):
            chunk = orphans[i:i + 400]
            snapshots += _rows(c, "SELECT * FROM decision_snapshots WHERE hash IN (%s)"
                               % ",".join("?" * len(chunk)), chunk)
    if os.path.exists(out_path):
        os.remove(out_path)
    out = sqlite3.connect(out_path)
    out.executescript("""
        CREATE TABLE decisions (symbol TEXT, session TEXT, version TEXT,
          config_hash TEXT, snapshot_hash TEXT, state BLOB, payload BLOB);
        CREATE TABLE decision_snapshots (hash TEXT PRIMARY KEY, payload BLOB);
        CREATE TABLE archive_meta (key TEXT PRIMARY KEY, value TEXT);""")
    out.executemany("INSERT INTO decisions VALUES (?,?,?,?,?,?,?)", decisions)
    out.executemany("INSERT INTO decision_snapshots VALUES (?,?)", snapshots)
    man = manifest(decisions, snapshots)
    out.executemany("INSERT INTO archive_meta VALUES (?,?)",
                    [("cutoff_session", cutoff_session), ("digest", man["digest"]),
                     ("decisions", str(man["decisions"])), ("snapshots", str(man["snapshots"]))])
    out.commit(); out.close()
    man["path"] = out_path
    man["bytes"] = os.path.getsize(out_path)
    return man


def verify(path, expected=None):
    """Re-derive the archive's digest from its own contents.

    Deliberately recomputed rather than trusting the stored value: a truncated
    or half-written file would still carry a plausible-looking meta row.
    """
    a = sqlite3.connect(path)
    try:
        decisions = _rows(a, "SELECT * FROM decisions")
        snapshots = _rows(a, "SELECT * FROM decision_snapshots")
        stored = dict(_rows(a, "SELECT key, value FROM archive_meta"))
    finally:
        a.close()
    got = manifest(decisions, snapshots)
    ok = got["digest"] == stored.get("digest")
    if expected:
        ok = ok and got["digest"] == expected["digest"]
    return {"ok": bool(ok), "recomputed": got["digest"], "stored": stored.get("digest"),
            "decisions": got["decisions"], "snapshots": got["snapshots"]}


def restore(path):
    """Put archived rows back. Idempotent -- restoring twice changes nothing."""
    a = sqlite3.connect(path)
    decisions = _rows(a, "SELECT * FROM decisions")
    snapshots = _rows(a, "SELECT * FROM decision_snapshots")
    a.close()
    with db.conn() as c:
        c.executemany("INSERT OR IGNORE INTO decision_snapshots VALUES (?,?)", snapshots)
        c.executemany("INSERT OR IGNORE INTO decisions VALUES (?,?,?,?,?,?,?)", decisions)
    return {"decisions": len(decisions), "snapshots": len(snapshots)}


def purge(path, cutoff_session):
    """Delete the archived rows from the live database -- only if the archive
    verifies AND actually contains this cutoff. Refuses otherwise."""
    check = verify(path)
    a = sqlite3.connect(path)
    stored_cutoff = dict(_rows(a, "SELECT key, value FROM archive_meta")).get("cutoff_session")
    a.close()
    if not check["ok"]:
        return {"purged": 0, "refused": "archive failed verification", **check}
    if stored_cutoff != cutoff_session:
        return {"purged": 0,
                "refused": f"archive cutoff {stored_cutoff!r} != requested {cutoff_session!r}"}
    with db.conn() as c:
        keep = {r[0] for r in _rows(
            c, "SELECT DISTINCT snapshot_hash FROM decisions WHERE session >= ?",
            (cutoff_session,)) if r[0]}
        moving = {r[0] for r in _rows(
            c, "SELECT DISTINCT snapshot_hash FROM decisions WHERE session < ?",
            (cutoff_session,)) if r[0]}
        orphans = sorted(moving - keep)
        n = c.execute("DELETE FROM decisions WHERE session < ?", (cutoff_session,)).rowcount
        s = 0
        for i in range(0, len(orphans), 400):
            chunk = orphans[i:i + 400]
            s += c.execute("DELETE FROM decision_snapshots WHERE hash IN (%s)"
                           % ",".join("?" * len(chunk)), chunk).rowcount
    return {"purged": n, "snapshots_purged": s, "verified": True}
