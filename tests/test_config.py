from pathlib import Path

import pytest
from pydantic import ValidationError

from spotlab.config import AppConfig, StrategyConfig, load_config


def test_default_config_loads_and_resolves_paths() -> None:
    config = load_config("config/default.yaml")
    assert config.exchange.symbol == "BTCUSDT"
    assert config.exchange.interval == "4h"
    assert config.data.database.is_absolute()


def test_strategy_rejects_inverted_periods() -> None:
    with pytest.raises(ValidationError):
        StrategyConfig(ema_fast=50, ema_slow=20)


def test_config_forbids_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("unknown: true\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(path)


def test_live_defaults_are_safely_testnet() -> None:
    config = AppConfig()
    assert config.exchange.testnet is True
    assert config.risk.max_open_positions == 1
