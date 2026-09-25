"""Disk-backed monthly research jobs. Linux/macOS runner, no trading credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import pandas as pd

from spotlab.data import MarketDataStore
from spotlab.exchange import BinanceRESTClient
from spotlab.quality import interval_milliseconds
from spotlab.research.dataset import audit, collect

INTERVALS = ("1m", "5m", "15m", "1h", "4h", "1d")


class CallBudgetExceeded(RuntimeError):
    pass


class BudgetClient(BinanceRESTClient):
    def __init__(self, limit):
        super().__init__(testnet=False, timeout=12)
        self.remaining = limit

    def _request(self, *args, **kwargs):
        if self.remaining <= 0:
            raise CallBudgetExceeded("Budget habis")
        self.remaining -= 1
        return super()._request(*args, **kwargs)


def connection(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / "queue.db")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, symbol TEXT, interval TEXT, start TEXT, end TEXT,
        expected INTEGER, state TEXT DEFAULT 'pending', rows INTEGER DEFAULT 0,
        error TEXT DEFAULT '', updated TEXT DEFAULT '')""")
    return conn


@contextmanager
def runner_lock(root):
    # OS releases flock even on a process crash. Never steal an active runner's jobs.
    import fcntl

    with (Path(root) / "runner.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Runner batch lain masih aktif") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def plan(conn, symbols, intervals, start, end):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    for value in (start, end):
        if value.tzinfo is None:
            raise ValueError("Tanggal wajib UTC")
        if value.day != 1 or value != value.normalize():
            raise ValueError("Gunakan batas awal bulan UTC untuk shard bulanan")
    if not start < end <= pd.Timestamp.now(tz="UTC"):
        raise ValueError("Rentang harus historis")
    symbols, intervals = sorted(set(symbols)), sorted(set(intervals))
    if not symbols or any(not s.isalnum() or not s.endswith("USDT") for s in symbols):
        raise ValueError("Pair harus ticker USDT alfanumerik")
    if not intervals or any(i not in INTERVALS for i in intervals):
        raise ValueError("Interval tidak didukung")
    bounds = pd.date_range(start, end, freq="MS")
    added = 0
    with conn:
        for symbol in symbols:
            for interval in intervals:
                for left, right in pairwise(bounds):
                    key = f"{symbol}:{interval}:{left.isoformat()}:{right.isoformat()}"
                    uid = hashlib.sha256(key.encode()).hexdigest()[:24]
                    expected = int(
                        (right - left).total_seconds() * 1000 / interval_milliseconds(interval)
                    )
                    cursor = conn.execute(
                        "INSERT OR IGNORE INTO jobs(id,symbol,interval,start,end,expected) "
                        "VALUES(?,?,?,?,?,?)",
                        (uid, symbol, interval, left.isoformat(), right.isoformat(), expected),
                    )
                    added += cursor.rowcount
    return added


def summary(conn):
    rows = conn.execute(
        "SELECT state,count(*) jobs,sum(rows) rows FROM jobs GROUP BY state"
    ).fetchall()
    estimate = conn.execute("SELECT expected FROM jobs").fetchall()
    return dict(
        jobs=sum(r["jobs"] for r in rows),
        by_state=[dict(r) for r in rows],
        planned_candles=sum(r[0] for r in estimate),
        minimum_initial_calls=sum(1 + math.ceil(r[0] / 1000) for r in estimate),
        note="Rencana bukan data terunduh; complete memerlukan audit setiap shard. "
        "Estimasi belum termasuk retries/gap repair. Bukan training ML atau izin live.",
    )


def run(root, conn, limit, client):
    if limit < 1:
        raise ValueError("jobs harus positif")
    with runner_lock(root):
        with conn:
            conn.execute("UPDATE jobs SET state='pending' WHERE state='running'")
        jobs = conn.execute(
            "SELECT * FROM jobs WHERE state='pending' ORDER BY start,symbol,interval LIMIT ?",
            (limit,),
        ).fetchall()
        for job in jobs:
            if client.remaining <= 0:
                break
            with conn:
                conn.execute("UPDATE jobs SET state='running' WHERE id=?", (job["id"],))
            shard = Path(root) / "parts" / job["id"]
            result = collect(
                client,
                MarketDataStore(shard.with_suffix(".db")),
                [job["symbol"]],
                datetime.fromisoformat(job["start"]),
                datetime.fromisoformat(job["end"]),
                job["interval"],
                shard.with_suffix(".json"),
            )["symbols"][job["symbol"]]
            error = result.get("error_type", "")
            state = (
                "complete"
                if result.get("complete")
                else "pending"
                if error == "CallBudgetExceeded"
                else "incomplete"
            )
            with conn:
                conn.execute(
                    "UPDATE jobs SET state=?,rows=?,error=?,updated=? WHERE id=?",
                    (state, result.get("rows", 0), error, datetime.now(UTC).isoformat(), job["id"]),
                )
            if error == "CallBudgetExceeded":
                break
    return summary(conn)


