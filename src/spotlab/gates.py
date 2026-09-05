from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from spotlab.config import GatesConfig
from spotlab.journal import TradingJournal


@dataclass(frozen=True, slots=True)
class GateResult:
    passed: bool
    reasons: tuple[str, ...]
    metrics: dict[str, float | int | str]


def research_gate(
    report_directory: str | Path, config: GatesConfig, fingerprint: str | None = None
) -> GateResult:
    report_path = Path(report_directory) / "validation_summary.json"
    if not report_path.exists():
        return GateResult(False, (f"Laporan validasi tidak ditemukan: {report_path}",), {})
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    profit_factor = float(payload.get("profit_factor", 0))
    drawdown = float(payload.get("max_drawdown_pct", 100))
    positive_ratio = float(payload.get("positive_windows_ratio", 0))
    expectancy = float(payload.get("expectancy_per_trade", 0))
    reasons: list[str] = []
    if fingerprint is not None and payload.get("fingerprint") != fingerprint:
        reasons.append(
            "Laporan riset tidak cocok dengan strategi, risiko, biaya, interval, atau pair"
        )
    if not all(
        math.isfinite(value) for value in (drawdown, positive_ratio, expectancy)
    ) or math.isnan(profit_factor):
        reasons.append("Metrik riset tidak valid")
    if profit_factor < config.research_min_profit_factor:
        reasons.append("Profit factor riset belum memenuhi minimum")
    if drawdown > config.research_max_drawdown_pct:
        reasons.append("Drawdown riset melebihi batas")
    if positive_ratio < config.research_min_positive_windows_ratio:
        reasons.append("Rasio rolling-window positif belum memenuhi minimum")
    if expectancy <= 0:
        reasons.append("Expectancy riset belum positif")
    if payload.get("status") != "RESEARCH_PASS":
        reasons.append("Status laporan bukan RESEARCH_PASS")
    return GateResult(not reasons, tuple(reasons), payload)


def paper_gate(
    journal: TradingJournal, config: GatesConfig, fingerprint: str | None = None
) -> GateResult:
    runtime_days = journal.paper_runtime_seconds(fingerprint) / 86_400
    trades = journal.trade_rows("paper", fingerprint)
    pnl = [float(row["net_pnl"]) for row in trades]
    wins = sum(value for value in pnl if value > 0)
    losses = abs(sum(value for value in pnl if value < 0))
    profit_factor = wins / losses if losses else (float("inf") if wins else 0.0)
    expectancy = sum(pnl) / len(pnl) if pnl else 0.0
    snapshots = journal.equity_rows("paper", fingerprint)
    equity_values = [float(row["equity"]) for row in snapshots]
    peak = equity_values[0] if equity_values else 0.0
    max_drawdown = 0.0
    for equity in equity_values:
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)
    metrics: dict[str, float | int | str] = {
        "runtime_days": runtime_days,
        "closed_trades": len(trades),
        "starting_equity": equity_values[0] if equity_values else 0.0,
        "final_equity": equity_values[-1] if equity_values else 0.0,
        "profit_factor": profit_factor,
        "max_drawdown_pct": max_drawdown,
        "expectancy_per_trade": expectancy,
    }
    reasons: list[str] = []
    if runtime_days < config.paper_min_days:
        reasons.append(f"Paper runtime {runtime_days:.2f}/{config.paper_min_days} hari")
    if len(trades) < config.paper_min_closed_trades:
        reasons.append(f"Paper trades {len(trades)}/{config.paper_min_closed_trades}")
    if not equity_values:
        reasons.append("Snapshot equity paper belum tersedia")
    if profit_factor < config.paper_min_profit_factor:
        reasons.append("Profit factor paper belum memenuhi minimum")
    if max_drawdown > config.paper_max_drawdown_pct:
        reasons.append("Drawdown paper melebihi batas")
    if expectancy <= 0:
        reasons.append("Expectancy paper belum positif")
    return GateResult(not reasons, tuple(reasons), metrics)


def assert_live_gate(
    report_directory: str | Path,
    journal: TradingJournal,
    config: GatesConfig,
    acknowledgement: str,
    fingerprint: str | None = None,
) -> None:
    research = research_gate(report_directory, config, fingerprint)
    paper = paper_gate(journal, config, fingerprint)
    failures = [*research.reasons, *paper.reasons]
    if acknowledgement != config.live_acknowledgement:
        failures.append("Acknowledgement live tidak cocok")
    if failures:
        raise RuntimeError("LIVE BLOCKED:\n- " + "\n- ".join(failures))
