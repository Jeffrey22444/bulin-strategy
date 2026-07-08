from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from bbmr.live.config import LiveConfig, load_live_config


CONFIG_PATH = Path("configs/live_hyperliquid_testnet.yaml")


def _data():
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_live_config_loads_trailing_strategy():
    config = load_live_config(CONFIG_PATH)
    assert config.strategy_config == "configs/strategy_bbmr_trailing_stop_v1.yaml"
    assert config.exchange.env == "testnet"
    assert config.execution.idle_1h_aligned_poll is True
    assert config.execution.idle_candle_grace_seconds == 10
    assert config.execution.idle_position_guard_seconds == 30
    assert config.execution.margin_fraction == 0.15
    assert config.execution.max_total_notional_fraction == 1.0
    assert config.execution.max_market_spread_bps == 50.0
    assert config.execution.max_entry_slippage_bps == 100.0
    assert config.execution.leverage == 3
    assert config.execution.adverse_slope_leverage == 2
    assert config.execution.adopt_manual_positions is True
    assert config.execution.manage_full_manual_added_size is True


def test_old_strategy_config_is_rejected():
    data = _data()
    data["strategy_config"] = "configs/strategy_bbmr_v3_2.yaml"
    with pytest.raises(ValidationError, match="strategy_config"):
        LiveConfig.model_validate(data)


def test_equivalent_trailing_strategy_paths_are_allowed():
    data = _data()
    data["strategy_config"] = str(Path("./configs/strategy_bbmr_trailing_stop_v1.yaml").resolve())
    assert LiveConfig.model_validate(data).strategy_config == data["strategy_config"]


def test_other_trailing_strategy_path_is_rejected(tmp_path):
    data = _data()
    copied = tmp_path / "strategy_bbmr_trailing_stop_v1.yaml"
    copied.write_text(Path("configs/strategy_bbmr_trailing_stop_v1.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    data["strategy_config"] = str(copied)
    with pytest.raises(ValidationError, match="strategy_config"):
        LiveConfig.model_validate(data)


@pytest.mark.parametrize("fraction", [0, -0.1, 1, 1.1])
def test_margin_fraction_must_be_between_0_and_1(fraction):
    data = _data()
    data["execution"]["margin_fraction"] = fraction
    with pytest.raises(ValidationError):
        LiveConfig.model_validate(data)


def test_leverage_fields_are_validated():
    data = _data()
    data["execution"]["adverse_slope_leverage"] = 0
    with pytest.raises(ValidationError):
        LiveConfig.model_validate(data)


@pytest.mark.parametrize("fraction", [0, -0.1])
def test_max_total_notional_fraction_must_be_positive(fraction):
    data = _data()
    data["execution"]["max_total_notional_fraction"] = fraction
    with pytest.raises(ValidationError):
        LiveConfig.model_validate(data)


def test_max_total_notional_fraction_defaults_to_one_for_old_configs():
    data = _data()
    data["execution"].pop("max_total_notional_fraction")
    assert LiveConfig.model_validate(data).execution.max_total_notional_fraction == 1.0


@pytest.mark.parametrize("field", ["max_market_spread_bps", "max_entry_slippage_bps"])
@pytest.mark.parametrize("value", [0, -1])
def test_execution_quality_bps_fields_must_be_positive(field, value):
    data = _data()
    data["execution"][field] = value
    with pytest.raises(ValidationError):
        LiveConfig.model_validate(data)


def test_execution_quality_bps_fields_default_for_old_configs():
    data = _data()
    data["execution"].pop("max_market_spread_bps")
    data["execution"].pop("max_entry_slippage_bps")
    config = LiveConfig.model_validate(data)
    assert config.execution.max_market_spread_bps == 50.0
    assert config.execution.max_entry_slippage_bps == 100.0


def test_mainnet_requires_config_allowance():
    data = _data()
    data["exchange"]["env"] = "mainnet"
    data["exchange"]["allow_mainnet"] = False
    with pytest.raises(ValidationError, match="mainnet"):
        LiveConfig.model_validate(data)


def test_strategy_add_is_rejected():
    data = _data()
    data["execution"]["allow_strategy_add"] = True
    with pytest.raises(ValidationError, match="strategy add"):
        LiveConfig.model_validate(data)


def test_idle_scheduler_fields_are_validated():
    data = _data()
    data["execution"]["idle_candle_grace_seconds"] = -1
    with pytest.raises(ValidationError):
        LiveConfig.model_validate(data)

    data = _data()
    data["execution"]["idle_position_guard_seconds"] = 0
    with pytest.raises(ValidationError):
        LiveConfig.model_validate(data)


def test_unknown_live_execution_field_is_rejected():
    data = _data()
    data["execution"]["unexpected"] = True
    with pytest.raises(ValidationError):
        LiveConfig.model_validate(data)
