from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from bbmr.config import StrategyConfig, TrailingStrategyConfig, load_config


CONFIG_PATH = Path("configs/strategy_bbmr_v3_2.yaml")
TRAILING_CONFIG_PATH = Path("configs/strategy_bbmr_trailing_stop_v1.yaml")


def _config_data():
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _trailing_config_data():
    with TRAILING_CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_loads_strategy_config():
    config = load_config(CONFIG_PATH)
    assert config.strategy.name == "bbmr_v3_2"
    assert config.strategy.allow_live_trading is False
    assert config.safety.allow_live_trading is False


def test_loads_trailing_strategy_config():
    config = load_config(TRAILING_CONFIG_PATH)
    assert config.strategy.name == "bbmr_trailing_stop_v1"
    assert 0 < config.trailing_stop.initial_stop_pct < 1
    assert config.rsi.method == "wilder"
    assert config.rsi.warmup_bars == 500


def test_trailing_stop_initial_stop_pct_defaults_to_2_percent():
    data = _trailing_config_data()
    del data["trailing_stop"]
    config = TrailingStrategyConfig.model_validate(data)
    assert config.trailing_stop.initial_stop_pct == 0.02


@pytest.mark.parametrize("initial_stop_pct", [0, -0.01, 1, 1.01])
def test_trailing_stop_initial_stop_pct_must_be_between_0_and_1(initial_stop_pct):
    data = _trailing_config_data()
    data["trailing_stop"]["initial_stop_pct"] = initial_stop_pct
    with pytest.raises(ValidationError):
        TrailingStrategyConfig.model_validate(data)


def test_missing_required_config_fails():
    data = _config_data()
    del data["bollinger"]
    with pytest.raises(ValidationError):
        StrategyConfig.model_validate(data)


def test_wrong_type_fails():
    data = _config_data()
    data["bollinger"]["bb_period"] = "twenty"
    with pytest.raises(ValidationError):
        StrategyConfig.model_validate(data)


def test_negative_bar_count_fails():
    data = _config_data()
    data["entry_confirmation"]["reentry_bars"] = -1
    with pytest.raises(ValidationError):
        StrategyConfig.model_validate(data)


def test_ratio_out_of_range_fails():
    data = _config_data()
    data["position_sizing"]["risk_per_trade"] = 2
    with pytest.raises(ValidationError):
        StrategyConfig.model_validate(data)


def test_phase1a_runtime_dependencies_stay_minimal():
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "SQLAlchemy" not in text
    assert "vectorbt" not in text
