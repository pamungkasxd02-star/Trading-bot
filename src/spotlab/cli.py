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
from spotlab.research.walkforward import research_fingerprint, run_walkforward
from spotlab.strategies import build_strategy
from spotlab.universe import discover_universe
from spotlab.validation import validate_rolling_windows

LOGGER = logging.getLogger(__name__)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="spotlab", description="Research-first Binance Spot bot")
    root.add_argument("--config", default="config/default.yaml")
    root.add_argument("--verbose", action="store_true")
    commands = root.add_subparsers(dest="command", required=True)
    demo_init = commands.add_parser("demo-init", help="Buat akun belajar virtual tanpa API key")
    demo_init.add_argument("--initial-cash", type=float)
    demo_run = commands.add_parser("demo-run", help="Kumpulkan data publik + simulasi forward")
    demo_run.add_argument("--duration-seconds", type=int)
    commands.add_parser("demo-status", help="Saldo virtual, posisi, data, dan statistik demo")
    commands.add_parser(
        "demo-stop-trading", help="Hentikan trading virtual; data tetap dikumpulkan"
    )
    demo_export = commands.add_parser("demo-export", help="Export data belajar + backup SQLite")
    demo_export.add_argument("--output", default="reports/learning")

    fetch = commands.add_parser("fetch", help="Fetch dan cache OHLCV + exchange filters")
    fetch.add_argument("--months", type=int)
    universe = commands.add_parser(
        "universe", help="Temukan pair Spot USDT dengan volume/spread/OCO filter"
    )
    universe.add_argument("--all", action="store_true")
    pool = commands.add_parser(
        "fetch-universe", help="Cache banyak pair; --production untuk data riset publik"
    )
    pool.add_argument("--production", action="store_true")
    pool.add_argument("--months", type=int)
    research = commands.add_parser(
        "research", help="Seleksi train lalu evaluasi OOS portfolio dan cost stress"
    )
    research.add_argument("--symbols", nargs="+")
    research.add_argument("--output", default="reports/research")
    research.add_argument("--initial-cash", type=float)
    scan = commands.add_parser("scan", help="Ranking sinyal dari cache riset; tidak mengirim order")
    scan.add_argument("--symbols", nargs="+")
    commands.add_parser("inspect-intent", help="Tampilkan intent paper yang perlu rekonsiliasi")
    clear_intent = commands.add_parser(
        "clear-intent", help="Hanya setelah order diperiksa di Testnet"
    )
    clear_intent.add_argument("--ack", required=True)

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
    commands.add_parser(
        "research-readiness", help="Cek kecocokan bukti riset sebelum startup paper"
    )
    health = commands.add_parser("health", help="Cek heartbeat runtime untuk container/VPS")
    health.add_argument("--mode", choices=("paper", "live"), default="paper")
    backup = commands.add_parser("backup", help="Backup konsisten database runtime SQLite")
    backup.add_argument("--output", required=True)
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
    symbols = _execution_symbols(config, store)
    fingerprint = research_fingerprint(config, symbols)
    rules = store.load_symbol_rules(symbols[0])
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
    brokers = {
        symbol: type(broker)(
            client, store.load_symbol_rules(symbol), expected_testnet=mode == "paper"
        )
        for symbol in symbols
    }
    runner = RealtimeRunner(
        mode=mode,
        config=config,
        strategy=_build(config),
        store=store,
        journal=journal,
        broker=broker,
        notifier=_notifier(config, secrets),
        brokers=brokers,
        fingerprint=fingerprint,
    )
    asyncio.run(run_realtime(runner))


