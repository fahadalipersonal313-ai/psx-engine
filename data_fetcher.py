"""data_fetcher.py — Fetches prices, volume, and public news.

Rules enforced here:
  * Only public, login-free endpoints (PSX official data portal + public RSS).
  * No protection bypass, no fabricated data.
  * Every value carries a `source` and `as_of` tag.
  * On failure, return the latest stored data with a clear staleness warning.
"""

import logging
import re
from datetime import datetime

import requests
import pandas as pd

import config
import database as db
import ssl_compat

log = logging.getLogger("data_fetcher")

# Ensure HTTPS verification uses the OS trust store before any request runs.
# Fixes CERTIFICATE_VERIFY_FAILED on machines whose required root CA lives in
# the Windows store but not in certifi's bundle (e.g. SSL-inspecting networks).
ssl_compat.enable()

COMPANY_KEYWORDS = {
    "PSO": ["pso", "pakistan state oil"],
    "TREET": ["treet"],
    "FABL": ["fabl", "faysal bank"],
    "AIRLINK": ["airlink", "air link"],
    "MEBL": ["mebl", "meezan bank"],
    "SYS": ["systems limited", "systems ltd"],
    "LUCK": ["lucky cement", "lucky core"],
    "FFC": ["fauji fertilizer"],
    "OGDC": ["ogdc", "oil & gas development", "oil and gas development"],
    "MARI": ["mari energies", "mari petroleum"],
}


def _get(url):
    return requests.get(url, headers=config.REQUEST_HEADERS,
                        timeout=config.REQUEST_TIMEOUT)


