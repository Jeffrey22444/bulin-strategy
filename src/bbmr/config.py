from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrategySection(StrictModel):
    name: str
    mode: str
    allow_ai_signal: bool = False
    allow_breakout_trade: bool = False
    allow_live_trading: bool = False
    allow_leverage: bool = False


class SymbolsSection(StrictModel):
    default: list[str]

    @field_validator("default")
    @classmethod
    def require_symbols(cls, value: list[str]) -> list[str]:
        if not value or any(not symbol.strip() for symbol in value):
            raise ValueError("symbols.default must contain non-empty symbols")
        return value


class TimeframesSection(StrictModel):
    signal_tf: str
    entry_confirm_tf: str
    execution_tf: str


class BollingerSection(StrictModel):
    bb_period: int = Field(gt=0)
    bb_std_mult: float = Field(gt=0)
    bandwidth_lookback: int = Field(gt=0)


class TrailingBollingerSection(StrictModel):
    bb_period: int = Field(gt=0)
    bb_std_mult: float = Field(gt=0)


class RsiSection(StrictModel):
    period: int = Field(gt=0)
    oversold: float = Field(ge=0, le=100)
    overbought: float = Field(ge=0, le=100)
    method: str = "sma"
    warmup_bars: int = Field(500, gt=0)

    @field_validator("method")
    @classmethod
    def validate_method(cls, value: str) -> str:
        if value not in {"sma", "wilder"}:
            raise ValueError("rsi.method must be sma or wilder")
        return value

    @model_validator(mode="after")
    def validate_order(self) -> "RsiSection":
        if self.oversold >= self.overbought:
            raise ValueError("rsi.oversold must be below rsi.overbought")
        return self


class RsiFlatEntryFilterSection(StrictModel):
    enabled: bool
    low: float = Field(ge=0, le=100)
    high: float = Field(ge=0, le=100)
    bars: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_order(self) -> "RsiFlatEntryFilterSection":
        if self.low >= self.high:
            raise ValueError("rsi_flat_entry_filter.low must be below high")
        return self


class AtrSection(StrictModel):
    period: int = Field(gt=0)


class StopLossSection(StrictModel):
    sl_atr_mult_mr: float = Field(gt=0)
    min_stop_pct: float = Field(gt=0, lt=1)


class TrailingStopSection(StrictModel):
    initial_stop_pct: float = Field(0.02, gt=0, lt=1)
    first_step_risk_reduction: float = Field(1.0, ge=0, le=1)


class BandwidthStateSection(StrictModel):
    squeeze_pct: float = Field(ge=0, le=100)
    high_pct: float = Field(ge=0, le=100)
    early_fail_bw_pct: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_order(self) -> "BandwidthStateSection":
        if self.squeeze_pct >= self.high_pct:
            raise ValueError("bandwidth_state.squeeze_pct must be below high_pct")
        return self


class VolumeSection(StrictModel):
    ma_period: int = Field(gt=0)
    weak: float = Field(gt=0)
    reject: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_order(self) -> "VolumeSection":
        if self.weak >= self.reject:
            raise ValueError("volume.weak must be below reject")
        return self


class MiddleBandSlopeSection(StrictModel):
    slope_n: int = Field(gt=0)
    slope_max: float = Field(ge=0, lt=1)


class BandWalkingSection(StrictModel):
    walk_bars: int = Field(gt=0)
    walk_min_side_bars: int = Field(gt=0)
    walk_min_near_bars: int = Field(gt=0)
    walk_min_outside_bars: int = Field(gt=0)
    walk_atr_dist: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> "BandWalkingSection":
        counts = (self.walk_min_side_bars, self.walk_min_near_bars, self.walk_min_outside_bars)
        if any(count > self.walk_bars for count in counts):
            raise ValueError("band walking minimum counts cannot exceed walk_bars")
        return self


class EntryConfirmationSection(StrictModel):
    reentry_bars: int = Field(gt=0)


class TrailingEntryConfirmationSection(StrictModel):
    require_15m_rsi_reversal: bool = True


class ProfitTargetSection(StrictModel):
    tp_mid_frac: float = Field(ge=0, le=1)
    min_profit_r_after_add: float = Field(ge=0)
    keep_dynamic_tp_without_breakeven_floor: bool