def assemble(root, conn, interval, destination, symbols=None):
    """Export only a fully audited interval to a NEW research DB, never execution."""
    destination = Path(destination)
    if destination.exists():
        raise ValueError("Tujuan sudah ada; gunakan file database baru")
    with runner_lock(root):
        jobs = conn.execute(
            "SELECT * FROM jobs WHERE interval=? ORDER BY symbol,start", (interval,)
        ).fetchall()
        if symbols:
            chosen = set(symbols)
            jobs = [j for j in jobs if j["symbol"] in chosen]
            if {j["symbol"] for j in jobs} != chosen:
                raise ValueError("Symbol tidak ditemukan dalam rencana interval ini")
        if not jobs or any(j["state"] != "complete" for j in jobs):
            raise ValueError("Semua job interval ini harus complete sebelum assemble")
        temporary = destination.with_suffix(destination.suffix + ".building")
        if temporary.exists():
            raise ValueError("File building lama ada; periksa sebelum mencoba lagi")
        target = MarketDataStore(temporary)
        ranges = {}
        try:
            for job in jobs:
                source = MarketDataStore(Path(root) / "parts" / (job["id"] + ".db"))
                meta = source.metadata("market")
                if (
                    not meta.get("exchange_verified")
                    or meta.get("source") != "https://api.binance.com/api"
                ):
                    raise ValueError("Provenance shard tidak valid")
                left, right = (
                    datetime.fromisoformat(job["start"]),
                    datetime.fromisoformat(job["end"]),
                )
                frame = source.load_candles(job["symbol"], interval, left, right)
                frame = frame[frame.open_time < pd.Timestamp(right)]
                if not audit(frame, left, right, interval)["complete"]:
                    raise ValueError("Audit ulang shard gagal")
                raw = [
                    [
                        int(r.open_time.timestamp() * 1000),
                        r.open,
                        r.high,
                        r.low,
                        r.close,
                        r.volume,
                        int(r.close_time.timestamp() * 1000),
                        r.quote_volume,
                        r.trades,
                    ]
                    for r in frame.itertuples()
                ]
                target.upsert_klines(job["symbol"], interval, raw)
                target.save_symbol_rules(source.load_symbol_rules(job["symbol"]))
                old = ranges.get(job["symbol"], (left, right))
                ranges[job["symbol"]] = (min(old[0], left), max(old[1], right))
            for symbol, (left, right) in ranges.items():
                if not audit(target.load_candles(symbol, interval), left, right, interval)[
                    "complete"
                ]:
                    raise ValueError("Ada gap antarbulan")
            target.set_metadata(
                "market",
                dict(
                    source="https://api.binance.com/api",
                    environment="production",
                    exchange_verified=True,
                    symbols=sorted(ranges),
                    assembled_at=datetime.now(UTC).isoformat(),
                    historical_filter_snapshot=False,
                ),
            )
            target.set_metadata("universe", {"symbols": sorted(ranges)})
            temporary.replace(destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    return str(destination)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default="data/research-batch")
    sub = p.add_subparsers(dest="command", required=True)
    build = sub.add_parser("plan")
    source = build.add_mutually_exclusive_group(required=True)
    source.add_argument("--symbols", nargs="+")
    source.add_argument("--all-usdt", action="store_true")
    build.add_argument("--intervals", nargs="+", choices=INTERVALS, default=["15m", "1h", "4h"])
    build.add_argument("--start", required=True)
    build.add_argument("--end", required=True)
    execute = sub.add_parser("run")
    execute.add_argument("--jobs", type=int, default=5)
    execute.add_argument("--max-calls", type=int, default=30)
    export = sub.add_parser("assemble")
    export.add_argument("--interval", choices=INTERVALS, required=True)
    export.add_argument("--database", required=True)
    export.add_argument("--symbols", nargs="+")
    sub.add_parser("status")
    sub.add_parser("retry-incomplete")
    args = p.parse_args()
    conn = connection(args.root)
    if args.command == "plan":
        if args.all_usdt:
            info = BinanceRESTClient().exchange_info()
            symbols = [
                r["symbol"]
                for r in info["symbols"]
                if r.get("quoteAsset") == "USDT"
                and r.get("isSpotTradingAllowed")
                and r.get("status") == "TRADING"
            ]
        else:
            symbols = [s.upper() for s in args.symbols]
        plan(
            conn,
            symbols,
            args.intervals,
            pd.Timestamp(args.start, tz="UTC"),
            pd.Timestamp(args.end, tz="UTC"),
        )
    elif args.command == "run":
        if args.max_calls < 1 or args.jobs < 1:
            p.error("jobs dan max-calls harus positif")
        run(args.root, conn, args.jobs, BudgetClient(args.max_calls))
    elif args.command == "assemble":
        print(
            assemble(
                args.root,
                conn,
                args.interval,
                args.database,
                [s.upper() for s in args.symbols] if args.symbols else None,
            )
        )
    elif args.command == "retry-incomplete":
        with runner_lock(args.root), conn:
            conn.execute("UPDATE jobs SET state='pending' WHERE state='incomplete'")
    print(json.dumps(summary(conn), indent=2))
    conn.close()


if __name__ == "__main__":
    main()
