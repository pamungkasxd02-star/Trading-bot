from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from spotlab.exchange import BinanceRESTClient
from spotlab.models import SymbolRules


class MarketDataStore:
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
                CREATE TABLE IF NOT EXISTS candles (
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    open_time INTEGER NOT NULL,
                    close_time INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    quote_volume REAL NOT NULL,
                    trades INTEGER NOT NULL,
                    PRIMARY KEY (symbol, interval, open_time)
                );
                CREATE INDEX IF NOT EXISTS ix_candles_lookup
                    ON candles(symbol, interval, open_time);
                CREATE TABLE IF NOT EXISTS symbol_rules (
                    symbol TEXT PRIMARY KEY,
                    min_qty TEXT NOT NULL,
                    max_qty TEXT NOT NULL,
                    step_size TEXT NOT NULL,
                    tick_size TEXT NOT NULL,
                    min_notional TEXT NOT NULL,
                    max_notional TEXT,
                    fetched_at TEXT NOT NULL
                );
                """
            )

    def upsert_klines(self, symbol: str, interval: str, klines: list[list[Any]]) -> int:
        rows = [
            (
                symbol.upper(),
                interval,
                int(item[0]),
                int(item[6]),
                float(item[1]),
                float(item[2]),
                float(item[3]),
                float(item[4]),
                float(item[5]),
                float(item[7]),
                int(item[8]),
            )
            for item in klines
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO candles (
                    symbol, interval, open_time, close_time, open, high, low,
                    close, volume, quote_volume, trades
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, interval, open_time) DO UPDATE SET
                    close_time=excluded.close_time, open=excluded.open,
                    high=excluded.high, low=excluded.low, close=excluded.close,
                    volume=excluded.volume, quote_volume=excluded.quote_volume,
                    trades=excluded.trades
                """,
                rows,
            )
        return len(rows)

    def upsert_closed_candle(self, symbol: str, interval: str, candle: dict[str, Any]) -> None:
        synthetic = [
            candle["open_time"],
            candle["open"],
            candle["high"],
            candle["low"],
            candle["close"],
            candle["volume"],
            candle["close_time"],
            candle.get("quote_volume", 0),
            candle.get("trades", 0),
        ]
        self.upsert_klines(symbol, interval, [synthetic])

    def load_candles(
        self,
        symbol: str,
        interval: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        clauses = ["symbol = ?", "interval = ?"]
        params: list[Any] = [symbol.upper(), interval]
        if start:
            clauses.append("open_time >= ?")
            params.append(int(start.timestamp() * 1000))
        if end:
            clauses.append("open_time <= ?")
            params.append(int(end.timestamp() * 1000))
        query = f"SELECT * FROM candles WHERE {' AND '.join(clauses)} ORDER BY open_time"
        with self._connect() as connection:
            frame = pd.read_sql_query(query, connection, params=params)
        if not frame.empty:
            frame["open_time"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
            frame["close_time"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True)
        return frame

    def save_symbol_rules(self, rules: SymbolRules) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO symbol_rules VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    min_qty=excluded.min_qty, max_qty=excluded.max_qty,
                    step_size=excluded.step_size, tick_size=excluded.tick_size,
                    min_notional=excluded.min_notional,
                    max_notional=excluded.max_notional, fetched_at=excluded.fetched_at
                """,
                (
                    rules.symbol,
                    str(rules.min_qty),
                    str(rules.max_qty),
                    str(rules.step_size),
                    str(rules.tick_size),
                    str(rules.min_notional),
                    str(rules.max_notional) if rules.max_notional is not None else None,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def load_symbol_rules(self, symbol: str) -> SymbolRules:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM symbol_rules WHERE symbol = ?", (symbol.upper(),)
            ).fetchone()
        if row is None:
            raise RuntimeError(
                f"Aturan exchange untuk {symbol} belum di-cache; jalankan `spotlab fetch` dahulu"
            )
        return SymbolRules(
            symbol=row["symbol"],
            min_qty=Decimal(row["min_qty"]),
            max_qty=Decimal(row["max_qty"]),
            step_size=Decimal(row["step_size"]),
            tick_size=Decimal(row["tick_size"]),
            min_notional=Decimal(row["min_notional"]),
            max_notional=Decimal(row["max_notional"]) if row["max_notional"] else None,
        )


def parse_symbol_rules(info: dict[str, Any], symbol: str) -> SymbolRules:
    symbols = info.get("symbols", [])
    if not symbols:
        raise RuntimeError(f"Symbol {symbol} tidak ditemukan di exchangeInfo")
    filters = {item["filterType"]: item for item in symbols[0]["filters"]}
    lot = filters["LOT_SIZE"]
    price = filters["PRICE_FILTER"]
    notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL")
    if notional is None:
        raise RuntimeError("Exchange tidak mengembalikan filter NOTIONAL/MIN_NOTIONAL")
    raw_max_notional = Decimal(str(notional.get("maxNotional", "0")))
    return SymbolRules(
        symbol=symbol.upper(),
        min_qty=Decimal(lot["minQty"]),
        max_qty=Decimal(lot["maxQty"]),
        step_size=Decimal(lot["stepSize"]),
        tick_size=Decimal(price["tickSize"]),
        min_notional=Decimal(notional["minNotional"]),
        max_notional=raw_max_notional if raw_max_notional > 0 else None,
    )


def fetch_history(
    client: BinanceRESTClient,
    store: MarketDataStore,
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
) -> int:
    cursor = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    total = 0
    while cursor <= end_ms:
        batch = client.klines(symbol, interval, start_time=cursor, end_time=end_ms, limit=1000)
        if not batch:
            break
        total += store.upsert_klines(symbol, interval, batch)
        next_cursor = int(batch[-1][0]) + 1
        if next_cursor <= cursor:
            raise RuntimeError("Pagination Binance tidak maju")
        cursor = next_cursor
        if len(batch) < 1000:
            break
    rules = parse_symbol_rules(client.exchange_info(symbol), symbol)
    store.save_symbol_rules(rules)
    return total
