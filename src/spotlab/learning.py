"""Forward demo with public market data. No exchange account, credentials or orders.

This intentionally never writes TradingJournal or research/paper approvals.
Account changes, decisions and fills commit together in a separate SQLite database.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import signal
import sqlite3
import time
import uuid
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from spotlab.config import AppConfig
from spotlab.data import MarketDataStore, fetch_history, parse_symbol_rules
from spotlab.exchange import MARKET_DATA_REST, PublicMarketClient, stream_klines
from spotlab.quality import interval_milliseconds
from spotlab.risk import RiskManager, RiskViolation
from spotlab.selection import ranked_entries
from spotlab.strategies import build_strategy
from spotlab.universe import discover_universe

LOGGER = logging.getLogger(__name__)


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def fingerprint(config: AppConfig) -> str:
    payload = {
        "engine": "learning-v1",
        "interval": config.demo.interval,
        "strategy": config.strategy.model_dump(),
        "risk": config.risk.model_dump(),
        "costs": config.backtest.model_dump(exclude={"initial_cash"}),
        "universe": config.universe.model_dump(),
        "symbol": config.exchange.symbol,
        "warmup": config.demo.warmup_bars,
        "quote_seconds": config.demo.quote_seconds,
        "max_hold_seconds": config.demo.max_hold_seconds,
        "max_signal_age": config.runtime.max_signal_age_seconds,
        "max_signal_drift": config.runtime.max_signal_price_drift_bps,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class DemoAccount:
    def __init__(self, config: AppConfig):
        self.config = config
        self.database = config.demo.database
        self.market = MarketDataStore(self.database)
        self.owner = ""
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS demo_account (
                    id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL,
                    owner TEXT NOT NULL DEFAULT '', heartbeat REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS demo_records (
                    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS demo_kind ON demo_records(kind, id);
            """)

    def connect(self):
        conn = sqlite3.connect(self.database, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self, initial_cash: float | None = None):
        amount = self.config.demo.initial_cash if initial_cash is None else initial_cash
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError("Saldo virtual harus positif dan finite")
        state = {
            "name": self.config.demo.name,
            "mode": "demo",
            "initial_cash": amount,
            "cash": amount,
            "equity": amount,
            "peak": amount,
            "day_start": amount,
            "day": datetime.now(UTC).date().isoformat(),
            "position": None,
            "pending": {},
            "decisions": {},
            "cooldown_until": 0,
            "halt_reason": "",
            "created_at": timestamp(),
            "quote_received_at": None,
            "fingerprint": fingerprint(self.config),
            "status": "created",
            "unobserved_gap": False,
            "quote_times": {},
        }
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT payload FROM demo_account WHERE id=1").fetchone()
            if existing:
                state = json.loads(existing[0])
                if initial_cash is not None and amount != state["initial_cash"]:
                    raise ValueError("Akun sudah ada; gunakan database demo baru untuk saldo lain")
            else:
                conn.execute(
                    "INSERT INTO demo_account(id,payload) VALUES(1,?)", (json.dumps(state),)
                )
        return state

    def start(self):
        self.initialize()
        token = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM demo_account WHERE id=1").fetchone()
            if row["owner"] and time.time() - row["heartbeat"] < 180:
                raise RuntimeError("Akun demo sedang dijalankan proses lain")
            state = json.loads(row["payload"])
            if state["fingerprint"] != fingerprint(self.config):
                raise RuntimeError("Konfigurasi berubah; pakai database akun demo baru")
            state.update(status="starting", pending={}, unobserved_gap=bool(state["position"]))
            conn.execute(
                "UPDATE demo_account SET payload=?,owner=?,heartbeat=? WHERE id=1",
                (json.dumps(state), token, time.time()),
            )
        self.owner = token

    @contextmanager
    def edit(self):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM demo_account WHERE id=1").fetchone()
            if not row or not self.owner or row["owner"] != self.owner:
                raise RuntimeError("Lease demo hilang; proses ini tidak boleh menulis saldo")
            state = json.loads(row["payload"])
            yield conn, state
            conn.execute(
                "UPDATE demo_account SET payload=?,heartbeat=? WHERE id=1",
                (json.dumps(state, allow_nan=False), time.time()),
            )

    def record(self, conn, kind, symbol, payload):
        conn.execute(
            "INSERT INTO demo_records(kind,timestamp,symbol,payload) VALUES(?,?,?,?)",
            (kind, timestamp(), symbol, json.dumps({"mode": "demo", **payload}, allow_nan=False)),
        )

    def heartbeat(self):
        with self.edit():
            pass

    def stop(self):
        with self.edit() as (conn, state):
            state.update(status="stopped", pending={})
            conn.execute("UPDATE demo_account SET owner='' WHERE id=1")
        self.owner = ""

    def status(self):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM demo_account WHERE id=1").fetchone()
            if not row:
                raise RuntimeError("Akun demo belum dibuat; jalankan demo-init")
            state = json.loads(row["payload"])
            counts = dict(conn.execute("SELECT kind,count(*) FROM demo_records GROUP BY kind"))
            candles = dict(conn.execute("SELECT symbol,count(*) FROM candles GROUP BY symbol"))
            trades = [
                json.loads(r[0])
                for r in conn.execute(
                    "SELECT payload FROM demo_records WHERE kind='trade' ORDER BY id"
                )
            ]
        pnl = [t["net_pnl"] for t in trades]
        wins, losses = [p for p in pnl if p > 0], [p for p in pnl if p < 0]
        state.pop("pending")
        state.pop("decisions")
        quote_age = (
            (datetime.now(UTC) - datetime.fromisoformat(state["quote_received_at"])).total_seconds()
            if state["quote_received_at"]
            else None
        )
        state.update(
            process_alive=bool(row["owner"]) and time.time() - row["heartbeat"] < 180,
            quote_age_seconds=quote_age,
            candles=candles,
            records=counts,
            trade_count=len(pnl),
            realized_pnl=sum(pnl),
            win_rate_pct=len(wins) / len(pnl) * 100 if pnl else None,
            profit_factor=sum(wins) / -sum(losses) if losses else None,
            expectancy=sum(pnl) / len(pnl) if pnl else None,
            learning_only=True,
            counts_toward_paper_gate=False,
            position_quote_age_seconds=(
                time.time() - state["quote_times"].get(state["position"]["symbol"], 0)
            )
            if state["position"]
            else None,
        )
        return state

    def export(self, output: str | Path):
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        (output / "summary.json").write_text(json.dumps(self.status(), indent=2) + "\n")
        with self.connect() as conn:
            for kind in ("signal", "order", "trade", "quote", "equity", "event"):
                rows = [
                    {"timestamp": r["timestamp"], "symbol": r["symbol"], **json.loads(r["payload"])}
                    for r in conn.execute(
                        "SELECT * FROM demo_records WHERE kind=? ORDER BY id", (kind,)
                    )
                ]
                pd.DataFrame(rows).to_csv(output / f"{kind}.csv", index=False)
            pd.read_sql_query("SELECT * FROM candles ORDER BY symbol,open_time", conn).to_csv(
                output / "candles.csv", index=False
            )
            backup = output / "learning.db"
            if backup.resolve() == self.database.resolve():
                raise ValueError("Backup tidak boleh menimpa database aktif")
            with sqlite3.connect(backup) as target:
                conn.backup(target)
        return output


