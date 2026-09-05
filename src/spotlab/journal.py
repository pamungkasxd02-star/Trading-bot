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
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(sessions)")}
            if "fingerprint" not in columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN fingerprint TEXT NOT NULL DEFAULT ''"
                )
            if "active_seconds" not in columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN active_seconds REAL NOT NULL DEFAULT 0"
                )
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS candle_decisions (
                    mode TEXT NOT NULL, symbol TEXT NOT NULL, interval TEXT NOT NULL,
                    open_time INTEGER NOT NULL,
                    PRIMARY KEY(mode, symbol, interval)
                );
                CREATE TABLE IF NOT EXISTS execution_intents (
                    mode TEXT PRIMARY KEY, payload TEXT NOT NULL
                );
            """)

    def start_session(self, mode: str, stale_seconds: int = 180, fingerprint: str = "") -> int:
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
                INSERT INTO sessions(mode, started_at, last_heartbeat, status, fingerprint)
                VALUES (?, ?, ?, 'running', ?)
                """,
                (mode, now.isoformat(), now.isoformat(), fingerprint),
            )
            return int(cursor.lastrowid)

    def heartbeat(self, session_id: int) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE sessions SET active_seconds=active_seconds + "
                "max(0, min(60, (julianday(?) - julianday(last_heartbeat)) * 86400)), "
                "last_heartbeat=? WHERE id=? AND status='running'",
                (now, now, session_id),
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

    def runtime_health(self, mode: str, stale_seconds: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, status, started_at, last_heartbeat, stop_reason
                FROM sessions WHERE mode=? ORDER BY id DESC LIMIT 1
                """,
                (mode,),
            ).fetchone()
        if row is None:
            return {
                "healthy": False,
                "mode": mode,
                "reason": "session belum pernah dijalankan",
            }
        payload = dict(row)
        heartbeat = datetime.fromisoformat(payload["last_heartbeat"])
        age_seconds = max(0.0, (datetime.now(UTC) - heartbeat).total_seconds())
        healthy = payload["status"] == "running" and age_seconds <= stale_seconds
        payload.update(
            {
                "healthy": healthy,
                "mode": mode,
                "heartbeat_age_seconds": age_seconds,
                "reason": (
                    "ok"
                    if healthy
                    else f"session {payload['status']}; heartbeat {age_seconds:.1f}s lalu"
                ),
            }
        )
        return payload

    def backup(self, destination: str | Path) -> Path:
        output = Path(destination)
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.resolve() == self.database.resolve():
            raise ValueError("Tujuan backup tidak boleh sama dengan database runtime")
        with self._connect() as source, sqlite3.connect(output) as target:
            source.backup(target)
        return output

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

    def paper_runtime_seconds(self, fingerprint: str | None = None) -> float:
        with self._connect() as connection:
            sql = "SELECT active_seconds FROM sessions WHERE mode='paper'"
            rows = connection.execute(
                sql + (" AND fingerprint=?" if fingerprint is not None else ""),
                (fingerprint,) if fingerprint is not None else (),
            ).fetchall()
        return sum(float(row["active_seconds"]) for row in rows)

    def trade_rows(self, mode: str, fingerprint: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT t.* FROM trades t JOIN sessions s ON s.id=t.session_id WHERE t.mode=?"
                + (" AND s.fingerprint=?" if fingerprint is not None else "")
                + " ORDER BY exit_time",
                (mode, fingerprint) if fingerprint is not None else (mode,),
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

    def equity_rows(self, mode: str, fingerprint: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT e.* FROM equity_snapshots e JOIN sessions s ON s.id=e.session_id "
                "WHERE e.mode=?"
                + (" AND s.fingerprint=?" if fingerprint is not None else "")
                + " ORDER BY timestamp, e.id",
                (mode, fingerprint) if fingerprint is not None else (mode,),
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

    def close_recorded_position(
        self, session_id: int, mode: str, symbol: str, trade: dict[str, Any]
    ) -> bool:
        """Trade PnL and position removal commit together, so crash recovery cannot double-count."""
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
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT symbol FROM positions WHERE mode=?", (mode,)
            ).fetchone()
            if row is None or row["symbol"] != symbol:
                return False
            connection.execute(
                f"INSERT INTO trades(session_id, mode, symbol, {', '.join(columns)}) "
                f"VALUES (?, ?, ?, {', '.join('?' for _ in columns)})",
                (session_id, mode, symbol, *(trade[column] for column in columns)),
            )
            connection.execute("DELETE FROM positions WHERE mode=?", (mode,))
            connection.execute("DELETE FROM execution_intents WHERE mode=?", (mode,))
            return True

    def claim_candle(self, mode: str, symbol: str, interval: str, open_time: int) -> bool:
        """Claim before order submission: stale/duplicate signals cannot submit twice."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO candle_decisions VALUES (?, ?, ?, ?)
                ON CONFLICT(mode, symbol, interval) DO UPDATE SET open_time=excluded.open_time
                WHERE excluded.open_time > candle_decisions.open_time
            """,
                (mode, symbol, interval, open_time),
            )
            return cursor.rowcount == 1

    def set_intent(self, mode: str, payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO execution_intents VALUES (?, ?)", (mode, json.dumps(payload))
            )

    def pending_intent(self, mode: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM execution_intents WHERE mode=?", (mode,)
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def clear_intent(self, mode: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM execution_intents WHERE mode=?", (mode,))
