from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class SignalAction(StrEnum):
    HOLD = "hold"
    ENTER_LONG = "enter_long"
    EXIT_LONG = "exit_long"


@dataclass(frozen=True, slots=True)
class Signal:
    action: SignalAction
    reason: str
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class SymbolRules:
    symbol: str
    min_qty: Decimal
    max_qty: Decimal
    step_size: Decimal
    tick_size: Decimal
    min_notional: Decimal
    max_notional: Decimal | None = None


@dataclass(slots=True)
class Position:
    entry_time: datetime
    entry_price: float
    quantity: float
    entry_fee: float
    stop_price: float
    take_profit_price: float
    entry_reason: str
    entry_order_id: str | None = None
    protection_order_list_id: str | None = None


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: float
    gross_pnl: float
    fees: float
    net_pnl: float
    return_pct: float
    exit_reason: str
    entry_reason: str
