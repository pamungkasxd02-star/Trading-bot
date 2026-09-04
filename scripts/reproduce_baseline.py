#!/usr/bin/env python3
"""Reproduce the baseline from a timestamp/open/high/low/close/volume CSV."""

from __future__ import annotations

import argparse
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

from spotlab.backtest import Backtester, metric_dict
from spotlab.config import load_config
from spotlab.models import SymbolRules
from spotlab.strategies import build_strategy
from spotlab.validation import validate_rolling_windows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--output", default="reports/baseline")
    parser.add_argument("--months", type=int, default=24)
    parser.add_argument("--initial-cash", type=float)
    args = parser.parse_args()

    config = load_config("config/default.yaml")
    if args.initial_cash is not None:
        if args.initial_cash <= 0:
            parser.error("--initial-cash harus lebih besar dari nol")
        config = config.model_copy(
            update={
                "backtest": config.backtest.model_copy(update={"initial_cash": args.initial_cash})
            }
        )
    candles = pd.read_csv(args.csv)
    candles["open_time"] = pd.to_datetime(candles.pop("timestamp"), utc=True)
    candles["close_time"] = candles["open_time"] + timedelta(hours=4) - timedelta(milliseconds=1)
    cutoff = candles["open_time"].max() - pd.DateOffset(months=args.months)
    candles = candles[candles["open_time"] >= cutoff].reset_index(drop=True)
    rules = SymbolRules(
        symbol="BTCUSDT",
        min_qty=Decimal("0.00001000"),
        max_qty=Decimal("9000.00000000"),
        step_size=Decimal("0.00001000"),
        tick_size=Decimal("0.01000000"),
        min_notional=Decimal("5.00000000"),
        max_notional=Decimal("9000000.00000000"),
    )
    strategy = build_strategy(config.strategy.name, config=config.strategy)
    result, summary = validate_rolling_windows(
        candles, strategy, config, rules, Path(args.output), window_months=3
    )
    costs: list[dict[str, object]] = []
    for fee_bps, slippage_bps in ((10, 5), (15, 7.5), (20, 10), (30, 15)):
        cost_config = config.backtest.model_copy(
            update={"fee_bps": fee_bps, "slippage_bps": slippage_bps}
        )
        cost_result = Backtester(strategy, cost_config, config.risk, rules).run(candles)
        costs.append(
            {
                "fee_bps_per_side": fee_bps,
                "slippage_bps_per_side": slippage_bps,
                **metric_dict(cost_result.metrics),
            }
        )
    pd.DataFrame(costs).to_csv(Path(args.output) / "cost_sensitivity.csv", index=False)
    print(f"Candles: {len(candles)}")
    print(f"Status: {summary['status']}")
    print(result.metrics)


if __name__ == "__main__":
    main()
