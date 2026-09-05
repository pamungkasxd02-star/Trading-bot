from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from math import isfinite

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
        *,
        atr_value: float | None = None,
        cost_bps: float = 0,
    ) -> SizedOrder:
        if not all(isfinite(v) and v > 0 for v in (equity, entry_price)):
            raise RiskViolation("Equity dan harga harus positif")
        if available_quote is not None and (not isfinite(available_quote) or available_quote < 0):
            raise RiskViolation("Saldo quote tersedia tidak boleh negatif")
        cfg = self.config
        price = Decimal(str(entry_price))
        equity_decimal = Decimal(str(equity))
        stop_pct = cfg.stop_loss_pct
        target_pct = cfg.take_profit_pct
        if cfg.stop_mode == "atr":
            if atr_value is None or not isfinite(atr_value) or atr_value <= 0:
                raise RiskViolation("ATR positif wajib tersedia untuk sizing volatilitas")
            stop_pct = max(
                cfg.atr_min_stop_pct,
                min(cfg.atr_max_stop_pct, atr_value / entry_price * 100 * cfg.atr_stop_multiplier),
            )
            target_pct = stop_pct * cfg.reward_risk_ratio
        stop = floor_to_tick(
            price * (Decimal("1") - Decimal(str(stop_pct / 100))), self.rules.tick_size
        )
        take_profit = floor_to_tick(
            price * (Decimal("1") + Decimal(str(target_pct / 100))), self.rules.tick_size
        )
        if not Decimal("0") < stop < price < take_profit:
            raise RiskViolation("Tick size tidak memungkinkan stop dan target yang valid")
        risk_budget = equity_decimal * Decimal(str(cfg.risk_per_trade_pct / 100))
        risk_per_unit = price - stop + price * Decimal(str(cost_bps / 10_000))
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
        if quantity * stop * Decimal("0.998") < self.rules.min_notional:
            raise RiskViolation("Notional stop di bawah minimum exchange; posisi dilewati")
        if self.rules.max_notional is not None and quantity * take_profit > self.rules.max_notional:
            quantity = floor_to_step(self.rules.max_notional / take_profit, self.rules.step_size)
            notional = quantity * price
            if quantity < self.rules.min_qty or quantity * stop < self.rules.min_notional:
                raise RiskViolation("Tidak ada ukuran yang memenuhi notional entry dan OCO")
        return SizedOrder(quantity, notional, stop, take_profit)

    def assert_loss_limits(
        self,
        equity: float,
        day_start_equity: float,
        peak_equity: float,
    ) -> None:
        if not all(isfinite(v) and v > 0 for v in (equity, day_start_equity, peak_equity)):
            raise RiskViolation("Equity risiko harus lebih besar dari nol")
        daily_loss = (day_start_equity - equity) / day_start_equity * 100
        drawdown = (peak_equity - equity) / peak_equity * 100
        if daily_loss >= self.config.daily_loss_limit_pct:
            raise RiskViolation(f"Daily loss limit tercapai: {daily_loss:.2f}%")
        if drawdown >= self.config.max_drawdown_pct:
            raise RiskViolation(f"Max drawdown limit tercapai: {drawdown:.2f}%")
