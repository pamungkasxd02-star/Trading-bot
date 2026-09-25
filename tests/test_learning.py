import json
import time
from decimal import Decimal

import pandas as pd
import pytest

from spotlab.config import AppConfig, DemoConfig
from spotlab.exchange import BinanceAPIError, PublicMarketClient
from spotlab.journal import TradingJournal
from spotlab.learning import DemoAccount, DemoEngine
from spotlab.models import SymbolRules


@pytest.fixture
def demo(tmp_path):
    cfg = AppConfig(
        demo=DemoConfig(database=tmp_path / "demo.db", kill_switch_file=tmp_path / "STOP")
    )
    account = DemoAccount(cfg)
    account.start()
    rules = {
        "BTCUSDT": SymbolRules(
            "BTCUSDT",
            Decimal("0.001"),
            Decimal("100000"),
            Decimal("0.001"),
            Decimal("0.01"),
            Decimal("5"),
        )
    }
    engine = DemoEngine(account, rules)
    yield account, engine
    if account.owner:
        account.stop()


def entry_row(**updates):
    return {
        "close_time": pd.Timestamp(time.time() - 2, unit="s", tz="UTC"),
        "enter_long": True,
        "exit_long": False,
        "signal_score": 90,
        "signal_reason": "test_cross",
        "close": 100,
        "volume": 1000000,
        **updates,
    }


def quote(price=100):
    return [{"symbol": "BTCUSDT", "bidPrice": price, "askPrice": price + 0.01}]


def test_fills_only_after_signal_and_pnl_includes_costs(demo):
    account, engine = demo
    row = entry_row()
    engine.signal("BTCUSDT", row)
    assert account.status()["position"] is None
    engine.quotes(quote())
    pos = account.status()["position"]
    assert pos["entry_price"] > 100.01
    assert 0 < pos["stop_price"] < pos["entry_price"] < pos["take_profit_price"]
    engine.signal("BTCUSDT", row)  # replay cannot create a second decision
    assert account.status()["records"]["signal"] == 1
    engine.quotes(quote(96))
    result = account.status()
    assert result["position"] is None
    assert result["trade_count"] == 1
    assert result["realized_pnl"] == pytest.approx(result["cash"] - 1000)
    gross_without_fees = (96 - pos["entry_price"]) * pos["quantity"]
    assert result["realized_pnl"] < gross_without_fees
    assert result["counts_toward_paper_gate"] is False
    engine.quotes(quote(96))
    assert account.status()["trade_count"] == 1


def test_restart_retains_balance_and_closes_unobserved_position(demo):
    account, engine = demo
    engine.signal("BTCUSDT", entry_row())
    engine.quotes(quote())
    cash = account.status()["cash"]
    account.stop()
    account.start()
    assert account.status()["cash"] == cash
    engine.quotes(quote(99))
    assert account.status()["trade_count"] == 1
    with account.connect() as conn:
        trade = json.loads(
            conn.execute("SELECT payload FROM demo_records WHERE kind='trade'").fetchone()[0]
        )
    assert trade["exit_reason"] == "resume_exit_unobserved_gap"


def test_stale_or_future_signals_cannot_buy(demo):
    account, engine = demo
    engine.signal(
        "BTCUSDT", entry_row(close_time=pd.Timestamp(time.time() - 3600, unit="s", tz="UTC"))
    )
    engine.quotes(quote())
    engine.signal(
        "BTCUSDT", entry_row(close_time=pd.Timestamp(time.time() + 60, unit="s", tz="UTC"))
    )
    engine.quotes(quote())
    assert account.status()["position"] is None
    assert account.status()["records"].get("order", 0) == 0


def test_risk_halt_keeps_collecting_quotes(demo):
    account, engine = demo
    account.config.demo.kill_switch_file.touch()
    engine.signal("BTCUSDT", entry_row())
    engine.quotes(quote())
    engine.quotes(quote())
    assert account.status()["halt_reason"] == "manual_stop_trading"
    assert account.status()["records"]["quote"] == 2
    assert account.status()["position"] is None


