from datetime import UTC, datetime

import pandas as pd
import pytest

from spotlab.data import MarketDataStore
from spotlab.research.dataset import audit, collect


def test_audit_requires_complete_contiguous_closed_range():
    start, end = datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)
    times = pd.date_range(start, periods=24, freq="h")
    frame = pd.DataFrame(
        dict(
            open_time=times,
            close_time=times + pd.Timedelta(3599999, unit="ms"),
            open=10.0,
            high=11.0,
            low=9.0,
            close=10.0,
            volume=1.0,
        )
    )
    assert audit(frame, start, end, "1h")["complete"]
    assert not audit(frame.drop(4), start, end, "1h")["complete"]
    assert not audit(frame.iloc[1:], start, end, "1h")["complete"]
    frame.loc[0, "close_time"] = frame.loc[0, "open_time"] + pd.Timedelta(1, unit="s")
    assert not audit(frame, start, end, "1h")["complete"]


def test_collection_isolates_failures_and_cannot_mark_them_verified(tmp_path):
    class Client:
        base_url = "https://api.binance.com/api"

        def exchange_info(self, symbol):
            raise RuntimeError("do not publish raw network details")

    store = MarketDataStore(tmp_path / "research.db")
    report = collect(
        Client(),
        store,
        ["BTCUSDT", "ETHUSDT"],
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
        "1h",
        tmp_path / "coverage.json",
    )
    assert len(report["symbols"]) == 2
    assert not store.metadata("market")["exchange_verified"]
    assert "do not publish" not in (tmp_path / "coverage.json").read_text()
    assert not store.metadata("universe")["symbols"]


def test_unproven_existing_data_cannot_be_relabelled_official(tmp_path):
    from types import SimpleNamespace

    store = MarketDataStore(tmp_path / "research.db")
    store.upsert_klines("BTCUSDT", "1h", [[1, 10, 11, 9, 10, 1, 3599999, 10, 1]])
    with pytest.raises(ValueError, match="database dataset baru"):
        collect(
            SimpleNamespace(base_url="official"),
            store,
            ["BTCUSDT"],
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
            "1h",
            tmp_path / "report.json",
        )


def test_restart_fetches_only_missing_suffix(tmp_path, monkeypatch):
    from decimal import Decimal
    from types import SimpleNamespace

    from spotlab.models import SymbolRules

    store = MarketDataStore(tmp_path / "research.db")
    store.set_metadata("dataset_provenance", {"source": "official"})
    start, end = datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC)
    start_ms = int(start.timestamp() * 1000)

    def rows(first, last):
        return [
            [start_ms + i * 3600000, 10, 11, 9, 10, 1, start_ms + (i + 1) * 3600000 - 1, 10, 1]
            for i in range(first, last)
        ]

    store.upsert_klines("BTCUSDT", "1h", rows(0, 12))
    calls = []

    def fetch(client, target, symbol, interval, left, right):
        calls.append((left, right))
        target.upsert_klines(symbol, interval, rows(12, 24))

    monkeypatch.setattr("spotlab.research.dataset.fetch_history", fetch)
    monkeypatch.setattr(
        "spotlab.research.dataset.parse_symbol_rules",
        lambda info, symbol: SymbolRules(
            symbol, Decimal(".001"), Decimal("1000"), Decimal(".001"), Decimal(".01"), Decimal("5")
        ),
    )
    client = SimpleNamespace(base_url="official", exchange_info=lambda symbol: {})
    output = tmp_path / "coverage.json"
    result = collect(client, store, ["BTCUSDT"], start, end, "1h", output)
    assert result["symbols"]["BTCUSDT"]["complete"]
    assert calls[0][0] == datetime(2025, 1, 1, 12, tzinfo=UTC)
    collect(client, store, ["BTCUSDT"], start, end, "1h", output)
    assert len(calls) == 1
