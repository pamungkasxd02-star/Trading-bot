from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from spotlab import __version__
from spotlab.backtest import BacktestResult, metric_dict
from spotlab.config import AppConfig
from spotlab.models import SymbolRules
from spotlab.portfolio import PortfolioBacktester
from spotlab.quality import interval_milliseconds, validate_candles
from spotlab.reporting import plot_equity
from spotlab.strategies import build_strategy

LOGGER = logging.getLogger(__name__)


def research_fingerprint(config: AppConfig, symbols: list[str]) -> str:
    # model_copy updates may retain ints in float fields. Normalize before hashing
    # so exporting a candidate to YAML and loading it cannot change its identity.
    config = AppConfig.model_validate(config.model_dump())
    universe = config.universe.model_dump(exclude={"mode", "symbols", "max_symbols"})
    payload = {
        "engine": f"portfolio-v1/{__version__}",
        "strategy": config.strategy.model_dump(),
        "risk": config.risk.model_dump(),
        "interval": config.exchange.interval,
        "universe": universe,
        "symbols": sorted(symbols),
        "costs": config.backtest.model_dump(exclude={"initial_cash"}),
        "validation": config.research.model_dump(mode="json", exclude={"report_directory"}),
        "execution_filters": config.runtime.model_dump(
            include={
                "history_bars",
                "max_signal_age_seconds",
                "signal_batch_seconds",
                "max_signal_price_drift_bps",
            }
        ),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def wilson_interval(wins: int, count: int) -> tuple[float, float]:
    if count == 0:
        return 0, 100
    z, p = 1.959963984540054, wins / count
    denominator = 1 + z * z / count
    middle = (p + z * z / (2 * count)) / denominator
    radius = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    return max(0, middle - radius) * 100, min(1, middle + radius) * 100


@dataclass(frozen=True)
class Candidate:
    name: str
    config: AppConfig


def candidates(config: AppConfig) -> list[Candidate]:
    baseline = config.model_copy(
        update={
            "strategy": config.strategy.model_copy(update={"name": "rule_based_v1"}),
            "risk": config.risk.model_copy(update={"stop_mode": "fixed"}),
        }
    )
    adaptive = config.model_copy(
        update={
            "strategy": config.strategy.model_copy(update={"name": "adaptive_trend_v2"}),
            "risk": config.risk.model_copy(update={"stop_mode": "atr"}),
        }
    )
    selective = adaptive.model_copy(
        update={
            "strategy": adaptive.strategy.model_copy(
                update={
                    "min_adx": 25,
                    "min_relative_volume": 1.0,
                    "pullback_rsi": 45,
                }
            )
        }
    )
    result = [
        Candidate("baseline", baseline),
        Candidate("adaptive", adaptive),
        Candidate("adaptive_selective", selective),
    ]
    if config.research.candidate_set == "regime":
        # Fixed candidate family, not an unbounded search for the best historical WR.
        result = result[:2]
        for name, mode, volume, score in (
            ("reversion_trend", "trend", 0.8, 55),
            ("reversion_range", "range", 0.8, 55),
            ("reversion_hybrid", "hybrid", 0.8, 55),
            ("reversion_selective", "hybrid", 1.0, 70),
        ):
            values = config.model_dump()
            values["strategy"].update(
                name="regime_reversion_v3",
                regime_mode=mode,
                min_relative_volume=volume,
                min_reversion_score=score,
            )
            values["risk"].update(stop_mode="atr", atr_stop_multiplier=1.5, reward_risk_ratio=1.2)
            result.append(Candidate(name, AppConfig.model_validate(values)))
    if config.research.candidate_set == "quality":
        result = [Candidate("baseline", baseline)]
        for name, strength, volume in (
            ("quality_cross", 20, 1.0),
            ("quality_cross_selective", 25, 1.2),
        ):
            values = baseline.model_dump()
            values["strategy"].update(
                name="quality_cross_v1", min_adx=strength, min_relative_volume=volume
            )
            result.append(Candidate(name, AppConfig.model_validate(values)))
    return result


def _train_score(result: BacktestResult, config: AppConfig) -> float | None:
    m = result.metrics
    if (
        m.trade_count < config.research.min_train_trades
        or m.expectancy_per_trade <= 0
        or m.profit_factor < config.gates.research_min_profit_factor
        or m.max_drawdown_pct > config.gates.research_max_drawdown_pct
        or m.win_rate_pct < config.research.target_win_rate_pct
    ):
        return None
    # Win rate alone is deliberately not the objective.
    return min(m.profit_factor, 3) + m.net_return_pct / 100 - m.max_drawdown_pct / 100


def run_walkforward(
    candles: dict[str, pd.DataFrame],
    rules: dict[str, SymbolRules],
    config: AppConfig,
    output: str | Path,
    *,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select on initial training only, freeze parameters, audit unseen chronological windows.

    OOS is one continuous account run: no resets of cash, peak, stops or open position
    at window boundaries. Rolling train diagnostics never feed back into OOS selection.
    """
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    datasets = {s: validate_candles(f) for s, f in candles.items()}
    duration = pd.Timedelta(interval_milliseconds(config.exchange.interval), unit="ms")
    start = max(f["open_time"].min() for f in datasets.values())
    end = min(f["open_time"].max() for f in datasets.values()) + duration
    if (end - start).total_seconds() / 86400 < config.universe.min_history_days:
        raise ValueError("Usia histori bersama belum memenuhi universe.min_history_days")
    # Use a shared complete history so new listings cannot borrow older symbols' data.
    datasets = {
        s: f[(f.open_time >= start) & (f.open_time < end)].reset_index(drop=True)
        for s, f in datasets.items()
    }
    for symbol, frame in datasets.items():
        if not frame["open_time"].diff().dropna().eq(duration).all():
            raise ValueError(f"{symbol}: candle gap; perbaiki dataset sebelum validasi")
    train_end = start + pd.DateOffset(months=config.research.train_months)
    oos_start = train_end + duration  # one-bar embargo after training
    windows = []
    cursor = oos_start
    while cursor + pd.DateOffset(months=config.research.test_months) <= end:
        next_cursor = cursor + pd.DateOffset(months=config.research.test_months)
        windows.append((cursor, next_cursor))
        cursor = next_cursor
    if not windows:
        raise ValueError("Data belum cukup untuk train dan satu window OOS penuh")
    oos_end = windows[-1][1]
    variants = candidates(config)
    prepared = {}
    train_scores, diagnostics = [], []
    capitals = sorted({config.backtest.initial_cash, *config.research.evaluation_capitals})
    for candidate in variants:
        LOGGER.info("Training candidate: %s", candidate.name)
        cfg = candidate.config
        strategy = build_strategy(cfg.strategy.name, config=cfg.strategy)
        frames = {s: strategy.prepare(frame) for s, frame in datasets.items()}
        prepared[candidate.name] = frames
        for capital in capitals:
            settings = cfg.backtest.model_copy(update={"initial_cash": capital})
            engine = PortfolioBacktester(strategy, settings, cfg.risk, rules)
            training = engine.run(frames, trade_start=start, trade_end=train_end, prepared=True)
            train_scores.append(
                {
                    "candidate": candidate.name,
                    "score": _train_score(training, cfg),
                    "train_start": start.isoformat(),
                    "train_end": train_end.isoformat(),
                    **metric_dict(training.metrics),
                }
            )
    eligible = []
    for candidate in variants:
        scores = [row["score"] for row in train_scores if row["candidate"] == candidate.name]
        if all(score is not None for score in scores):
            eligible.append({"candidate": candidate.name, "score": min(scores)})
    selected = (
        sorted(eligible, key=lambda row: (-row["score"], row["candidate"]))[0]["candidate"]
        if eligible
        else None
    )
    comparisons, summaries, capital_results = [], {}, []
    for candidate in variants:
        LOGGER.info("Evaluating frozen candidate across capitals and costs: %s", candidate.name)
        cfg = candidate.config
        strategy = build_strategy(cfg.strategy.name, config=cfg.strategy)
        engine = PortfolioBacktester(strategy, cfg.backtest, cfg.risk, rules)
        result = engine.run(
            prepared[candidate.name], trade_start=oos_start, trade_end=oos_end, prepared=True
        )
        folder = destination / candidate.name
        folder.mkdir(exist_ok=True)
        result.trades.to_csv(folder / "trades.csv", index=False)
        result.equity.to_csv(folder / "equity.csv", index=False)
        plot_equity(result.equity, folder / "equity_curve.svg")
        positive = 0
        for number, (left, right) in enumerate(windows, start=1):
            curve = result.equity
            before = curve[curve.time < left]
            initial = (
                float(before.iloc[-1].equity) if not before.empty else cfg.backtest.initial_cash
            )
            subset = curve[(curve.time >= left) & (curve.time < right)]
            final = float(subset.iloc[-1].equity) if not subset.empty else initial
            positive += final > initial
            diagnostics.append(
                {
                    "candidate": candidate.name,
                    "fold": number,
                    "start": left.isoformat(),
                    "end": right.isoformat(),
                    "initial_equity": initial,
                    "final_equity": final,
                    "return_pct": (final / initial - 1) * 100,
                }
            )
        pnl = result.trades.net_pnl if not result.trades.empty else pd.Series(dtype=float)
        low, high = wilson_interval(int((pnl > 0).sum()), len(pnl))
        cost_rows = []
        for multiplier in (1.5, 2):
            cost_config = cfg.backtest.model_copy(
                update={
                    "fee_bps": cfg.backtest.fee_bps * multiplier,
                    "slippage_bps": cfg.backtest.slippage_bps * multiplier,
                }
            )
            stress = PortfolioBacktester(strategy, cost_config, cfg.risk, rules).run(
                prepared[candidate.name], trade_start=oos_start, trade_end=oos_end, prepared=True
            )
            cost_rows.append({"cost_multiplier": multiplier, **metric_dict(stress.metrics)})
        pd.DataFrame(cost_rows).to_csv(folder / "cost_sensitivity.csv", index=False)
        # Re-run the same frozen signals at each balance. Larger balances can enable
        # orders rejected by minimum notional, changing the shared portfolio path.
        capital_failures = []
        for capital in capitals:
            if capital == cfg.backtest.initial_cash:
                account_result = result
                account_costs = cost_rows
                account_positive_ratio = positive / len(windows)
            else:
                settings = cfg.backtest.model_copy(update={"initial_cash": capital})
                account_result = PortfolioBacktester(strategy, settings, cfg.risk, rules).run(
                    prepared[candidate.name],
                    trade_start=oos_start,
                    trade_end=oos_end,
                    prepared=True,
                )
                account_costs = []
                for multiplier in (1.5, 2):
                    stress_settings = settings.model_copy(
                        update={
                            "fee_bps": settings.fee_bps * multiplier,
                            "slippage_bps": settings.slippage_bps * multiplier,
                        }
                    )
                    stress = PortfolioBacktester(strategy, stress_settings, cfg.risk, rules).run(
                        prepared[candidate.name],
                        trade_start=oos_start,
                        trade_end=oos_end,
                        prepared=True,
                    )
                    account_costs.append(
                        {"cost_multiplier": multiplier, **metric_dict(stress.metrics)}
                    )
                positive_count = 0
                curve = account_result.equity
                for left, right in windows:
                    before = curve[curve.time < left]
                    initial = float(before.iloc[-1].equity) if not before.empty else capital
                    subset = curve[(curve.time >= left) & (curve.time < right)]
                    final = float(subset.iloc[-1].equity) if not subset.empty else initial
                    positive_count += final > initial
                account_positive_ratio = positive_count / len(windows)
                account_folder = folder / f"capital_{capital:g}"
                account_folder.mkdir(exist_ok=True)
                account_result.trades.to_csv(account_folder / "trades.csv", index=False)
                pd.DataFrame(account_costs).to_csv(
                    account_folder / "cost_sensitivity.csv", index=False
                )
            account = account_result.metrics
            account_ok = (
                account.trade_count >= cfg.research.min_oos_trades
                and account.win_rate_pct >= cfg.research.target_win_rate_pct
                and account.profit_factor >= cfg.gates.research_min_profit_factor
                and account.expectancy_per_trade > 0
                and account.max_drawdown_pct <= cfg.gates.research_max_drawdown_pct
                and account_positive_ratio >= cfg.gates.research_min_positive_windows_ratio
                and all(row["expectancy_per_trade"] > 0 for row in account_costs)
            )
            if not account_ok:
                capital_failures.append(f"capital_validation_failed:{capital:g}")
            capital_results.append(
                {
                    "candidate": candidate.name,
                    **metric_dict(account),
                    "positive_windows_ratio": account_positive_ratio,
                    "metrics_passed": account_ok,
                }
            )
        failures = []
        m = result.metrics
        if len(windows) < cfg.research.min_folds:
            failures.append("insufficient_oos_windows")
        if m.trade_count < cfg.research.min_oos_trades:
            failures.append("insufficient_oos_trades")
        if m.win_rate_pct < cfg.research.target_win_rate_pct:
            failures.append("win_rate_below_research_target")
        if m.profit_factor < cfg.gates.research_min_profit_factor or m.expectancy_per_trade <= 0:
            failures.append("unprofitable_after_costs")
        if m.max_drawdown_pct > cfg.gates.research_max_drawdown_pct:
            failures.append("excessive_drawdown")
        if positive / len(windows) < cfg.gates.research_min_positive_windows_ratio:
            failures.append("inconsistent_oos_windows")
        if any(row["expectancy_per_trade"] <= 0 for row in cost_rows):
            failures.append("cost_stress_failed")
        if not provenance or not provenance.get("exchange_verified", False):
            failures.append("source_or_exchange_filters_unverified")
        if candidate.name != selected:
            failures.append("not_selected_on_training")
        failures.extend(capital_failures)
        if provenance and provenance.get("evaluation_period_previously_inspected"):
            failures.append("evaluation_period_previously_inspected")
        summary = {
            **metric_dict(m),
            "candidate": candidate.name,
            "fingerprint": research_fingerprint(cfg, list(datasets)),
            "symbols": sorted(datasets),
            "train_selected": candidate.name == selected,
            "oos_start": oos_start.isoformat(),
            "oos_end": oos_end.isoformat(),
            "win_rate_ci_low_pct": low,
            "win_rate_ci_high_pct": high,
            "positive_windows_ratio": positive / len(windows),
            "window_count": len(windows),
            "evaluated_capitals": capitals,
            "target_win_rate_pct": cfg.research.target_win_rate_pct,
            "status": "RESEARCH_PASS" if not failures else "RESEARCH_FAIL",
            "failures": failures,
        }
        (folder / "validation_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        portable = cfg.model_dump(mode="json")
        for section, key in (
            ("data", "database"),
            ("data", "research_database"),
            ("runtime", "database"),
            ("runtime", "kill_switch_file"),
        ):
            portable[section][key] = str(Path("data") / Path(portable[section][key]).name)
        portable["research"]["report_directory"] = str(
            Path("reports") / destination.name / candidate.name
        )
        portable["universe"]["mode"] = "explicit"
        portable["universe"]["symbols"] = sorted(datasets)
        (folder / "config.yaml").write_text(yaml.safe_dump(portable, sort_keys=False))
        comparisons.append(summary)
        summaries[candidate.name] = summary
    pd.DataFrame(train_scores).to_csv(destination / "training.csv", index=False)
    pd.DataFrame(diagnostics).to_csv(destination / "windows.csv", index=False)
    pd.DataFrame(capital_results).to_csv(destination / "capital_sensitivity.csv", index=False)
    pd.DataFrame(comparisons).drop(columns=["symbols", "failures"]).to_csv(
        destination / "comparison.csv", index=False
    )
    manifest = {
        "selection": selected,
        "policy_action": "NO_TRADE" if selected is None else "CHECK_SELECTED_RESEARCH_GATE",
        "selection_rule": "initial_training_only_then_freeze",
        "selection_objective": "worst_score_across_capitals_with_"
        "profit_drawdown_trade_count_and_WR_constraints",
        "evaluated_capitals": capitals,
        "train_end_exclusive": train_end.isoformat(),
        "embargo_bars": 1,
        "oos_start": oos_start.isoformat(),
        "oos_end_exclusive": oos_end.isoformat(),
        "unused_tail_start": oos_end.isoformat(),
        "data_end_exclusive": end.isoformat(),
        "source": provenance or {},
        "results": summaries,
        "limitations": [
            "Static universe has survivorship bias; it is not all past Binance listings.",
            "OHLCV stop/target fills approximate execution; stop-limit fills are not guaranteed.",
            "Backtest windows cannot prove future win rate; research stops do not enable live.",
        ],
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
