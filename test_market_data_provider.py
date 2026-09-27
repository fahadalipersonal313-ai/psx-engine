import os
from unittest.mock import patch, Mock

import market_data_provider as md

def test_requires_secret():
    old = os.environ.pop(md.TOKEN_ENV, None)
    try:
        try:
            md._headers()
            assert False, "expected ProviderUnavailable"
        except md.ProviderUnavailable:
            pass
    finally:
        if old is not None:
            os.environ[md.TOKEN_ENV] = old

def test_intraday_normalizes_documented_shape():
    payload = {"status": "ok", "message": "", "data": [
        {"time": 1700000000, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1234}
    ]}
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    with patch.dict(os.environ, {md.TOKEN_ENV: "test-token"}):
        with patch("market_data_provider.requests.get", return_value=response):
            assert md.intraday_1m("PSO") == [[1700000000.0, 10.5, 1234.0]]

def test_daily_summary_normalizes_documented_shape():
    payload = {"status": "ok", "message": "", "data": [
        {"symbol": "PSO", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1234}
    ]}
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    with patch.dict(os.environ, {md.TOKEN_ENV: "test-token"}):
        with patch("market_data_provider.requests.get", return_value=response):
            row = md.daily_market_summary()["PSO"]
            assert row == {"open": 10.0, "high": 11.0, "low": 9.0, "current": 10.5, "volume": 1234.0}
