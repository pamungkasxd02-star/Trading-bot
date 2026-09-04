from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from spotlab.backtest import Backtester, BacktestResult, metric_dict
from spotlab.config import AppConfig
from spotlab.models import SymbolRules
from spotlab.reporting import write_backtest_report
from spotlab.strategies.base import Strategy


def validate_rolling_windows(
    candles: pd.DataFrame,
    strategy: Strategy,
    config: AppConfig,
    rules: SymbolRules,
    output: str | Path,
    *,
    window_months: int = 3,
) -> tuple[BacktestResult, dict[str, object]]:
    destination = Path(output)
    result = Backtester(strategy, config.backtest, config.risk, rules).run(candles)
    write_backtest_report(result, destination)

    start = pd.Timestamp(candles["open_time"].min())
    end = pd.Timestamp(candles["open_time"].max())
    cursor = start
    rows: list[dict[str, object]] = []
    while cursor < end:
        window_end = min(cursor + pd.DateOffset(months=window_months), end + pd.Timedelta(1, "ns"))
        subset = candles[
            (pd.to_datetime(candles["open_time"]) >= cursor)
            & (pd.to_datetime(candles["open_time"]) < window_end)
        ]
        if len(subset) >= max(config.strategy.sma_trend + 5, 120):
            window_result = Backtester(strategy, config.backtest, config.risk, rules).run(subset)
            rows.append(
                {
                    "start": cursor.isoformat(),
                    "end": window_end.isoformat(),
                    **metric_dict(window_result.metrics),
                }
            )
        cursor = window_end

    windows = pd.DataFrame(rows)
    positive = int((windows["net_return_pct"] > 0).sum()) if not windows.empty else 0
    ratio = positive / len(windows) if len(windows) else 0.0
    metrics = result.metrics
    passed = (
        metrics.profit_factor >= config.gates.research_min_profit_factor
        and metrics.max_drawdown_pct <= config.gates.research_max_drawdown_pct
        and metrics.expectancy_per_trade > 0
        and ratio >= config.gates.research_min_positive_windows_ratio
    )
    summary: dict[str, object] = {
        **asdict(metrics),
        "positive_windows": positive,
        "window_count": len(windows),
        "positive_windows_ratio": ratio,
        "window_months": window_months,
        "status": "RESEARCH_PASS" if passed else "RESEARCH_FAIL",
        "warning": (
            "Riset historis bukan prediksi profit. Paper gate tetap wajib; "
            "pemilihan parameter menimbulkan selection bias."
        ),
    }
    destination.mkdir(parents=True, exist_ok=True)
    windows.to_csv(destination / "validation_windows.csv", index=False)
    (destination / "validation_summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return result, summary
