from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExchangeConfig(StrictModel):
    symbol: str = "BTCUSDT"
    interval: str = "4h"
    testnet: bool = True
    recv_window_ms: int = Field(5000, ge=1000, le=60000)
    rest_timeout_seconds: int = Field(15, ge=1, le=60)


class DataConfig(StrictModel):
    database: Path = Path("data/spotlab.db")
    history_months: int = Field(24, ge=6, le=120)


class StrategyConfig(StrictModel):
    name: str = "rule_based_v1"
    ema_fast: int = Field(20, ge=2)
    ema_slow: int = Field(50, ge=3)
    sma_trend: int = Field(100, ge=5)
    rsi_period: int = Field(14, ge=2)
    rsi_min: float = Field(48.0, ge=0, le=100)
    rsi_max: float = Field(72.0, ge=0, le=100)
    macd_fast: int = Field(12, ge=2)
    macd_slow: int = Field(26, ge=3)
    macd_signal: int = Field(9, ge=2)
    bb_period: int = Field(20, ge=3)
    bb_std: float = Field(2.0, gt=0)
    volume_period: int = Field(20, ge=2)
    min_confirmations: int = Field(3, ge=1, le=4)

    @model_validator(mode="after")
    def validate_periods(self) -> StrategyConfig:
        if self.ema_fast >= self.ema_slow:
            raise ValueError("ema_fast must be lower than ema_slow")
        if self.macd_fast >= self.macd_slow:
            raise ValueError("macd_fast must be lower than macd_slow")
        if self.rsi_min >= self.rsi_max:
            raise ValueError("rsi_min must be lower than rsi_max")
        return self


class BacktestConfig(StrictModel):
    initial_cash: float = Field(20.0, gt=0)
    fee_bps: float = Field(10.0, ge=0)
    slippage_bps: float = Field(5.0, ge=0)


class RiskConfig(StrictModel):
    risk_per_trade_pct: float = Field(1.0, gt=0, le=5)
    max_allocation_pct: float = Field(50.0, gt=0, le=100)
    max_position_notional_usdt: float | None = Field(default=None, gt=0)
    market_order_buffer_pct: float = Field(0.5, ge=0, le=5)
    stop_loss_pct: float = Field(3.0, gt=0, le=20)
    take_profit_pct: float = Field(6.0, gt=0, le=100)
    daily_loss_limit_pct: float = Field(3.0, gt=0, le=20)
    max_drawdown_pct: float = Field(10.0, gt=0, le=50)
    max_open_positions: int = Field(1, ge=1, le=1)


class GatesConfig(StrictModel):
    research_min_profit_factor: float = Field(1.05, gt=0)
    research_max_drawdown_pct: float = Field(10.0, gt=0, le=100)
    research_min_positive_windows_ratio: float = Field(0.75, gt=0, le=1)
    paper_min_days: int = Field(14, ge=7)
    paper_min_closed_trades: int = Field(20, ge=1)
    paper_min_profit_factor: float = Field(1.05, gt=0)
    paper_max_drawdown_pct: float = Field(10.0, gt=0, le=100)
    live_acknowledgement: str = "I_ACCEPT_REAL_MONEY_RISK"


class RuntimeConfig(StrictModel):
    database: Path = Path("data/runtime.db")
    kill_switch_file: Path = Path("data/KILL_SWITCH")
    session_stale_seconds: int = Field(180, ge=30, le=3600)
    telegram_enabled: bool = False


class AppConfig(StrictModel):
    exchange: ExchangeConfig = ExchangeConfig()
    data: DataConfig = DataConfig()
    strategy: StrategyConfig = StrategyConfig()
    backtest: BacktestConfig = BacktestConfig()
    risk: RiskConfig = RiskConfig()
    gates: GatesConfig = GatesConfig()
    runtime: RuntimeConfig = RuntimeConfig()


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    binance_api_key: str = ""
    binance_api_secret: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


def _resolve_paths(config: AppConfig, base: Path) -> AppConfig:
    data = config.model_dump()
    for section, key in (
        ("data", "database"),
        ("runtime", "database"),
        ("runtime", "kill_switch_file"),
    ):
        path = Path(data[section][key])
        data[section][key] = path if path.is_absolute() else base / path
    return AppConfig.model_validate(data)


def load_config(path: str | Path = "config/default.yaml") -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open(encoding="utf-8") as handle:
        raw: dict[str, Any] = yaml.safe_load(handle) or {}
    return _resolve_paths(AppConfig.model_validate(raw), config_path.parent.parent)
