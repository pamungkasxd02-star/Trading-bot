from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from spotlab.config import RiskConfig
from spotlab.models import SymbolRules


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        raise ValueError("step must be positive")
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def floor_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    return floor_to_step(value, tick)


def decimal_string(value: Decimal) -> str:
    return format(value.normalize(), "f")


@dataclass(frozen=True, slots=True)
class SizedOrder:
    quantity: Decimal
    notional: Decimal
    stop_price: Decimal
    take_profit_price: Decimal


class RiskViolation(RuntimeError):
    pass


class RiskManager:
    def __init__(self, config: RiskConfig, rules: SymbolRules) -> None:
        self.config = config
        self.rules = rules

    def size_long(
        self,
        equity: float,
        entry_price: float,
        available_quote: float | None = None,
    ) -> SizedOrder:
        if equity <= 0 or entry_price <= 0:
            raise RiskViolation("Equity dan harga harus positif")
        if available_quote is not None and available_quote < 0:
            raise RiskViolation("Saldo quote tersedia tidak boleh negatif")
        cfg = self.config
        price = Decimal(str(entry_price))
        equity_decimal = Decimal(str(equity))
        risk_budget = equity_decimal * Decimal(str(cfg.risk_per_trade_pct / 100))
        risk_per_unit = price * Decimal(str(cfg.stop_loss_pct / 100))
        by_risk = risk_budget / risk_per_unit
        by_allocation = equity_decimal * Decimal(str(cfg.max_allocation_pct / 100)) / price
        limits = [by_risk, by_allocation, self.rules.max_qty]
        if self.rules.max_notional is not None:
            limits.append(self.rules.max_notional / price)
        if cfg.max_position_notional_usdt is not None:
            limits.append(Decimal(str(cfg.max_position_notional_usdt)) / price)
        if available_quote is not None:
            buffer = Decimal("1") - Decimal(str(cfg.market_order_buffer_pct / 100))
            limits.append(Decimal(str(available_quote)) * buffer / price)
        quantity = floor_to_step(min(limits), self.rules.step_size)
        notional = quantity * price
        if quantity < self.rules.min_qty:
            raise RiskViolation("Quantity di bawah LOT_SIZE minimum")
        if notional < self.rules.min_notional:
            raise RiskViolation(
                f"Notional {notional} di bawah minimum exchange {self.rules.min_notional}"
            )
        stop = floor_to_tick(
            price * (Decimal("1") - Decimal(str(cfg.stop_loss_pct / 100))),
            self.rules.tick_size,
        )
        take_profit = floor_to_tick(
            price * (Decimal("1") + Decimal(str(cfg.take_profit_pct / 100))),
            self.rules.tick_size,
        )
        return SizedOrder(quantity, notional, stop, take_profit)

    def assert_loss_limits(
        self,
        equity: float,
        day_start_equity: float,
        peak_equity: float,
    ) -> None:
        if equity <= 0 or day_start_equity <= 0 or peak_equity <= 0:
            raise RiskViolation("Equity risiko harus lebih besar dari nol")
        daily_loss = (day_start_equity - equity) / day_start_equity * 100
        drawdown = (peak_equity - equity) / peak_equity * 100
        if daily_loss >= self.config.daily_loss_limit_pct:
            raise RiskViolation(f"Daily loss limit tercapai: {daily_loss:.2f}%")
        if drawdown >= self.config.max_drawdown_pct:
            raise RiskViolation(f"Max drawdown limit tercapai: {drawdown:.2f}%")
