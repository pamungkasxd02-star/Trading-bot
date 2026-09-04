from decimal import Decimal

import pytest

from spotlab.config import RiskConfig
from spotlab.models import SymbolRules
from spotlab.risk import RiskManager, RiskViolation, floor_to_step


def rules(min_notional: str = "5") -> SymbolRules:
    return SymbolRules(
        symbol="BTCUSDT",
        min_qty=Decimal("0.00001"),
        max_qty=Decimal("9000"),
        step_size=Decimal("0.00001"),
        tick_size=Decimal("0.01"),
        min_notional=Decimal(min_notional),
        max_notional=Decimal("9000000"),
    )


def test_floor_to_step_never_rounds_up() -> None:
    assert floor_to_step(Decimal("0.001239"), Decimal("0.00001")) == Decimal("0.00123")


def test_position_size_respects_small_account_and_filters() -> None:
    sized = RiskManager(RiskConfig(), rules()).size_long(20.0, 50_000.0)
    assert sized.quantity == Decimal("0.00013")
    assert sized.notional == Decimal("6.500000")
    assert sized.stop_price == Decimal("48500.00")
    assert sized.take_profit_price == Decimal("53000.00")


def test_min_notional_can_block_tiny_account() -> None:
    with pytest.raises(RiskViolation, match="minimum exchange"):
        RiskManager(RiskConfig(max_allocation_pct=10), rules()).size_long(20.0, 50_000.0)


def test_daily_loss_and_drawdown_halt() -> None:
    manager = RiskManager(RiskConfig(), rules())
    with pytest.raises(RiskViolation, match="Daily loss"):
        manager.assert_loss_limits(19.3, 20.0, 20.0)


def test_zero_equity_state_halts_cleanly() -> None:
    manager = RiskManager(RiskConfig(), rules())
    with pytest.raises(RiskViolation, match="lebih besar dari nol"):
        manager.assert_loss_limits(0.0, 0.0, 0.0)


def test_large_account_is_clamped_to_exchange_maximum() -> None:
    sized = RiskManager(RiskConfig(), rules()).size_long(1_000_000_000.0, 50_000.0)
    assert sized.notional == Decimal("9000000.00000")
    assert sized.quantity == Decimal("180.00000")


def test_available_balance_and_market_buffer_cap_order() -> None:
    config = RiskConfig(market_order_buffer_pct=0.5)
    sized = RiskManager(config, rules()).size_long(
        equity=10_000.0,
        entry_price=50_000.0,
        available_quote=1_000.0,
    )
    assert sized.notional <= Decimal("995")
    assert sized.notional > Decimal("990")
