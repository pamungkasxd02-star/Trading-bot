import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from spotlab.config import GatesConfig
from spotlab.gates import assert_live_gate, paper_gate, research_gate
from spotlab.journal import TradingJournal


def write_research(path, *, status="RESEARCH_PASS") -> None:
    path.mkdir()
    (path / "validation_summary.json").write_text(
        json.dumps(
            {
                "status": status,
                "profit_factor": 1.5,
                "max_drawdown_pct": 4.0,
                "positive_windows_ratio": 1.0,
                "expectancy_per_trade": 0.05,
            }
        ),
        encoding="utf-8",
    )


def test_research_pass_does_not_bypass_empty_paper_gate(tmp_path) -> None:
    report = tmp_path / "report"
    write_research(report)
    journal = TradingJournal(tmp_path / "runtime.db")
    assert research_gate(report, GatesConfig()).passed
    assert not paper_gate(journal, GatesConfig()).passed
    with pytest.raises(RuntimeError, match="LIVE BLOCKED"):
        assert_live_gate(report, journal, GatesConfig(), "I_ACCEPT_REAL_MONEY_RISK")


def test_wrong_acknowledgement_blocks_live_even_if_other_gates_can_pass(tmp_path) -> None:
    report = tmp_path / "report"
    write_research(report)
    journal = TradingJournal(tmp_path / "runtime.db")
    with pytest.raises(RuntimeError, match="Acknowledgement"):
        assert_live_gate(report, journal, GatesConfig(), "wrong")


def test_journal_rejects_second_session_and_recovers_stale_one(tmp_path) -> None:
    journal = TradingJournal(tmp_path / "runtime.db")
    first = journal.start_session("paper", stale_seconds=30)
    with pytest.raises(RuntimeError, match="masih aktif"):
        journal.start_session("paper", stale_seconds=30)
    stale = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    with sqlite3.connect(journal.database) as connection:
        connection.execute("UPDATE sessions SET last_heartbeat=? WHERE id=?", (stale, first))
    second = journal.start_session("paper", stale_seconds=30)
    assert second != first


def test_runtime_health_tracks_fresh_and_stale_heartbeat(tmp_path) -> None:
    journal = TradingJournal(tmp_path / "runtime.db")
    session = journal.start_session("paper")
    assert journal.runtime_health("paper", stale_seconds=30)["healthy"]
    stale = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    with sqlite3.connect(journal.database) as connection:
        connection.execute("UPDATE sessions SET last_heartbeat=? WHERE id=?", (stale, session))
    health = journal.runtime_health("paper", stale_seconds=30)
    assert not health["healthy"]
    assert health["heartbeat_age_seconds"] >= 300


def test_runtime_backup_is_consistent(tmp_path) -> None:
    journal = TradingJournal(tmp_path / "runtime.db")
    session = journal.start_session("paper")
    output = journal.backup(tmp_path / "backups" / "runtime.db")
    restored = TradingJournal(output)
    assert restored.runtime_health("paper", stale_seconds=30)["healthy"]
    assert session == 1


def test_runtime_counts_heartbeat_not_wall_clock(tmp_path) -> None:
    journal = TradingJournal(tmp_path / "runtime.db")
    session = journal.start_session("paper")
    long_ago = (datetime.now(UTC) - timedelta(days=20)).isoformat()
    heartbeat = (datetime.now(UTC) - timedelta(days=19, hours=23)).isoformat()
    with sqlite3.connect(journal.database) as connection:
        connection.execute(
            "UPDATE sessions SET started_at=?, last_heartbeat=? WHERE id=?",
            (long_ago, heartbeat, session),
        )
    assert journal.paper_runtime_seconds() < 3700


def test_paper_drawdown_uses_recorded_account_equity(tmp_path) -> None:
    journal = TradingJournal(tmp_path / "runtime.db")
    session = journal.start_session("paper")
    journal.log_equity(session, "paper", 1_000.0, 1_000.0, 0.0, 0.0)
    journal.log_equity(session, "paper", 900.0, 700.0, 0.0, 200.0)
    result = paper_gate(journal, GatesConfig())
    assert result.metrics["starting_equity"] == 1_000.0
    assert result.metrics["final_equity"] == 900.0
    assert result.metrics["max_drawdown_pct"] == 10.0
