"""news_feed.py — Reads the authentic news feed produced by the daily Claude
news routine (news_signals.json) and exposes per-symbol verdicts to the engine.

The routine (see news_routine.md) reads real articles from an allowlist of
authentic PSX/financial sources, judges each stock's news, and writes a verdict
WITH source URLs. This module only READS that file — it never fetches news
itself, so the 15-min engine loop stays fast and offline-safe.

Freshness contract: if the file is missing, malformed, or older than
config.NEWS_SIGNALS_MAX_AGE_HOURS, get() returns None for every symbol and the
caller falls back to RSS/VADER scoring. Authentic-but-absent is never faked.

Per-symbol verdict schema (values the engine relies on):
    score        float 0-100  (50 = neutral; >50 positive, <50 negative)
    direction    "positive" | "negative" | "neutral"
    materiality  "normal" | "material_negative" | "material_positive"
    confidence   "high" | "medium" | "low"
    summary      str   one-line plain-English reason
    headlines    list[str]
    sources      list[str]  (URLs — authenticity is traceable, not asserted)
"""

import json
import logging
from datetime import datetime, timezone

import config

log = logging.getLogger("news_feed")

_CACHE = {"mtime": None, "data": None}


def _parse_as_of(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def load_signals():
    """Return (signals_dict, meta) where signals_dict maps SYMBOL -> verdict.
    Returns ({}, meta) when the file is missing, malformed, or stale."""
    path = config.NEWS_SIGNALS_PATH
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}, {"status": "absent"}
    except (json.JSONDecodeError, OSError) as e:
        log.warning("news_signals.json unreadable (%s) — using RSS/VADER fallback", e)
        return {}, {"status": "malformed"}

    as_of = _parse_as_of(raw.get("as_of"))
    if as_of is not None:
        age_h = (datetime.now(timezone.utc) - as_of).total_seconds() / 3600
        if age_h > config.NEWS_SIGNALS_MAX_AGE_HOURS:
            log.warning("news_signals.json is %.1fh old (> %dh) — RSS/VADER fallback",
                        age_h, config.NEWS_SIGNALS_MAX_AGE_HOURS)
            return {}, {"status": "stale", "age_hours": round(age_h, 1)}

    signals = {k.upper(): v for k, v in (raw.get("signals") or {}).items()}
    return signals, {"status": "ok", "as_of": raw.get("as_of"),
                     "count": len(signals)}


def get(symbol):
    """Per-symbol authentic verdict dict, or None if unavailable/stale."""
    signals, _ = load_signals()
    return signals.get(symbol.upper())


def status_line():
    """One-line health string for reports/logs."""
    _, meta = load_signals()
    if meta["status"] == "ok":
        return f"Authentic news feed: {meta['count']} symbols, as of {meta['as_of']}."
    return f"Authentic news feed unavailable ({meta['status']}) — RSS/VADER fallback."