def _execution_symbols(config: AppConfig, store: MarketDataStore) -> list[str]:
    if config.universe.mode == "single":
        return [config.exchange.symbol.upper()]
    if config.universe.mode == "explicit":
        return sorted(config.universe.symbols)
    symbols = store.metadata("universe").get("symbols", [])
    if not symbols:
        raise RuntimeError("Universe belum di-cache; jalankan fetch-universe")
    return sorted(symbols)


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
    if args.command.startswith("demo-"):
        from spotlab.learning import DemoAccount, run_demo

        # Do not load .env credentials or create paper/live journals for learning commands.
        account = DemoAccount(config)
        if args.command == "demo-init":
            print(json.dumps(account.initialize(args.initial_cash), indent=2))
        elif args.command == "demo-run":
            if args.duration_seconds is not None and args.duration_seconds <= 0:
                raise ValueError("duration-seconds harus positif")
            asyncio.run(run_demo(config, duration_seconds=args.duration_seconds))
        elif args.command == "demo-status":
            print(json.dumps(account.status(), indent=2))
        elif args.command == "demo-export":
            print(account.export(args.output).resolve())
        else:
            config.demo.kill_switch_file.parent.mkdir(parents=True, exist_ok=True)
            config.demo.kill_switch_file.touch()
            print("Trading virtual dihentikan pada quote berikutnya; collector tetap berjalan")
        return
    secrets = Secrets()
    store = MarketDataStore(config.data.database)
    journal = TradingJournal(config.runtime.database)
    symbol = config.exchange.symbol
    interval = config.exchange.interval

    if args.command == "universe":
        chosen_config = config
        if args.all:
            chosen_config = config.model_copy(
                update={"universe": config.universe.model_copy(update={"mode": "all"})}
            )
        payload = discover_universe(_client(config, secrets), chosen_config)
        payload.pop("exchange_info")
        print(json.dumps(payload, indent=2))
    elif args.command == "fetch-universe":
        cfg = (
            config.model_copy(
                update={"exchange": config.exchange.model_copy(update={"testnet": False})}
            )
            if args.production
            else config
        )
        client = BinanceRESTClient(testnet=False) if args.production else _client(cfg, secrets)
        target = MarketDataStore(config.data.research_database) if args.production else store
        expected = "production" if not cfg.exchange.testnet else "testnet"
        previous = target.metadata("market")
        if previous and previous.get("environment") != expected:
            raise RuntimeError("Database tidak boleh mencampur data production dan Testnet")
        target.set_metadata("market", {"environment": expected, "exchange_verified": False})
        discovery = discover_universe(client, cfg)
        symbols = [item["symbol"] for item in discovery["selected"]]
        if not symbols:
            raise RuntimeError("Tidak ada pair yang memenuhi filter universe")
        end = datetime.now(UTC)
        start = (
            pd.Timestamp(end) - pd.DateOffset(months=args.months or config.data.history_months)
        ).to_pydatetime()
        for name in symbols:
            count = fetch_history(client, target, name, interval, start, end)
            print(f"{name}: {count} closed candles")
        target.set_metadata("universe", {"symbols": symbols, "asof": end.isoformat()})
        target.set_metadata(
            "market",
            {
                "environment": expected,
                "exchange_verified": expected == "production",
                "source": client.base_url,
                "fetched_at": end.isoformat(),
                "symbols": symbols,
            },
        )
    elif args.command in {"research", "scan"}:
        research_store = MarketDataStore(config.data.research_database)
        symbols = (
            [s.upper() for s in args.symbols]
            if args.symbols
            else _execution_symbols(config, research_store)
        )
        datasets = {
            name: _period(research_store.load_candles(name, interval), config.data.history_months)
            for name in symbols
        }
        if any(frame.empty for frame in datasets.values()):
            raise RuntimeError("Cache riset kosong; jalankan fetch-universe --production")
        if args.command == "scan":
            from spotlab.selection import ranked_entries

            rows = {
                s: _build(config).prepare(f.tail(config.runtime.history_bars)).iloc[-1]
                for s, f in datasets.items()
            }
            print(
                json.dumps(
                    {
                        "source": "cached_closed_candles",
                        "ranked_entries": ranked_entries(rows),
                        "signals": {
                            s: {
                                "asof": str(r["close_time"]),
                                "score": float(r["signal_score"]),
                                "reason": r["signal_reason"],
                            }
                            for s, r in rows.items()
                        },
                    },
                    indent=2,
                )
            )
        else:
            if args.initial_cash is not None:
                config = config.model_copy(
                    update={
                        "backtest": config.backtest.model_copy(
                            update={"initial_cash": args.initial_cash}
                        )
                    }
                )
                config = AppConfig.model_validate(config.model_dump())
            rules = {name: research_store.load_symbol_rules(name) for name in symbols}
            manifest = run_walkforward(
                datasets, rules, config, args.output, provenance=research_store.metadata("market")
            )
            print(f"Selected from training: {manifest['selection']}")
            for name, row in manifest["results"].items():
                print(
                    f"{name}: WR {row['win_rate_pct']:.2f}% | PF {row['profit_factor']} | "
                    f"DD {row['max_drawdown_pct']:.2f}% | {row['status']}"
                )
    elif args.command == "inspect-intent":
        print(json.dumps(journal.pending_intent("paper"), indent=2))
    elif args.command == "clear-intent":
        if args.ack != "I_RECONCILED_TESTNET_ORDERS":
            raise RuntimeError("Periksa order/posisi Testnet sebelum menghapus intent")
        if not config.exchange.testnet:
            raise RuntimeError("Command ini hanya untuk Testnet")
        journal.clear_intent("paper")
        print("Intent paper dihapus; kill-switch tetap perlu diperiksa")
    elif args.command == "fetch":
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
        fingerprint = research_fingerprint(config, _execution_symbols(config, store))
        research = research_gate(config.research.report_directory, config.gates, fingerprint)
        if not research.passed:
            details = "; ".join(research.reasons) or "research gate belum lulus"
            raise RuntimeError(f"PAPER BLOCKED: {details}")
        _run_execution(config, secrets, "paper")
    elif args.command == "live":
        if config.universe.mode != "single" or config.strategy.name != "rule_based_v1":
            raise RuntimeError(
                "LIVE BLOCKED: perlu 14 hari paper dan peninjauan modul baru "
                "sebelum rollout multi-pair"
            )
        fingerprint = research_fingerprint(config, _execution_symbols(config, store))
        assert_live_gate(
            config.research.report_directory, journal, config.gates, args.ack, fingerprint
        )
        _run_execution(config, secrets, "live")
    elif args.command in {"readiness", "research-readiness"}:
        fingerprint = research_fingerprint(config, _execution_symbols(config, store))
        research = research_gate(config.research.report_directory, config.gates, fingerprint)
        if args.command == "research-readiness":
            print(
                json.dumps(
                    {
                        "passed": research.passed,
                        "reasons": research.reasons,
                        "fingerprint": fingerprint,
                    },
                    indent=2,
                )
            )
            if not research.passed:
                raise SystemExit(2)
            return
        paper = paper_gate(journal, config.gates, fingerprint)
        print(f"Research: {'PASS' if research.passed else 'BLOCKED'}")
        print(json.dumps(research.metrics, indent=2))
        print(f"Paper: {'PASS' if paper.passed else 'BLOCKED'}")
        print(json.dumps(paper.metrics, indent=2, default=str))
        live_supported = (
            config.universe.mode == "single" and config.strategy.name == "rule_based_v1"
        )
        live_status = (
            "READY (ack tetap wajib)"
            if research.passed and paper.passed and live_supported
            else "BLOCKED"
        )
        print(f"Live: {live_status}")
        if not (research.passed and paper.passed and live_supported):
            raise SystemExit(3)
    elif args.command == "health":
        health = journal.runtime_health(args.mode, config.runtime.session_stale_seconds)
        print(json.dumps(health, indent=2, default=str))
        if not health["healthy"]:
            raise SystemExit(1)
    elif args.command == "backup":
        print(journal.backup(args.output).resolve())
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
