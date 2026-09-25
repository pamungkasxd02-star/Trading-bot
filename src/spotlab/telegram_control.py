"""Private-chat controls for a single running demo account. No exchange orders."""

from __future__ import annotations

import json
import math
import time
from datetime import UTC, datetime

from spotlab.candle_alerts import candle_png
from spotlab.candle_analysis import analysis_report
from spotlab.entry_preview import preview
from spotlab.market_browser import browse, coin_info, coverage
from spotlab.market_charts import INTERVALS, MarketCharts, normalize_coin, selected_symbol
from spotlab.strategy_review import catalogue as strategy_catalogue
from spotlab.strategy_review import review
from spotlab.telegram_diagnostics import position_report, why_report
from spotlab.telegram_menu import (
    BROWSER_ROWS,
    GUIDE,
    PANELS,
    SECTIONS,
    health_label,
    keyboard,
    metric,
    route,
)


class TelegramControl:
    def __init__(self, account, notifier):
        self.account, self.notifier = account, notifier
        if not notifier.chat_id.isdecimal() or int(notifier.chat_id) <= 0:
            raise ValueError("Command Telegram memerlukan chat ID privat numerik positif")
        self.owner = int(notifier.chat_id)
        self.started = int(time.time())
        self.market_charts = MarketCharts()

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
        markup = None
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
            text, prompt, markup = route(text, control, time.time())
            if prompt:
                reply = prompt
                text = "/_prompt"
            parts = text.strip().split()
            if not parts:
                return
            command, args = parts[0].lower(), parts[1:]
            if command == "/_prompt":
                pass
            elif command in {"/start", "/menu", "/guide", "/help", *SECTIONS, *PANELS}:
                reply = (command, args)
            elif command in {"/alerts", "/mode"}:
                choices = {
                    "/alerts": {"on": True, "off": False},
                    "/mode": {"setups": True, "observe": False},
                }
                if len(args) != 1 or args[0] not in choices[command]:
                    reply = "/alerts on|off atau /mode setups|observe"
                else:
                    key = "alerts" if command == "/alerts" else "setups_only"
                    control[key] = choices[command][args[0]]
                    label = (
                        ("Gambar otomatis ON" if control[key] else "Gambar otomatis OFF")
                        if key == "alerts"
                        else (
                            "Gambar hanya saat setup" if control[key] else "Gambar semua pengamatan"
                        )
                    )
                    reply = (
                        label + ". Hanya mengubah notifikasi; auto-buy tetap seperti sebelumnya."
                    )
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
                else:
                    try:
                        symbols = list(dict.fromkeys(selected_symbol(s, selected) for s in args))
                        if not symbols:
                            raise ValueError("Gunakan coin dari /eligible atau ALL.")
                    except ValueError as exc:
                        reply = str(exc)
                if reply is None:
                    key = "watch" if command == "/watch" else "tradecoins"
                    control[key] = symbols
                    if key == "tradecoins":
                        state["pending"] = {}
                    label = "Coin gambar" if key == "watch" else "Coin entry demo baru"
                    reply = f"{label}: {', '.join(symbols) if symbols else 'semua eligible'}. "
                    reply += "Ini tidak membuat order atau menutup posisi yang ada."
            elif command in {
                "/status",
                "/health",
                "/coins",
                "/signals",
                "/chart",
                "/settings",
                "/eligible",
                "/intervals",
                "/analyze",
                "/why",
                "/position",
                "/strategies",
                "/techniques",
                "/plan",
                "/markets",
                "/coverage",
                "/coin",
            }:
                reply = (command, args)
            else:
                reply = "Perintah belum dikenali. Kirim /menu atau pilih Panduan dan bantuan."
        # Network/chart work happens after releasing the account transaction.
        if isinstance(reply, tuple):
            command, args = reply
            try:
                reply = self.read_command(command, args)
                if command == "/markets":
                    markup = keyboard(BROWSER_ROWS)
            except ValueError as exc:
                reply = str(exc)
            except Exception:
                reply = "Data/layanan belum tersedia. Coba lagi; detail jaringan tidak ditampilkan."
        if reply is None and markup is not None:
            reply = "Selesai. Pilih menu untuk lanjut."
        if reply:
            if markup is not None:
                self.notifier.send(reply[:3900], reply_markup=markup)
            else:
                self.notifier.send(reply[:3900])

    def read_command(self, command, args):
        account = self.account
        if command == "/markets":
            if len(args) > 2 or (len(args) == 2 and not args[1].isdigit()):
                return "Contoh: /markets USDT 1, /markets BTC 1 atau /markets ALL 1."
            result, page, quote = browse(
                self.market_charts.catalogue(),
                args[0] if args else "USDT",
                int(args[1]) if len(args) == 2 else 1,
            )
            with account.edit() as (_, state):
                state.setdefault("telegram_control", {})["market_browser"] = dict(
                    page=page, quote=quote
                )
            return result
        if command == "/coverage":
            return coverage(self.market_charts.catalogue(), account)
        if command == "/coin":
            if len(args) != 1:
                return "Contoh: /coin SOL atau /coin ETHBTC."
            return coin_info(self.market_charts.catalogue(), account, args[0])
        if command == "/strategies":
            return strategy_catalogue(account.config.strategy.name)
        if command in {"/techniques", "/plan"}:
            if not 1 <= len(args) <= 2:
                return f"Contoh: {command} SOL 15m. /strategies untuk penjelasan teknik."
            if command == "/plan":
                return preview(
                    account,
                    self.market_charts,
                    args[0],
                    args[1] if len(args) == 2 else account.config.demo.interval,
                )
            return review(
                self.market_charts,
                args[0],
                args[1] if len(args) == 2 else account.config.demo.interval,
                account.config.strategy,
            )
        if command == "/why":
            return why_report(account)
        if command == "/position":
            return position_report(account)
        if command in PANELS:
            return PANELS[command]
        if command in {"/guide", "/help"}:
            return GUIDE
        if command in {"/start", "/menu", "/demo"}:
            status = account.status()
            study = account.config.demo.analysis_only
            enabled = status.get("telegram_control", {}).get("auto", True)
            active = not study and enabled and not status["trading_halted"]
            mode = "BELAJAR CANDLE (tanpa order)" if study else "DEMO (saldo virtual)"
            intro = (
                f"Selamat datang! Mode: {mode}\n"
                f"Kondisi: {health_label(status['health'])} | "
                f"Auto entry diizinkan: {'YA' if active else 'TIDAK'}\n"
                "Live tidak diaktifkan oleh menu ini.\n\n"
            )
            if command == "/demo":
                return intro + (
                    "Pilih coin demo membatasi entry baru. Aktifkan auto-buy demo menunggu "
                    "sinyal yang lolos filter dan batas risiko. Jeda menghentikan entry baru; "
                    "posisi lama tetap dikelola. Akun belajar menolak aktivasi order."
                )
            return intro + (
                "Mulai dari Lihat candle, lalu ketik BTC 15m.\n"
                "Analisis coin membandingkan tren beberapa timeframe.\n"
                "Pasar dan coin untuk katalog; Strategi dan analisis untuk penilaian.\n"
                "Akun demo mengatur entry virtual. Notifikasi hanya mengatur pesan.\n"
                "Panduan dan bantuan menjelaskan cara pakai; /menu mengembalikan menu utama."
            )
        if command in {"/status", "/health"}:
            s = account.status()
            auto = not account.config.demo.analysis_only and s.get("telegram_control", {}).get(
                "auto", True
            )
            mode = "BELAJAR (tanpa order)" if account.config.demo.analysis_only else "DEMO VIRTUAL"
            return (
                f"{mode} | Kondisi: {health_label(s['health'])}\n"
                f"Auto entry: {'ON' if auto else 'OFF'} | "
                f"Risk halt: {'YA' if s['trading_halted'] else 'TIDAK'}\n"
                f"Equity virtual: {s['equity']:.4f} USDT | Trade selesai: {s['trade_count']}\n"
                f"WR: {metric(s['win_rate_pct'], '%')} | PF: {metric(s['profit_factor'])}\n"
                f"Expectancy: {metric(s['expectancy'])} USDT/trade\n"
                f"Posisi: {s['position']['symbol'] if s['position'] else 'belum ada'}\n"
                "ON bukan jaminan entry: data, sinyal dan risk tetap diperiksa.\n"
                "N/A = belum dapat dihitung. Pilih Kenapa belum buy? di Akun demo.\n"
                "Akun virtual ini tidak dihitung sebagai paper Testnet; live punya gate terpisah."
            )
        if command == "/settings":
            control = account.status().get("telegram_control", {})
            cfg = account.config.candle_alerts
            watch = control.get("watch", cfg.symbols)
            trade = control.get("tradecoins", [])
            mode = control.get("setups_only", cfg.setups_only)
            alerts = cfg.enabled and control.get("alerts", True)
            return (
                "PENGATURAN AKUN INI\n"
                f"Coin gambar: {', '.join(watch) if watch else 'semua eligible'}\n"
                f"Coin entry demo: {', '.join(trade) if trade else 'semua eligible'}\n"
                f"Gambar otomatis: {'ON' if alerts else 'OFF'}\n"
                f"Mode gambar: {'hanya setup' if mode else 'semua pengamatan'}\n"
                f"Jeda minimal semua gambar: {cfg.min_interval_seconds} detik\n"
                f"Jeda per coin: {cfg.symbol_cooldown_seconds} detik\n"
                "Notifikasi tidak mengubah coin trading. Lihat Status akun untuk auto entry."
            )
        if command == "/analyze":
            if not args:
                return "Contoh: /analyze bitcoin 1m 5m 15m (maksimal 4 interval)."
            return analysis_report(
                self.market_charts,
                args[0],
                args[1:] or account.config.candle_alerts.analysis_intervals,
                account.config.strategy,
            )
        if command == "/intervals":
            return "Interval chart: " + " ".join(INTERVALS) + "\n1m=menit; 1M=bulan."
        if command == "/coins":
            catalogue = self.market_charts.catalogue()
            query = normalize_coin(args[0]) if args and not args[0].isdigit() else ""
            page_arg = args[-1] if args and args[-1].isdigit() else "1"
            symbols = sorted(s for s in catalogue if query in s)
            page, pages = int(page_arg), max(1, math.ceil(len(symbols) / 40))
            if not 1 <= page <= pages:
                return f"Halaman 1-{pages}"
            return (
                f"Binance Spot {len(symbols)} pair | {page}/{pages} | chart only\n"
                + " ".join(symbols[(page - 1) * 40 : page * 40])
                + "\n/eligible untuk pair yang boleh dipilih trading."
            )
        if command == "/eligible":
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
                symbol = selected_symbol(args[0], {r["symbol"] for r in rows})
                rows = [r for r in rows if r["symbol"] == symbol]
            return (
                "\n".join(
                    f"{r['symbol']}: "
                    + {
                        "stale": "data kedaluwarsa",
                        "wait": "menunggu",
                        "setup_detected": "setup terdeteksi (belum order)",
                    }.get(r["assessment"], r["assessment"])
                    + f", skor aturan={r['signal_score']:.1f}"
                    for r in rows
                )
                or "Belum ada sinyal."
            )
        if not 1 <= len(args) <= 2:
            return "Contoh: /chart bitcoin 15m atau /chart ETHBTC 4h. /intervals untuk pilihan."
        interval = args[1] if len(args) == 2 else account.config.demo.interval
        market, frame = self.market_charts.candles(args[0], interval)
        png = candle_png(
            frame,
            market["symbol"],
            interval,
            account.config.strategy.ema_fast,
            account.config.strategy.ema_slow,
            account.config.candle_alerts.bars,
            quote_asset=market["quoteAsset"],
        )
        self.notifier.send_photo(
            png,
            f"{market['symbol']} | {interval} | closed {frame.close_time.iloc[-1].isoformat()}\n"
            "Grafik publik saja; tidak menambahkan coin ke trading/watchlist.",
        )
        return None
