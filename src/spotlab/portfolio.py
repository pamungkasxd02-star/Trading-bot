from __future__ import annotations

from typing import Any

import pandas as pd

from spotlab.backtest import BacktestResult, calculate_metrics
from spotlab.config import BacktestConfig, RiskConfig
from spotlab.models import Position, SymbolRules
from spotlab.quality import validate_candles
from spotlab.risk import RiskManager, RiskViolation
from spotlab.selection import ranked_entries
from spotlab.strategies.base import Strategy


class PortfolioBacktester:
    """One account, one position across N symbols, ranked closed-bar signals.

    The single-symbol baseline engine is retained for reproducing the frozen report.
    This engine adds account risk stops, liquidity caps, gaps, and temporal splits.
    """

    def __init__(
        self,
        strategy: Strategy,
        backtest: BacktestConfig,
        risk: RiskConfig,
        rules: dict[str, SymbolRules],
    ) -> None:
        self.strategy, self.backtest, self.risk, self.rules = strategy, backtest, risk, rules

    def run(
        self,
        candles: dict[str, pd.DataFrame],
        *,
        trade_start: pd.Timestamp | None = None,
        trade_end: pd.Timestamp | None = None,
        prepared: bool = False,
    ) -> BacktestResult:
        frames = {}
        for symbol, source in candles.items():
            valid = validate_candles(source)
            frame = valid if prepared else self.strategy.prepare(valid)
            frames[symbol] = frame.set_index("open_time", drop=False)
        if not frames:
            raise ValueError("Minimal satu pair diperlukan")
        times = sorted(set().union(*(frame.index for frame in frames.values())))
        times = [
            t
            for t in times
            if (trade_start is None or t >= trade_start) and (trade_end is None or t < trade_end)
        ]
        if not times:
            raise ValueError("Periode evaluasi kosong")
        cash = self.backtest.initial_cash
        peak, day_start = cash, cash
        day = times[0].date()
        position: Position | None = None
        held: str | None = None
        trades: list[dict[str, Any]] = []
        equity = [{"time": times[0], "equity": cash}]
        cooldown_until: dict[str, pd.Timestamp] = {}
        marks: dict[str, float] = {}
        halted, daily_halted = False, False
        skips = 0
        fee = self.backtest.fee_bps / 10_000
        slip = self.backtest.slippage_bps / 10_000
        # Convert once: repeated pandas .loc calls dominate multi-capital research.
        records = {s: f.to_dict("index") for s, f in frames.items()}
        previous_rows = {
            s: dict(zip(rows, [{}, *list(rows.values())[:-1]], strict=True))
            for s, rows in records.items()
        }

        def close(row: Any, raw_price: float, reason: str, when: pd.Timestamp) -> None:
            nonlocal cash, position, held
            assert position is not None and held is not None
            price = raw_price * (1 - slip)
            exit_fee = price * position.quantity * fee
            gross = (price - position.entry_price) * position.quantity
            net = gross - position.entry_fee - exit_fee
            cash += price * position.quantity - exit_fee
            trades.append(
                {
                    "symbol": held,
                    "entry_time": position.entry_time,
                    "exit_time": when,
                    "entry_price": position.entry_price,
                    "exit_price": price,
                    "quantity": position.quantity,
                    "gross_pnl": gross,
                    "fees": position.entry_fee + exit_fee,
                    "net_pnl": net,
                    "return_pct": net / (position.entry_price * position.quantity) * 100,
                    "entry_reason": position.entry_reason,
                    "exit_reason": reason,
                }
            )
            duration = pd.Timestamp(row["close_time"]) - pd.Timestamp(row["open_time"])
            cooldown_until[held] = when + duration * self.risk.cooldown_bars
            position, held = None, None

        def marked(prices: dict[str, float]) -> float:
            return cash + (position.quantity * prices[held] if position is not None else 0)

        for time in times:
            rows = {s: data[time] for s, data in records.items() if time in data}
            previous = {s: previous_rows[s][time] for s in rows}
            opens = {**marks, **{s: float(r["open"]) for s, r in rows.items()}}
            if position is not None and held in rows:
                row = rows[held]
                if float(row["open"]) <= position.stop_price:
                    close(row, float(row["open"]), "gap_stop", time)
                elif float(row["open"]) >= position.take_profit_price:
                    close(row, position.take_profit_price, "take_profit", time)
                elif pd.notna(previous[held].get("exit_long")) and bool(
                    previous[held].get("exit_long", False)
                ):
                    close(row, float(row["open"]), "strategy_exit_next_open", time)
            account = marked(opens)
            if time.date() != day:
                day, day_start, daily_halted = time.date(), account, False
            peak = max(peak, account)
            halted = halted or (peak - account) / peak * 100 >= self.risk.max_drawdown_pct
            daily_halted = (
                daily_halted
                or (day_start - account) / day_start * 100 >= self.risk.daily_loss_limit_pct
            )
            if position is None and not halted and not daily_halted:
                candidates = {}
                for symbol, prev in previous.items():
                    if pd.isna(prev.get("open_time")):
                        continue
                    # Missing bars cannot be treated as a fresh signal.
                    duration = pd.Timestamp(prev["close_time"]) - pd.Timestamp(prev["open_time"])
                    if time - pd.Timestamp(prev["open_time"]) > duration + pd.Timedelta(
                        1, unit="s"
                    ):
                        continue
                    if symbol in cooldown_until and time <= cooldown_until[symbol]:
                        continue
                    candidates[symbol] = prev
                for symbol in ranked_entries(candidates):
                    row, prev = rows[symbol], previous[symbol]
                    price = float(row["open"]) * (1 + slip)
                    liquidity = (
                        float(prev["volume"])
                        * float(prev["close"])
                        * self.risk.max_candle_participation_pct
                        / 100
                    )
                    manager = RiskManager(self.risk, self.rules[symbol])
                    try:
                        sized = manager.size_long(
                            cash,
                            price,
                            min(cash, liquidity),
                            atr_value=prev.get("atr"),
                            cost_bps=2 * (self.backtest.fee_bps + self.backtest.slippage_bps),
                        )
                    except RiskViolation:
                        skips += 1
                        continue
                    cost = float(sized.notional)
                    entry_fee = cost * fee
                    if cost + entry_fee > cash:
                        skips += 1
                        continue
                    cash -= cost + entry_fee
                    held = symbol
                    position = Position(
                        entry_time=time.to_pydatetime(),
                        entry_price=price,
                        quantity=float(sized.quantity),
                        entry_fee=entry_fee,
                        stop_price=float(sized.stop_price),
                        take_profit_price=float(sized.take_profit_price),
                        entry_reason=str(prev["signal_reason"]),
                    )
                    break
            if position is not None and held in rows:
                row = rows[held]
                if float(row["low"]) <= position.stop_price:
                    close(row, position.stop_price, "stop_loss", pd.Timestamp(row["close_time"]))
                elif float(row["high"]) >= position.take_profit_price:
                    close(
                        row,
                        position.take_profit_price,
                        "take_profit",
                        pd.Timestamp(row["close_time"]),
                    )
            marks.update({s: float(r["close"]) for s, r in rows.items()})
            account = marked(marks)
            peak = max(peak, account)
            halted = halted or (peak - account) / peak * 100 >= self.risk.max_drawdown_pct
            daily_halted = (
                daily_halted
                or (day_start - account) / day_start * 100 >= self.risk.daily_loss_limit_pct
            )
            equity.append({"time": max(r["close_time"] for r in rows.values()), "equity": account})
        if position is not None and held is not None:
            last = frames[held][frames[held].index <= times[-1]].iloc[-1]
            close(last, float(last["close"]), "end_of_window", pd.Timestamp(last["close_time"]))
            equity[-1]["equity"] = cash
        trades_frame, equity_frame = pd.DataFrame(trades), pd.DataFrame(equity)
        metrics = calculate_metrics(
            self.backtest.initial_cash, cash, trades_frame, equity_frame, skips
        )
        return BacktestResult(metrics, trades_frame, equity_frame)
