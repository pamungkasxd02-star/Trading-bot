from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from spotlab.exchange import BinanceAPIError, BinanceRESTClient
from spotlab.models import SymbolRules
from spotlab.risk import decimal_string, floor_to_step, floor_to_tick


@dataclass(frozen=True, slots=True)
class AssetBalance:
    asset: str
    free: float
    locked: float

    @property
    def total(self) -> float:
        return self.free + self.locked


@dataclass(frozen=True, slots=True)
class ManagedPosition:
    symbol: str
    entry_time: str
    entry_price: float
    quantity: float
    entry_fee_quote: float
    entry_reason: str
    entry_order_id: str
    order_list_id: str
    protection_order_ids: tuple[str, str]
    stop_price: float
    take_profit_price: float

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["protection_order_ids"] = list(self.protection_order_ids)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ManagedPosition:
        copy = dict(payload)
        copy["protection_order_ids"] = tuple(copy["protection_order_ids"])
        return cls(**copy)


@dataclass(frozen=True, slots=True)
class ExitExecution:
    exit_time: str
    price: float
    quantity: float
    fee_quote: float
    order_id: str
    reason: str
    payload: dict[str, Any]


class BinanceBroker:
    def __init__(
        self,
        client: BinanceRESTClient,
        rules: SymbolRules,
        *,
        expected_testnet: bool,
        fee_rate: float = 0.001,
    ) -> None:
        self.client = client
        self.rules = rules
        self.expected_testnet = expected_testnet
        self.fee_rate = fee_rate

    def validate_account(self) -> None:
        account = self.client.account()
        if not account.get("canTrade", False):
            raise RuntimeError("API key tidak memiliki izin trading")

    def asset_balance(self, asset: str) -> AssetBalance:
        target = asset.upper()
        account = self.client.account()
        for balance in account.get("balances", []):
            if str(balance.get("asset", "")).upper() == target:
                return AssetBalance(
                    asset=target,
                    free=float(balance.get("free", 0)),
                    locked=float(balance.get("locked", 0)),
                )
        return AssetBalance(asset=target, free=0.0, locked=0.0)

    def _quote_fee(self, order: dict[str, Any], base_asset: str) -> tuple[float, Decimal]:
        estimated = float(order.get("cummulativeQuoteQty", 0)) * self.fee_rate
        base_commission = Decimal("0")
        quote_fee = 0.0
        saw_fee = False
        for fill in order.get("fills", []):
            commission = Decimal(str(fill.get("commission", "0")))
            asset = str(fill.get("commissionAsset", ""))
            saw_fee = saw_fee or "commission" in fill
            if asset == base_asset:
                base_commission += commission
                quote_fee += float(commission) * float(fill["price"])
                saw_fee = True
            elif asset == "USDT":
                quote_fee += float(commission)
                saw_fee = True
            elif asset and commission:
                try:
                    book = self.client.book_ticker(f"{asset}USDT")
                    quote_fee += float(commission) * float(book["askPrice"])
                except (BinanceAPIError, KeyError, ValueError):
                    # Fee conversion must never interrupt OCO placement after a buy.
                    return max(estimated, quote_fee), base_commission
                saw_fee = True
        return (quote_fee if saw_fee else estimated), base_commission

    def enter(
        self,
        *,
        symbol: str,
        base_asset: str,
        quantity: Decimal,
        stop_price: Decimal,
        take_profit_price: Decimal,
        entry_time: str,
        reason: str,
        client_order_id: str | None = None,
    ) -> tuple[ManagedPosition, list[dict[str, Any]]]:
        entry = self.client.order(
            symbol=symbol,
            side="BUY",
            type="MARKET",
            quantity=decimal_string(quantity),
            newOrderRespType="FULL",
            newClientOrderId=client_order_id,
        )
        executed = Decimal(str(entry.get("executedQty", "0")))
        quote = Decimal(str(entry.get("cummulativeQuoteQty", "0")))
        if executed <= 0:
            raise BinanceAPIError(f"Market buy tidak terisi: {entry}")
        entry_fee, base_commission = self._quote_fee(entry, base_asset)
        protect_quantity = floor_to_step(executed - base_commission, self.rules.step_size)
        stop_limit = floor_to_tick(stop_price * Decimal("0.999"), self.rules.tick_size)
        try:
            protection = self.client.create_oco(
                symbol=symbol,
                quantity=decimal_string(protect_quantity),
                take_profit_price=decimal_string(take_profit_price),
                stop_price=decimal_string(stop_price),
                stop_limit_price=decimal_string(stop_limit),
            )
        except Exception:
            # A naked position violates the project guardrail: flatten immediately.
            self.client.order(
                symbol=symbol,
                side="SELL",
                type="MARKET",
                quantity=decimal_string(protect_quantity),
                newOrderRespType="FULL",
            )
            raise
        reports = protection.get("orderReports", [])
        order_ids = tuple(str(item["orderId"]) for item in reports)
        if len(order_ids) != 2:
            raise BinanceAPIError(f"OCO tidak mengembalikan dua order: {protection}")
        position = ManagedPosition(
            symbol=symbol,
            entry_time=entry_time,
            entry_price=float(quote / executed),
            quantity=float(protect_quantity),
            entry_fee_quote=entry_fee,
            entry_reason=reason,
            entry_order_id=str(entry["orderId"]),
            order_list_id=str(protection["orderListId"]),
            protection_order_ids=(order_ids[0], order_ids[1]),
            stop_price=float(stop_price),
            take_profit_price=float(take_profit_price),
        )
        return position, [entry, protection]

    def poll_exit(self, position: ManagedPosition) -> ExitExecution | None:
        statuses = []
        for order_id in position.protection_order_ids:
            order = self.client.query_order(position.symbol, order_id)
            statuses.append(order.get("status"))
            if order.get("status") == "PARTIALLY_FILLED":
                raise BinanceAPIError("OCO partial fill; hentikan dan rekonsiliasi quantity/fee")
            if order.get("status") == "FILLED":
                quantity = float(order["executedQty"])
                quote = float(order["cummulativeQuoteQty"])
                price = quote / quantity
                fills = self.client.my_trades(position.symbol, order_id)
                fee, _ = self._quote_fee(
                    {**order, "fills": fills}, position.symbol.removesuffix("USDT")
                )
                return ExitExecution(
                    exit_time=str(order.get("updateTime", order.get("transactTime", ""))),
                    price=price,
                    quantity=quantity,
                    fee_quote=fee,
                    order_id=str(order["orderId"]),
                    reason="exchange_protection_fill",
                    payload=order,
                )
        if not all(status in {"NEW", "PENDING_NEW"} for status in statuses):
            raise BinanceAPIError(
                "OCO dibatalkan/expired tanpa fill; rekonsiliasi posisi diperlukan"
            )
        return None

    def exit_market(self, position: ManagedPosition, reason: str) -> ExitExecution:
        try:
            self.client.cancel_order_list(position.symbol, position.order_list_id)
        except BinanceAPIError:
            filled = self.poll_exit(position)
            if filled is not None:
                return filled
            raise
        order = self.client.order(
            symbol=position.symbol,
            side="SELL",
            type="MARKET",
            quantity=decimal_string(Decimal(str(position.quantity))),
            newOrderRespType="FULL",
        )
        quantity = float(order["executedQty"])
        quote = float(order["cummulativeQuoteQty"])
        if order.get("status") != "FILLED" or quantity < position.quantity * 0.999999:
            raise BinanceAPIError("Market exit belum filled penuh; rekonsiliasi diperlukan")
        fee, _ = self._quote_fee(order, position.symbol.removesuffix("USDT"))
        return ExitExecution(
            exit_time=str(order.get("transactTime", "")),
            price=quote / quantity,
            quantity=quantity,
            fee_quote=fee,
            order_id=str(order["orderId"]),
            reason=reason,
            payload=order,
        )
