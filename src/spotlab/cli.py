from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from spotlab.backtest import Backtester
from spotlab.config import AppConfig, Secrets, load_config
from spotlab.data import MarketDataStore, fetch_history
from spotlab.exchange import BinanceRESTClient
from spotlab.execution.live import LiveBroker
from spotlab.execution.paper import TestnetPaperBroker
from spotlab.execution.realtime import RealtimeRunner, run_realtime
from spotlab.gates import assert_live_gate, paper_gate, research_gate
from spotlab.journal import TradingJournal
from spotlab.notifier import TelegramNotifier
from spotlab.reporting import terminal_summary, write_backtest_report
from spotlab.strategies import build_strategy
from spotlab.validation import validate_rolling_windows

LOGGER = logging.getLogger(__name__)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="spotlab", description="Research-first Binance Spot bot")
    root.add_argument("--config", default="config/default.yaml")
    root.add_argument("--verbose", action="store_true")
    commands = root.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser("fetch", help="Fetch dan cache OHLCV + exchange filters")
    fetch.add_argument("--months", type=int)

    backtest = commands.add_parser("backtest", help="Backtest dari cache lokal")
    backtest.add_argument("--months", type=int)
    backtest.add_argument("--initial-cash", type=float)
    backtest.add_argument("--output", default="reports/latest")

    validate = commands.add_parser("validate", help="Backtest penuh + rolling windows")
    validate.add_argument("--months", type=int)
    validate.add_argument("--initial-cash", type=float)
    validate.add_argument("--window-months", type=int, default=3)
    validate.add_argument("--output", default="reports/validation")

    ml = commands.add_parser("ml-research", help="Eksperimen ML walk-forward (tanpa execution)")
    ml.add_argument("--model", choices=("logistic", "random_forest"), default="logistic")
    ml.add_argument("--horizon", type=int, default=1)
    ml.add_argument("--output", default="reports/ml")

    commands.add_parser("paper", help="Jalankan Binance Spot Testnet")
    live = commands.add_parser("live", help="Jalankan production setelah semua gate lulus")
    live.add_argument("--ack", default="")

    commands.add_parser("readiness", help="Tampilkan research/paper/live gate")
    export = commands.add_parser("export-trades", help="Export jurnal trade ke CSV")
    export.add_argument("--mode", choices=("paper", "live"), required=True)
    export.add_argument("--output", required=True)
    commands.add_parser("kill", help="Aktifkan kill-switch")
    commands.add_parser("clear-kill", help="Hapus kill-switch setelah investigasi")
    return root


def _client(
    config: AppConfig,
    secrets: Secrets,
    *,
    testnet: bool | None = None,
) -> BinanceRESTClient:
    return BinanceRESTClient(
        secrets.binance_api_key,
        secrets.binance_api_secret,
        testnet=config.exchange.testnet if testnet is None else testnet,
        timeout=config.exchange.rest_timeout_seconds,
        recv_window_ms=config.exchange.recv_window_ms,
    )


def _period(candles: pd.DataFrame, months: int) -> pd.DataFrame:
    if candles.empty:
        return candles
    cutoff = pd.Timestamp(candles["open_time"].max()) - pd.DateOffset(months=months)
    return candles[pd.to_datetime(candles["open_time"]) >= cutoff].copy()


def _build(config: AppConfig):
    return build_strategy(config.strategy.name, config=config.strategy)


def _notifier(config: AppConfig, secrets: Secrets) -> TelegramNotifier:
    return TelegramNotifier(
        secrets.telegram_bot_token,
        secrets.telegram_chat_id,
        config.runtime.telegram_enabled,
    )


def _run_execution(config: AppConfig, secrets: Secrets, mode: str) -> None:
    store = MarketDataStore(config.data.database)
    journal = TradingJournal(config.runtime.database)
    rules = store.load_symbol_rules(config.exchange.symbol)
    if mode == "paper":
        if not config.exchange.testnet:
            raise RuntimeError("Paper mode wajib exchange.testnet=true")
        client = _client(config, secrets, testnet=True)
        broker = TestnetPaperBroker(client, rules, expected_testnet=True)
    else:
        if config.exchange.testnet:
            raise RuntimeError("Live mode memerlukan config khusus dengan exchange.testnet=false")
        client = _client(config, secrets, testnet=False)
        broker = LiveBroker(client, rules, expected_testnet=False)
    runner = RealtimeRunner(
        mode=mode,
        config=config,
        strategy=_build(config),
        store=store,
        journal=journal,
        broker=broker,
        notifier=_notifier(config, secrets),
    )
    asyncio.run(run_realtime(runner))


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        _dispatch(args)
    except (RuntimeError, ValueError) as error:
        LOGGER.error("%s", error)
        raise SystemExit(2) from error


