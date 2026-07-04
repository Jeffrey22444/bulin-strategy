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
