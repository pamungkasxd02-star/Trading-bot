#!/usr/bin/env python3
"""Bounded robustness sweep for research only; never changes config automatically."""

from __future__ import annotations

import argparse
import itertools
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

from spotlab.backtest import Backtester
from spotlab.config import StrategyConfig, load_config
from spotlab.models import SymbolRules
from spotlab.strategies.rule_based import RuleBasedStrategy


def _rules() -> SymbolRules:
    return SymbolRules(
        "BTCUSDT",
        Decimal("0.00001000"),
        Decimal("9000"),
        Decimal("0.00001000"),
        Decimal("0.01"),
        Decimal("5"),
        Decimal("9000000"),
    )


def _load(path: str, months: int) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["open_time"] = pd.to_datetime(frame.pop("timestamp"), utc=True)
    frame["close_time"] = frame["open_time"] + timedelta(hours=4) - timedelta(milliseconds=1)
    cutoff = frame["open_time"].max() - pd.DateOffset(months=months)
    return frame[frame["open_time"] >= cutoff].reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--output", default="reports/sweep.csv")
    parser.add_argument("--months", type=int, default=24)
    parser.add_argument("--shortlist", type=int, default=60)
    args = parser.parse_args()
    app = load_config("config/default.yaml")
    candles = _load(args.csv, args.months)
    parameter_sets = itertools.product(
        (16, 20, 24),
        (44, 50, 56),
        (80, 100),
        (44.0, 48.0),
        (70.0, 74.0),
        (2, 3),
        ((2.5, 5.0), (3.0, 6.0), (3.5, 7.0)),
    )
    full_rows: list[dict[str, float | int]] = []
    for ema_fast, ema_slow, sma_trend, rsi_min, rsi_max, confirmations, exits in parameter_sets:
        strategy_config = StrategyConfig(
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            sma_trend=sma_trend,
            rsi_min=rsi_min,
            rsi_max=rsi_max,
            min_confirmations=confirmations,
        )
        risk = app.risk.model_copy(update={"stop_loss_pct": exits[0], "take_profit_pct": exits[1]})
        metric = (
            Backtester(RuleBasedStrategy(strategy_config), app.backtest, risk, _rules())
            .run(candles)
            .metrics
        )
        full_rows.append(
            {
                "ema_fast": ema_fast,
                "ema_slow": ema_slow,
                "sma_trend": sma_trend,
                "rsi_min": rsi_min,
                "rsi_max": rsi_max,
                "min_confirmations": confirmations,
                "stop_loss_pct": exits[0],
                "take_profit_pct": exits[1],
                "net_return_pct": metric.net_return_pct,
                "profit_factor": metric.profit_factor,
                "max_drawdown_pct": metric.max_drawdown_pct,
                "trade_count": metric.trade_count,
                "expectancy": metric.expectancy_per_trade,
            }
        )
    full = pd.DataFrame(full_rows)
    eligible = full[
        (full["net_return_pct"] > 0)
        & (full["profit_factor"] >= 1.05)
        & (full["max_drawdown_pct"] <= 10)
        & (full["trade_count"] >= 20)
    ].nlargest(args.shortlist, ["net_return_pct", "profit_factor"])

    evaluated: list[dict[str, float | int]] = []
    for candidate in eligible.to_dict("records"):
        strategy_config = StrategyConfig(
            ema_fast=int(candidate["ema_fast"]),
            ema_slow=int(candidate["ema_slow"]),
            sma_trend=int(candidate["sma_trend"]),
            rsi_min=float(candidate["rsi_min"]),
            rsi_max=float(candidate["rsi_max"]),
            min_confirmations=int(candidate["min_confirmations"]),
        )
        risk = app.risk.model_copy(
            update={
                "stop_loss_pct": candidate["stop_loss_pct"],
                "take_profit_pct": candidate["take_profit_pct"],
            }
        )
        window_returns: list[float] = []
        cursor = candles["open_time"].min()
        end = candles["open_time"].max()
        while cursor < end:
            boundary = min(cursor + pd.DateOffset(months=3), end + pd.Timedelta(1, unit="ns"))
            window = candles[(candles["open_time"] >= cursor) & (candles["open_time"] < boundary)]
            result = Backtester(
                RuleBasedStrategy(strategy_config), app.backtest, risk, _rules()
            ).run(window)
            window_returns.append(result.metrics.net_return_pct)
            cursor = boundary
        evaluated.append(
            {
                **candidate,
                "positive_windows": sum(value > 0 for value in window_returns),
                "window_count": len(window_returns),
                "worst_window_return_pct": min(window_returns),
                "median_window_return_pct": float(pd.Series(window_returns).median()),
            }
        )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result = pd.DataFrame(evaluated).sort_values(
        ["positive_windows", "worst_window_return_pct", "net_return_pct"], ascending=False
    )
    result.to_csv(output, index=False)
    print(result.head(15).to_string(index=False))
    print("WARNING: seluruh sampel dipakai untuk shortlist; hasil mengandung selection bias.")


if __name__ == "__main__":
    main()
