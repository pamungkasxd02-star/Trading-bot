import numpy as np
import pandas as pd

from spotlab.config import load_config
from spotlab.strategies.curve import CurveScalpingStrategy
from spotlab.universe import select_universe


def candles():
    rng = np.random.default_rng(804)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0001, 0.002, 2000)))
    times = pd.date_range("2026-01-01", periods=len(close), freq="min", tz="UTC")
    return pd.DataFrame(
        dict(
            open_time=times,
            close_time=times + pd.Timedelta(59999, unit="ms"),
            open=close * 0.9995,
            high=close * 1.0005,
            low=close * 0.9985,
            close=close,
            volume=rng.uniform(50, 200, len(close)),
        )
    )


def test_curve_is_causal_and_entries_have_confirmed_trend():
    cfg = load_config("config/all-scalping-demo.yaml")
    strategy = CurveScalpingStrategy(cfg.strategy)
    data = candles()
    result = strategy.prepare(data)
    prefix = strategy.prepare(data.iloc[:1300])
    pd.testing.assert_frame_equal(result.iloc[:1300], prefix)
    entries = result[result.enter_long]
    assert len(entries) > 0
    assert entries.curve_slope_atr.gt(0).all()
    assert entries.close.gt(result.high.shift(1).loc[entries.index]).all()
    assert entries.entry_quality_ok.all()
    assert result.curve_efficiency.between(0, 1).all()
    flat = data.copy()
    flat[["open", "high", "low", "close"]] = 100
    flat["volume"] = 0
    assert not strategy.prepare(flat).enter_long.any()


def test_all_scanner_accepts_unfamiliar_liquid_coin_without_top_cap():
    cfg = load_config("config/all-scalping-demo.yaml")
    assert cfg.universe.max_symbols is None
    names = ["BTCUSDT", "EXAMPLEUSDT", "ILLIQUIDUSDT"]
    info = {
        "symbols": [
            dict(
                symbol=s,
                baseAsset=s[:-4],
                quoteAsset="USDT",
                status="TRADING",
                isSpotTradingAllowed=True,
                ocoAllowed=True,
                orderTypes=["MARKET", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT"],
            )
            for s in names
        ]
    }
    tickers = [
        dict(symbol=s, quoteVolume="6000000" if s != "ILLIQUIDUSDT" else "20") for s in names
    ]
    books = [dict(symbol=s, bidPrice="100", askPrice="100.01") for s in names]
    selected, rejected = select_universe(cfg, info, tickers, books)
    assert {s.symbol for s in selected} == {"BTCUSDT", "EXAMPLEUSDT"}
    assert rejected == [{"symbol": "ILLIQUIDUSDT", "reason": "insufficient_quote_volume"}]