class DemoEngine:
    def __init__(self, account: DemoAccount, rules: dict):
        self.account, self.config, self.rules = account, account.config, rules
        self.strategy = build_strategy(self.config.strategy.name, config=self.config.strategy)
        self.fee = self.config.backtest.fee_bps / 10_000
        self.slip = self.config.backtest.slippage_bps / 10_000
        if not 0 < self.fee <= 0.01 or not 0 <= self.slip <= 0.1:
            raise ValueError("Demo fee harus 0-100 bps (nonzero); slippage 0-1000 bps")

    def signal(self, symbol, row):
        """Log closed-bar decisions; only fresh forward observations can schedule a fill."""
        close_ms = int(pd.Timestamp(row["close_time"]).timestamp() * 1000)
        now_ms = int(time.time() * 1000)
        if close_ms >= now_ms:
            return
        with self.account.edit() as (conn, state):
            if close_ms <= state["decisions"].get(symbol, 0):
                return
            state["decisions"][symbol] = close_ms
            fresh = now_ms - close_ms <= self.config.runtime.max_signal_age_seconds * 1000
            payload = {
                "enter_long": bool(row["enter_long"]),
                "exit_long": bool(row["exit_long"]),
                "signal_score": float(row.get("signal_score", 0)),
                "signal_reason": str(row["signal_reason"]),
                "close_time": close_ms,
                "close": float(row["close"]),
                "volume": float(row["volume"]),
                "atr": float(row["atr"]) if pd.notna(row.get("atr")) else None,
                "fresh": fresh,
            }
            if not math.isfinite(payload["signal_score"]):
                payload["signal_score"] = 0
            self.account.record(conn, "signal", symbol, payload)
            if fresh:
                state["pending"][symbol] = payload

    def closed_candle(self, symbol, candle):
        if int(candle["close_time"]) >= time.time() * 1000:
            return
        self.account.market.upsert_closed_candle(symbol, self.config.demo.interval, candle)
        self.latest_signal(symbol)

    def latest_signal(self, symbol):
        frame = self.account.market.load_candles(symbol, self.config.demo.interval)
        if len(frame) >= self.config.demo.warmup_bars:
            # Missing recent bars invalidate signals, but remain visible in the dataset.
            frame = frame.tail(self.config.demo.warmup_bars)
            spacing = interval_milliseconds(self.config.demo.interval)
            if not frame.open_time.diff().dropna().eq(pd.Timedelta(spacing, unit="ms")).all():
                return
            self.signal(symbol, self.strategy.prepare(frame).iloc[-1])

    def quotes(self, books: list[dict]):
        now = time.time()
        valid = {}
        for book in books:
            if book["symbol"] not in self.rules:
                continue
            bid, ask = float(book["bidPrice"]), float(book["askPrice"])
            if math.isfinite(bid) and math.isfinite(ask) and 0 < bid <= ask:
                valid[book["symbol"]] = (bid, ask)
        if not valid:
            return
        with self.account.edit() as (conn, state):
            previous_quotes = state["quote_times"].copy()
            state.update(status="collecting", quote_received_at=timestamp())
            for symbol, (bid, ask) in valid.items():
                state["quote_times"][symbol] = now
                self.account.record(
                    conn, "quote", symbol, {"bid": bid, "ask": ask, "source": MARKET_DATA_REST}
                )
            position = state["position"]
            if position and now - previous_quotes.get(position["symbol"], 0) > max(
                90, self.config.demo.quote_seconds * 3
            ):
                state["unobserved_gap"] = True
            if position and position["symbol"] not in valid:
                return  # Never mark an unknown position to zero or trade on stale quotes.
            if position:
                bid = valid[position["symbol"]][0]
                value = position["quantity"] * bid
            else:
                value = 0
            state["equity"] = state["cash"] + value
            today = datetime.now(UTC).date().isoformat()
            if state["day"] != today:
                state.update(day=today, day_start=state["equity"])
            state["peak"] = max(state["peak"], state["equity"])
            try:
                RiskManager(self.config.risk, next(iter(self.rules.values()))).assert_loss_limits(
                    state["equity"], state["day_start"], state["peak"]
                )
            except RiskViolation as exc:
                state["halt_reason"] = str(exc)
            if self.config.demo.kill_switch_file.exists():
                state["halt_reason"] = "manual_stop_trading"
            pending = {
                s: r
                for s, r in state["pending"].items()
                if 0
                < now * 1000 - r["close_time"]
                <= self.config.runtime.max_signal_age_seconds * 1000
            }
            if position:
                reason = ""
                if state["unobserved_gap"]:
                    reason = "resume_exit_unobserved_gap"
                elif state["halt_reason"]:
                    reason = "risk_limit"
                elif bid <= position["stop_price"]:
                    reason = "stop_loss_observed_quote"
                elif bid >= position["take_profit_price"]:
                    reason = "take_profit_observed_quote"
                    bid = position["take_profit_price"]
                elif pending.get(position["symbol"], {}).get("exit_long"):
                    reason = "strategy_exit"
                elif self.config.demo.max_hold_seconds is not None and (
                    now - datetime.fromisoformat(position["entry_time"]).timestamp()
                    >= self.config.demo.max_hold_seconds
                ):
                    reason = "max_hold_time"
                if reason:
                    price = bid * (1 - self.slip)
                    qty = position["quantity"]
                    exit_fee = price * qty * self.fee
                    gross = (price - position["entry_price"]) * qty
                    fees = position["entry_fee"] + exit_fee
                    trade = {
                        **position,
                        "exit_time": timestamp(),
                        "exit_price": price,
                        "gross_pnl": gross,
                        "fees": fees,
                        "net_pnl": gross - fees,
                        "return_pct": (gross - fees) / (position["entry_price"] * qty) * 100,
                        "exit_reason": reason,
                        "win": gross > fees,
                    }
                    self.account.record(conn, "trade", position["symbol"], trade)
                    self.account.record(
                        conn,
                        "order",
                        position["symbol"],
                        {
                            "side": "SELL",
                            "status": "SIMULATED",
                            "price": price,
                            "quantity": qty,
                            "reason": reason,
                        },
                    )
                    state.update(
                        cash=state["cash"] + price * qty - exit_fee,
                        position=None,
                        unobserved_gap=False,
                        cooldown_until=now
                        + max(1, self.config.risk.cooldown_bars)
                        * interval_milliseconds(self.config.demo.interval)
                        / 1000,
                    )
                    LOGGER.info(
                        "DEMO SELL %s net PnL %.6f (%s)", position["symbol"], gross - fees, reason
                    )
            if (
                not state["position"]
                and not state["halt_reason"]
                and now >= state["cooldown_until"]
            ):
                for symbol in ranked_entries(pending):
                    if symbol not in valid:
                        continue
                    row = pending[symbol]
                    bid, ask = valid[symbol]
                    reason = ""
                    try:
                        if (ask - bid) / bid * 10000 > self.config.universe.max_spread_bps:
                            raise RiskViolation("spread_too_wide")
                        if (
                            abs(ask / row["close"] - 1) * 10000
                            > self.config.runtime.max_signal_price_drift_bps
                        ):
                            raise RiskViolation("signal_price_drift")
                        price = ask * (1 + self.slip)
                        sized = RiskManager(self.config.risk, self.rules[symbol]).size_long(
                            state["cash"],
                            price,
                            state["cash"] / (1 + self.fee),
                            atr_value=row["atr"],
                            cost_bps=2
                            * (self.config.backtest.fee_bps + self.config.backtest.slippage_bps),
                        )
                        qty = float(sized.quantity)
                        if (
                            qty
                            > row["volume"] * self.config.risk.max_candle_participation_pct / 100
                        ):
                            raise RiskViolation("candle_participation_limit")
                        cost = price * qty
                        fee = cost * self.fee
                        if cost + fee > state["cash"]:
                            raise RiskViolation("insufficient_virtual_cash")
                    except RiskViolation as exc:
                        reason = str(exc)
                    if reason:
                        self.account.record(
                            conn, "event", symbol, {"event": "entry_skipped", "reason": reason}
                        )
                        continue
                    state["cash"] -= cost + fee
                    state["position"] = {
                        "symbol": symbol,
                        "entry_time": timestamp(),
                        "entry_price": price,
                        "quantity": qty,
                        "entry_fee": fee,
                        "stop_price": float(sized.stop_price),
                        "take_profit_price": float(sized.take_profit_price),
                        "entry_reason": row["signal_reason"],
                    }
                    self.account.record(
                        conn,
                        "order",
                        symbol,
                        {"side": "BUY", "status": "SIMULATED", **state["position"]},
                    )
                    LOGGER.info(
                        "DEMO BUY %s qty %.8f SL %.6f TP %.6f",
                        symbol,
                        qty,
                        float(sized.stop_price),
                        float(sized.take_profit_price),
                    )
                    break
            state["pending"] = {}  # One attempt per decision; never repeat an old entry.
            position = state["position"]
            state["equity"] = state["cash"] + (
                position["quantity"] * valid[position["symbol"]][0] if position else 0
            )
            self.account.record(
                conn,
                "equity",
                "",
                {
                    "equity": state["equity"],
                    "available_quote": state["cash"],
                    "halt_reason": state["halt_reason"],
                },
            )