def test_lease_fences_old_process_and_atomic_rollback(demo):
    account, _ = demo
    second = DemoAccount(account.config)
    with pytest.raises(RuntimeError, match="proses lain"):
        second.start()
    with pytest.raises(ValueError), account.edit() as (conn, state):
        state["cash"] = 1
        account.record(conn, "order", "BTCUSDT", {"side": "BUY"})
        raise ValueError("crash before commit")
    assert account.status()["cash"] == 1000
    assert account.status()["records"].get("order", 0) == 0
    with account.connect() as conn:
        conn.execute("UPDATE demo_account SET heartbeat=0")
    second.start()
    with pytest.raises(RuntimeError, match="Lease"):
        account.heartbeat()
    account.owner = ""
    second.stop()


def test_export_and_demo_do_not_credit_testnet_gate(demo, tmp_path):
    account, engine = demo
    engine.signal("BTCUSDT", entry_row())
    engine.quotes(quote())
    engine.quotes(quote(96))
    destination = account.export(tmp_path / "export")
    assert pd.read_csv(destination / "trade.csv").iloc[0]["mode"] == "demo"
    assert (destination / "learning.db").exists()
    journal = TradingJournal(account.database)
    assert journal.paper_runtime_seconds() == 0
    assert journal.trade_rows("paper") == []


def test_public_transport_rejects_orders_even_with_credentials():
    client = PublicMarketClient()
    with pytest.raises(BinanceAPIError, match="public market data"):
        client.order(symbol="BTCUSDT", side="BUY")
    with pytest.raises(BinanceAPIError, match="public market data"):
        client.account()
    client.api_key = "do-not-send"
    with pytest.raises(BinanceAPIError, match="credential-free"):
        client.klines("BTCUSDT", "1m")


def test_demo_balance_is_not_reset_by_initialization(demo):
    account, engine = demo
    engine.signal("BTCUSDT", entry_row())
    engine.quotes(quote())
    before = account.status()["cash"]
    account.initialize()
    assert account.status()["cash"] == before
    with pytest.raises(ValueError, match="Akun sudah ada"):
        account.initialize(10000)


def test_quote_outage_is_not_claimed_as_continuous_protection(demo):
    account, engine = demo
    engine.signal("BTCUSDT", entry_row())
    engine.quotes(quote())
    with account.edit() as (_, state):
        state["quote_times"]["BTCUSDT"] = time.time() - 300
    engine.quotes(quote(98))
    assert account.status()["position"] is None
    assert account.status()["trade_count"] == 1


def test_demo_cli_never_loads_exchange_secrets(tmp_path, monkeypatch, capsys):
    from spotlab import cli

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "demo.yaml"
    config_file.write_text("demo:\n  initial_cash: 2500\n")

    def reject_credentials():
        raise AssertionError("Demo must not load .env credentials")

    monkeypatch.setattr(cli, "Secrets", reject_credentials)
    cli.main(["--config", str(config_file), "demo-init"])
    assert json.loads(capsys.readouterr().out)["cash"] == 2500
    assert not (tmp_path / "data/runtime.db").exists()


def test_scalping_exits_at_time_limit_with_costs(demo):
    account, engine = demo
    account.config.demo.max_hold_seconds = 900
    engine.signal("BTCUSDT", entry_row())
    engine.quotes(quote())
    with account.edit() as (_, state):
        state["position"]["entry_time"] = pd.Timestamp(
            time.time() - 901, unit="s", tz="UTC"
        ).isoformat()
    engine.quotes(quote())
    assert account.status()["position"] is None
    assert account.status()["realized_pnl"] < 0  # flat price is still a loss after costs
    with account.connect() as conn:
        trade = json.loads(
            conn.execute("SELECT payload FROM demo_records WHERE kind='trade'").fetchone()[0]
        )
    assert trade["exit_reason"] == "max_hold_time"


def test_large_history_reads_only_requested_tail_in_time_order(demo):
    account, _ = demo
    rows = [[i * 60000, 100, 101, 99, 100, 10, (i + 1) * 60000 - 1, 1000, 5] for i in range(100)]
    account.market.upsert_klines("BTCUSDT", "1m", rows)
    tail = account.market.load_candles("BTCUSDT", "1m", limit=10)
    assert len(tail) == 10
    assert tail.open_time.is_monotonic_increasing
    assert tail.open_time.iloc[0] == pd.Timestamp(90 * 60000, unit="ms", tz="UTC")
    assert len(account.market.load_candles("BTCUSDT", "1m")) == 100


