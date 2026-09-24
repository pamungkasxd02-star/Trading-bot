import io
import json
import time
from urllib.error import HTTPError, URLError

import pandas as pd
import pytest

from spotlab.candle_alerts import CandleAlerts, candle_png
from spotlab.config import AppConfig, CandleAlertsConfig, DemoConfig
from spotlab.learning import DemoAccount
from spotlab.notifier import PhotoDeliveryError, TelegramNotifier


@pytest.fixture
def alert_account(tmp_path):
    cfg = AppConfig(
        demo=DemoConfig(database=tmp_path / "account.db"),
        candle_alerts=CandleAlertsConfig(enabled=True),
    )
    cfg.runtime.max_signal_age_seconds = 900
    account = DemoAccount(cfg)
    account.start()
    end = int(time.time() // 60) * 60000
    rows = [
        [
            end - (60 - i) * 60000,
            100 + i,
            102 + i,
            99 + i,
            101 + i,
            100,
            end - (59 - i) * 60000 - 1,
            10000,
            5,
        ]
        for i in range(60)
    ]
    account.market.upsert_klines("BTCUSDT", "1m", rows)
    signal = dict(
        close_time=end - 1,
        enter_long=True,
        exit_long=False,
        close=160,
        signal_score=70,
        signal_reason="test:recovery",
        entry_checks={"trend": True},
    )
    with account.edit() as (conn, _):
        account.record(conn, "signal", "BTCUSDT", signal)
    yield account
    account.stop()


class Capture:
    def __init__(self):
        self.sent = []

    def send_photo(self, png, caption):
        self.sent.append((png, caption))


def test_picture_delivery_deduplicates_and_survives_worker_restart(alert_account):
    client = Capture()
    CandleAlerts(alert_account, client).tick()
    CandleAlerts(alert_account, client).tick()
    assert len(client.sent) == 1
    png, caption = client.sent[0]
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert "BTCUSDT" in caption and "trend=OK" in caption
    assert "1000" not in caption  # no virtual account balance
    assert alert_account.status()["candle_alerts"]["last_status"] == "sent"


def test_stale_signal_is_not_sent(alert_account):
    with alert_account.connect() as conn:
        payload = json.loads(
            conn.execute("SELECT payload FROM demo_records WHERE kind='signal'").fetchone()[0]
        )
        payload["close_time"] -= 3600000
        conn.execute(
            "UPDATE demo_records SET payload=? WHERE kind='signal'", (json.dumps(payload),)
        )
    client = Capture()
    CandleAlerts(alert_account, client).tick()
    assert client.sent == []


def test_future_candles_are_not_rendered(alert_account, monkeypatch):
    from spotlab import candle_alerts

    now_ms = int(time.time() * 1000)
    alert_account.market.upsert_klines(
        "BTCUSDT", "1m", [[now_ms, 1, 2, 1, 2, 1, now_ms + 59999, 1, 1]]
    )
    captured = []
    monkeypatch.setattr(
        candle_alerts, "candle_png", lambda frame, *args: captured.append(frame) or b"png"
    )
    CandleAlerts(alert_account, Capture()).tick()
    assert len(captured[0]) == 60
    assert captured[0].close_time.max() < pd.Timestamp.now(tz="UTC")


def test_rate_limit_persists_delay_without_secret_error_log(alert_account):
    class Limited:
        def send_photo(self, *args):
            raise PhotoDeliveryError(300)

    CandleAlerts(alert_account, Limited()).tick()
    status = alert_account.status()
    assert status["candle_alerts"]["last_status"] == "delivery_failed"
    assert status["candle_alerts"]["next_at"] > time.time() + 290
    assert status["process_alive"]


def test_transport_multipart_and_redacted_failure(monkeypatch):
    from spotlab import notifier

    captured = []

    def success(request, timeout):
        captured.append(request)
        return io.BytesIO(b'{"ok":true}')

    monkeypatch.setattr(notifier, "urlopen", success)
    client = TelegramNotifier("sample-token", "sample-chat", True)
    client.send_photo(b"png-data", "Candle setup")
    assert b'filename="candle.png"' in captured[0].data
    assert b"png-data" in captured[0].data
    assert b"protect_content" in captured[0].data

    def fail(*args, **kwargs):
        raise URLError("sample-token sample-chat")

    monkeypatch.setattr(notifier, "urlopen", fail)
    with pytest.raises(PhotoDeliveryError) as error:
        client.send_photo(b"png", "caption")
    assert "sample-token" not in str(error.value)
    assert "sample-chat" not in str(error.value)

    def rate_limit(*args, **kwargs):
        raise HTTPError(
            "private-url", 429, "limited", {}, io.BytesIO(b'{"parameters":{"retry_after":120}}')
        )

    monkeypatch.setattr(notifier, "urlopen", rate_limit)
    with pytest.raises(PhotoDeliveryError) as error:
        client.send_photo(b"png", "caption")
    assert error.value.retry_after == 120


def test_candle_preview_rejects_empty_history():
    with pytest.raises(ValueError, match="two closed candles"):
        candle_png(pd.DataFrame(), "BTCUSDT", "1m")
