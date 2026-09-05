#!/usr/bin/env python3
"""Frozen multi-capital experiment or short historical demo; never submits orders."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
from reproduce_multicoin import download_snapshot

from spotlab.config import AppConfig, load_config
from spotlab.models import SymbolRules
from spotlab.portfolio import PortfolioBacktester
from spotlab.reporting import terminal_summary, write_backtest_report
from spotlab.research.walkforward import candidates, run_walkforward
from spotlab.strategies import build_strategy


def snapshot_dataset(cfg: AppConfig, directory: Path):
    if cfg.exchange.interval != "4h":
        raise ValueError("Snapshot hanya mendukung interval 4h")
    reference = json.loads(Path("reports/evaluation-v0_4/manifest.json").read_text())
    sources = {item["symbol"]: item for item in reference["source"]["sources"]}
    datasets, rules, provenance = {}, {}, []
    for symbol in cfg.universe.symbols:
        source = sources[symbol]
        path = directory / source["file"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != source["sha256"]:
            raise ValueError(f"Hash snapshot berbeda: {path}; jangan mencampur dataset")
        frame = pd.read_csv(path)
        frame["open_time"] = pd.to_datetime(frame.pop("timestamp"), utc=True)
        frame["close_time"] = frame["open_time"] + timedelta(hours=4, milliseconds=-1)
        cutoff = frame.open_time.max() - pd.DateOffset(months=cfg.data.history_months)
        datasets[symbol] = frame[frame.open_time >= cutoff].reset_index(drop=True)
        fields = {
            key: None if value == "None" else Decimal(value)
            for key, value in source["assumed_filters"].items()
            if key != "symbol"
        }
        rules[symbol] = SymbolRules(symbol=symbol, **fields)
        provenance.append({**source, "rows_used": len(datasets[symbol])})
    return (
        datasets,
        rules,
        {
            "exchange_verified": False,
            "evaluation_period_previously_inspected": True,
            "type": "third_party_csv_snapshot",
            "repository": reference["source"]["repository"],
            "sources": provenance,
            "warning": "Exploratory reuse of earlier history; "
            "neither fresh holdout nor Binance-verified filters.",
        },
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/regime.yaml")
    parser.add_argument("--snapshot-dir", default="data/snapshots")
    parser.add_argument("--output", default="reports/evaluation-v0_5")
    parser.add_argument("--download-snapshot", action="store_true")
    parser.add_argument("--demo", action="store_true", help="Replay 6 bulan; bukan paper/Testnet")
    parser.add_argument("--initial-cash", type=float)
    args = parser.parse_args()
    cfg = load_config(args.config)
    if args.initial_cash is not None:
        values = cfg.model_dump()
        values["backtest"]["initial_cash"] = args.initial_cash
        cfg = AppConfig.model_validate(values)
    if args.download_snapshot:
        download_snapshot(Path(args.snapshot_dir))
    datasets, rules, source = snapshot_dataset(cfg, Path(args.snapshot_dir))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if args.demo:
        strategy = build_strategy(cfg.strategy.name, config=cfg.strategy)
        start = min(f.open_time.max() for f in datasets.values()) - pd.DateOffset(months=6)
        result = PortfolioBacktester(strategy, cfg.backtest, cfg.risk, rules).run(
            datasets, trade_start=start
        )
        write_backtest_report(result, output)
        (output / "source.json").write_text(json.dumps(source, indent=2) + "\n")
        print("HISTORICAL REPLAY DEMO — snapshot, no exchange keys, no Testnet/live orders")
        print(terminal_summary(result))
    else:
        # Record the candidate family and protocol before evaluating its returns.
        protocol = {
            "selection": "training_only; all configured capitals must qualify",
            "config": cfg.model_dump(mode="json", exclude={"data", "runtime"}),
            "candidates": [
                {
                    "name": c.name,
                    "strategy": c.config.strategy.model_dump(),
                    "risk": c.config.risk.model_dump(),
                }
                for c in candidates(cfg)
            ],
            "source": source,
        }
        protocol["config"]["research"].pop("report_directory")
        (output / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
        manifest = run_walkforward(datasets, rules, cfg, output, provenance=source)
        print("Training selection:", manifest["selection"])
        for name, row in manifest["results"].items():
            print(
                f"{name}: WR {row['win_rate_pct']:.2f}% | PF {row['profit_factor']} | "
                f"return {row['net_return_pct']:.2f}% | {row['status']}"
            )
        print("All balances:")
        print(
            pd.read_csv(output / "capital_sensitivity.csv")[
                [
                    "candidate",
                    "initial_cash",
                    "trade_count",
                    "win_rate_pct",
                    "profit_factor",
                    "net_return_pct",
                ]
            ].to_string(index=False)
        )
    print(f"Reports: {output}")


if __name__ == "__main__":
    main()
