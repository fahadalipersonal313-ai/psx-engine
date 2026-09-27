from unittest.mock import patch
import pandas as pd
import market_data_provider as md

def test_intraday_normalizes_toolkit_shape():
    df = pd.DataFrame({
        "datetime": ["2026-09-24T09:32:00+05:00"],
        "close": [10.5],
        "volume": [1234],
    })
    with patch("market_data_provider.pt.get_intraday", return_value=df):
        row = md.intraday_1m("PSO")[0]
        assert row[1:] == [10.5, 1234.0]

def test_daily_normalizes_toolkit_shape():
    df = pd.DataFrame({
        "datetime": ["2026-09-24"],
        "open": [10], "high": [11], "low": [9], "close": [10.5], "volume": [1234],
    })
    with patch("market_data_provider.pt.download", return_value=df):
        row = md.eod_adjusted("PSO")[0]
        assert row["open"] == 10.0
        assert row["high"] == 11.0
        assert row["low"] == 9.0
        assert row["close"] == 10.5
        assert row["volume"] == 1234.0

def test_summary_uses_observed_intraday_only():
    ticks = [[1.0, 10.0, 100.0], [2.0, 11.0, 200.0], [3.0, 9.5, 50.0]]
    with patch("market_data_provider.intraday_1m", return_value=ticks):
        row = md.daily_market_summary(["PSO"])["PSO"]
        assert row == {"open": 10.0, "high": 11.0, "low": 9.5,
                       "current": 9.5, "volume": 350.0}
