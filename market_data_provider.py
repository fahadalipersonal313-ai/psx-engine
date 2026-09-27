"""Licensed PSX market-data provider adapter.

Capital Stake is listed by PSX as an authorized market-data vendor. This
module uses only its documented authenticated REST API. The bearer token must
come from the CAPITALSTAKE_API_TOKEN environment variable; it is never stored
in the repository.
"""
import os
import requests

BASE_URL = "https://csapis.com/3.0"
TOKEN_ENV = "CAPITALSTAKE_API_TOKEN"
TIMEOUT = 30

class ProviderUnavailable(RuntimeError):
    pass

def _headers():
    token = os.getenv(TOKEN_ENV, "").strip()
    if not token:
        raise ProviderUnavailable(
            f"{TOKEN_ENV} is not configured; engine remains paused until a licensed provider token is available"
        )
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

def _get(path, params=None):
    r = requests.get(BASE_URL + path, headers=_headers(), params=params, timeout=TIMEOUT)
    r.raise_for_status()
    payload = r.json()
    if payload.get("status") != "ok":
        raise ProviderUnavailable(payload.get("message") or f"provider returned status={payload.get('status')!r}")
    return payload.get("data") or []

def intraday_1m(symbol):
    """Return legacy-compatible [timestamp, close, volume] rows."""
    rows = _get("/market/intraday/1m", {"symbol": symbol})
    out = []
    for row in rows:
        try:
            out.append([float(row["time"]), float(row["close"]), float(row["volume"])])
        except (KeyError, TypeError, ValueError):
            continue
    return out

def eod_adjusted(symbol, date_from=None, date_to=None):
    params = {"symbol": symbol}
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to
    return _get("/market/eod-adj", params)

def daily_market_summary():
    """Return {symbol: legacy market-watch bar} for the current trading day."""
    rows = _get("/market/closing")
    out = {}
    for row in rows:
        try:
            sym = str(row["symbol"]).upper()
            out[sym] = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "current": float(row["close"]),
                "volume": float(row["volume"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
    return out