def test_account_closes_sqlite_connection_after_transaction(demo):
    import sqlite3

    account, _ = demo
    with account.connect() as conn:
        conn.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")


def test_health_requires_fresh_data_for_every_selected_symbol(demo):
    account, engine = demo
    account.market.set_metadata("learning_source", {"symbols": ["BTCUSDT", "ETHUSDT"]})
    engine.signal("BTCUSDT", entry_row(enter_long=False))
    engine.quotes(quote())
    status = account.status()
    assert status["process_alive"] is True
    assert status["health"] == "degraded"
    assert status["symbol_health"]["BTCUSDT"]["fresh"] is True
    assert status["symbol_health"]["ETHUSDT"]["fresh"] is False
    with account.edit() as (_, state):
        state["quote_times"]["ETHUSDT"] = time.time()
        state["decisions"]["ETHUSDT"] = int((time.time() - 2) * 1000)
    assert account.status()["health"] == "healthy"
    with account.edit() as (_, state):
        state["quote_times"]["BTCUSDT"] -= 120
    assert account.status()["health"] == "degraded"


def test_health_does_not_confuse_fresh_quotes_with_fresh_strategy(demo):
    account, engine = demo
    engine.signal("BTCUSDT", entry_row(enter_long=False))
    engine.quotes(quote())
    assert account.status()["health"] == "healthy"
    with account.edit() as (_, state):
        state["decisions"]["BTCUSDT"] -= 3600000
    assert account.status()["health"] == "degraded"
    account.stop()
    assert account.status()["health"] == "offline"


def test_connection_outage_and_recovery_are_persisted_without_event_spam(demo):
    account, engine = demo
    engine.signal("BTCUSDT", entry_row(enter_long=False))
    engine.quotes(quote())
    account.connection_result("quotes", "timeout")
    account.connection_result("quotes", "timeout")
    status = account.status()
    assert status["health"] == "degraded"
    assert status["connections"]["quotes"]["consecutive_failures"] == 2
    assert status["records"]["event"] == 1
    account.connection_result("quotes")
    account.connection_result("quotes")
    assert account.status()["health"] == "healthy"
    assert account.status()["records"]["event"] == 2
    assert DemoAccount(account.config).status()["connections"]["quotes"]["last_success_at"]


def test_market_store_closes_connection(demo):
    import sqlite3

    account, _ = demo
    with account.market._connect() as conn:
        conn.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")


def test_cli_health_returns_failure_when_collector_is_offline(demo, monkeypatch, capsys):
    from spotlab import cli

    account, engine = demo
    monkeypatch.setattr(cli, "load_config", lambda _: account.config)
    engine.signal("BTCUSDT", entry_row(enter_long=False))
    engine.quotes(quote())
    cli.main(["demo-health"])
    assert json.loads(capsys.readouterr().out)["health"] == "healthy"
    account.stop()
    with pytest.raises(SystemExit) as exc:
        cli.main(["demo-health"])
    assert exc.value.code == 2
    assert json.loads(capsys.readouterr().out)["health"] == "offline"


