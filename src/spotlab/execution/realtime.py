from __future__ import annotations

import asyncio
import logging
import signal
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime

import pandas as pd

from spotlab.config import AppConfig
from spotlab.data import MarketDataStore, fetch_history
from spotlab.exchange import stream_klines
from spotlab.execution.broker import AssetBalance, BinanceBroker, ExitExecution, ManagedPosition
from spotlab.journal import TradingJournal
from spotlab.notifier import TelegramNotifier
from spotlab.quality import interval_milliseconds
from spotlab.risk import RiskManager, RiskViolation
from spotlab.selection import ranked_entries
from spotlab.strategies.base import Strategy
from spotlab.universe import spread_bps

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
        brokers: dict[str, BinanceBroker] | None = None,
        fingerprint: str = "",
    ) -> None:
        self.mode = mode
        self.config = config
        self.strategy = strategy
        self.store = store
        self.journal = journal
        self.broker = broker
        self.brokers = brokers or {config.exchange.symbol.upper(): broker}
        self.fingerprint = fingerprint
        self.notifier = notifier
        self.stop_event = asyncio.Event()
        payload = journal.load_position(mode)
        self.position = ManagedPosition.from_dict(payload) if payload else None
        self.lock = asyncio.Lock()
        self.marks: dict[str, float] = {}
        self.seen: dict[str, float] = {}
        self.histories: dict[str, pd.DataFrame] = {}
        self.cooldown_until: dict[str, pd.Timestamp] = {}
        duration = pd.Timedelta(interval_milliseconds(config.exchange.interval), unit="ms")
        for trade in journal.trade_rows(mode):
            self.cooldown_until[trade["symbol"]] = (
                pd.Timestamp(trade["exit_time"]) + duration * config.risk.cooldown_bars
            )

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
        if not self.journal.close_recorded_position(session_id, self.mode, position.symbol, trade):
            raise RuntimeError("Posisi jurnal berubah saat merekam exit; rekonsiliasi diperlukan")
        self.position = None
        self.cooldown_until[position.symbol] = pd.Timestamp(trade["exit_time"]) + pd.Timedelta(
            interval_milliseconds(self.config.exchange.interval) * self.config.risk.cooldown_bars,
            unit="ms",
        )
        self.notifier.send(
            f"[{self.mode.upper()}] EXIT {position.symbol} | PnL {net:.6f} USDT | "
            f"{execution.reason}"
        )

    async def _supervise(self, session_id: int) -> None:
        started = time.monotonic()
        while not self.stop_event.is_set():
            if self.config.runtime.kill_switch_file.exists():
                self.request_stop()
                return
            async with self.lock:
                if self.position is not None:
                    execution = await asyncio.to_thread(
                        self.brokers[self.position.symbol].poll_exit, self.position
                    )
                    if execution is not None:
                        self._record_exit(session_id, execution)
                fresh = self._market_fresh()
                if fresh:
                    await self._check_account(session_id)
                    self.journal.heartbeat(session_id)
                elif time.monotonic() - started > self.config.runtime.session_stale_seconds:
                    raise RuntimeError("Market data basi; entry dihentikan dan OCO tetap aktif")
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    self.stop_event.wait(), timeout=self.config.runtime.supervision_seconds
                )

    def _market_fresh(self) -> bool:
        now = time.monotonic()
        symbols = [self.position.symbol] if self.position is not None else list(self.brokers)
        return all(
            now - self.seen.get(symbol, -1e20) < self.config.runtime.max_signal_age_seconds
            for symbol in symbols
        )

    async def _check_account(self, session_id: int) -> tuple[AssetBalance, float]:
        price = self.marks.get(self.position.symbol, 0) if self.position is not None else 0
        balance, equity, position_value = await self._account_capital(price)
        self._record_equity(session_id, balance, equity, position_value)
        state = self.journal.get_or_reset_risk_state(self.mode, equity)
        RiskManager(self.config.risk, self.broker.rules).assert_loss_limits(
            equity, float(state["day_start_equity"]), float(state["peak_equity"])
        )
        return balance, equity

    async def run(self) -> None:
        if self.config.runtime.kill_switch_file.exists():
            raise RuntimeError("Kill-switch aktif; periksa exchange sebelum clear-kill")
        if self.journal.pending_intent(self.mode):
            raise RuntimeError(
                "Order intent belum direkonsiliasi; gunakan inspect-intent dan periksa exchange"
            )
        if self.position is not None and self.position.symbol not in self.brokers:
            raise RuntimeError(
                "Posisi tersimpan berada di luar universe; sertakan pair posisi saat restart"
            )
        await asyncio.to_thread(self.broker.validate_account)
        for symbol in self.brokers:
            history = self.store.load_candles(symbol, self.config.exchange.interval)
            if (
                len(history)
                < max(self.config.strategy.sma_trend, self.config.strategy.ema_slow) + 5
            ):
                raise RuntimeError(f"Cache {symbol} belum cukup; fetch dahulu")
            if self.config.strategy.name in {"adaptive_trend_v2", "regime_reversion_v3"}:
                days = (history.open_time.max() - history.open_time.min()).total_seconds() / 86400
                if days < self.config.strategy.daily_ema_period + 2:
                    raise RuntimeError(f"{symbol}: candle harian selesai belum cukup untuk warmup")
            self.histories[symbol] = history.tail(self.config.runtime.history_bars)
        session_id = self.journal.start_session(
            self.mode, self.config.runtime.session_stale_seconds, self.fingerprint
        )
        status, reason = "stopped", "operator stop"
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(self._supervise(session_id))
                group.create_task(self._loop(session_id))
        except Exception:
            status, reason = "halted", "runtime exception; inspect before restart"
            self.config.runtime.kill_switch_file.touch()
            raise
        finally:
            self.request_stop()
            self.journal.end_session(session_id, status, reason)

    async def _loop(self, session_id: int) -> None:
        queue: asyncio.Queue[dict | Exception] = asyncio.Queue(maxsize=2048)

        async def read_stream() -> None:
            try:
                async for item in stream_klines(
                    list(self.brokers),
                    self.config.exchange.interval,
                    testnet=self.config.exchange.testnet,
                    stop_event=self.stop_event,
                    chunk_size=self.config.runtime.streams_per_connection,
                ):
                    await queue.put(item)
            except Exception as error:
                await queue.put(error)

        reader = asyncio.create_task(read_stream())
        pending: dict[int, dict[str, dict]] = {}
        deadlines: dict[int, float] = {}
        try:
            while not self.stop_event.is_set():
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=0.5)
                except TimeoutError:
                    item = None
                if isinstance(item, Exception):
                    raise item
                if item is not None:
                    symbol = item["symbol"]
                    if symbol not in self.brokers:
                        continue
                    now_ms = datetime.now(UTC).timestamp() * 1000
                    age_ms = now_ms - item["close_time"]
                    if (
                        item["open_time"] > now_ms
                        or age_ms > self.config.runtime.max_signal_age_seconds * 1000
                    ):
                        continue
                    self.marks[symbol], self.seen[symbol] = float(item["close"]), time.monotonic()
                    if item["closed"]:
                        epoch = item["open_time"]
                        pending.setdefault(epoch, {})[symbol] = item
                        deadlines.setdefault(
                            epoch, time.monotonic() + self.config.runtime.signal_batch_seconds
                        )
                for epoch in sorted(list(pending)):
                    if time.monotonic() >= deadlines[epoch]:
                        async with self.lock:
                            await self._process_batch(session_id, pending.pop(epoch))
                        deadlines.pop(epoch)
        finally:
            self.request_stop()
            reader.cancel()
            with suppress(asyncio.CancelledError):
                await reader

    async def _process_batch(self, session_id: int, candles: dict[str, dict]) -> None:
        rows = {}
        interval = self.config.exchange.interval
        interval_ms = interval_milliseconds(interval)
        for symbol, candle in sorted(candles.items()):
            self.store.upsert_closed_candle(symbol, interval, candle)
            history = self.histories[symbol]
            last_ms = int(pd.Timestamp(history.iloc[-1].open_time).timestamp() * 1000)
            if candle["open_time"] > last_ms + interval_ms:
                await asyncio.to_thread(
                    fetch_history,
                    self.brokers[symbol].client,
                    self.store,
                    symbol,
                    interval,
                    pd.Timestamp(history.iloc[-1].open_time).to_pydatetime(),
                    datetime.now(UTC),
                )
                history = self.store.load_candles(symbol, interval)
            row = dict(candle)
            row["open_time"] = pd.to_datetime(row["open_time"], unit="ms", utc=True)
            row["close_time"] = pd.to_datetime(row["close_time"], unit="ms", utc=True)
            history = pd.concat([history, pd.DataFrame([row])], ignore_index=True)
            history = (
                history.drop_duplicates("open_time", keep="last")
                .sort_values("open_time")
                .tail(self.config.runtime.history_bars)
            )
            self.histories[symbol] = history
            age = (datetime.now(UTC) - row["close_time"].to_pydatetime()).total_seconds()
            if age < 0 or age > self.config.runtime.max_signal_age_seconds:
                continue
            if not history.open_time.diff().dropna().eq(pd.Timedelta(interval_ms, unit="ms")).all():
                LOGGER.warning("%s: gap belum pulih; sinyal dilewati", symbol)
                continue
            if not self.journal.claim_candle(self.mode, symbol, interval, candle["open_time"]):
                continue
            latest = self.strategy.prepare(history).iloc[-1]
            action = (
                "exit_long"
                if bool(latest["exit_long"])
                else "enter_long"
                if bool(latest["enter_long"])
                else "hold"
            )
            self.journal.log_signal(
                session_id,
                self.mode,
                symbol,
                action,
                str(latest["signal_reason"]),
                float(latest["close"]),
                {
                    "signal_score": float(latest["signal_score"]),
                    "candle_open_time": candle["open_time"],
                    "fingerprint": self.fingerprint,
                },
            )
            rows[symbol] = latest
        if not rows or not self._market_fresh():
            return
        if self.position is not None:
            broker = self.brokers[self.position.symbol]
            execution = await asyncio.to_thread(broker.poll_exit, self.position)
            if (
                execution is None
                and self.position.symbol in rows
                and bool(rows[self.position.symbol]["exit_long"])
            ):
                self.journal.set_intent(
                    self.mode,
                    {
                        "symbol": self.position.symbol,
                        "action": "SELL",
                        "order_list_id": self.position.order_list_id,
                        "created_at": datetime.now(UTC).isoformat(),
                    },
                )
                execution = await asyncio.to_thread(
                    broker.exit_market, self.position, "strategy_exit"
                )
            if execution is not None:
                self._record_exit(session_id, execution)
        balance, equity = await self._check_account(session_id)
        if self.position is not None:
            return
        for symbol in ranked_entries(rows):
            row = rows[symbol]
            until = self.cooldown_until.get(symbol)
            if until is not None and pd.Timestamp(row["close_time"]) <= until:
                continue
            if await self._enter_ranked(session_id, symbol, row, balance, equity):
                break

    async def _enter_ranked(
        self, session_id: int, symbol: str, row: pd.Series, balance: AssetBalance, equity: float
    ) -> bool:
        broker = self.brokers[symbol]
        book = await asyncio.to_thread(broker.client.book_ticker, symbol)
        if spread_bps(book) > self.config.universe.max_spread_bps:
            LOGGER.info("%s: entry dilewati karena spread", symbol)
            return False
        price = float(book["askPrice"])
        drift = abs(price / float(row["close"]) - 1) * 10_000
        if drift > self.config.runtime.max_signal_price_drift_bps:
            LOGGER.info("%s: harga telah menjauh dari sinyal", symbol)
            return False
        liquidity = (
            float(row["volume"])
            * float(row["close"])
            * self.config.risk.max_candle_participation_pct
            / 100
        )
        try:
            sized = RiskManager(self.config.risk, broker.rules).size_long(
                equity,
                price,
                min(balance.free, liquidity),
                atr_value=row.get("atr"),
                cost_bps=2 * (self.config.backtest.fee_bps + self.config.backtest.slippage_bps),
            )
        except RiskViolation as error:
            LOGGER.info("%s: entry dilewati: %s", symbol, error)
            return False
        client_id = "sl_" + uuid.uuid4().hex[:28]
        self.journal.set_intent(
            self.mode,
            {
                "symbol": symbol,
                "client_order_id": client_id,
                "quantity": str(sized.quantity),
                "action": "BUY",
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        position, orders = await asyncio.to_thread(
            broker.enter,
            symbol=symbol,
            base_asset=symbol.removesuffix("USDT"),
            quantity=sized.quantity,
            stop_price=sized.stop_price,
            take_profit_price=sized.take_profit_price,
            entry_time=datetime.now(UTC).isoformat(),
            reason=str(row["signal_reason"]),
            client_order_id=client_id,
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
            {"orders": orders},
        )
        self.journal.clear_intent(self.mode)
        self.notifier.send(
            f"[{self.mode.upper()}] ENTRY {symbol} {position.quantity:g} @ "
            f"{position.entry_price:.8g} | SL {position.stop_price:.8g} | "
            f"TP {position.take_profit_price:.8g}"
        )
        return True


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
