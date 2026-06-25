import pandas as pd

from bbmr.config import load_config
from bbmr.market_state import (
    compute_lower_band_walking,
    compute_market_state,
    compute_range_allowed,
    compute_rsi_flat_entry_block,
    compute_rsi_flat_entry_released,
    compute_squeeze,
    compute_upper_band_walking,
)


def test_squeeze_expansion_range_boundaries():
    bw = pd.Series([19.0, 20.0, 80.0, 81.0, None])
    slope = pd.Series([0.0, 0.0, 0.006, 0.0, 0.0])
    assert compute_squeeze(bw, 20).tolist() == [True, False, False, False, False]
    allowed = compute_range_allowed(bw, 20, 80, slope, 0.006)
    assert allowed.tolist() == [False, True, True, False, False]


def test_range_disallows_nan_slope_warmup():
    allowed = compute_range_allowed(pd.Series([50.0]), 20, 80, pd.Series([None]), 0.006)
    assert bool(allowed.iloc[0]) is False


def test_lower_band_walking_covers_combined_and_outside_conditions():
    config = load_config("configs/strategy_bbmr_v3_2.yaml").band_walking
    close = pd.Series([90, 90, 90, 90, 90, 99, 90, 90, 90, 90, 90, 90], dtype=float)
    mb = pd.Series([100] * 12, dtype=float)
    lb = pd.Series([90] * 12, dtype=float)
    atr = pd.Series([10] * 12, dtype=float)
    result = compute_lower_band_walking(close, mb, lb, atr, config)
    assert bool(result.iloc[5]) is True
    assert bool(result.iloc[-1]) is True


def test_upper_band_walking_covers_combined_and_outside_conditions():
    config = load_config("configs/strategy_bbmr_v3_2.yaml").band_walking
    close = pd.Series([110, 110, 110, 110, 110, 101, 110, 110, 110, 110, 110, 110], dtype=float)
    mb = pd.Series([100] * 12, dtype=float)
    ub = pd.Series([110] * 12, dtype=float)
    atr = pd.Series([10] * 12, dtype=float)
    result = compute_upper_band_walking(close, mb, ub, atr, config)
    assert bool(result.iloc[5]) is True
    assert bool(result.iloc[-1]) is True


def test_rsi_flat_block_and_release():
    rsi = pd.Series([44, 45, 50, 51, 52, 53, 54, 55, 56])
    block = compute_rsi_flat_entry_block(rsi, low=45, high=55, bars=7)
    released = compute_rsi_flat_entry_released(rsi, low=45, high=55)
    assert bool(block.iloc[7]) is True
    assert released.tolist() == [True, False, False, False, False, False, False, False, True]


def test_market_state_warmup_does_not_create_tradable_signal():
    config = load_config("configs/strategy_bbmr_v3_2.yaml")
    indicators = pd.DataFrame(
        {
            "close": [100.0],
            "mb": [None],
            "lb": [None],
            "ub": [None],
            "atr": [None],
            "bw_percentile": [None],
            "mb_slope_pct": [None],
            "rsi14": [50.0],
            "volume_ratio": [1.0],
        }
    )
    state = compute_market_state(indicators, config)
    assert bool(state.loc[0, "range_allowed"]) is False
    assert bool(state.loc[0, "long_market_allowed"]) is False
    assert bool(state.loc[0, "short_market_allowed"]) is False
