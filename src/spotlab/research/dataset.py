"""Public REST dataset bootstrap, with auditable coverage and restartable cache."""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from spotlab.data import MarketDataStore, fetch_history, parse_symbol_rules
from spotlab.exchange import BinanceRESTClient
from spotlab.quality import interval_milliseconds, validate_candles


def audit(frame, start, end, interval):
    step = interval_milliseconds(interval)
    expected = int((end - start).total_seconds() * 1000 // step)
    if frame.empty:
        return {"rows": 0, "complete": False, "expected_rows": expected}
    frame = validate_candles(frame)
    # Compare timestamps directly: pandas may retain microsecond resolution.
    gaps = int(frame.open_time.diff().dropna().ne(pd.Timedelta(step, unit="ms")).sum())
    durations_ok = frame.close_time.sub(frame.open_time).eq(pd.Timedelta(step - 1, unit="ms")).all()
    complete = (
        durations_ok
        and len(frame) == expected
        and not gaps
        and frame.open_time.iloc[0] == pd.Timestamp(start)
        and frame.open_time.iloc[-1] + pd.Timedelta(step, unit="ms") == pd.Timestamp(end)
    )
    return dict(
        rows=len(frame),
        expected_rows=expected,
        complete=bool(complete),
        gaps=gaps,
        start=frame.open_time.iloc[0].isoformat(),
        end=frame.close_time.iloc[-1].isoformat(),
        sha256=hashlib.sha256(frame.to_csv(index=False).encode()).hexdigest(),
    )


def collect(client, store, symbols, start, end, interval, output, workers=1):
    if not 1 <= workers <= 4:
        raise ValueError("workers harus 1-4")
    previous = store.metadata("dataset_provenance")
    with store._connect() as connection:
        has_rows = connection.execute("SELECT count(*) FROM candles").fetchone()[0] > 0
    if (store.metadata("market") or has_rows) and not previous:
        raise ValueError("Gunakan database dataset baru, jangan campur sumber sebelumnya.")
    if previous and previous.get("source") != client.base_url:
        raise ValueError("Sumber database berbeda")
    store.set_metadata(
        "dataset_provenance", {"source": client.base_url, "environment": "production"}
    )
    store.set_metadata(
        "market",
        {
            "source": client.base_url,
            "environment": "production",
            "exchange_verified": False,
            "status": "collecting",
        },
    )
    report = dict(
        source=client.base_url,
        requested_start=start.isoformat(),
        requested_end=end.isoformat(),
        interval=interval,
        fetched_at=datetime.now(UTC).isoformat(),
        symbols={},
        execution_connected=False,
        historical_filter_snapshot=False,
        warning="Coverage bukan bukti profit/ML. Universe saat ini memiliki survivorship bias.",
    )

    def fetch_one(symbol):
        print(f"Fetching {symbol} {interval}...", flush=True)
        try:
            info = client.exchange_info(symbol)
            store.save_symbol_rules(parse_symbol_rules(info, symbol))
            frame = store.load_candles(symbol, interval, start, end)
            frame = frame[frame.open_time < pd.Timestamp(end)] if not frame.empty else frame
            before = audit(frame, start, end, interval)
            if not before["complete"]:
                resume = start
                if not frame.empty:
                    next_open = frame.open_time.iloc[-1] + pd.Timedelta(
                        interval_milliseconds(interval), unit="ms"
                    )
                    if audit(frame, start, next_open.to_pydatetime(), interval)["complete"]:
                        resume = next_open.to_pydatetime()
                fetch_history(client, store, symbol, interval, resume, end)
            frame = store.load_candles(symbol, interval, start, end)
            frame = frame[frame.open_time < pd.Timestamp(end)] if not frame.empty else frame
            return audit(frame, start, end, interval)
        except Exception as exc:
            return {"complete": False, "error_type": type(exc).__name__}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(fetch_one, symbol): symbol for symbol in symbols}
        for future in as_completed(jobs):
            symbol = jobs[future]
            report["symbols"][symbol] = future.result()
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            checkpoint = Path(str(output) + ".tmp")
            checkpoint.write_text(json.dumps(report, indent=2) + "\n")
            checkpoint.replace(output)
            print(symbol, report["symbols"][symbol], flush=True)
    complete = [s for s, r in report["symbols"].items() if r.get("complete")]
    store.set_metadata("universe", {"symbols": complete, "asof": report["fetched_at"]})
    store.set_metadata(
        "market",
        {
            "source": client.base_url,
            "environment": "production",
            "exchange_verified": len(complete) == len(symbols),
            "fetched_at": report["fetched_at"],
            "symbols": complete,
        },
    )
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workers", type=int, choices=range(1, 5), default=2)
    p.add_argument("--symbols", nargs="+", required=True)
    p.add_argument("--start", required=True, help="UTC YYYY-MM-DD inclusive")
    p.add_argument("--end", required=True, help="UTC YYYY-MM-DD exclusive")
    p.add_argument("--interval", choices=["1m", "5m", "15m", "1h", "4h", "1d"], default="1h")
    p.add_argument("--database", default="data/official-research.db")
    p.add_argument("--output", default="reports/dataset/coverage.json")
    args = p.parse_args()
    start, end = [datetime.fromisoformat(s).replace(tzinfo=UTC) for s in (args.start, args.end)]
    if not start < end <= datetime.now(UTC):
        p.error("Rentang harus historis dan end setelah start")
    symbols = list(dict.fromkeys(s.upper() for s in args.symbols))
    if any(not s.isalnum() or not s.endswith("USDT") for s in symbols):
        p.error("Gunakan ticker pair USDT alfanumerik")
    report = collect(
        BinanceRESTClient(testnet=False, timeout=12),
        MarketDataStore(args.database),
        symbols,
        start,
        end,
        args.interval,
        args.output,
        workers=args.workers,
    )

    if any(not row.get("complete") for row in report["symbols"].values()):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
