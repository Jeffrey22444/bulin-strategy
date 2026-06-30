import pandas as pd

from bbmr.config import load_config
from bbmr.signals import compute_signals, freeze_entry_reference


def _config(volume_filter=True, range_filter=True):
    config = load_config("configs/strategy_bbmr_v3_2.yaml")
    config.volume.entry_filter_enabled = volume_filter
    config.range_filter.entry_filter_enabled = range_filter
    return config


def test_long_signal_requires_all_filters():
    config = _config()
    data = pd.DataFrame(
        {
            "close": [89.0, 89.0],
            "lb": [90.0, 90.0],
            "ub": [110.0, 110.0],
            "rsi14": [29.0, 29.0],
            "volume_ratio": [1.0, config.volume.weak + 0.1],
            "range_allowed": [True, True],
            "lower_band_walking": [False, False],
            "upper_band_walking": [False, False],
            "rsi_flat_entry_block": [False, False],
        }
    )
    signals = compute_signals(data, config)
    assert bool(signals.loc[0, "long_signal_1h"]) is True
    assert bool(signals.loc[1, "long_signal_1h"]) is False


def test_long_signal_range_filter_blocks_when_enabled():
    config = _config()
    data = pd.DataFrame(
        {
            "close": [89.0],
            "lb": [90.0],
            "ub": [110.0],
            "rsi14": [29.0],
            "volume_ratio": [1.0],
            "range_allowed": [False],
            "lower_band_walking": [False],
            "upper_band_walking": [False],
            "rsi_flat_entry_block": [False],
        }
    )
    signals = compute_signals(data, config)
    assert bool(signals.loc[0, "long_signal_1h"]) is False


def test_long_signal_ignores_disabled_volume_filter():
    config = _config(volume_filter=False)
    data = pd.DataFrame(
        {
            "close": [89.0],
            "lb": [90.0],
            "ub": [110.0],
            "rsi14": [29.0],
            "volume_ratio": [config.volume.weak + 0.1],
            "range_allowed": [True],
            "lower_band_walking": [False],
            "upper_band_walking": [False],
            "rsi_flat_entry_block": [False],
        }
    )
    signals = compute_signals(data, config)
    assert bool(signals.loc[0, "long_signal_1h"]) is True


def test_long_signal_ignores_disabled_range_filter():
    config = _config(range_filter=False)
    data = pd.DataFrame(
        {
            "close": [89.0],
            "lb": [90.0],
            "ub": [110.0],
            "rsi14": [29.0],
            "volume_ratio": [1.0],
            "range_allowed": [False],
            "lower_band_walking": [False],
            "upper_band_walking": [False],
            "rsi_flat_entry_block": [False],
        }
    )
    signals = compute_signals(data, config)
    assert bool(signals.loc[0, "long_signal_1h"]) is True


def test_disabled_volume_and_range_filters_allow_long_and_short_signals():
    config = _config(volume_filter=False, range_filter=False)
    data = pd.DataFrame(
        {
            "close": [89.0, 111.0],
            "lb": [90.0, 90.0],
            "ub": [110.0, 110.0],
            "rsi14": [29.0, 71.0],
            "volume_ratio": [config.volume.weak + 0.1, config.volume.weak + 0.1],
            "range_allowed": [False, False],
            "lower_band_walking": [False, False],
            "upper_band_walking": [False, False],
            "rsi_flat_entry_block": [False, False],
        }
    )
    signals = compute_signals(data, config)
    assert bool(signals.loc[0, "long_signal_1h"]) is True
    assert bool(signals.loc[1, "short_signal_1h"]) is True


def test_short_signal_requires_all_filters():
    config = _config()
    data = pd.DataFrame(
        {
            "close": [111.0, 111.0],
            "lb": [90.0, 90.0],
            "ub": [110.0, 110.0],
            "rsi14": [71.0, 71.0],
            "volume_ratio": [1.0, 1.0],
            "range_allowed": [True, True],
            "lower_band_walking": [False, False],
            "upper_band_walking": [False, True],
            "rsi_flat_entry_block": [False, False],
        }
    )
    signals = compute_signals(data, config)
    assert bool(signals.loc[0, "short_signal_1h"]) is True
    assert bool(signals.loc[1, "short_signal_1h"]) is False


def test_same_bar_long_short_conflict_is_invalid():
    config = load_config("configs/strategy_bbmr_v3_2.yaml")
    data = pd.DataFrame(
        {
            "close": [100.0],
            "lb": [101.0],
            "ub": [99.0],
            "rsi14": [50.0],
            "volume_ratio": [1.0],
            "range_allowed": [True],
            "lower_band_walking": [False],
            "upper_band_walking": [False],
            "rsi_flat_entry_block": [False],
        }
    )
    config.rsi.oversold = 60
    config.rsi.overbought = 40
    signals = compute_signals(data, config)
    assert bool(signals.loc[0, "invalid_signal"]) is True
    assert bool(signals.loc[0, "long_signal_1h"]) is False
    assert bool(signals.loc[0, "short_signal_1h"]) is False


def test_entry_reference_freezes_signal_values():
    row = pd.Series({"lb": 90.0, "mb": 100.0, "ub": 110.0, "atr": 4.0}, name=pd.Timestamp("2026-01-01"))
    ref = freeze_entry_reference(row, "long")
    row["lb"] = 1.0
    assert ref.signal_time == pd.Timestamp("2026-01-01")
    assert ref.entry_reference_LB == 90.0
    assert ref.entry_reference_MB == 100.0
    assert ref.entry_reference_UB == 110.0
    assert ref.frozen_ATR == 4.0
    assert ref.signal_side == "long"