def _dispatch(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    secrets = Secrets()
    store = MarketDataStore(config.data.database)
    journal = TradingJournal(config.runtime.database)
    symbol = config.exchange.symbol
    interval = config.exchange.interval

    if args.command == "fetch":
        months = args.months or config.data.history_months
        end = datetime.now(UTC)
        start = (pd.Timestamp(end) - pd.DateOffset(months=months)).to_pydatetime()
        count = fetch_history(_client(config, secrets), store, symbol, interval, start, end)
        print(f"Cached {count} candles {symbol} {interval} ke {config.data.database}")
    elif args.command in {"backtest", "validate"}:
        months = args.months or config.data.history_months
        candles = _period(store.load_candles(symbol, interval), months)
        if candles.empty:
            raise RuntimeError("Cache kosong; jalankan `spotlab fetch` dahulu")
        rules = store.load_symbol_rules(symbol)
        run_config = config
        if args.initial_cash is not None:
            if args.initial_cash <= 0:
                raise ValueError("--initial-cash harus lebih besar dari nol")
            run_config = config.model_copy(
                update={
                    "backtest": config.backtest.model_copy(
                        update={"initial_cash": args.initial_cash}
                    )
                }
            )
        if args.command == "backtest":
            result = Backtester(
                _build(run_config), run_config.backtest, run_config.risk, rules
            ).run(candles)
            write_backtest_report(result, args.output)
            print(terminal_summary(result))
            print(f"Report: {Path(args.output).resolve()}")
        else:
            result, summary = validate_rolling_windows(
                candles,
                _build(run_config),
                run_config,
                rules,
                args.output,
                window_months=args.window_months,
            )
            print(terminal_summary(result))
            print(
                f"Validation: {summary['status']} ({summary['positive_windows']}/"
                f"{summary['window_count']} positive windows)"
            )
    elif args.command == "ml-research":
        research = research_gate("reports/baseline", config.gates)
        if not research.passed:
            raise RuntimeError("ML ditunda sampai baseline rule-based lulus research gate")
        from spotlab.research.ml import run_ml_research

        candles = store.load_candles(symbol, interval)
        metrics = run_ml_research(candles, args.output, model_name=args.model, horizon=args.horizon)
        print(json.dumps(metrics, indent=2))
    elif args.command == "paper":
        research = research_gate("reports/baseline", config.gates)
        if not research.passed:
            details = "; ".join(research.reasons) or "research gate belum lulus"
            raise RuntimeError(f"PAPER BLOCKED: {details}")
        _run_execution(config, secrets, "paper")
    elif args.command == "live":
        assert_live_gate("reports/baseline", journal, config.gates, args.ack)
        _run_execution(config, secrets, "live")
    elif args.command == "readiness":
        research = research_gate("reports/baseline", config.gates)
        paper = paper_gate(journal, config.gates)
        print(f"Research: {'PASS' if research.passed else 'BLOCKED'}")
        print(json.dumps(research.metrics, indent=2))
        print(f"Paper: {'PASS' if paper.passed else 'BLOCKED'}")
        print(json.dumps(paper.metrics, indent=2, default=str))
        live_status = "READY (ack tetap wajib)" if research.passed and paper.passed else "BLOCKED"
        print(f"Live: {live_status}")
        if not (research.passed and paper.passed):
            raise SystemExit(3)
    elif args.command == "export-trades":
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(journal.trade_rows(args.mode)).to_csv(destination, index=False)
        print(destination.resolve())
    elif args.command == "kill":
        config.runtime.kill_switch_file.parent.mkdir(parents=True, exist_ok=True)
        config.runtime.kill_switch_file.touch(exist_ok=True)
        print("Kill-switch aktif. OCO yang sudah ada tetap melindungi posisi.")
    elif args.command == "clear-kill":
        config.runtime.kill_switch_file.unlink(missing_ok=True)
        print("Kill-switch dihapus. Periksa posisi/order sebelum restart.")


if __name__ == "__main__":
    main(sys.argv[1:])
