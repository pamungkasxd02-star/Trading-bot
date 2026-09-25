from types import SimpleNamespace

import pandas as pd
import pytest

from spotlab.research.batch import connection, plan, run, runner_lock, summary


def test_thousands_of_jobs_are_idempotent_not_counted_as_downloads(tmp_path):
    conn = connection(tmp_path)
    symbols = [f"TOKEN{i}USDT" for i in range(100)]
    start, end = pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2026-01-01", tz="UTC")
    assert plan(conn, symbols, ["15m", "1h", "4h"], start, end) == 3600
    assert plan(conn, symbols, ["15m", "1h", "4h"], start, end) == 0
    result = summary(conn)
    assert result["jobs"] == 3600
    assert result["by_state"] == [{"state": "pending", "jobs": 3600, "rows": 0}]
    assert result["planned_candles"] == 100 * (35040 + 8760 + 2190)
    conn.close()


def test_budget_exhaustion_returns_job_to_pending_and_crash_recovers(tmp_path, monkeypatch):
    conn = connection(tmp_path)
    plan(
        conn,
        ["BTCUSDT"],
        ["1h"],
        pd.Timestamp("2025-01-01", tz="UTC"),
        pd.Timestamp("2025-03-01", tz="UTC"),
    )
    client = SimpleNamespace(remaining=1)

    def exhausted(*args, **kwargs):
        client.remaining = 0
        return {"symbols": {"BTCUSDT": {"complete": False, "error_type": "CallBudgetExceeded"}}}

    monkeypatch.setattr("spotlab.research.batch.collect", exhausted)
    assert run(tmp_path, conn, 2, client)["by_state"][0]["state"] == "pending"
    with conn:
        conn.execute("UPDATE jobs SET state='running'")
    monkeypatch.setattr(
        "spotlab.research.batch.collect",
        lambda *a, **k: {"symbols": {"BTCUSDT": {"complete": True, "rows": 744}}},
    )
    client.remaining = 10
    result = run(tmp_path, conn, 1, client)
    assert {r["state"]: r["jobs"] for r in result["by_state"]} == {"complete": 1, "pending": 1}
    conn.close()


def test_runner_lock_prevents_concurrent_recovery(tmp_path):
    with (
        runner_lock(tmp_path),
        pytest.raises(RuntimeError, match="masih aktif"),
        runner_lock(tmp_path),
    ):
        pass


def test_plan_rejects_partial_month_and_unknown_intervals(tmp_path):
    conn = connection(tmp_path)
    for start, interval in [("2025-01-02", "1h"), ("2025-01-01", "2m")]:
        with pytest.raises(ValueError):
            plan(
                conn,
                ["BTCUSDT"],
                [interval],
                pd.Timestamp(start, tz="UTC"),
                pd.Timestamp("2025-02-01", tz="UTC"),
            )


def test_assemble_reaudits_shards_and_rejects_existing_destination(tmp_path):
    from decimal import Decimal

    from spotlab.data import MarketDataStore
    from spotlab.models import SymbolRules
    from spotlab.research.batch import assemble

    conn = connection(tmp_path)
    start, end = pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2025-02-01", tz="UTC")
    plan(conn, ["BTCUSDT"], ["1h"], start, end)
    output = tmp_path / "joined.db"
    with pytest.raises(ValueError, match="harus complete"):
        assemble(tmp_path, conn, "1h", output)
    job = conn.execute("SELECT * FROM jobs").fetchone()
    source = MarketDataStore(tmp_path / "parts" / (job["id"] + ".db"))
    base = int(start.timestamp() * 1000)
    source.upsert_klines(
        "BTCUSDT",
        "1h",
        [
            [base + i * 3600000, 10, 11, 9, 10, 1, base + (i + 1) * 3600000 - 1, 10, 1]
            for i in range(744)
        ],
    )
    source.save_symbol_rules(
        SymbolRules(
            "BTCUSDT",
            Decimal(".001"),
            Decimal("1000"),
            Decimal(".001"),
            Decimal(".01"),
            Decimal("5"),
        )
    )
    source.set_metadata(
        "market", dict(source="https://api.binance.com/api", exchange_verified=True)
    )
    with conn:
        conn.execute("UPDATE jobs SET state='complete'")
    assert assemble(tmp_path, conn, "1h", output) == str(output)
    assert len(MarketDataStore(output).load_candles("BTCUSDT", "1h")) == 744
    with pytest.raises(ValueError, match="sudah ada"):
        assemble(tmp_path, conn, "1h", output)
