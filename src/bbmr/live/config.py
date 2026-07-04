from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from bbmr.config import TrailingStrategyConfig, load_config

REQUIRED_STRATEGY_CONFIG = Path("configs/strategy_bbmr_trailing_stop_v1.yaml")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LiveExchangeSection(StrictModel):
    name: str
    env: str
    wallet_address_env: str
    private_key_env: str
    allow_mainnet: bool = False
    default_leverage: int = Field(ge=1)
    margin_mode: str
    enable_rate_limit: bool = True
    timeout_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_exchange(self) -> "LiveExchangeSection":
        if self.name != "hyperliquid":
            raise ValueError("only hyperliquid is supported")
        if self.env not in {"testnet", "mainnet"}:
            raise ValueError("exchange.env must be testnet or mainnet")
        if self.env == "mainnet" and not self.allow_mainnet:
            raise ValueError("mainnet requires exchange.allow_mainnet=true")
        return self


class LiveExecutionSection(StrictModel):
    allow_testnet_orders: bool = False
    margin_fraction: float = Field(gt=0, lt=1)
    leverage: int = Field(ge=1)
    allow_strategy_add: bool = False
    adopt_manual_positions: bool = True
    manage_full_manual_added_size: bool = True
    poll_seconds: int = Field(gt=0)
    idle_1h_aligned_poll: bool = True
    idle_candle_grace_seconds: int = Field(default=10, ge=0)
    idle_position_guard_seconds: int = Field(default=30, gt=0)
    maintain_exchange_stop: bool = True

    @model_validator(mode="after")
    def reject_strategy_add(self) -> "LiveExecutionSection":
        if self.allow_strategy_add:
            raise ValueError("strategy add-ons are out of scope")
        return self


class LiveSymbolsSection(StrictModel):
    default: list[str]


class LiveStorageSection(StrictModel):
    sqlite_path: str


class LiveConfig(StrictModel):
    strategy_config: str
    exchange: LiveExchangeSection
    execution: LiveExecutionSection
    symbols: LiveSymbolsSection
    storage: LiveStorageSection

    @model_validator(mode="after")
    def validate_strategy_config(self) -> "LiveConfig":
        if Path(self.strategy_config).resolve() != REQUIRED_STRATEGY_CONFIG.resolve():
            raise ValueError("live runner strategy_config must be configs/strategy_bbmr_trailing_stop_v1.yaml")
        strategy = load_config(self.strategy_config)
        if not isinstance(strategy, TrailingStrategyConfig):
            raise ValueError("live runner requires bbmr_trailing_stop_v1 strategy config")
        return self


def load_live_config(path: str | Path) -> LiveConfig:
    with Path(path).open("r", encoding="utf-8") as handle:
        data: Any = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError("live config must be a YAML mapping")
    return LiveConfig.model_validate(data)
