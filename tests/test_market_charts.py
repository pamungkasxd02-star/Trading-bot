import time

import pandas as pd
import pytest

from spotlab.market_charts import MarketCharts, selected_symbol


def market(symbol, base, quote):
    return dict(
        symbol=symbol, baseAsset=base, quoteAsset=quote, status="TRADING", isSpotTradingAllowed=True
    )


class PublicFake:
    def __init__(self):
        self.rows = []
        self.calls = []

    def exchange_info(self):
        return {
            "symbols": [
                market("BTCUSDT", "BTC", "USDT"),
                market("ETHBTC", "ETH", "BTC"),
                market("SMALLBTC", "SMALL", "BTC"),
                market("SMALLETH", "SMALL", "ETH"),
            ]
        }

    def klines(self, symbol, interval, limit):
        self.calls.append((symbol, interval, limit))
        return self.rows


def row(start, end):
    return [
        int(start.timestamp() * 1000),
        "10",
        "12",
        "9",
        "11",
        "100",
        int(end.timestamp() * 1000) - 1,
    ]


def test_coin_resolution_and_execution_separation():
    charts = MarketCharts(PublicFake())
    assert charts.resolve("bitcoin")["symbol"] == "BTCUSDT"
    assert charts.resolve("BTC")["symbol"] == "BTCUSDT"
    assert charts.resolve("ETH/BTC")["quoteAsset"] == "BTC"
    with pytest.raises(ValueError, match="Pilih pair"):
        charts.resolve("SMALL")
    with pytest.raises(ValueError, match="tidak ditemukan"):
        charts.resolve("nonexistent")
    assert selected_symbol("bitcoin", {"BTCUSDT"}) == "BTCUSDT"
    with pytest.raises(ValueError, match="universe"):
        selected_symbol("ETHBTC", {"BTCUSDT"})


def test_closed_candles_only_and_invalid_interval():
    client = PublicFake()
    charts = MarketCharts(client)
    now = pd.Timestamp.now(tz="UTC").floor("min")
    client.rows = [
        row(now - pd.Timedelta(i, unit="min"), now - pd.Timedelta(i - 1, unit="min"))
        for i in [2, 1, 0]
    ]
    _, frame = charts.candles("bitcoin", "1m")
    assert len(frame) == 2
    assert frame.close_time.iloc[-1].timestamp() < time.time()
    assert client.calls == [("BTCUSDT", "1m", 500)]
    with pytest.raises(ValueError, match="Interval"):
        charts.candles("bitcoin", "2m")
    assert len(client.calls) == 1


def test_monthly_calendar_spacing():
    client = PublicFake()
    now = pd.Timestamp.now(tz="UTC")
    month = now.normalize().replace(day=1)
    client.rows = [
        row(month - pd.DateOffset(months=i), month - pd.DateOffset(months=i - 1))
        for i in [4, 3, 2, 1]
    ]
    _, frame = MarketCharts(client).candles("BTC", "1M")
    assert len(frame) == 4


@pytest.mark.parametrize("issue", ["gap", "stale", "nan", "ohlc"])
def test_bad_data_rejected(issue):
    client = PublicFake()
    now = pd.Timestamp.now(tz="UTC").floor("min")
    if issue == "stale":
        now -= pd.Timedelta(1, unit="d")
    client.rows = [
        row(now - pd.Timedelta(i, unit="min"), now - pd.Timedelta(i - 1, unit="min"))
        for i in ([3, 1] if issue == "gap" else [2, 1])
    ]
    if issue == "nan":
        client.rows[0][1] = "nan"
    if issue == "ohlc":
        client.rows[0][2] = "1"
    with pytest.raises(ValueError):
        MarketCharts(client).candles("BTC", "1m")
