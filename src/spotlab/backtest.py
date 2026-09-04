from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from spotlab.config import BacktestConfig, RiskConfig
from spotlab.models import ClosedTrade, Position, SymbolRules
from spotlab.risk import RiskManager, RiskViolation
from spotlab.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    initial_cash: float
    final_equity: float
    net_return_pct: float
    trade_count: int
    win_rate_pct: float
    profit_factor: float
    max_drawdown_pct: float
    average_win: float
    average_loss: float
    expectancy_per_trade: float
    total_fees: float
    min_notional_skips: int


@dataclass(slots=True)
class BacktestResult:
    metrics: BacktestMetrics
    trades: pd.DataFrame
    equity: pd.DataFrame


class Backtester:
    def __init__(
        self,
        strategy: Strategy,
        backtest: BacktestConfig,
        risk: RiskConfig,
        rules: SymbolRules,
    ) -> None:
        self.strategy = strategy
        self.backtest = backtest
        self.risk = risk
        self.risk_manager = RiskManager(risk, rules)

    def run(self, candles: pd.DataFrame) -> BacktestResult:
        frame = self.strategy.prepare(candles)
        if len(frame) < 2:
            raise ValueError("Minimal dua candle diperlukan")

        cash = self.backtest.initial_cash
        position: Position | None = None
        trades: list[ClosedTrade] = []
        equity_rows: list[dict[str, object]] = []
        min_notional_skips = 0
        fee_rate = self.backtest.fee_bps / 10_000
        slip_rate = self.backtest.slippage_bps / 10_000

        def close_position(row: pd.Series, raw_price: float, reason: str) -> None:
            nonlocal cash, position
            assert position is not None
            exit_price = raw_price * (1 - slip_rate)
            gross = (exit_price - position.entry_price) * position.quantity
            exit_fee = exit_price * position.quantity * fee_rate
            net = gross - position.entry_fee - exit_fee
            cash += exit_price * position.quantity - exit_fee
            trades.append(
                ClosedTrade(
                    entry_time=position.entry_time,
                    exit_time=pd.Timestamp(row["open_time"]).to_pydatetime(),
                    entry_price=position.entry_price,
                    exit_price=exit_price,
                    quantity=position.quantity,
                    gross_pnl=gross,
                    fees=position.entry_fee + exit_fee,
                    net_pnl=net,
                    return_pct=net / (position.entry_price * position.quantity) * 100,
                    exit_reason=reason,
                    entry_reason=position.entry_reason,
                )
            )
            position = None

        for index in range(1, len(frame)):
            row = frame.iloc[index]
            previous = frame.iloc[index - 1]

            if position is not None and bool(previous["exit_long"]):
                close_position(row, float(row["open"]), "strategy_exit_next_open")

            if position is None and bool(previous["enter_long"]):
                entry_price = float(row["open"]) * (1 + slip_rate)
                try:
                    sized = self.risk_manager.size_long(cash, entry_price)
                except RiskViolation:
                    min_notional_skips += 1
                else:
                    quantity = float(sized.quantity)
                    cost = entry_price * quantity
                    entry_fee = cost * fee_rate
                    if cost + entry_fee <= cash:
                        cash -= cost + entry_fee
                        position = Position(
                            entry_time=pd.Timestamp(row["open_time"]).to_pydatetime(),
                            entry_price=entry_price,
                            quantity=quantity,
                            entry_fee=entry_fee,
                            stop_price=float(sized.stop_price),
                            take_profit_price=float(sized.take_profit_price),
                            entry_reason=str(previous["signal_reason"]),
                        )

            if position is not None:
                hit_stop = float(row["low"]) <= position.stop_price
                hit_target = float(row["high"]) >= position.take_profit_price
                if hit_stop:
                    # If both are touched in one candle, assume stop first.
                    close_position(row, position.stop_price, "stop_loss")
                elif hit_target:
                    close_position(row, position.take_profit_price, "take_profit")

            marked_equity = cash
            if position is not None:
                marked_equity += position.quantity * float(row["close"])
            equity_rows.append({"time": row["close_time"], "equity": marked_equity})

        if position is not None:
            close_position(frame.iloc[-1], float(frame.iloc[-1]["close"]), "end_of_data")
            equity_rows[-1]["equity"] = cash

        trades_frame = pd.DataFrame([asdict(trade) for trade in trades])
        equity_frame = pd.DataFrame(equity_rows)
        metrics = calculate_metrics(
            self.backtest.initial_cash, cash, trades_frame, equity_frame, min_notional_skips
        )
        return BacktestResult(metrics, trades_frame, equity_frame)


def calculate_metrics(
    initial_cash: float,
    final_equity: float,
    trades: pd.DataFrame,
    equity: pd.DataFrame,
    min_notional_skips: int = 0,
) -> BacktestMetrics:
    pnl = trades["net_pnl"] if not trades.empty else pd.Series(dtype=float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    gross_profit = float(wins.sum())
    gross_loss = abs(float(losses.sum()))
    if gross_loss:
        profit_factor = gross_profit / gross_loss
    elif gross_profit:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    if equity.empty:
        max_drawdown = 0.0
    else:
        values = equity["equity"].astype(float)
        drawdowns = (values.cummax() - values) / values.cummax()
        max_drawdown = float(drawdowns.max() * 100)

    return BacktestMetrics(
        initial_cash=initial_cash,
        final_equity=final_equity,
        net_return_pct=(final_equity / initial_cash - 1) * 100,
        trade_count=len(trades),
        win_rate_pct=float((pnl > 0).mean() * 100) if len(pnl) else 0.0,
        profit_factor=profit_factor,
        max_drawdown_pct=max_drawdown,
        average_win=float(wins.mean()) if len(wins) else 0.0,
        average_loss=float(losses.mean()) if len(losses) else 0.0,
        expectancy_per_trade=float(pnl.mean()) if len(pnl) else 0.0,
        total_fees=float(trades["fees"].sum()) if not trades.empty else 0.0,
        min_notional_skips=min_notional_skips,
    )


def metric_dict(metrics: BacktestMetrics) -> dict[str, float | int | str]:
    result = asdict(metrics)
    if np.isinf(metrics.profit_factor):
        result["profit_factor"] = "inf"
    return result
