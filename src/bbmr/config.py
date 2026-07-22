from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrategySection(StrictModel):
    name: str


class TrailingBollingerSection(StrictModel):
    bb_period: int = Field(gt=0)
    bb_std_mult: float = Field(gt=0)


class RsiSection(StrictModel):
    period: int = Field(gt=0)
    oversold: float = Field(ge=0, le=100)
    overbought: float = Field(ge=0, le=100)
    adverse_slope_oversold: float = Field(32, ge=0, le=100)
    adverse_slope_overbought: float = Field(68, ge=0, le=100)
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
        if self.adverse_slope_oversold >= self.adverse_slope_overbought:
            raise ValueError("rsi.adverse_slope_oversold must be below rsi.adverse_slope_overbought")
        return self


class TrailingEntryConfirmationSection(StrictModel):
    require_15m_rsi_reversal: bool = True


class TrailingStopSection(StrictModel):
    initial_stop_pct: float = Field(0.02, gt=0, lt=1)
    first_step_risk_reduction: float = Field(1.0, ge=0, le=1)


class AdverseSlopeTakeProfitSection(StrictModel):
    enabled: bool = False
    slope_n: int = Field(3, gt=0)
    special_slope_threshold_pct: float = Field(0.0009, ge=0)
    exspecial_slope_threshold_pct: float = Field(0.0025, ge=0)
    special_near_middle_frac: float = Field(0.0, ge=0, le=1)
    exspecial_near_middle_frac: float = Field(0.5, ge=0, le=1)

    @model_validator(mode="after")
    def validate_slope_thresholds(self) -> "AdverseSlopeTakeProfitSection":
        if self.special_slope_threshold_pct >= self.exspecial_slope_threshold_pct:
            raise ValueError("adverse_slope_take_profit.special_slope_threshold_pct must be below exspecial_slope_threshold_pct")
        return self


class BandwidthEntryGuardSection(StrictModel):
    enabled: bool = True
    percentile_lookback: int = Field(120, gt=3)
    high_percentile: float = Field(80, ge=0, le=100)
    min_1h_expansion_pct: float = Field(0.10, ge=0)


class TrendRidingSection(StrictModel):
    mode: str = "off"
    opposite_mr_takeover_mode: str = "off"
    pending_ttl_hours: int = Field(6, gt=0, strict=True)
    entry_pullback_pct: float = Field(0.01, gt=0, lt=1)
    weakening_slope_threshold_pct: float = Field(0.0018, gt=0, lt=1)
    initial_stop_distance_pct: float = Field(0.05, gt=0, lt=1)

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        if value not in {"off", "shadow", "live"}:
            raise ValueError("trend_riding.mode must be off, shadow, or live")
        return value

    @field_validator("opposite_mr_takeover_mode")
    @classmethod
    def validate_takeover_mode(cls, value: str) -> str:
        if value not in {"off", "shadow", "live"}:
            raise ValueError("trend_riding.opposite_mr_takeover_mode must be off, shadow, or live")
        return value

    @model_validator(mode="after")
    def validate_takeover_parent_mode(self) -> "TrendRidingSection":
        if self.opposite_mr_takeover_mode == "live" and self.mode != "live":
            raise ValueError("live opposite_mr_takeover_mode requires trend_riding.mode=live")
        if self.opposite_mr_takeover_mode == "shadow" and self.mode not in {"shadow", "live"}:
            raise ValueError("shadow opposite_mr_takeover_mode requires trend_riding.mode=shadow or live")
        return self


class CostsSection(StrictModel):
    taker_fee_bps: float = Field(ge=0)
    maker_fee_bps: float = Field(ge=0)
    slippage_bps: float = Field(ge=0)


class TrailingStrategyConfig(StrictModel):
    strategy: StrategySection
    bollinger: TrailingBollingerSection
    rsi: RsiSection
    entry_confirmation: TrailingEntryConfirmationSection = Field(default_factory=TrailingEntryConfirmationSection)
    trailing_stop: TrailingStopSection = Field(default_factory=TrailingStopSection)
    adverse_slope_take_profit: AdverseSlopeTakeProfitSection = Field(default_factory=AdverseSlopeTakeProfitSection)
    bandwidth_entry_guard: BandwidthEntryGuardSection = Field(default_factory=BandwidthEntryGuardSection)
    trend_riding: TrendRidingSection = Field(default_factory=TrendRidingSection)
    costs: CostsSection

    @model_validator(mode="after")
    def validate_active_strategy(self) -> "TrailingStrategyConfig":
        if self.strategy.name != "bbmr_trailing_stop_v1":
            raise ValueError("trailing config strategy.name must be bbmr_trailing_stop_v1")
        if not (
            self.adverse_slope_take_profit.special_slope_threshold_pct
            < self.trend_riding.weakening_slope_threshold_pct
            < self.adverse_slope_take_profit.exspecial_slope_threshold_pct
        ):
            raise ValueError(
                "adverse_slope_take_profit.special_slope_threshold_pct must be below "
                "trend_riding.weakening_slope_threshold_pct, which must be below "
                "adverse_slope_take_profit.exspecial_slope_threshold_pct"
            )
        return self


def load_config(path: str | Path) -> TrailingStrategyConfig:
    with Path(path).open("r", encoding="utf-8") as handle:
        data: Any = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError("strategy config must be a YAML mapping")
    strategy = data.get("strategy")
    if not isinstance(strategy, dict) or strategy.get("name") != "bbmr_trailing_stop_v1":
        raise ValueError("strategy.name must be bbmr_trailing_stop_v1")
    return TrailingStrategyConfig.model_validate(data)