async def run_demo(config: AppConfig, *, duration_seconds: int | None = None):
    if config.strategy.name in {"adaptive_trend_v2", "regime_reversion_v3"}:
        needed = (
            (config.strategy.daily_ema_period + 5)
            * 86400000
            / interval_milliseconds(config.demo.interval)
        )
        if config.demo.warmup_bars < needed:
            raise ValueError(
                "Warmup demo tidak cukup untuk indikator harian; pilih interval lebih besar"
            )
    account = DemoAccount(config)
    account.start()
    client = PublicMarketClient(timeout=config.exchange.rest_timeout_seconds)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    tasks = []

    async def pause(seconds):
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=seconds)

    async def heartbeats():
        while not stop.is_set():
            account.heartbeat()
            await pause(15)

    async def deadline():
        await pause(duration_seconds)
        stop.set()

    async def guard(coro):
        try:
            await coro
        except Exception:
            stop.set()
            raise

    tasks.append(asyncio.create_task(guard(heartbeats())))
    try:
        discovery = await asyncio.to_thread(discover_universe, client, config)
        symbols = [r["symbol"] for r in discovery["selected"]]
        if not symbols:
            raise RuntimeError("Tidak ada pair yang lolos filter data demo")
        position = account.status()["position"]
        if position and position["symbol"] not in symbols:
            symbols.append(position["symbol"])
        rules = {s: parse_symbol_rules(discovery["exchange_info"], s) for s in symbols}
        for rule in rules.values():
            account.market.save_symbol_rules(rule)
        account.market.set_metadata(
            "learning_source",
            {
                "source": MARKET_DATA_REST,
                "symbols": symbols,
                "interval": config.demo.interval,
                "observed_at": timestamp(),
                "purpose": "learning_only",
            },
        )
        engine = DemoEngine(account, rules)

        def repair():
            end = datetime.now(UTC)
            for symbol in symbols:
                frame = account.market.load_candles(symbol, config.demo.interval)
                start = pd.Timestamp(end) - pd.Timedelta(
                    interval_milliseconds(config.demo.interval) * (config.demo.warmup_bars + 2),
                    unit="ms",
                )
                if not frame.empty:
                    start = min(start, frame.open_time.iloc[-1])
                watermark = account.market.metadata(f"repair:{symbol}").get("through")
                if watermark:
                    start = min(start, pd.Timestamp(watermark))
                fetch_history(
                    client, account.market, symbol, config.demo.interval, start.to_pydatetime(), end
                )
                account.market.set_metadata(f"repair:{symbol}", {"through": end.isoformat()})

        await asyncio.to_thread(repair)
        for symbol in symbols:
            engine.latest_signal(symbol)
        LOGGER.info(
            "DEMO ready: virtual account %s, %s, database %s",
            config.demo.name,
            symbols,
            account.database,
        )

        async def collect():
            async for candle in stream_klines(
                symbols,
                config.demo.interval,
                testnet=False,
                market_data_only=True,
                stop_event=stop,
                chunk_size=config.runtime.streams_per_connection,
            ):
                if candle["closed"]:
                    engine.closed_candle(candle["symbol"], candle)

        async def quote_loop():
            while not stop.is_set():
                try:
                    started = time.monotonic()
                    books = await asyncio.to_thread(client.book_ticker)
                    if time.monotonic() - started <= config.demo.quote_seconds:
                        engine.quotes(books)
                except RuntimeError as exc:
                    LOGGER.warning("Public quote unavailable: %s", exc)
                await pause(config.demo.quote_seconds)

        async def repair_loop():
            while not stop.is_set():
                await pause(config.demo.repair_seconds)
                if stop.is_set():
                    break
                try:
                    await asyncio.to_thread(repair)
                    for symbol in symbols:
                        engine.latest_signal(symbol)
                except RuntimeError as exc:
                    LOGGER.warning("Candle backfill unavailable: %s", exc)

        tasks.extend(
            asyncio.create_task(guard(c)) for c in (collect(), quote_loop(), repair_loop())
        )
        if duration_seconds is not None:
            tasks.append(asyncio.create_task(deadline()))
        await stop.wait()
        # Propagate fatal worker errors; network reconnects are handled inside the workers.
        for task in tasks:
            if task.done() and not task.cancelled() and task.exception():
                raise task.exception()
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        account.stop()
        LOGGER.info(
            "Demo stopped; SQLite account/data retained. Virtual stops are inactive offline."
        )
