#!/usr/bin/env python3
"""Reproduce an explicitly UNVERIFIED snapshot experiment. Never unlocks paper/live."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

from spotlab.backtest import metric_dict
from spotlab.config import AppConfig, load_config
from spotlab.models import SymbolRules
from spotlab.portfolio import PortfolioBacktester
from spotlab.research.walkforward import candidates, run_walkforward
from spotlab.strategies import build_strategy


def download_snapshot(destination: Path) -> None:
    manifest = json.loads(Path("reports/evaluation-v0_4/source_blobs.json").read_text())
    destination.mkdir(parents=True, exist_ok=True)
    for item in manifest["files"]:
        path = destination / item["file"]
        if path.exists():
            continue
        url = f"https://api.github.com/repos/{manifest['repository']}/git/blobs/{item['blob_sha']}"
        headers = {"User-Agent": "spotlab-research"}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with urlopen(Request(url, headers=headers), timeout=30) as response:
            payload = json.load(response)
        raw = base64.b64decode(payload["content"])
        digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if digest != item["blob_sha"]:
            raise ValueError(f"SHA Git tidak cocok: {item['file']}")
        path.write_bytes(raw.replace(b"\r\n", b"\n"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", default="data/snapshots")
    parser.add_argument("--output", default="reports/evaluation-v0_4")
    parser.add_argument("--config", default="config/multicoin.yaml")
    parser.add_argument("--initial-cash", type=float)
    parser.add_argument("--download-snapshot", action="store_true")
    parser.add_argument("--capital-sensitivity", action="store_true")
    args = parser.parse_args()
    cfg = load_config(args.config)
    if args.download_snapshot:
        download_snapshot(Path(args.snapshot_dir))
    if args.initial_cash is not None:
        if args.initial_cash <= 0:
            parser.error("initial-cash harus positif")
        cfg = cfg.model_copy(
            update={"backtest": cfg.backtest.model_copy(update={"initial_cash": args.initial_cash})}
        )
        cfg = AppConfig.model_validate(cfg.model_dump())
    # Illustrative order constraints, explicitly not claimed to be exchange snapshots.
    steps = {
        "BTCUSDT": "0.00001",
        "ETHUSDT": "0.0001",
        "BNBUSDT": "0.001",
        "SOLUSDT": "0.001",
        "XRPUSDT": "0.1",
        "ADAUSDT": "0.1",
        "AVAXUSDT": "0.01",
        "LINKUSDT": "0.01",
    }
    ticks = {
        "BTCUSDT": "0.01",
        "ETHUSDT": "0.01",
        "BNBUSDT": "0.01",
        "SOLUSDT": "0.01",
        "XRPUSDT": "0.0001",
        "ADAUSDT": "0.0001",
        "AVAXUSDT": "0.01",
        "LINKUSDT": "0.001",
    }
    datasets, rules, sources = {}, {}, []
    for symbol in cfg.universe.symbols:
        path = Path(args.snapshot_dir) / f"{symbol}_4h.csv"
        frame = pd.read_csv(path)
        frame["open_time"] = pd.to_datetime(frame.pop("timestamp"), utc=True)
        frame["close_time"] = frame["open_time"] + timedelta(hours=4, milliseconds=-1)
        cutoff = frame.open_time.max() - pd.DateOffset(months=cfg.data.history_months)
        datasets[symbol] = frame[frame.open_time >= cutoff].reset_index(drop=True)
        rules[symbol] = SymbolRules(
            symbol,
            Decimal(steps[symbol]),
            Decimal("100000000"),
            Decimal(steps[symbol]),
            Decimal(ticks[symbol]),
            Decimal("5"),
        )
        sources.append(
            {
                "symbol": symbol,
                "file": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "rows_used": len(datasets[symbol]),
                "assumed_filters": {k: str(v) for k, v in asdict(rules[symbol]).items()},
            }
        )
    manifest = run_walkforward(
        datasets,
        rules,
        cfg,
        args.output,
        provenance={
            "exchange_verified": False,
            "type": "third_party_csv_snapshot",
            "repository": "https://github.com/Ilnyr2006-droid/python-paper-trading-agent-1-data",
            "sources": sources,
            "warning": "CSV and historical exchange filters have not been "
            "independently verified against Binance.",
        },
    )
    if args.capital_sensitivity:
        cash_rows = []
        for candidate in candidates(cfg):
            strategy = build_strategy(
                candidate.config.strategy.name, config=candidate.config.strategy
            )
            prepared = {symbol: strategy.prepare(frame) for symbol, frame in datasets.items()}
            for initial_cash in (20, 1000, 10000):
                if initial_cash == cfg.backtest.initial_cash:
                    base = manifest["results"][candidate.name]
                    row = {
                        k: base[k]
                        for k in (
                            "initial_cash",
                            "final_equity",
                            "net_return_pct",
                            "trade_count",
                            "win_rate_pct",
                            "profit_factor",
                            "max_drawdown_pct",
                            "average_win",
                            "average_loss",
                            "expectancy_per_trade",
                            "total_fees",
                            "min_notional_skips",
                        )
                    }
                else:
                    settings = candidate.config.backtest.model_copy(
                        update={"initial_cash": initial_cash}
                    )
                    result = PortfolioBacktester(
                        strategy, settings, candidate.config.risk, rules
                    ).run(
                        prepared,
                        trade_start=pd.Timestamp(manifest["oos_start"]),
                        trade_end=pd.Timestamp(manifest["oos_end_exclusive"]),
                        prepared=True,
                    )
                    row = metric_dict(result.metrics)
                cash_rows.append({"candidate": candidate.name, **row})
        pd.DataFrame(cash_rows).to_csv(Path(args.output) / "capital_sensitivity.csv", index=False)
    print("Selected on initial training:", manifest["selection"])
    for name, result in manifest["results"].items():
        print(
            name,
            {
                k: result[k]
                for k in (
                    "trade_count",
                    "win_rate_pct",
                    "profit_factor",
                    "net_return_pct",
                    "max_drawdown_pct",
                    "status",
                    "failures",
                )
            },
        )


if __name__ == "__main__":
    main()
