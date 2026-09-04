from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class TradingJournal:
    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mode TEXT NOT NULL CHECK(mode IN ('paper', 'live')),
                    started_at TEXT NOT NULL,
                    last_heartbeat TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL,
                    stop_reason TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ux_one_running_mode
                    ON sessions(mode) WHERE status = 'running';
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    close_price REAL NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    exchange_order_id TEXT,
                    status TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    gross_pnl REAL NOT NULL,
                    fees REAL NOT NULL,
                    net_pnl REAL NOT NULL,
                    return_pct REAL NOT NULL,
                    entry_reason TEXT NOT NULL,
                    exit_reason TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );
                CREATE TABLE IF NOT EXISTS risk_state (
                    mode TEXT PRIMARY KEY,
                    trading_day TEXT NOT NULL,
                    day_start_equity REAL NOT NULL,
                    peak_equity REAL NOT NULL,
                    managed_equity REAL NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS positions (
                    mode TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS equity_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    equity REAL NOT NULL,
                    available_quote REAL NOT NULL,
                    locked_quote REAL NOT NULL,
                    position_value REAL NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );
                CREATE INDEX IF NOT EXISTS ix_equity_snapshots_mode_time
                    ON equity_snapshots(mode, timestamp);
                """
            )

    def start_session(self, mode: str, stale_seconds: int = 180) -> int:
        now = datetime.now(UTC)
        cutoff = (now - timedelta(seconds=stale_seconds)).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE sessions SET status='stale', ended_at=last_heartbeat,
                    stop_reason='stale heartbeat recovered'
                WHERE mode=? AND status='running' AND last_heartbeat < ?
                """,
                (mode, cutoff),
            )
            active = connection.execute(
                "SELECT id FROM sessions WHERE mode=? AND status='running'", (mode,)
            ).fetchone()
            if active:
                raise RuntimeError(f"Session {mode} lain masih aktif (id={active['id']})")
            cursor = connection.execute(
                """
                INSERT INTO sessions(mode, started_at, last_heartbeat, status)
                VALUES (?, ?, ?, 'running')
                """,
                (mode, now.isoformat(), now.isoformat()),
            )
            return int(cursor.lastrowid)

    def heartbeat(self, session_id: int) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE sessions SET last_heartbeat=? WHERE id=? AND status='running'",
                (datetime.now(UTC).isoformat(), session_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Session tidak aktif")

    def end_session(self, session_id: int, status: str, reason: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE sessions SET last_heartbeat=?, ended_at=?, status=?, stop_reason=?
                WHERE id=?
                """,
                (now, now, status, reason, session_id),
            )

    def log_signal(
        self,
        session_id: int,
        mode: str,
        symbol: str,
        action: str,
        reason: str,
        close_price: float,
        payload: dict[str, Any],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO signals(
                    session_id, mode, timestamp, symbol, action, reason, close_price, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    mode,
                    datetime.now(UTC).isoformat(),
                    symbol,
                    action,
                    reason,
                    close_price,
                    json.dumps(payload, separators=(",", ":")),
                ),
            )

    def log_order(
        self,
        session_id: int,
        mode: str,
        symbol: str,
        side: str,
        order_type: str,
        exchange_order_id: str | None,
        status: str,
        quantity: float,
        price: float | None,
        payload: dict[str, Any],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO orders(
                    session_id, mode, timestamp, symbol, side, order_type,
                    exchange_order_id, status, quantity, price, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    mode,
                    datetime.now(UTC).isoformat(),
                    symbol,
                    side,
                    order_type,
                    exchange_order_id,
                    status,
                    quantity,
                    price,
                    json.dumps(payload, separators=(",", ":")),
                ),
            )

    def log_trade(self, session_id: int, mode: str, symbol: str, trade: dict[str, Any]) -> None:
        columns = (
            "entry_time",
            "exit_time",
            "entry_price",
            "exit_price",
            "quantity",
            "gross_pnl",
            "fees",
            "net_pnl",
            "return_pct",
            "entry_reason",
            "exit_reason",
        )
        values = [trade[column] for column in columns]
        with self._connect() as connection:
            connection.execute(
                f"INSERT INTO trades(session_id, mode, symbol, {', '.join(columns)}) "
                f"VALUES (?, ?, ?, {', '.join('?' for _ in columns)})",
                (session_id, mode, symbol, *values),
            )

    def paper_runtime_seconds(self) -> float:
        now = datetime.now(UTC)
        total = 0.0
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT started_at, last_heartbeat, ended_at FROM sessions WHERE mode='paper'"
            ).fetchall()
        for row in rows:
            start = datetime.fromisoformat(row["started_at"])
            endpoint = row["ended_at"] or row["last_heartbeat"]
            end = min(datetime.fromisoformat(endpoint), now)
            total += max(0.0, (end - start).total_seconds())
        return total

    def trade_rows(self, mode: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM trades WHERE mode=? ORDER BY exit_time", (mode,)
            ).fetchall()
        return [dict(row) for row in rows]

    def log_equity(
        self,
        session_id: int,
        mode: str,
        equity: float,
        available_quote: float,
        locked_quote: float,
        position_value: float,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO equity_snapshots(
                    session_id, mode, timestamp, equity, available_quote,
                    locked_quote, position_value
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    mode,
                    datetime.now(UTC).isoformat(),
                    equity,
                    available_quote,
                    locked_quote,
                    position_value,
                ),
            )

    def equity_rows(self, mode: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM equity_snapshots WHERE mode=? ORDER BY timestamp, id", (mode,)
            ).fetchall()
        return [dict(row) for row in rows]

    def get_or_reset_risk_state(self, mode: str, managed_equity: float) -> dict[str, Any]:
        today = datetime.now(UTC).date().isoformat()
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM risk_state WHERE mode=?", (mode,)).fetchone()
            if row is None or row["trading_day"] != today:
                peak = max(managed_equity, float(row["peak_equity"])) if row else managed_equity
                connection.execute(
                    """
                    INSERT INTO risk_state VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(mode) DO UPDATE SET trading_day=excluded.trading_day,
                        day_start_equity=excluded.day_start_equity,
                        peak_equity=excluded.peak_equity,
                        managed_equity=excluded.managed_equity, updated_at=excluded.updated_at
                    """,
                    (mode, today, managed_equity, peak, managed_equity, now),
                )
                return {
                    "mode": mode,
                    "trading_day": today,
                    "day_start_equity": managed_equity,
                    "peak_equity": peak,
                    "managed_equity": managed_equity,
                }
            state = dict(row)
            state["peak_equity"] = max(float(state["peak_equity"]), managed_equity)
            state["managed_equity"] = managed_equity
            connection.execute(
                "UPDATE risk_state SET peak_equity=?, managed_equity=?, updated_at=? WHERE mode=?",
                (state["peak_equity"], managed_equity, now, mode),
            )
            return state

    def save_position(self, mode: str, symbol: str, payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO positions VALUES (?, ?, ?, ?)
                ON CONFLICT(mode) DO UPDATE SET symbol=excluded.symbol,
                    payload=excluded.payload, updated_at=excluded.updated_at
                """,
                (
                    mode,
                    symbol,
                    json.dumps(payload, separators=(",", ":")),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def load_position(self, mode: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM positions WHERE mode=?", (mode,)
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def clear_position(self, mode: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM positions WHERE mode=?", (mode,))
