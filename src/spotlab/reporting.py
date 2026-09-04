from __future__ import annotations

import json
from pathlib import Path

import matplotlib
import pandas as pd

from spotlab.backtest import BacktestResult, metric_dict

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def write_backtest_report(result: BacktestResult, output: str | Path) -> Path:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    metrics = metric_dict(result.metrics)
    (destination / "summary.json").write_text(
        json.dumps(metrics, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    pd.DataFrame([metrics]).to_csv(destination / "summary.csv", index=False)
    result.trades.to_csv(destination / "trades.csv", index=False)
    result.equity.to_csv(destination / "equity.csv", index=False)
    plot_equity(result.equity, destination / "equity_curve.png")
    return destination


def plot_equity(equity: pd.DataFrame, output: str | Path) -> None:
    figure, axis = plt.subplots(figsize=(10, 4.8))
    if not equity.empty:
        axis.plot(pd.to_datetime(equity["time"]), equity["equity"], color="#16a34a", lw=1.7)
    axis.set_title("Binance Spot Lab — Equity Curve")
    axis.set_xlabel("Time (UTC)")
    axis.set_ylabel("Equity (USDT)")
    axis.grid(alpha=0.25)
    figure.tight_layout()
    figure.savefig(output, dpi=160)
    plt.close(figure)


def terminal_summary(result: BacktestResult) -> str:
    metric = result.metrics
    profit_factor = "∞" if metric.profit_factor == float("inf") else f"{metric.profit_factor:.3f}"
    return "\n".join(
        (
            "=== BACKTEST SUMMARY ===",
            f"Initial / final : {metric.initial_cash:.4f} / {metric.final_equity:.4f} USDT",
            f"Net return      : {metric.net_return_pct:.3f}%",
            f"Trades          : {metric.trade_count}",
            f"Win rate        : {metric.win_rate_pct:.2f}%",
            f"Profit factor   : {profit_factor}",
            f"Max drawdown    : {metric.max_drawdown_pct:.3f}%",
            f"Average W / L   : {metric.average_win:.6f} / {metric.average_loss:.6f} USDT",
            f"Expectancy      : {metric.expectancy_per_trade:.6f} USDT/trade",
            f"Fees            : {metric.total_fees:.6f} USDT",
            f"Min-notional skip: {metric.min_notional_skips}",
        )
    )