def seed_repair_candles(account, *, gap=False):
    end = int(time.time() // 60) * 60000
    rows = [
        [end - (501 - i) * 60000, 100, 101, 99, 100, 10, end - (500 - i) * 60000 - 1, 1000, 5]
        for i in range(500)
    ]
    if gap:
        rows[200][0] -= 30000
    account.market.upsert_klines("BTCUSDT", "1m", rows)
    return rows


def test_repair_downloads_incrementally_but_refetches_gaps(demo, monkeypatch):
    from spotlab import learning

    account, _ = demo
    rows = seed_repair_candles(account)
    requests = []
    monkeypatch.setattr(learning, "fetch_history", lambda *args: requests.append(args) or 1)
    learning.repair_demo_history(account, None, ["BTCUSDT"])
    assert int(requests[-1][4].timestamp() * 1000) == rows[-1][0]
    # Introduce an actual missing candle; newest candle alone cannot prove continuity.
    with account.market._connect() as db:
        db.execute("DELETE FROM candles WHERE open_time=?", (rows[200][0],))
    learning.repair_demo_history(account, None, ["BTCUSDT"])
    assert requests[-1][4].timestamp() * 1000 < rows[200][0]


def test_repair_respects_rest_watermark_when_websocket_advanced(demo, monkeypatch):
    from spotlab import learning

    account, _ = demo
    rows = seed_repair_candles(account)
    boundary = pd.Timestamp(rows[0][0] - 60000, unit="ms", tz="UTC")
    account.market.set_metadata("repair:BTCUSDT", {"through": boundary.isoformat()})
    requests = []
    monkeypatch.setattr(learning, "fetch_history", lambda *args: requests.append(args) or 1)
    learning.repair_demo_history(account, None, ["BTCUSDT"])
    assert pd.Timestamp(requests[0][4]) == boundary


def test_failed_pair_does_not_block_other_pair_or_advance_watermark(demo, monkeypatch):
    from spotlab import learning

    account, _ = demo
    old = {"through": "2026-01-01T00:00:00+00:00"}
    account.market.set_metadata("repair:BTCUSDT", old)
    seen = []

    def fetch(*args):
        seen.append(args[2])
        if args[2] == "BTCUSDT":
            raise BinanceAPIError("temporarily unavailable")
        return 3

    monkeypatch.setattr(learning, "fetch_history", fetch)
    result = learning.repair_demo_history(account, None, ["BTCUSDT", "ETHUSDT"])
    assert seen == ["BTCUSDT", "ETHUSDT"]
    assert account.market.metadata("repair:BTCUSDT") == old
    assert result["symbols"]["ETHUSDT"]["rows"] == 3
    assert account.status()["backfill"] == result


def test_repair_stops_between_pairs_and_propagates_internal_error(demo, monkeypatch):
    from spotlab import learning

    account, _ = demo
    calls = []
    monkeypatch.setattr(learning, "fetch_history", lambda *args: calls.append(args) or 1)
    result = learning.repair_demo_history(
        account, None, ["BTCUSDT", "ETHUSDT"], should_stop=lambda: bool(calls)
    )
    assert len(calls) == 1 and result["cancelled"]

    def broken(*args):
        raise RuntimeError("pagination failed")

    monkeypatch.setattr(learning, "fetch_history", broken)
    with pytest.raises(RuntimeError, match="pagination failed"):
        learning.repair_demo_history(account, None, ["BTCUSDT"])


def test_analysis_only_logs_buy_setup_but_cannot_create_order(demo):
    account, engine = demo
    account.config.demo.analysis_only = True
    row = entry_row(
        check_trend=True, check_pullback=False, body_ratio=0.7, candle_direction="bullish"
    )
    engine.signal("BTCUSDT", row)
    engine.quotes(quote())
    result = account.status()
    assert result["position"] is None
    assert result["cash"] == 1000
    assert result["records"].get("order", 0) == 0
    signal = account.signals()[0]
    assert signal["assessment"] == "setup_detected"
    assert signal["entry_checks"] == {"trend": True, "pullback": False}
    assert signal["diagnostics"]["body_ratio"] == 0.7
    assert signal["is_order"] is False
    # Inspecting a once-fresh signal later cannot report it as a current setup.
    with account.connect() as conn:
        payload = json.loads(
            conn.execute("SELECT payload FROM demo_records WHERE kind='signal'").fetchone()[0]
        )
        payload["close_time"] -= 3600000
        conn.execute(
            "UPDATE demo_records SET payload=? WHERE kind='signal'", (json.dumps(payload),)
        )
    assert account.signals()[0]["assessment"] == "stale"


def test_analysis_mode_cannot_be_changed_on_existing_account(demo):
    account, _ = demo
    account.stop()
    account.config.demo.analysis_only = True
    with pytest.raises(RuntimeError, match="Konfigurasi berubah"):
        account.start()


class ControlCapture:
    chat_id = "12345"

    def __init__(self):
        self.sent = []

    def send(self, text, reply_markup=None):
        self.sent.append(text)
        self.markup = reply_markup


def command_update(text, uid=1, owner=12345, **changes):
    message = dict(
        chat={"id": owner, "type": "private"},
        **{"from": {"id": owner, "is_bot": False}},
        date=int(time.time()),
        text=text,
    )
    message.update(changes)
    return {"update_id": uid, "message": message}


def test_telegram_control_rejects_other_owner_stale_and_duplicate(demo):
    from spotlab.telegram_control import TelegramControl

    account, _ = demo
    sender = ControlCapture()
    bot = TelegramControl(account, sender)
    bot.process(command_update("/auto off", owner=54321))
    bot.process(command_update("/auto off", uid=2, date=int(time.time()) - 300))
    assert not sender.sent
    assert "auto" not in account.status()["telegram_control"]
    bot.process(command_update("/auto off", uid=3))
    bot.process(command_update("/auto on", uid=3))
    assert account.status()["telegram_control"]["auto"] is False
    assert len(sender.sent) == 1


def test_telegram_auto_off_blocks_entry_but_can_resume_with_new_signal(demo):
    from spotlab.telegram_control import TelegramControl

    account, engine = demo
    bot = TelegramControl(account, ControlCapture())
    bot.process(command_update("/auto off"))
    row = entry_row()
    engine.signal("BTCUSDT", row)
    engine.quotes(quote())
    assert account.status()["position"] is None
    bot.process(command_update("/auto on", uid=2))
    # /auto on itself cannot buy or reuse an old pending signal.
    engine.quotes(quote())
    assert account.status()["position"] is None
    row["close_time"] += pd.Timedelta(1, unit="ms")
    engine.signal("BTCUSDT", row)
    engine.quotes(quote())
    assert account.status()["position"]["symbol"] == "BTCUSDT"


def test_telegram_cannot_override_analysis_or_risk_halt(demo):
    from spotlab.telegram_control import TelegramControl

    account, _ = demo
    bot = TelegramControl(account, ControlCapture())
    bot.process(command_update("/auto off"))
    account.config.demo.analysis_only = True
    bot.process(command_update("/auto on", uid=2))
    assert account.status()["telegram_control"]["auto"] is False
    account.config.demo.analysis_only = False
    with account.edit() as (_, state):
        state["halt_reason"] = "daily loss limit"
    bot.process(command_update("/auto on", uid=3))
    assert account.status()["telegram_control"]["auto"] is False
    assert account.status()["halt_reason"] == "daily loss limit"


def test_watch_does_not_change_trade_universe_and_tradecoins_blocks_entry(demo):
    from spotlab.telegram_control import TelegramControl

    account, engine = demo
    account.market.set_metadata("learning_source", {"symbols": ["BTCUSDT", "ETHUSDT"]})
    bot = TelegramControl(account, ControlCapture())
    bot.process(command_update("/watch BTCUSDT"))
    bot.process(command_update("/tradecoins ETHUSDT", uid=2))
    state = account.status()["telegram_control"]
    assert state["watch"] == ["BTCUSDT"] and state["tradecoins"] == ["ETHUSDT"]
    engine.signal("BTCUSDT", entry_row())
    engine.quotes(quote())
    assert account.status()["position"] is None
    bot.process(command_update("/tradecoins UNKNOWNUSDT", uid=3))
    assert account.status()["telegram_control"]["tradecoins"] == ["ETHUSDT"]


def test_telegram_group_and_sender_impersonation_rejected(demo):
    from spotlab.telegram_control import TelegramControl

    account, _ = demo
    sender = ControlCapture()
    bot = TelegramControl(account, sender)
    bot.process(command_update("/status", chat={"id": 12345, "type": "group"}))
    bot.process(command_update("/status", uid=2, **{"from": {"id": 999}}))
    assert not sender.sent


def test_telegram_alert_settings_do_not_toggle_auto_and_order_notice_dedupes(demo):
    from spotlab.telegram_control import TelegramControl

    account, engine = demo
    sender = ControlCapture()
    bot = TelegramControl(account, sender)
    bot.process(command_update("/alerts off"))
    bot.process(command_update("/mode observe", uid=2))
    control = account.status()["telegram_control"]
    assert control["alerts"] is False and control["setups_only"] is False
    assert control.get("auto", True)
    engine.signal("BTCUSDT", entry_row())
    engine.quotes(quote())
    bot.order_notice()
    bot.order_notice()
    assert sum("DEMO BUY" in text for text in sender.sent) == 1


def test_manual_chart_and_catalogue_independent_of_trade_universe(demo, monkeypatch):
    from spotlab.telegram_control import TelegramControl

    account, _ = demo
    account.market.set_metadata("learning_source", {"symbols": ["BTCUSDT"]})
    sender = ControlCapture()
    photos = []
    sender.send_photo = lambda png, caption: photos.append((png, caption))
    bot = TelegramControl(account, sender)
    market = {"symbol": "ETHBTC", "quoteAsset": "BTC"}
    bot.market_charts.catalogue = lambda: {"ETHBTC": market, "BTCUSDT": {}}
    calls = []

    def candles(coin, interval):
        calls.append((coin, interval))
        return market, pd.DataFrame({"close_time": [pd.Timestamp.now(tz="UTC")]})

    bot.market_charts.candles = candles
    rendered = []

    def render(*args, **kwargs):
        rendered.append(kwargs)
        return b"png"

    monkeypatch.setattr("spotlab.telegram_control.candle_png", render)
    bot.process(command_update("/chart ETH/BTC 4h"))
    assert calls == [("ETH/BTC", "4h")]
    assert rendered == [{"quote_asset": "BTC"}]
    assert "ETHBTC | 4h" in photos[0][1]
    assert "ETHBTC" in bot.read_command("/coins", [])
    assert "ETHBTC" not in bot.read_command("/eligible", [])
    bot.process(command_update("/watch bitcoin", uid=2))
    assert account.status()["telegram_control"]["watch"] == ["BTCUSDT"]
    bot.process(command_update("/tradecoins ETHBTC", uid=3))
    assert not account.status()["telegram_control"].get("tradecoins")


def test_telegram_analyze_routes_config_defaults_without_enabling_orders(demo, monkeypatch):
    from spotlab.telegram_control import TelegramControl

    account, _ = demo
    sender = ControlCapture()
    bot = TelegramControl(account, sender)
    calls = []

    def report(charts, query, intervals, config):
        calls.append((query, intervals))
        return "analisis selesai"

    monkeypatch.setattr("spotlab.telegram_control.analysis_report", report)
    bot.process(command_update("/auto off"))
    bot.process(command_update("/analyze bitcoin", uid=2))
    bot.process(command_update("/analyze ETH 15m 1h", uid=3))
    assert calls == [("bitcoin", ["1m", "5m", "15m"]), ("ETH", ["15m", "1h"])]
    assert sender.sent[-1] == "analisis selesai"
    assert account.status()["telegram_control"]["auto"] is False
    assert account.status()["position"] is None


def test_start_menu_preserves_auto_and_guided_input(demo, monkeypatch):
    from spotlab.telegram_control import TelegramControl

    account, _ = demo
    sender = ControlCapture()
    bot = TelegramControl(account, sender)
    bot.process(command_update("/auto off"))
    bot.process(command_update("/start", uid=2))
    assert sender.markup["resize_keyboard"] is True
    assert "Lihat candle" in str(sender.markup)
    assert account.status()["telegram_control"]["auto"] is False
    bot.process(command_update("Lihat candle", uid=3))
    assert "BTC 15m" in sender.sent[-1]
    calls = []
    monkeypatch.setattr(bot, "read_command", lambda cmd, args: calls.append((cmd, args)) or "ok")
    bot.process(command_update("ETH 1h", uid=4))
    assert calls == [("/chart", ["ETH", "1h"])]
    assert "menu_prompt" not in account.status()["telegram_control"]
    assert account.status()["telegram_control"]["auto"] is False


def test_menu_unauthorized_input_cancel_and_expiry(demo, monkeypatch):
    from spotlab.telegram_control import TelegramControl

    account, _ = demo
    sender = ControlCapture()
    bot = TelegramControl(account, sender)
    bot.process(command_update("Pilih coin demo", owner=999))
    assert "menu_prompt" not in account.status()["telegram_control"]
    bot.process(command_update("Pilih coin demo", uid=2))
    bot.process(command_update("Batal", uid=3))
    assert "menu_prompt" not in account.status()["telegram_control"]
    bot.process(command_update("Lihat candle", uid=4))
    with account.edit() as (_, state):
        state["telegram_control"]["menu_prompt"]["expires"] = 0
    bot.process(command_update("BTC 1m", uid=5))
    assert "kedaluwarsa" in sender.sent[-1]
    assert not account.status()["telegram_control"].get("tradecoins")


def test_menu_auto_button_respects_study_gate(demo):
    from spotlab.telegram_control import TelegramControl

    account, _ = demo
    account.config.demo.analysis_only = True
    sender = ControlCapture()
    bot = TelegramControl(account, sender)
    bot.process(command_update("Jeda auto-buy demo"))
    bot.process(command_update("Aktifkan auto-buy demo", uid=2))
    assert "tidak bisa order" in sender.sent[-1]
    assert account.status()["telegram_control"]["auto"] is False


def test_diagnostics_and_position_describe_state_without_mutation(demo):
    from spotlab.telegram_diagnostics import position_report, why_report

    account, engine = demo
    with account.edit() as (_, state):
        state.setdefault("telegram_control", {})["auto"] = False
    account.config.demo.analysis_only = True
    report = why_report(account)
    assert "Mode belajar" in report and "dijeda" in report
    assert "Belum ada posisi" in position_report(account)
    account.config.demo.analysis_only = False
    with account.edit() as (_, state):
        state["telegram_control"]["auto"] = True
    engine.signal("BTCUSDT", entry_row())
    engine.quotes(quote())
    assert "batas satu posisi" in why_report(account)
    report = position_report(account)
    assert "Stop-loss:" in report and "take-profit:" in report
    assert account.status()["position"]["symbol"] == "BTCUSDT"


def test_diagnostics_skip_history_does_not_expose_unknown_error(demo):
    from spotlab.telegram_diagnostics import why_report

    account, _ = demo
    with account.edit() as (conn, _):
        account.record(
            conn,
            "event",
            "BTCUSDT",
            {"event": "entry_skipped", "reason": "private-token-network-error"},
        )
    report = why_report(account)
    assert "private-token" not in report
    assert "bisa sudah lama" in report


def test_photo_wizard_restores_main_keyboard(demo, monkeypatch):
    from spotlab.telegram_control import TelegramControl

    account, _ = demo
    sender = ControlCapture()
    bot = TelegramControl(account, sender)
    calls = []
    monkeypatch.setattr(bot, "read_command", lambda cmd, args: calls.append((cmd, args)))
    bot.process(command_update("Lihat candle"))
    bot.process(command_update("BTC", uid=2))
    assert not calls
    bot.process(command_update("15m", uid=3))
    assert calls == [("/chart", ["BTC", "15m"])]
    assert "Selesai" in sender.sent[-1]
    assert "Lihat candle" in str(sender.markup)


def test_market_navigation_private_chat_and_scoped_state(demo):
    from spotlab.telegram_control import TelegramControl

    account, _ = demo
    sender = ControlCapture()
    bot = TelegramControl(account, sender)
    bot.market_charts.catalogue = lambda: {
        f"T{i}USDT": {"symbol": f"T{i}USDT", "baseAsset": f"T{i}", "quoteAsset": "USDT"}
        for i in range(45)
    }
    bot.process(command_update("/auto off"))
    bot.process(command_update("Semua pair USDT", uid=2))
    assert "halaman 1/2" in sender.sent[-1]
    assert "Halaman berikut" in str(sender.markup)
    bot.process(command_update("Halaman berikut", uid=3))
    assert "halaman 2/2" in sender.sent[-1]
    bot.process(command_update("Halaman sebelumnya", uid=4, owner=98765))
    assert account.status()["telegram_control"]["market_browser"]["page"] == 2
    assert account.status()["telegram_control"]["auto"] is False


def test_section_panels_are_owner_only_and_status_is_readable(demo):
    from spotlab.telegram_control import TelegramControl
    from spotlab.telegram_menu import PANELS

    account, _ = demo
    sender = ControlCapture()
    bot = TelegramControl(account, sender)
    bot.process(command_update("/auto off"))
    for uid, command in enumerate(PANELS, start=2):
        bot.process(command_update(command, uid=uid))
        assert sender.sent[-1] == PANELS[command]
        assert sender.markup is not None
    before = len(sender.sent)
    bot.process(command_update("Akun demo", uid=20, owner=98765))
    assert len(sender.sent) == before
    bot.process(command_update("/status", uid=21))
    assert "N/A" in sender.sent[-1] and "None" not in sender.sent[-1]
    bot.process(command_update("/settings", uid=22))
    assert "Coin gambar:" in sender.sent[-1] and "Coin entry demo:" in sender.sent[-1]
    assert account.status()["telegram_control"]["auto"] is False
