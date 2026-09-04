from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress
from datetime import UTC, datetime

import pandas as pd

from spotlab.config import AppConfig
from spotlab.data import MarketDataStore
from spotlab.exchange import stream_closed_klines
from spotlab.execution.broker import AssetBalance, BinanceBroker, ExitExecution, ManagedPosition
from spotlab.journal import TradingJournal
from spotlab.notifier import TelegramNotifier
from spotlab.risk import RiskManager, RiskViolation
from spotlab.strategies.base import Strategy

LOGGER = logging.getLogger(__name__)


class RealtimeRunner:
    def __init__(
        self,
        *,
        mode: str,
        config: AppConfig,
        strategy: Strategy,
        store: MarketDataStore,
        journal: TradingJournal,
        broker: BinanceBroker,
        notifier: TelegramNotifier,
    ) -> None:
        self.mode = mode
        self.config = config
        self.strategy = strategy
        self.store = store
        self.journal = journal
        self.broker = broker
        self.notifier = notifier
        self.stop_event = asyncio.Event()
        payload = journal.load_position(mode)
        self.position = ManagedPosition.from_dict(payload) if payload else None

    def request_stop(self) -> None:
        self.stop_event.set()

    async def _account_capital(self, mark_price: float) -> tuple[AssetBalance, float, float]:
        balance = await asyncio.to_thread(self.broker.asset_balance, "USDT")
        position_value = self.position.quantity * mark_price if self.position is not None else 0.0
        return balance, balance.total + position_value, position_value

    def _record_equity(
        self,
        session_id: int,
        balance: AssetBalance,
        equity: float,
        position_value: float,
    ) -> None:
        self.journal.log_equity(
            session_id,
            self.mode,
            equity,
            balance.free,
            balance.locked,
            position_value,
        )

    def _record_exit(self, session_id: int, execution: ExitExecution) -> None:
        assert self.position is not None
        position = self.position
        quantity = min(position.quantity, execution.quantity)
        gross = (execution.price - position.entry_price) * quantity
        fees = position.entry_fee_quote + execution.fee_quote
        net = gross - fees
        trade = {
            "entry_time": position.entry_time,
            "exit_time": _normalize_exchange_time(execution.exit_time),
            "entry_price": position.entry_price,
            "exit_price": execution.price,
            "quantity": quantity,
            "gross_pnl": gross,
            "fees": fees,
            "net_pnl": net,
            "return_pct": net / (position.entry_price * quantity) * 100,
            "entry_reason": position.entry_reason,
            "exit_reason": execution.reason,
        }
        self.journal.log_order(
            session_id,
            self.mode,
            position.symbol,
            "SELL",
            "PROTECTION_OR_MARKET",
            execution.order_id,
            "FILLED",
            quantity,
            execution.price,
            execution.payload,
        )
        self.journal.log_trade(session_id, self.mode, position.symbol, trade)
        self.journal.clear_position(self.mode)
        self.position = None
        self.notifier.send(
            f"[{self.mode.upper()}] EXIT {position.symbol} | PnL {net:.6f} USDT | "
            f"{execution.reason}"
        )

    async def _supervise(self, session_id: int) -> None:
        while not self.stop_event.is_set():
            if self.config.runtime.kill_switch_file.exists():
                LOGGER.warning("Kill-switch terdeteksi; OCO aktif dibiarkan melindungi posisi")
                self.stop_event.set()
                return
            self.journal.heartbeat(session_id)
            with suppress(TimeoutError):
                await asyncio.wait_for(self.stop_event.wait(), timeout=30)

    async def run(self) -> None:
        if self.config.runtime.kill_switch_file.exists():
            raise RuntimeError("Kill-switch aktif; jalankan `spotlab clear-kill` setelah diperiksa")
        await asyncio.to_thread(self.broker.validate_account)
        session_id = self.journal.start_session(
            self.mode, self.config.runtime.session_stale_seconds
        )
        supervisor = asyncio.create_task(self._supervise(session_id))
        reason = "operator stop"
        status = "stopped"
        try:
            await self._loop(session_id)
            if self.config.runtime.kill_switch_file.exists():
                reason = "kill-switch"
        except Exception:
            status = "halted"
            reason = "runtime exception"
            raise
        finally:
            self.stop_event.set()
            supervisor.cancel()
            with suppress(asyncio.CancelledError):
                await supervisor
            self.journal.end_session(session_id, status, reason)

    async def _loop(self, session_id: int) -> None:
        symbol = self.config.exchange.symbol.upper()
        if not symbol.endswith("USDT"):
            raise RuntimeError("Versi baseline hanya mendukung quote asset USDT")
        base_asset = symbol.removesuffix("USDT")
        history = self.store.load_candles(symbol, self.config.exchange.interval).tail(400)
        if len(history) < max(self.config.strategy.sma_trend, self.config.strategy.ema_slow) + 5:
            raise RuntimeError("Cache candle belum cukup; jalankan `spotlab fetch` dahulu")

        latest_mark = float(history.iloc[-1]["close"])
        if self.position is not None:
            execution = await asyncio.to_thread(self.broker.poll_exit, self.position)
            if execution is not None:
                self._record_exit(session_id, execution)
        balance, equity, position_value = await self._account_capital(latest_mark)
        if equity <= 0:
            raise RuntimeError("Saldo USDT akun dan nilai posisi bot harus lebih besar dari nol")
        self._record_equity(session_id, balance, equity, position_value)
        state = self.journal.get_or_reset_risk_state(self.mode, equity)
        RiskManager(self.config.risk, self.store.load_symbol_rules(symbol)).assert_loss_limits(
            equity, float(state["day_start_equity"]), float(state["peak_equity"])
        )

        async for candle in stream_closed_klines(
            symbol,
            self.config.exchange.interval,
            testnet=self.config.exchange.testnet,
            stop_event=self.stop_event,
        ):
            if self.stop_event.is_set():
                break
            self.store.upsert_closed_candle(symbol, self.config.exchange.interval, candle)
            row = dict(candle)
            row["open_time"] = pd.to_datetime(row["open_time"], unit="ms", utc=True)
            row["close_time"] = pd.to_datetime(row["close_time"], unit="ms", utc=True)
            history = pd.concat([history, pd.DataFrame([row])], ignore_index=True)
            history = history.drop_duplicates("open_time", keep="last").tail(400)
            prepared = self.strategy.prepare(history)
            latest = prepared.iloc[-1]

            if self.position is not None:
                execution = await asyncio.to_thread(self.broker.poll_exit, self.position)
                if execution is not None:
                    self._record_exit(session_id, execution)

            action = "hold"
            if bool(latest["exit_long"]):
                action = "exit_long"
            elif bool(latest["enter_long"]):
                action = "enter_long"
            self.journal.log_signal(
                session_id,
                self.mode,
                symbol,
                action,
                str(latest["signal_reason"]),
                float(latest["close"]),
                {"confirmation_count": int(latest["confirmation_count"])},
            )

            if self.position is not None and action == "exit_long":
                execution = await asyncio.to_thread(
                    self.broker.exit_market, self.position, "strategy_exit"
                )
                self._record_exit(session_id, execution)
            elif self.position is None and action == "enter_long":
                balance, equity, _ = await self._account_capital(float(latest["close"]))
                await self._enter(
                    session_id,
                    symbol,
                    base_asset,
                    float(latest["close"]),
                    str(latest["close_time"]),
                    str(latest["signal_reason"]),
                    equity,
                    balance.free,
                )

            balance, equity, position_value = await self._account_capital(float(latest["close"]))
            self._record_equity(session_id, balance, equity, position_value)
            state = self.journal.get_or_reset_risk_state(self.mode, equity)
            RiskManager(self.config.risk, self.store.load_symbol_rules(symbol)).assert_loss_limits(
                equity, float(state["day_start_equity"]), float(state["peak_equity"])
            )

    async def _enter(
        self,
        session_id: int,
        symbol: str,
        base_asset: str,
        mark_price: float,
        entry_time: str,
        reason: str,
        equity: float,
        available_quote: float,
    ) -> None:
        rules = self.store.load_symbol_rules(symbol)
        manager = RiskManager(self.config.risk, rules)
        state = self.journal.get_or_reset_risk_state(self.mode, equity)
        manager.assert_loss_limits(
            equity,
            float(state["day_start_equity"]),
            float(state["peak_equity"]),
        )
        try:
            sized = manager.size_long(equity, mark_price, available_quote)
        except RiskViolation as error:
            LOGGER.info("Entry dilewati: %s", error)
            return
        position, raw_orders = await asyncio.to_thread(
            self.broker.enter,
            symbol=symbol,
            base_asset=base_asset,
            quantity=sized.quantity,
            stop_price=sized.stop_price,
            take_profit_price=sized.take_profit_price,
            entry_time=entry_time,
            reason=reason,
        )
        self.position = position
        self.journal.save_position(self.mode, symbol, position.to_dict())
        self.journal.log_order(
            session_id,
            self.mode,
            symbol,
            "BUY",
            "MARKET+OCO",
            position.entry_order_id,
            "PROTECTED",
            position.quantity,
            position.entry_price,
            {"orders": raw_orders},
        )
        self.notifier.send(
            f"[{self.mode.upper()}] ENTRY {symbol} {position.quantity:g} @ "
            f"{position.entry_price:.2f} | SL {position.stop_price:.2f} | "
            f"TP {position.take_profit_price:.2f}"
        )


def _normalize_exchange_time(value: str) -> str:
    if value.isdigit():
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC).isoformat()
    return value or datetime.now(UTC).isoformat()


def install_signal_handlers(runner: RealtimeRunner) -> None:
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signal_name, runner.request_stop)


async def run_realtime(runner: RealtimeRunner) -> None:
    install_signal_handlers(runner)
    await runner.run()
