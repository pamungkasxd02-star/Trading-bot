"""Private-chat controls for a single running demo account. No exchange orders."""

from __future__ import annotations

import json
import math
import time
from datetime import UTC, datetime

import pandas as pd

from spotlab.candle_alerts import candle_png

HELP = (
    "/status /health /coins [page] /signals [COIN] /settings\n"
    "/watch ALL or BTCUSDT ETHUSDT (pictures only)\n"
    "/tradecoins ALL or BTCUSDT ETHUSDT (demo entries)\n"
    "/chart BTCUSDT\n/auto on | off\n/alerts on | off\n/mode setups | observe\n"
    "Demo only; filters/SL/TP/risk limits always apply."
)


class TelegramControl:
    def __init__(self, account, notifier):
        self.account, self.notifier = account, notifier
        if not notifier.chat_id.isdecimal() or int(notifier.chat_id) <= 0:
            raise ValueError("Command Telegram memerlukan chat ID privat numerik positif")
        self.owner = int(notifier.chat_id)
        self.started = int(time.time())

    def tick(self):
        with self.account.connect() as conn:
            state = json.loads(
                conn.execute("SELECT payload FROM demo_account WHERE id=1").fetchone()[0]
            )
        cursor = state.get("telegram_control", {}).get("cursor", -1)
        for update in self.notifier.updates(cursor + 1 if cursor >= 0 else -1):
            self.process(update)
        self.order_notice()

    def order_notice(self):
        # Reserve before network send; old/replayed orders are never announced as new.
        with self.account.edit() as (conn, state):
            control = state.setdefault("telegram_control", {"cursor": -1})
            since = datetime.fromtimestamp(max(self.started, time.time() - 120), UTC).isoformat()
            row = conn.execute(
                "SELECT id,symbol,payload FROM demo_records WHERE kind='order' "
                "AND id>? AND timestamp>=? ORDER BY id LIMIT 1",
                (control.get("order_cursor", 0), since),
            ).fetchone()
            if row is None:
                return
            control["order_cursor"] = row["id"]
            order = json.loads(row["payload"])
        self.notifier.send(
            f"DEMO {order['side']} {row['symbol']}\n"
            f"Quantity={order['quantity']} | price={order.get('price', order.get('entry_price'))}\n"
            "Order virtual, tidak dikirim ke exchange. Lihat /status untuk hasil akun."
        )

    def process(self, update):
        account = self.account
        message = update.get("message", {})
        uid = update.get("update_id")
        if not isinstance(uid, int):
            return
        reply = None
        with account.edit() as (_, state):
            control = state.setdefault("telegram_control", {"cursor": -1})
            if uid <= control["cursor"]:
                return
            control["cursor"] = uid
            date = message.get("date", 0)
            if (
                message.get("chat", {}).get("type") != "private"
                or message.get("chat", {}).get("id") != self.owner
                or message.get("from", {}).get("id") != self.owner
                or message.get("from", {}).get("is_bot", False)
                or not self.started <= date <= time.time()
                or time.time() - date > 120
            ):
                return
            text = message.get("text", "")[:1024]
            parts = text.strip().split()
            if not parts:
                return
            command, args = parts[0].lower(), parts[1:]
            if command in {"/alerts", "/mode"}:
                choices = {
                    "/alerts": {"on": True, "off": False},
                    "/mode": {"setups": True, "observe": False},
                }
                if len(args) != 1 or args[0] not in choices[command]:
                    reply = "/alerts on|off atau /mode setups|observe"
                else:
                    key = "alerts" if command == "/alerts" else "setups_only"
                    control[key] = choices[command][args[0]]
                    reply = f"{key}={control[key]} (hanya notifikasi, bukan trading)"
            elif command == "/auto":
                if args == ["off"]:
                    control["auto"] = False
                    state["pending"] = {}
                    reply = "Auto entry DEMO OFF. Posisi yang ada tetap dikelola SL/TP."
                elif args == ["on"]:
                    if account.config.demo.analysis_only:
                        reply = "Candle study tidak bisa order. Gunakan akun demo trading terpisah."
                    elif state["halt_reason"] or account.config.demo.kill_switch_file.exists():
                        reply = (
                            "Risk halt/kill-switch aktif. Periksa lokal; reset lewat chat ditolak."
                        )
                    else:
                        control["auto"] = True
                        state["pending"] = {}
                        reply = (
                            "Auto entry DEMO ON. Menunggu sinyal baru; tidak ada pembelian paksa."
                        )
                else:
                    reply = "Gunakan /auto on atau /auto off."
            elif command in {"/watch", "/tradecoins"}:
                symbols = list(dict.fromkeys(s.upper() for s in args))
                selected = set(account.market.metadata("learning_source").get("symbols", []))
                if symbols == ["ALL"]:
                    symbols = []
                elif not symbols or not set(symbols) <= selected:
                    reply = "Pilih coin dari /coins. Gunakan simbol BTCUSDT, ETHUSDT, atau ALL."
                if reply is None:
                    key = "watch" if command == "/watch" else "tradecoins"
                    control[key] = symbols
                    if key == "tradecoins":
                        state["pending"] = {}
                    reply = f"{key}: {', '.join(symbols) if symbols else 'ALL eligible'}"
            elif command in {"/status", "/health", "/coins", "/signals", "/chart", "/settings"}:
                reply = (command, args)
            else:
                reply = HELP
        # Network/chart work happens after releasing the account transaction.
        if isinstance(reply, tuple):
            command, args = reply
            reply = self.read_command(command, args)
        if reply:
            self.notifier.send(reply[:3900])

    def read_command(self, command, args):
        account = self.account
        if command in {"/status", "/health"}:
            s = account.status()
            auto = not account.config.demo.analysis_only and s.get("telegram_control", {}).get(
                "auto", True
            )
            return (
                f"DEMO | health={s['health']} | auto entry={auto}\n"
                f"Equity virtual={s['equity']:.4f} | closed trades={s['trade_count']}\n"
                f"WR={s['win_rate_pct']} | PF={s['profit_factor']} | expectancy={s['expectancy']}\n"
                f"Trading halted={s['trading_halted']}\n"
                f"Posisi={s['position']['symbol'] if s['position'] else 'none'}\n"
                "Tidak dihitung sebagai paper Testnet. Live tetap terkunci."
            )
        if command == "/settings":
            control = account.status().get("telegram_control", {})
            return (
                "Watch: "
                f"{control.get('watch', account.config.candle_alerts.symbols) or 'ALL eligible'}\n"
                f"Trade coins: {control.get('tradecoins', []) or 'ALL eligible'}\n"
                f"Alerts: {control.get('alerts', True)} | setups only: "
                f"{control.get('setups_only', account.config.candle_alerts.setups_only)}\n"
                f"Global interval: {account.config.candle_alerts.min_interval_seconds}s | "
                f"coin cooldown: {account.config.candle_alerts.symbol_cooldown_seconds}s"
            )
        if command == "/coins":
            symbols = sorted(account.market.metadata("learning_source").get("symbols", []))
            page = int(args[0]) if args and args[0].isdigit() else 1
            pages = max(1, math.ceil(len(symbols) / 40))
            if not 1 <= page <= pages:
                return f"Halaman 1-{pages}"
            return f"Eligible {len(symbols)} pair | halaman {page}/{pages}\n" + " ".join(
                symbols[(page - 1) * 40 : page * 40]
            )
        if command == "/signals":
            rows = account.signals(2000 if args else 20)
            if args:
                rows = [r for r in rows if r["symbol"] == args[0].upper()]
            return (
                "\n".join(
                    f"{r['symbol']}: {r['assessment']}, score={r['signal_score']:.1f}" for r in rows
                )
                or "Belum ada sinyal."
            )
        symbols = account.market.metadata("learning_source").get("symbols", [])
        if len(args) != 1 or args[0].upper() not in symbols:
            return "Gunakan /chart BTCUSDT; pilih coin dari /coins."
        symbol = args[0].upper()
        frame = account.market.load_candles(
            symbol, account.config.demo.interval, limit=account.config.demo.warmup_bars
        )
        if frame.empty:
            return "Data candle belum tersedia."
        now = pd.Timestamp.now(tz="UTC")
        frame = frame[frame.close_time < now]
        if len(frame) < 2 or (now - frame.close_time.iloc[-1]).total_seconds() > 120:
            return "Data belum cukup atau stale; periksa /health."
        png = candle_png(
            frame,
            symbol,
            account.config.demo.interval,
            account.config.strategy.ema_fast,
            account.config.strategy.ema_slow,
            account.config.candle_alerts.bars,
        )
        self.notifier.send_photo(png, f"{symbol} | closed candles | educational, bukan order")
        return None
