"""Optional, outbound-only candle pictures for the learning/demo collector."""

from __future__ import annotations

import io
import json
import time
from datetime import UTC, datetime

import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from pydantic_settings import BaseSettings, SettingsConfigDict

from spotlab.notifier import PhotoDeliveryError
from spotlab.quality import interval_milliseconds


class TelegramSecrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


def candle_png(frame, symbol, interval, fast=9, slow=21, bars=60, quote_asset="USDT"):
    """Render supplied closed history; no network, balances or account identifiers."""
    if len(frame) < 2:
        raise ValueError("Need at least two closed candles")
    full = frame.sort_values("open_time").copy()
    full["fast"] = full.close.ewm(span=fast, adjust=False).mean()
    full["slow"] = full.close.ewm(span=slow, adjust=False).mean()
    tail = full.tail(bars).reset_index(drop=True)
    fig = Figure(figsize=(10, 6), dpi=120)
    FigureCanvasAgg(fig)
    price, volume = fig.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    for i, row in tail.iterrows():
        color = "#159b70" if row.close >= row.open else "#d94c4c"
        price.vlines(i, row.low, row.high, color=color, linewidth=1)
        height = abs(row.close - row.open)
        if height:
            price.add_patch(
                Rectangle(
                    (i - 0.32, min(row.open, row.close)),
                    0.64,
                    height,
                    facecolor=color,
                    edgecolor=color,
                )
            )
        else:
            price.hlines(row.close, i - 0.32, i + 0.32, color=color)
        volume.bar(i, row.volume, color=color, width=0.64)
    price.plot(tail.index, tail.fast, label=f"EMA {fast}", color="#386be0", linewidth=1)
    price.plot(tail.index, tail.slow, label=f"EMA {slow}", color="#b46c13", linewidth=1)
    price.legend(loc="upper left")
    price.set_ylabel(f"Price ({quote_asset})")
    volume.set_ylabel("Volume")
    ticks = sorted(set([0, len(tail) // 3, 2 * len(tail) // 3, len(tail) - 1]))
    volume.set_xticks(ticks, [tail.open_time.iloc[i].strftime("%m-%d\n%H:%M") for i in ticks])
    volume.set_xlabel("UTC / closed candles / educational setup, not an order")
    price.set_title(
        f"{symbol} | {interval} | close "
        f"{tail.close_time.iloc[-1].strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )
    price.grid(alpha=0.2)
    fig.tight_layout()
    output = io.BytesIO()
    fig.savefig(output, format="png")
    fig.clear()
    return output.getvalue()


class CandleAlerts:
    def __init__(self, account, notifier):
        self.account = account
        self.config = account.config.candle_alerts
        self.notifier = notifier

    def tick(self):
        """One attempt per tick. Reserve before send to avoid repeat floods on restart."""
        account, cfg = self.account, self.config
        if not cfg.enabled:
            return
        now = time.time()
        with account.edit() as (conn, state):
            delivery = state.setdefault("candle_alerts", {"cursor": 0, "next_at": 0, "symbols": {}})
            if not state.get("telegram_control", {}).get("alerts", True):
                return
            if now < delivery["next_at"]:
                return
            rows = conn.execute(
                "SELECT id,symbol,payload FROM demo_records WHERE kind='signal' "
                "AND id>? AND timestamp>=? ORDER BY id LIMIT 200",
                (
                    delivery["cursor"],
                    datetime.fromtimestamp(
                        now - account.config.runtime.max_signal_age_seconds, UTC
                    ).isoformat(),
                ),
            ).fetchall()
            selected = None
            for row in rows:
                delivery["cursor"] = row["id"]
                signal = json.loads(row["payload"])
                symbol = row["symbol"]
                age = now - signal["close_time"] / 1000
                if not 0 < age <= account.config.runtime.max_signal_age_seconds:
                    continue
                watch = state.get("telegram_control", {}).get("watch", cfg.symbols)
                if watch and symbol not in watch:
                    continue
                setups_only = state.get("telegram_control", {}).get("setups_only", cfg.setups_only)
                if setups_only and (not signal["enter_long"] or signal["exit_long"]):
                    continue
                if now - delivery["symbols"].get(symbol, 0) < cfg.symbol_cooldown_seconds:
                    continue
                delivery["next_at"] = now + cfg.min_interval_seconds
                delivery["symbols"][symbol] = now
                delivery["last_status"] = "attempting"
                selected = (symbol, signal)
                break
        if selected is None:
            return
        symbol, signal = selected
        retry_after = 0
        try:
            end = pd.Timestamp(signal["close_time"], unit="ms", tz="UTC")
            frame = account.market.load_candles(
                symbol,
                account.config.demo.interval,
                end=end.to_pydatetime(),
                limit=account.config.demo.warmup_bars,
            )
            frame = frame[frame.close_time <= end]
            spacing = pd.Timedelta(interval_milliseconds(account.config.demo.interval), unit="ms")
            if (
                frame.empty
                or frame.close_time.iloc[-1] != end
                or not frame.open_time.diff().dropna().eq(spacing).all()
            ):
                raise ValueError("Chart history incomplete")
            png = candle_png(
                frame,
                symbol,
                account.config.demo.interval,
                account.config.strategy.ema_fast,
                account.config.strategy.ema_slow,
                cfg.bars,
            )
            if (
                time.time() - signal["close_time"] / 1000
                > account.config.runtime.max_signal_age_seconds
            ):
                raise ValueError("Signal expired during render")
            checks = ", ".join(
                f"{key}={'OK' if value else 'WAIT'}"
                for key, value in signal.get("entry_checks", {}).items()
            )
            setup = signal["enter_long"] and not signal["exit_long"]
            caption = (
                f"{symbol} | {account.config.demo.interval} | {'SETUP' if setup else 'OBSERVE'}\n"
                f"{end.isoformat()}\nClose: {signal['close']:g} | "
                f"Score: {signal['signal_score']:.1f} (not WR)\n"
                f"{checks}\n{signal['signal_reason']}\n"
                "Demo/study only. Not an order or guaranteed profit."
            )
            self.notifier.send_photo(png, caption[:1000])
            status = "sent"
        except PhotoDeliveryError as exc:
            retry_after = exc.retry_after
            status = "delivery_failed"
        except Exception:
            # Never echo exception text: network exceptions can contain token-bearing URLs.
            status = "failed_or_skipped"
        with account.edit() as (conn, state):
            state["candle_alerts"]["last_status"] = status
            state["candle_alerts"]["next_at"] = max(
                state["candle_alerts"]["next_at"], time.time() + retry_after
            )
            account.record(conn, "event", symbol, {"event": "candle_alert", "status": status})
