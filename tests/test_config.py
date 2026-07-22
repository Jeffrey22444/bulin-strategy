from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from bbmr.config import TrailingStrategyConfig, load_config


CONFIG_PATH = Path("configs/strategy_bbmr_trailing_stop_v1.yaml")


def _data():
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_loads_active_trailing_strategy_config():
    config = load_config(CONFIG_PATH)

    assert config.strategy.name == "bbmr_trailing_stop_v1"
    assert config.rsi.method == "wilder"
    assert config.rsi.warmup_bars == 500
    assert config.rsi.oversold == 40
    assert config.rsi.overbought == 60
    assert config.rsi.adverse_slope_oversold == 32
    assert config.rsi.adverse_slope_overbought == 68
    assert config.entry_confirmation.require_15m_rsi_reversal is False
    assert config.trailing_stop.first_step_risk_reduction == 0.5
    assert config.adverse_slope_take_profit.special_near_middle_frac == 0.0
    assert config.adverse_slope_take_profit.exspecial_near_middle_frac == 0.5
    assert config.bandwidth_entry_guard.percentile_lookback == 120
    assert config.trend_riding.mode == "live"
    assert config.trend_riding.opposite_mr_takeover_mode == "live"
    assert config.trend_riding.pending_ttl_hours == 6


@pytest.mark.parametrize("strategy_name", [None, "bbmr_v3_2", "unknown"])
def test_load_config_rejects_missing_or_non_active_strategy_identity(tmp_path, strategy_name):
    data = _data()
    if strategy_name is None:
        data.pop("strategy")
    else:
        data["strategy"]["name"] = strategy_name
    path = tmp_path / "wrong_strategy.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(ValueError, match="strategy.name must be bbmr_trailing_stop_v1"):
        load_config(path)


@pytest.mark.parametrize(
    ("container", "field", "value"),
    [
        ("strategy", "mode", "research_backtest"),
        ("strategy", "allow_ai_signal", False),
        ("strategy", "allow_breakout_trade", False),
        ("strategy", "allow_live_trading", False),
        ("strategy", "allow_leverage", False),
        (None, "symbols", {"default": ["BTC"]}),
        (None, "timeframes", {"signal_tf": "1h"}),
        (None, "safety", {"stop_on_undefined_rule": True}),
    ],
)
def test_removed_inert_strategy_keys_are_rejected(container, field, value):
    data = _data()
    target = data if container is None else data[container]
    target[field] = value

    with pytest.raises(ValidationError, match=field):
        TrailingStrategyConfig.model_validate(data)


def test_trend_riding_defaults_to_off():
    data = _data()
    del data["trend_riding"]
    config = TrailingStrategyConfig.model_validate(data)
    assert config.trend_riding.mode == "off"
    assert config.trend_riding.opposite_mr_takeover_mode == "off"
    assert config.trend_riding.pending_ttl_hours == 6


def test_trend_takeover_defaults_to_off_when_legacy_fields_are_missing():
    data = _data()
    data["trend_riding"].pop("opposite_mr_takeover_mode")
    data["trend_riding"].pop("pending_ttl_hours")

    config = TrailingStrategyConfig.model_validate(data)

    assert config.trend_riding.opposite_mr_takeover_mode == "off"
    assert config.trend_riding.pending_ttl_hours == 6


@pytest.mark.parametrize(
    ("mode", "takeover_mode"),
    [
        ("off", "shadow"),
        ("off", "live"),
        ("shadow", "live"),
        ("invalid", "off"),
        ("live", "invalid"),
    ],
)
def test_trend_takeover_mode_combinations_fail_closed(mode, takeover_mode):
    data = _data()
    data["trend_riding"]["mode"] = mode
    data["trend_riding"]["opposite_mr_takeover_mode"] = takeover_mode

    with pytest.raises(ValidationError):
        TrailingStrategyConfig.model_validate(data)


@pytest.mark.parametrize("ttl", [0, -1, 1.5, True])
def test_trend_pending_ttl_must_be_a_positive_integer(ttl):
    data = _data()
    data["trend_riding"]["pending_ttl_hours"] = ttl

    with pytest.raises(ValidationError):
        TrailingStrategyConfig.model_validate(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("entry_pullback_pct", 0),
        ("entry_pullback_pct", 1),
        ("weakening_slope_threshold_pct", 0),
        ("weakening_slope_threshold_pct", 1),
        ("initial_stop_distance_pct", 0),
        ("initial_stop_distance_pct", 1),
    ],
)
def test_trend_riding_ratios_must_be_between_zero_and_one(field, value):
    data = _data()
    data["trend_riding"][field] = value
    with pytest.raises(ValidationError):
        TrailingStrategyConfig.model_validate(data)


@pytest.mark.parametrize(
    ("special", "weakening", "exspecial"),
    [(0.0018, 0.0018, 0.0025), (0.0019, 0.0018, 0.0025), (0.0009, 0.0025, 0.0025)],
)
def test_trend_weakening_threshold_must_be_between_slope_regimes(special, weakening, exspecial):
    data = _data()
    data["adverse_slope_take_profit"]["special_slope_threshold_pct"] = special
    data["trend_riding"]["weakening_slope_threshold_pct"] = weakening
    data["adverse_slope_take_profit"]["exspecial_slope_threshold_pct"] = exspecial
    with pytest.raises(ValidationError, match="weakening_slope_threshold_pct"):
        TrailingStrategyConfig.model_validate(data)


@pytest.mark.parametrize(("field", "value"), [("adverse_slope_oversold", -1), ("adverse_slope_overbought", 101)])
def test_adverse_slope_rsi_thresholds_must_be_between_0_and_100(field, value):
    data = _data()
    data["rsi"][field] = value
    with pytest.raises(ValidationError):
        TrailingStrategyConfig.model_validate(data)


def test_adverse_slope_rsi_thresholds_must_be_ordered():
    data = _data()
    data["rsi"]["adverse_slope_oversold"] = 68
    with pytest.raises(ValidationError, match="adverse_slope_oversold"):
        TrailingStrategyConfig.model_validate(data)


@pytest.mark.parametrize(("field", "value"), [("special_near_middle_frac", -0.01), ("exspecial_near_middle_frac", 1.01)])
def test_regime_near_middle_fractions_must_be_between_zero_and_one(field, value):
    data = _data()
    data["adverse_slope_take_profit"][field] = value
    with pytest.raises(ValidationError):
        TrailingStrategyConfig.model_validate(data)


def test_legacy_near_middle_fraction_is_rejected():
    data = _data()
    data["adverse_slope_take_profit"]["near_middle_frac"] = 0.0
    with pytest.raises(ValidationError, match="near_middle_frac"):
        TrailingStrategyConfig.model_validate(data)
