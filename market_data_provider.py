"""Free public PSX market-data adapter using pypsx-toolkit.

pypsx-toolkit is the unauthenticated public-data package from pyPSX. It
provides daily OHLCV and recent intraday research data without an API key.
No TradingView scraping, browser automation, hidden PSX endpoints, or secrets.
"""
import pandas as pd
import pypsx_toolkit as pt

SOURCE = "pyPSX Toolkit public data"

def _col(df, *names):
    lookup = {str(c).lower().replace("_", ""): c for c in df.columns}
    for name in names:
        key = name.lower().replace("_", "")
        if key in lookup:
            return lookup[key]
    return None

def _epoch(value):
    ts = pd.to_datetime(value, utc=True)
    return float(ts.timestamp())

def intraday_1m(symbol):
    """Return legacy-compatible [timestamp, price, volume] rows.

    Toolkit intraday is a recent research snapshot, not a guaranteed live
    exchange feed. Downstream freshness checks remain authoritative.
    """
    df = pt.get_intraday(symbol)
    if df is None or len(df) == 0:
        return []
    df = df.reset_index()
    tc = _col(df, "datetime", "timestamp", "time", "date", "index")
    pc = _col(df, "close", "price", "last", "current")
    vc = _col(df, "volume", "vol")
    if tc is None or pc is None or vc is None:
        raise ValueError(f"pyPSX intraday shape changed; columns={list(df.columns)}")
    out = []
    for _, row in df.iterrows():
        try:
            out.append([_epoch(row[tc]), float(row[pc]), float(row[vc])])
        except (TypeError, ValueError):
            continue
    return out

def eod_adjusted(symbol, date_from=None, date_to=None):
    """Return normalized daily OHLCV records from the free toolkit."""
    if date_from or date_to:
        df = pt.download(symbol, start=date_from, end=date_to)
    else:
        df = pt.download(symbol, period="10y")
    if df is None or len(df) == 0:
        return []
    df = df.reset_index()
    tc = _col(df, "datetime", "date", "timestamp", "index")
    oc = _col(df, "open")
    hc = _col(df, "high")
    lc = _col(df, "low")
    cc = _col(df, "close")
    vc = _col(df, "volume", "vol")
    if None in (tc, oc, hc, lc, cc, vc):
        raise ValueError(f"pyPSX daily shape changed; columns={list(df.columns)}")
    out = []
    for _, row in df.iterrows():
        try:
            out.append({"time": _epoch(row[tc]), "open": float(row[oc]),
                        "high": float(row[hc]), "low": float(row[lc]),
                        "close": float(row[cc]), "volume": float(row[vc])})
        except (TypeError, ValueError):
            continue
    return out

def daily_market_summary(symbols=None):
    """Build current/recent OHLCV summary from public intraday snapshots.

    This intentionally makes no claim that a snapshot is live. The engine's
    existing timestamp/session freshness gates decide whether it is current.
    """
    out = {}
    for symbol in symbols or []:
        ticks = intraday_1m(symbol)
        if not ticks:
            continue
        prices = [x[1] for x in ticks]
        out[symbol] = {"open": prices[0], "high": max(prices), "low": min(prices),
                       "current": prices[-1], "volume": sum(x[2] for x in ticks)}
    return out
