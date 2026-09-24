import numpy as np
import pandas as pd
import pytest

from spotlab.candle_analysis import analysis_report, describe
from spotlab.config import StrategyConfig


def candles(direction=1):
    close = 100 + direction * np.arange(200) * 0.1
    return pd.DataFrame(
        dict(
            close=close,
            open=close - 0.01,
            high=close + 0.1,
            low=close - 0.1,
            volume=np.full(200, 100.0),
            close_time=pd.date_range("2026-01-01", periods=200, freq="min", tz="UTC"),
        )
    )


@pytest.mark.parametrize("direction,trend", [(1, "naik"), (-1, "turun"), (0, "campuran")])
def test_descriptive_trend_and_anatomy(direction, trend):
    result = describe(candles(direction), StrategyConfig())
    assert result["trend"] == trend
    assert result["relative_volume"] == 1
    assert result["body_pct"] + result["upper_wick_pct"] + result[
        "lower_wick_pct"
    ] == pytest.approx(100)
    if direction == 0:
        assert result["rsi"] == 50


def test_volume_and_range_exclude_signal_candle():
    frame = candles()
    frame.loc[199, "volume"] = 1000
    frame.loc[199, "close"] = frame.loc[199, "high"] = 500
    result = describe(frame, StrategyConfig())
    assert result["relative_volume"] == 10
    assert result["high"] < 500
    assert result["location"] == "di atas range sebelumnya"
    frame["volume"] = 0
    assert describe(frame, StrategyConfig())["relative_volume"] is None
    with pytest.raises(ValueError, match="Butuh"):
        describe(frame.head(3), StrategyConfig())


class Charts:
    def __init__(self, fail=None):
        self.fail = fail
        self.calls = []

    def resolve(self, query):
        return dict(symbol="BTCUSDT", quoteAsset="USDT")

    def candles(self, symbol, interval):
        self.calls.append(interval)
        if interval == self.fail:
            raise RuntimeError("secret transport details")
        return self.resolve(symbol), candles()


def test_missing_timeframe_cannot_be_confirmation_and_errors_sanitized():
    report = analysis_report(Charts("5m"), "BTC", ["1m", "5m"], StrategyConfig())
    assert "DATA TIDAK LENGKAP" in report
    assert "Tren naik selaras" not in report
    assert "secret" not in report


def test_complete_report_deduplicates_and_stays_within_telegram_limit():
    charts = Charts()
    report = analysis_report(charts, "BTC", ["1m", "1m", "5m", "15m", "1h"], StrategyConfig())
    assert charts.calls == ["1m", "5m", "15m", "1h"]
    assert "Tren naik selaras" in report
    assert len(report) < 3900
    assert "belum ada konfirmasi" in analysis_report(charts, "BTC", ["1m"], StrategyConfig())


@pytest.mark.parametrize("intervals", [[], ["2m"], ["1m", "3m", "5m", "15m", "1h"]])
def test_invalid_request_does_not_fetch(intervals):
    charts = Charts()
    with pytest.raises(ValueError):
        analysis_report(charts, "BTC", intervals, StrategyConfig())
    assert not charts.calls
