from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from bbmr.config import StrategyConfig, load_config


CONFIG_PATH = Path("configs/strategy_bbmr_v3_2.yaml")


def _config_data():
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_loads_strategy_config():
    config = load_config(CONFIG_PATH)
    assert config.strategy.name == "bbmr_v3_2"
    assert config.strategy.allow_live_trading is False
    assert config.safety.allow_live_trading is False


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
    assert "ccxt" not in text
