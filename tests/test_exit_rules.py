from types import SimpleNamespace

import pandas as pd
import pytest

from bbmr.config import load_config
from bbmr.exit_rules import (
    added_take_profit_price,
    early_fail_long,
    early_fail_short,
    fixed_sl_triggered,
    soft_fail_long,
    soft_fail_short,
    take_profit_price,
    take_profit_triggered,
)


def test_fixed_sl_and_take_profit_triggers():
    assert fixed_sl_triggered("long", low_5m=97, high_5m=103, fixed_sl=98) is True
    assert fixed_sl_triggered("short", low_5m=97, high_5m=103, fixed_sl=102) is True
    assert take_profit_price("long", 100, 90, 110, 0.5) == 105
    assert take_profit_price("short", 100, 90, 110, 0.5) == 95
    assert take_profit_triggered("long", high_5m=106, low_5m=99, tp_price=105) is True
    assert take_profit_triggered("short", high_5m=101, low_5m=94, tp_price=95) is True


def test_added_take_profit_price_uses_min_profit_buffer():
    assert added_take_profit_price("long", current_mb=100, weighted_avg_entry=104, one_r=10, min_profit_r_after_add=0.1) == 105
    assert added_take_profit_price("short", current_mb=100, weighted_avg_entry=96, one_r=10, min_profit_r_after_add=0.1) == 95


def test_soft_fail_long_short_rolling_behavior():
    close = pd.Series([100, 89, 88, 87])
    lb = pd.Series([90, 90, 90, 90])
    ub = pd.Series([110, 110, 110, 110])
    assert soft_fail_long(close, lb, 3).tolist() == [False, False, False, True]
    assert soft_fail_short(pd.Series([100, 111, 112, 113]), ub, 3).tolist() == [False, False, False, True]


def test_early_fail_respects_enabled_confirmations_and_min_count():
    config = load_config("configs/strategy_bbmr_v3_2.yaml")
    soft = pd.Series([True, True])
    bw = pd.Series([90, 10])
    volume = pd.Series([1.9, 1.9])
    walking = pd.Series([False, False])
    assert early_fail_long(soft, bw, volume, walking, config).tolist() == [True, False]
    assert early_fail_short(soft, bw, volume, walking, config).tolist() == [True, False]


def test_early_fail_rejects_impossible_min_confirmation_count():
    config = load_config("configs/strategy_bbmr_v3_2.yaml")
    config.early_fail = SimpleNamespace(
        min_confirmations=2,
        use_bw_expansion=True,
        use_shock_volume=False,
        use_band_walking=False,
    )
    with pytest.raises(ValueError, match="min_confirmations"):
        early_fail_long(pd.Series([True]), pd.Series([90]), pd.Series([1]), pd.Series([False]), config)
