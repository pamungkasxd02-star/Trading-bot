from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ExchangeConfig(StrictModel):
    symbol: str = "BTCUSDT"
    interval: str = "4h"
    testnet: bool = True
    recv_window_ms: int = Field(5000, ge=1000, le=60000)
    rest_timeout_seconds: int = Field(15, ge=1, le=60)


class DataConfig(StrictModel):
    database: Path = Path("data/spotlab.db")
    history_months: int = Field(24, ge=6, le=120)
    research_database: Path = Path("data/research.db")


class UniverseConfig(StrictModel):
    mode: Literal["single", "explicit", "all"] = "single"
    symbols: list[str] = Field(default_factory=list)
    quote_asset: Literal["USDT"] = "USDT"
    max_symbols: int | None = Field(30, ge=1, le=1500)
    min_quote_volume: float = Field(5_000_000, ge=0)
    max_spread_bps: float = Field(20, gt=0, le=200)
    min_history_days: int = Field(180, ge=30)
    excluded_bases: list[str] = Field(
        default_factory=lambda: ["USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "EUR", "USDE"]
    )

    @model_validator(mode="after")
    def validate_symbols(self) -> UniverseConfig:
        self.symbols = list(dict.fromkeys(item.upper() for item in self.symbols))
        self.excluded_bases = [item.upper() for item in self.excluded_bases]
        if self.mode == "explicit" and not self.symbols:
            raise ValueError("universe.symbols wajib diisi untuk mode explicit")
        if any(not item.endswith(self.quote_asset) for item in self.symbols):
            raise ValueError("Semua symbol harus menggunakan quote USDT")
        return self


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
    atr_period: int = Field(14, ge=2)
    adx_period: int = Field(14, ge=2)
    min_adx: float = Field(20, ge=0, le=60)
    min_atr_pct: float = Field(0.3, ge=0)
    max_atr_pct: float = Field(5, gt=0, le=30)
    min_relative_volume: float = Field(0.8, ge=0)
    daily_ema_period: int = Field(20, ge=2, le=100)
    pullback_rsi: float = Field(45, ge=20, le=65)
    pullback_lookback: int = Field(5, ge=1, le=30)
    regime_mode: Literal["trend", "range", "hybrid"] = "hybrid"
    fast_rsi_period: int = Field(3, ge=2, le=10)
    fast_rsi_oversold: float = Field(20, ge=5, le=40)
    range_entry_rsi: float = Field(35, ge=15, le=45)
    reversion_exit_rsi: float = Field(65, ge=50, le=85)
    range_max_adx: float = Field(22, ge=10, le=35)
    min_close_location: float = Field(0.6, ge=0.5, le=0.95)
    max_signal_candle_atr: float = Field(2.5, gt=1, le=5)
    max_daily_decline_pct: float = Field(0.25, ge=0, le=2)
    max_daily_distance_pct: float = Field(3, ge=0, le=10)
    max_pullback_distance_atr: float = Field(2, gt=0, le=5)
    min_reversion_score: float = Field(55, ge=0, le=100)

    @model_validator(mode="after")
    def validate_periods(self) -> StrategyConfig:
        if self.ema_fast >= self.ema_slow:
            raise ValueError("ema_fast must be lower than ema_slow")
        if self.macd_fast >= self.macd_slow:
            raise ValueError("macd_fast must be lower than macd_slow")
        if self.rsi_min >= self.rsi_max:
            raise ValueError("rsi_min must be lower than rsi_max")
        if self.min_atr_pct >= self.max_atr_pct:
            raise ValueError("min_atr_pct must be lower than max_atr_pct")
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
    stop_mode: Literal["fixed", "atr"] = "fixed"
    atr_stop_multiplier: float = Field(2.0, gt=0, le=10)
    atr_min_stop_pct: float = Field(1.0, gt=0, le=20)
    atr_max_stop_pct: float = Field(8.0, gt=0, le=20)
    reward_risk_ratio: float = Field(1.5, ge=1, le=5)
    cooldown_bars: int = Field(0, ge=0, le=100)
    max_candle_participation_pct: float = Field(0.1, gt=0, le=1)

    @model_validator(mode="after")
    def validate_stop_bounds(self) -> RiskConfig:
        if self.atr_min_stop_pct > self.atr_max_stop_pct:
            raise ValueError("atr_min_stop_pct harus <= atr_max_stop_pct")
        return self


class ResearchConfig(StrictModel):
    report_directory: Path = Path("reports/research")
    train_months: int = Field(9, ge=3)
    test_months: int = Field(3, ge=1)
    min_train_trades: int = Field(10, ge=1)
    min_oos_trades: int = Field(20, ge=1)
    min_folds: int = Field(3, ge=2)
    candidate_set: Literal["baseline", "regime"] = "baseline"
    evaluation_capitals: list[float] = Field(default_factory=list)
    target_win_rate_pct: float = Field(0, ge=0, le=90)

    @model_validator(mode="after")
    def validate_capitals(self) -> ResearchConfig:
        import math

        if any(not math.isfinite(value) or value <= 0 for value in self.evaluation_capitals):
            raise ValueError("evaluation_capitals harus positif dan finite")
        self.evaluation_capitals = sorted(set(self.evaluation_capitals))
        if len(self.evaluation_capitals) > 5:
            raise ValueError("Maksimal lima skala modal per eksperimen")
        return self


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
    history_bars: int = Field(1000, ge=200, le=5000)
    streams_per_connection: int = Field(100, ge=1, le=200)
    signal_batch_seconds: float = Field(3, ge=0.1, le=10)
    max_signal_age_seconds: int = Field(120, ge=30, le=900)
    max_signal_price_drift_bps: float = Field(50, gt=0, le=500)
    supervision_seconds: int = Field(15, ge=5, le=30)


class DemoConfig(StrictModel):
    database: Path = Path("data/learning.db")
    name: str = Field("Belajar", min_length=1, max_length=60)
    initial_cash: float = Field(1000, gt=0)
    interval: Literal["1m", "3m", "5m", "15m", "30m", "1h", "4h"] = "1m"
    warmup_bars: int = Field(500, ge=200, le=5000)
    quote_seconds: int = Field(15, ge=5, le=60)
    repair_seconds: int = Field(300, ge=60, le=3600)
    kill_switch_file: Path = Path("data/DEMO_STOP_TRADING")


class AppConfig(StrictModel):
    exchange: ExchangeConfig = ExchangeConfig()
    data: DataConfig = DataConfig()
    universe: UniverseConfig = UniverseConfig()
    strategy: StrategyConfig = StrategyConfig()
    backtest: BacktestConfig = BacktestConfig()
    risk: RiskConfig = RiskConfig()
    gates: GatesConfig = GatesConfig()
    runtime: RuntimeConfig = RuntimeConfig()
    research: ResearchConfig = ResearchConfig()
    demo: DemoConfig = DemoConfig()

    @model_validator(mode="after")
    def validate_storage(self) -> AppConfig:
        if self.data.database == self.data.research_database:
            raise ValueError("Database riset dan execution harus terpisah")
        if self.demo.database.resolve() in {
            self.data.database.resolve(),
            self.data.research_database.resolve(),
            self.runtime.database.resolve(),
        }:
            raise ValueError("Database demo harus terpisah dari database riset/execution")
        return self


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
        ("data", "research_database"),
        ("research", "report_directory"),
        ("runtime", "database"),
        ("runtime", "kill_switch_file"),
        ("demo", "database"),
        ("demo", "kill_switch_file"),
    ):
        path = Path(data[section][key])
        data[section][key] = path if path.is_absolute() else base / path
    return AppConfig.model_validate(data)


def load_config(path: str | Path = "config/default.yaml") -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open(encoding="utf-8") as handle:
        raw: dict[str, Any] = yaml.safe_load(handle) or {}
    return _resolve_paths(AppConfig.model_validate(raw), config_path.parent.parent)
