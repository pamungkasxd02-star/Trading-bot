from datetime import timedelta
from decimal import Decimal

import pandas as pd

from spotlab.backtest import Backtester
from spotlab.config import BacktestConfig, RiskConfig
from spotlab.models import SymbolRules
from spotlab.strategies.base import Strategy


class OneTradeStrategy(Strategy):
    def prepare(self, candles: pd.DataFrame) -> pd.DataFrame:
        frame = candles.copy()
        frame["enter_long"] = False
        frame["exit_long"] = False
        frame["signal_reason"] = "hold"
        frame.loc[0, ["enter_long", "signal_reason"]] = [True, "test_entry"]
        frame.loc[2, ["exit_long", "signal_reason"]] = [True, "test_exit"]
        return frame


def test_backtest_uses_next_bar_and_charges_two_sided_costs() -> None:
    time = pd.date_range("2025-01-01", periods=5, freq="4h", tz="UTC")
    frame = pd.DataFrame(
        {
            "open_time": time,
            "close_time": time + timedelta(hours=4),
            "open": [100, 100, 101, 102, 102],
            "high": [101, 102, 103, 103, 103],
            "low": [99, 99, 100, 101, 101],
            "close": [100, 101, 102, 102, 102],
            "volume": [100] * 5,
        }
    )
    rules = SymbolRules(
        "BTCUSDT",
        Decimal("0.001"),
        Decimal("100"),
        Decimal("0.001"),
        Decimal("0.01"),
        Decimal("0.5"),
    )
    result = Backtester(
        OneTradeStrategy(),
        BacktestConfig(initial_cash=20, fee_bps=10, slippage_bps=5),
        RiskConfig(stop_loss_pct=20, take_profit_pct=50),
        rules,
    ).run(frame)
    assert result.metrics.trade_count == 1
    assert result.trades.iloc[0]["entry_price"] > 100
    assert result.trades.iloc[0]["exit_price"] < 102
    assert result.metrics.total_fees > 0


def test_same_bar_stop_and_target_uses_pessimistic_stop() -> None:
    time = pd.date_range("2025-01-01", periods=3, freq="4h", tz="UTC")
    frame = pd.DataFrame(
        {
            "open_time": time,
            "close_time": time + timedelta(hours=4),
            "open": [100, 100, 100],
            "high": [100, 110, 100],
            "low": [100, 90, 100],
            "close": [100, 100, 100],
            "volume": [100] * 3,
        }
    )
    rules = SymbolRules(
        "BTCUSDT", Decimal("0.001"), Decimal("100"), Decimal("0.001"), Decimal("0.01"), Decimal("5")
    )
    result = Backtester(
        OneTradeStrategy(), BacktestConfig(slippage_bps=0), RiskConfig(), rules
    ).run(frame)
    assert result.trades.iloc[0]["exit_reason"] == "stop_loss"