class PositionSizingSection(StrictModel):
    risk_per_trade: float = Field(gt=0, lt=1)


class AddPositionSection(StrictModel):
    enabled: bool
    max_add_count: int = Field(ge=0)
    add_size_frac: float = Field(gt=0)
    add_max_total_r: float = Field(gt=0)
    add_trigger_loss_r: float = Field(gt=0)


class SoftFailSection(StrictModel):
    bars: int = Field(gt=0)


class EarlyFailSection(StrictModel):
    min_confirmations: int = Field(gt=0)
    use_bw_expansion: bool
    use_shock_volume: bool
    use_band_walking: bool


class CostsSection(StrictModel):
    taker_fee_bps: float = Field(ge=0)
    maker_fee_bps: float = Field(ge=0)
    slippage_bps: float = Field(ge=0)


class StorageSection(StrictModel):
    backend: str
    sqlite_path: str


class SafetySection(StrictModel):
    no_hardcoded_strategy_params: bool
    stop_on_undefined_rule: bool
    allow_liquidation_price_check: bool = False
    allow_hyperliquid_testnet: bool = False
    allow_live_trading: bool = False


class StrategyConfig(StrictModel):
    strategy: StrategySection
    symbols: SymbolsSection
    timeframes: TimeframesSection
    bollinger: BollingerSection
    rsi: RsiSection
    rsi_flat_entry_filter: RsiFlatEntryFilterSection
    atr: AtrSection
    stop_loss: StopLossSection
    bandwidth_state: BandwidthStateSection
    volume: VolumeSection
    middle_band_slope: MiddleBandSlopeSection
    band_walking: BandWalkingSection
    entry_confirmation: EntryConfirmationSection
    profit_target: ProfitTargetSection
    position_sizing: PositionSizingSection
    add_position: AddPositionSection
    soft_fail: SoftFailSection
    early_fail: EarlyFailSection
    costs: CostsSection
    storage: StorageSection
    safety: SafetySection

    @model_validator(mode="after")
    def reject_live_execution_flags(self) -> "StrategyConfig":
        if self.strategy.allow_live_trading or self.safety.allow_live_trading:
            raise ValueError("live trading must stay disabled in Phase 1A")
        if self.strategy.allow_leverage or self.safety.allow_liquidation_price_check:
            raise ValueError("leverage and liquidation checks are out of Phase 1A scope")
        if self.safety.allow_hyperliquid_testnet:
            raise ValueError("Hyperliquid testnet is out of Phase 1A scope")
        return self


class TrailingStrategyConfig(StrictModel):
    strategy: StrategySection
    symbols: SymbolsSection
    timeframes: TimeframesSection
    bollinger: TrailingBollingerSection
    rsi: RsiSection
    entry_confirmation: TrailingEntryConfirmationSection = Field(default_factory=TrailingEntryConfirmationSection)
    trailing_stop: TrailingStopSection = Field(default_factory=TrailingStopSection)
    costs: CostsSection
    safety: SafetySection

    @model_validator(mode="after")
    def reject_live_execution_flags(self) -> "TrailingStrategyConfig":
        if self.strategy.name != "bbmr_trailing_stop_v1":
            raise ValueError("trailing config strategy.name must be bbmr_trailing_stop_v1")
        if self.strategy.allow_live_trading or self.safety.allow_live_trading:
            raise ValueError("live trading must stay disabled")
        if self.strategy.allow_leverage or self.safety.allow_liquidation_price_check:
            raise ValueError("leverage and liquidation checks are out of scope")
        if self.safety.allow_hyperliquid_testnet:
            raise ValueError("Hyperliquid testnet is out of scope")
        return self


def load_config(path: str | Path) -> StrategyConfig | TrailingStrategyConfig:
    with Path(path).open("r", encoding="utf-8") as handle:
        data: Any = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError("strategy config must be a YAML mapping")
    if data.get("strategy", {}).get("name") == "bbmr_trailing_stop_v1":
        return TrailingStrategyConfig.model_validate(data)
    return StrategyConfig.model_validate(data)