# ---------------------------------------------------------------------------
# PRICES
# ---------------------------------------------------------------------------
def fetch_intraday(symbol):
    """PSX DPS intraday timeseries -> DataFrame[ts, price, volume].
    Returns (df, meta). df may be None on failure."""
    url = config.PSX_INTRADAY_URL.format(symbol=symbol)
    try:
        r = _get(url)
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data:
            raise ValueError("empty payload")
        # PSX DPS rows are [ts, price, volume, ...]; tolerate extra trailing
        # fields the portal may append by keeping only the first three.
        df = pd.DataFrame([row[:3] for row in data],
                          columns=["ts", "price", "volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="s")
        df = df.sort_values("ts").reset_index(drop=True)
        meta = {"source": "PSX DPS intraday", "as_of": str(df["ts"].iloc[-1]),
                "live": True, "warning": None}
        last = df.iloc[-1]
        db.save_price(symbol, str(last["ts"]), float(last["price"]),
                      float(last["volume"]), meta["source"])
        return df, meta
    except Exception as e:
        log.warning("Intraday fetch failed for %s: %s", symbol, e)
        return None, {"source": "PSX DPS intraday", "as_of": None,
                      "live": False,
                      "warning": f"Live fetch failed ({e}); using latest stored data."}


def fetch_eod(symbol):
    """PSX DPS end-of-day history -> DataFrame[date, close, volume]."""
    url = config.PSX_EOD_URL.format(symbol=symbol)
    try:
        r = _get(url)
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data:
            raise ValueError("empty payload")
        # PSX DPS EOD rows are now [ts, close, volume, open]; older format had
        # three. Keep the first three columns so both layouts parse cleanly.
        df = pd.DataFrame([row[:3] for row in data],
                          columns=["ts", "close", "volume"])
        df["date"] = pd.to_datetime(df["ts"], unit="s")
        df = df.sort_values("date").reset_index(drop=True)
        meta = {"source": "PSX DPS end-of-day", "as_of": str(df["date"].iloc[-1].date()),
                "live": True, "warning": None}
        return df[["date", "close", "volume"]], meta
    except Exception as e:
        log.warning("EOD fetch failed for %s: %s", symbol, e)
        return None, {"source": "PSX DPS end-of-day", "as_of": None,
                      "live": False,
                      "warning": f"EOD fetch failed ({e})."}


def latest_quote(symbol):
    """Best-effort latest price/volume with explicit provenance."""
    df, meta = fetch_intraday(symbol)
    if df is not None and len(df):
        last = df.iloc[-1]
        return {"price": float(last["price"]), "volume": float(df["volume"].sum()),
                **meta}
    # Fallback: last stored price
    with db.conn() as c:
        r = c.execute("""SELECT * FROM prices WHERE symbol=?
                         ORDER BY ts DESC LIMIT 1""", (symbol,)).fetchone()
    if r:
        return {"price": r["price"], "volume": r["volume"],
                "source": r["source"] + " (cached)", "as_of": r["ts"],
                "live": False,
                "warning": "Live data unavailable — showing last stored price."}
    return {"price": None, "volume": None, "source": "none", "as_of": None,
            "live": False, "warning": "No price data available for " + symbol}


# ---------------------------------------------------------------------------
# NEWS (public RSS only)
# ---------------------------------------------------------------------------
# Match <item> with or without attributes (feeds emit e.g.
# <item xmlns:default="...">), so attribute-bearing items aren't skipped.
_ITEM_RE = re.compile(r"<item\b[^>]*>(.*?)</item>", re.S | re.I)
_TAG_RE = {t: re.compile(rf"<{t}.*?>(.*?)</{t}>", re.S | re.I)
           for t in ("title", "link", "pubDate")}
_CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.S)


def _clean(text):
    if not text:
        return ""
    m = _CDATA_RE.search(text)
    if m:
        text = m.group(1)
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_rss_items(text, source, symbols, now):
    """Parse <item> blocks from RSS text into our news-item dicts."""
    out = []
    for raw in _ITEM_RE.findall(text)[:40]:
        m = _TAG_RE["title"].search(raw)
        title = _clean(m.group(1)) if m else ""
        if not title:
            continue
        link = _clean(_TAG_RE["link"].search(raw).group(1)) \
            if _TAG_RE["link"].search(raw) else ""
        pub = _clean(_TAG_RE["pubDate"].search(raw).group(1)) \
            if _TAG_RE["pubDate"].search(raw) else ""
        out.append({"fetched_at": now, "source": source, "title": title,
                    "link": link, "published": pub, "symbols": list(symbols)})
    return out


def fetch_company_news(symbol):
    """Per-company PUBLIC sentiment input via Google News RSS search.

    Returns news items tagged to `symbol` and stores them, so the sentiment
    module sees real per-stock mentions. Login-free, public, source-tagged.
    """
    from urllib.parse import quote
    query = config.COMPANY_NEWS_QUERY.get(symbol, f"{symbol} PSX Pakistan stock")
    url = config.GOOGLE_NEWS_RSS.format(query=quote(query))
    now = datetime.now().isoformat()
    try:
        r = _get(url)
        r.raise_for_status()
        items = _parse_rss_items(r.text, f"Google News: {query}", [symbol], now)
        if items:
            db.save_news(items)
        log.info("Company news for %s: %d items", symbol, len(items))
        return items
    except Exception as e:
        log.warning("Company news fetch failed for %s: %s", symbol, e)
        return []


def fetch_news():
    """Pull all configured public RSS feeds, tag symbols, store, return items."""
    items, now = [], datetime.now().isoformat()
    for name, url in config.NEWS_FEEDS:
        try:
            r = _get(url)
            r.raise_for_status()
            for raw in _ITEM_RE.findall(r.text)[:40]:
                title = _clean((_TAG_RE["title"].search(raw) or [None, ""])[1]
                               if _TAG_RE["title"].search(raw) else "")
                if not title:
                    continue
                link = _clean(_TAG_RE["link"].search(raw).group(1)) \
                    if _TAG_RE["link"].search(raw) else ""
                pub = _clean(_TAG_RE["pubDate"].search(raw).group(1)) \
                    if _TAG_RE["pubDate"].search(raw) else ""
                low = title.lower()
                syms = [s for s, kws in COMPANY_KEYWORDS.items()
                        if any(k in low for k in kws)]
                items.append({"fetched_at": now, "source": name, "title": title,
                              "link": link, "published": pub, "symbols": syms})
        except Exception as e:
            log.warning("News feed %s failed: %s", name, e)
    if items:
        db.save_news(items)
    log.info("Fetched %d news items", len(items))
    return items
