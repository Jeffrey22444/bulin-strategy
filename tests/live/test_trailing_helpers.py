from types import SimpleNamespace

import pandas as pd
import pytest

from bbmr.trailing import (
    _confirm_setup,
    _create_setup,
    _entry_signal,
    _entry_extreme_signal,
    _entry_rsi_direction_signal,
    _initial_stop_loss,
    adverse_slope_state,
    bandwidth_state,
    entry_risk_state,
    evaluate_setup,
    Setup,
    trend_episode,
    trend_pending_cancel_reason,
)
from bbmr.trailing_features import build_trailing_features


def _ts(value: str) -> pd.Timestamp:
    return pd.Timestamp(value, tz="UTC")


def _frame(index, rows):
    return pd.DataFrame(rows, index=[_ts(value) for value in index])


def _trend_features(middles, closes=None):
    closes = closes or middles
    return pd.DataFrame(
        {"mb": middles, "close": closes},
        index=pd.date_range("2026-01-01", periods=len(middles), freq="h", tz="UTC"),
    )


@pytest.mark.parametrize(
    ("middles", "closes", "side", "frozen_close", "limit_price"),
    [
        ([100, 100, 100, 100, 100.3], [100, 100, 100, 100, 200], "long", 200, 198),
        ([100, 100, 100, 100, 99.7], [100, 100, 100, 100, 80], "short", 80, 80.8),
    ],
)
def test_trend_episode_freezes_first_canonical_exspecial_close(middles, closes, side, frozen_close, limit_price):
    episode = trend_episode(_trend_features(middles, closes), _ts("2026-01-01 05:00"), 3, 0.0025, 0.01)

    assert episode.side == side
    assert episode.episode_bucket == _ts("2026-01-01 04:00")
    assert episode.current_bucket == episode.episode_bucket
    assert episode.first_slope == pytest.approx(0.003 if side == "long" else -0.003)
    assert episode.frozen_close == frozen_close
    assert episode.limit_price == pytest.approx(limit_price)
    assert episode.row_1h["close"] == frozen_close


def test_trend_episode_rebuilds_same_continuous_episode_without_moving_frozen_price():
    features = _trend_features([100, 100, 100, 100, 100.3, 100.4], [100, 100, 100, 100, 200, 250])

    episode = trend_episode(features, _ts("2026-01-01 06:00"), 3, 0.0025, 0.01)

    assert episode.episode_bucket == _ts("2026-01-01 04:00")
    assert episode.current_bucket == _ts("2026-01-01 05:00")
    assert episode.frozen_close == 200
    assert episode.limit_price == 198
    assert episode.current_slope == pytest.approx(0.004)


def test_trend_episode_direct_reversal_starts_a_new_opposite_episode():
    features = _trend_features([100, 100, 100, 100, 100.3, 99.7], [100, 100, 100, 100, 200, 80])

    episode = trend_episode(features, _ts("2026-01-01 06:00"), 3, 0.0025, 0.01)

    assert episode.side == "short"
    assert episode.episode_bucket == _ts("2026-01-01 05:00")
    assert episode.frozen_close == 80
    assert episode.limit_price == pytest.approx(80.8)


def test_trend_episode_uses_only_completed_1h_rows():
    features = _trend_features([100, 100, 100, 100, 100.3, 99.7], [100, 100, 100, 100, 200, 80])

    episode = trend_episode(features, _ts("2026-01-01 05:30"), 3, 0.0025, 0.01)

    assert episode.side == "long"
    assert episode.current_bucket == _ts("2026-01-01 04:00")
    assert episode.frozen_close == 200


@pytest.mark.parametrize(
    ("middles", "slope_n", "threshold", "pullback"),
    [
        ([100, 100, 100, 100, float("nan")], 3, 0.0025, 0.01),
        ([100, 100, 100, 100, 100.3], 0, 0.0025, 0.01),
        ([100, 100, 100, 100, 100.3], 3, None, 0.01),
        ([100, 100, 100, 100, 100.3], 3, 0, 0.01),
        ([100, 100, 100, 100, 100.3], 3, 0.0025, 0),
        ([100, 100, 100, 100, 100.3], 3, 0.0025, 1),
    ],
)
def test_trend_episode_invalid_inputs_fail_closed(middles, slope_n, threshold, pullback):
    assert trend_episode(_trend_features(middles), _ts("2026-01-01 05:00"), slope_n, threshold, pullback) is None


@pytest.mark.parametrize(
    ("side", "signed_slope", "reason"),
    [
        ("long", 0.0025, None),
        ("long", 0.0009, None),
        ("long", 0.000899, "directional_slope_normal"),
        ("long", -0.0001, "directional_slope_normal"),
        ("short", -0.0025, None),
        ("short", -0.0009, None),
        ("short", -0.000899, "directional_slope_normal"),
        ("short", 0.0001, "directional_slope_normal"),
    ],
)
def test_trend_pending_cancel_reason_uses_directional_normal_floor(side, signed_slope, reason):
    assert trend_pending_cancel_reason(side, signed_slope, 0.0009) == reason


@pytest.mark.parametrize(
    ("side", "signed_slope"),
    [
        ("invalid", 0.1),
        ("long", None),
        ("long", float("nan")),
        ("short", float("inf")),
    ],
)
def test_trend_pending_cancel_reason_invalid_inputs_fail_closed(side, signed_slope):
    assert trend_pending_cancel_reason(side, signed_slope, 0.0009) == "invalid_pending_state"


@pytest.mark.parametrize(
    ("side", "close", "middle", "reason"),
    [
        ("long", 100, 100, "completed_1h_middle_invalidated"),
        ("long", 99, 100, "completed_1h_middle_invalidated"),
        ("long", 101, 100, None),
        ("short", 100, 100, "completed_1h_middle_invalidated"),
        ("short", 101, 100, "completed_1h_middle_invalidated"),
        ("short", 99, 100, None),
    ],
)
def test_trend_pending_cancel_reason_uses_completed_close_middle(side, close, middle, reason):
    signed_slope = 0.001 if side == "long" else -0.001
    assert trend_pending_cancel_reason(side, signed_slope, 0.0009, close, middle) == reason


def _config():
    return SimpleNamespace(
        rsi=SimpleNamespace(oversold=40, overbought=60, adverse_slope_oversold=32, adverse_slope_overbought=68),
        adverse_slope_take_profit=SimpleNamespace(slope_n=3, special_slope_threshold_pct=0.0009, exspecial_slope_threshold_pct=0.0025),
        bandwidth_entry_guard=SimpleNamespace(percentile_lookback=4, high_percentile=80, min_1h_expansion_pct=0.10),
    )


def test_long_setup_waits_for_new_window_15m_baseline_rsi():
    setup = _create_setup(
        _frame(["2026-01-01 08:00"], [{"close": 95, "lb": 100, "mb": 120, "ub": 140, "rsi14": 20}]),
        _frame(["2026-01-01 08:30", "2026-01-01 08:45"], [{"rsi14": 15}, {"rsi14": 20}]),
        _ts("2026-01-01 09:05"),
        _config(),
    )

    assert setup.side == "long"
    assert setup.trigger_time == _ts("2026-01-01 09:00")
    assert setup.expiry_time == _ts("2026-01-01 10:00")
    assert setup.rsi_15m is None

    _confirm_setup(setup, _frame(["2026-01-01 08:45", "2026-01-01 09:00"], [{"rsi14": 20}, {"rsi14": 25}]), _ts("2026-01-01 09:15"))
    assert setup.rsi_15m == 25
    assert setup.confirmed_15m is False


def test_confirmation_compares_against_setup_baseline_and_honors_after_boundary():
    setup = _create_setup(
        _frame(["2026-01-01 08:00"], [{"close": 95, "lb": 100, "mb": 120, "ub": 140, "rsi14": 20}]),
        _frame(["2026-01-01 08:45"], [{"rsi14": 30}]),
        _ts("2026-01-01 09:05"),
        _config(),
    )

    _confirm_setup(setup, _frame(["2026-01-01 09:00"], [{"rsi14": 25}]), _ts("2026-01-01 09:15"))
    assert setup.confirmed_15m is False
    assert setup.rsi_15m == 25

    _confirm_setup(setup, _frame(["2026-01-01 09:00", "2026-01-01 09:15"], [{"rsi14": 25}, {"rsi14": 31}]), _ts("2026-01-01 09:30"))
    assert setup.confirmed_15m is True
    assert setup.confirm_15m_time == _ts("2026-01-01 09:30")

    setup.confirmed_15m = False
    setup.confirm_15m_time = None
    setup.confirmation_after = _ts("2026-01-01 09:30")
    _confirm_setup(setup, _frame(["2026-01-01 09:00", "2026-01-01 09:15"], [{"rsi14": 31}, {"rsi14": 32}]), _ts("2026-01-01 09:30"))
    assert setup.confirm_15m_time is None


def test_confirmation_does_not_cross_setup_expiry():
    setup = _create_setup(
        _frame(["2026-01-01 08:00"], [{"close": 95, "lb": 100, "mb": 120, "ub": 140, "rsi14": 20}]),
        _frame(["2026-01-01 09:00"], [{"rsi14": 25}]),
        _ts("2026-01-01 09:15"),
        _config(),
    )
    _confirm_setup(setup, _frame(["2026-01-01 09:00"], [{"rsi14": 25}]), _ts("2026-01-01 09:15"))

    _confirm_setup(setup, _frame(["2026-01-01 09:00", "2026-01-01 10:00"], [{"rsi14": 25}, {"rsi14": 50}]), _ts("2026-01-01 10:15"))

    assert setup.confirmed_15m is False


def test_short_setup_and_entry_signal_boundaries():
    setup = _create_setup(
        _frame(["2026-01-01 08:00"], [{"close": 145, "lb": 100, "mb": 120, "ub": 140, "rsi14": 80}]),
        _frame(["2026-01-01 08:45", "2026-01-01 09:00"], [{"rsi14": 70}, {"rsi14": 65}]),
        _ts("2026-01-01 09:15"),
        _config(),
    )

    _confirm_setup(setup, _frame(["2026-01-01 09:00", "2026-01-01 09:15"], [{"rsi14": 65}, {"rsi14": 60}]), _ts("2026-01-01 09:30"))

    assert setup.side == "short"
    assert setup.confirmed_15m is True
    assert _entry_signal(setup, pd.Series({"close": 135, "mb": 136})) is True
    assert _entry_signal(setup, pd.Series({"close": 141, "mb": 136})) is False


def test_initial_stop_loss_uses_configured_percent_for_both_sides():
    assert _initial_stop_loss("long", 100, 0.03) == 97
    assert _initial_stop_loss("short", 100, 0.03) == 103


@pytest.mark.parametrize(
    ("side", "middle_values", "rsi", "expected_side"),
    [
        ("long", [100, 100, 100, 99.9], 34, None),
        ("long", [100, 100, 100, 100], 34, "long"),
        ("short", [100, 100, 100, 100.1], 66, None),
        ("short", [100, 100, 100, 100], 66, "short"),
    ],
)
def test_setup_uses_adverse_slope_rsi_thresholds(side, middle_values, rsi, expected_side):
    setup = _create_setup(_setup_features(side, middle_values, rsi), _frame([], []), _ts("2026-01-01 12:05"), _config())

    assert (setup is None) == (expected_side is None)
    if expected_side:
        assert setup.side == expected_side


@pytest.mark.parametrize(
    ("side", "middle_values", "rsi", "expected_side"),
    [
        ("long", [100, 100, 100, 99.9], 32, None),
        ("long", [100, 100, 100, 99.9], 31.9, "long"),
        ("long", [100, 100, 100, 100], 40, None),
        ("short", [100, 100, 100, 100.1], 68, None),
        ("short", [100, 100, 100, 100.1], 68.1, "short"),
        ("short", [100, 100, 100, 100], 60, None),
    ],
)
def test_setup_rsi_thresholds_are_strict(side, middle_values, rsi, expected_side):
    setup = _create_setup(_setup_features(side, middle_values, rsi), _frame([], []), _ts("2026-01-01 12:05"), _config())

    assert (setup is None) == (expected_side is None)
    if expected_side:
        assert setup.side == expected_side


def test_setup_slope_state_is_per_input_and_uses_only_completed_1h():
    btc = _create_setup(_setup_features("long", [100, 100, 100, 99.9], 34), _frame([], []), _ts("2026-01-01 12:05"), _config())
    eth = _create_setup(_setup_features("long", [100, 100, 100, 100], 34), _frame([], []), _ts("2026-01-01 12:05"), _config())
    sol = _create_setup(_setup_features("short", [100, 100, 100, 100], 66), _frame([], []), _ts("2026-01-01 12:05"), _config())
    forming = _setup_features("long", [100, 100, 100, 99.9], 34)
    forming.loc[_ts("2026-01-01 12:00")] = {"close": 95, "lb": 100, "mb": 100, "ub": 120, "rsi14": 34}

    assert btc is None
    assert eth.side == "long"
    assert sol.side == "short"
    assert _create_setup(forming, _frame([], []), _ts("2026-01-01 12:05"), _config()) is None


@pytest.mark.parametrize("middle_values", [[100, 100, 100], [100, 100, 100, float("nan")]])
def test_setup_uses_strict_rsi_threshold_when_slope_is_unavailable(middle_values):
    setup = _create_setup(_setup_features("long", middle_values, 34), _frame([], []), _ts("2026-01-01 12:05"), _config())

    assert setup is None


@pytest.mark.parametrize(
    ("side", "middle", "expected"),
    [
        ("long", 99.92, "normal"),
        ("long", 99.91, "special"),
        ("long", 99.75, "exspecial"),
        ("short", 100.08, "normal"),
        ("short", 100.09, "special"),
        ("short", 100.25, "exspecial"),
    ],
)
def test_adverse_slope_state_uses_three_tiers_and_inclusive_boundaries(side, middle, expected):
    features = _setup_features(side, [100, 100, 100, middle], 50)

    assert adverse_slope_state(side, features, _config().adverse_slope_take_profit) == expected


@pytest.mark.parametrize(
    ("side", "middle_values", "rsi", "expected_side"),
    [
        ("long", [100, 100, 100, 100], 35, "long"),
        ("long", [100, 100, 100, 99.9], 35, None),
        ("long", [100, 100, 100, 99.7], 35, None),
        ("short", [100, 100, 100, 100], 65, "short"),
        ("short", [100, 100, 100, 100.1], 65, None),
        ("short", [100, 100, 100, 100.3], 65, None),
    ],
)
def test_setup_rsi_profile_changes_only_between_normal_and_special(side, middle_values, rsi, expected_side):
    setup = _create_setup(_setup_features(side, middle_values, rsi), _frame([], []), _ts("2026-01-01 12:05"), _config())

    assert (setup.side if setup else None) == expected_side


@pytest.mark.parametrize(
    ("widths", "expected_label", "allow"),
    [
        ([0.20, 0.30, 0.40, 0.50, 0.10], "LOW", True),
        ([0.10, 0.20, 0.30, 0.40, 0.25], "NORMAL", True),
        ([0.10, 0.20, 0.25, 0.30, 0.40], "HIGH_EXPANDING", False),
        ([0.10, 0.20, 0.30, 0.40, 0.40], "HIGH_STABLE", True),
        ([0.10, 0.20, 0.30, 0.50, 0.40], "HIGH_CONTRACTING", True),
    ],
)
def test_bandwidth_state_labels_and_active_guard(widths, expected_label, allow):
    features = _bandwidth_features(widths)
    config = _config().bandwidth_entry_guard
    config.percentile_lookback = len(widths)

    state = bandwidth_state(features, config)

    assert state["label"] == expected_label
    assert state["allow"] is allow


def test_bandwidth_state_rejects_invalid_or_insufficient_history():
    config = _config().bandwidth_entry_guard

    assert bandwidth_state(_bandwidth_features([0.1, 0.2, 0.3]), config)["label"] == "UNAVAILABLE"
    assert bandwidth_state(_bandwidth_features([0.1, 0.2, float("nan"), 0.3]), config)["label"] == "UNAVAILABLE"


def test_low_percentile_directional_expansion_blocks_matching_adverse_side():
    config = _config()
    config.bandwidth_entry_guard.percentile_lookback = 6
    features = _linkage_features([0.50, 0.50, 0.50, 0.50, 0.10, 0.12], [100, 100, 100, 100, 100.01, 100.02], [100, 100, 100, 100, 100, 200])

    risk = entry_risk_state("short", features, config)

    assert risk["bandwidth"]["percentile"] < config.bandwidth_entry_guard.high_percentile
    assert risk["bandwidth"]["rapid_expanding"] is True
    assert risk["shock_direction"] == "up"
    assert risk["linkage_state"] == "bw_shock_block"
    assert risk["allow"] is False


def test_bandwidth_metrics_keep_ratio_rank_and_relative_change_separate():
    config = _config()
    config.bandwidth_entry_guard.percentile_lookback = 6
    features = _linkage_features([0.10, 0.20, 0.30, 0.40, 0.50, 0.25], [100] * 6, [100] * 6)

    state = bandwidth_state(features, config.bandwidth_entry_guard)

    assert state["raw"] == 0.25
    assert state["percentile"] == pytest.approx(50.0)
    assert state["change_1h"] == pytest.approx(-0.5)
    assert state["change_3h"] == pytest.approx(-1 / 6)


def test_rapid_expansion_inside_bands_has_no_directional_linkage():
    config = _config()
    config.bandwidth_entry_guard.percentile_lookback = 6
    features = _linkage_features([0.50, 0.50, 0.50, 0.50, 0.10, 0.12], [100] * 6, [100] * 6)

    risk = entry_risk_state("short", features, config)

    assert risk["bandwidth"]["rapid_expanding"] is True
    assert risk["shock_direction"] is None
    assert risk["linkage_state"] == "none"


def test_bandwidth_shock_continuation_is_special_only_for_h1_and_h2():
    config = _config()
    config.bandwidth_entry_guard.percentile_lookback = 6
    widths = [0.05] * 5 + [0.06, 0.05, 0.05]
    middles = [100] * 6 + [100.02, 100.04]
    closes = [100] * 5 + [200, 100, 100]

    h1 = entry_risk_state("short", _linkage_features(widths[:-1], middles[:-1], closes[:-1]), config)
    h2 = entry_risk_state("short", _linkage_features(widths, middles, closes), config)

    assert (h1["linkage_state"], h1["shock_age"], h1["effective_state"]) == ("bw_continuation_special", 1, "special")
    assert (h2["linkage_state"], h2["shock_age"], h2["effective_state"]) == ("bw_continuation_special", 2, "special")


@pytest.mark.parametrize("last_middle", [99.98, 100.00])
def test_bandwidth_continuation_cancels_on_reversal_or_equality(last_middle):
    config = _config()
    config.bandwidth_entry_guard.percentile_lookback = 6
    risk = entry_risk_state("short", _linkage_features([0.05] * 5 + [0.06, 0.05], [100] * 6 + [last_middle], [100] * 5 + [200, 100]), config)

    assert risk["linkage_state"] == "none"
    assert risk["effective_state"] == "normal"


def test_bandwidth_continuation_expires_at_h3_and_fast_middle_alone_does_not_tighten():
    config = _config()
    config.bandwidth_entry_guard.percentile_lookback = 6
    expired = entry_risk_state("short", _linkage_features([0.05] * 5 + [0.06, 0.05, 0.05, 0.05], [100] * 6 + [100.02, 100.04, 100.06], [100] * 5 + [200, 100, 100, 100]), config)
    no_shock = entry_risk_state("short", _linkage_features([0.50] * 8, [100] * 6 + [100.02, 100.04], [100] * 8), config)

    assert (expired["linkage_state"], expired["effective_state"]) == ("none", "normal")
    assert (no_shock["linkage_state"], no_shock["effective_state"]) == ("none", "normal")


def test_continuation_uses_strict_rsi_profile_at_setup_seam():
    config = _config()
    config.bandwidth_entry_guard.percentile_lookback = 6
    features = _linkage_features([0.05] * 5 + [0.06, 0.05], [100] * 6 + [100.02], [100] * 5 + [200, 200])
    close_time = _ts("2026-01-01 07:05")
    features.iloc[-1, features.columns.get_loc("rsi14")] = 65

    assert evaluate_setup(features, close_time, config).rsi_threshold is False
    features.iloc[-1, features.columns.get_loc("rsi14")] = 69
    assert evaluate_setup(features, close_time, config).rsi_threshold is True


def test_eth_calibration_values_reproduce_shared_bandwidth_and_slow_slope_path():
    config = _config()
    config.bandwidth_entry_guard.percentile_lookback = 120
    raw, previous, slope = 0.048064547, 0.028484758, 0.003646426
    middle = 1829.244210335 / (1 + raw / 2)
    widths = [0.02] * 118 + [previous, raw]
    middles = [middle] * 116 + [middle / (1 + slope), middle, middle, middle]
    features = _linkage_features(widths, middles[:120], [1800] * 119 + [1862.2])

    state = bandwidth_state(features, config.bandwidth_entry_guard)
    risk = entry_risk_state("short", features, config)

    assert state["raw"] == pytest.approx(raw)
    assert state["change_1h"] == pytest.approx(raw / previous - 1)
    assert state["percentile"] == 100.0
    assert risk["slow_slope_state"] == "exspecial"


def _linkage_features(widths, middles, closes):
    return pd.DataFrame(
        [{"lb": middle - width * middle / 2, "mb": middle, "ub": middle + width * middle / 2, "close": close, "rsi14": 50} for width, middle, close in zip(widths, middles, closes)],
        index=pd.date_range("2026-01-01", periods=len(widths), freq="h", tz="UTC"),
    )


def test_previous_completed_5m_extreme_is_the_production_entry_trigger():
    long_setup = Setup("long", pd.Series({"close": 95, "lb": 100, "mb": 120, "ub": 140}), _ts("2026-01-01 09:00"), _ts("2026-01-01 10:00"))
    short_setup = Setup("short", pd.Series({"close": 145, "lb": 100, "mb": 120, "ub": 140}), _ts("2026-01-01 09:00"), _ts("2026-01-01 10:00"))

    assert _entry_extreme_signal(long_setup, pd.Series({"close": 105}), pd.Series({"high": 100})) is True
    assert _entry_extreme_signal(long_setup, pd.Series({"close": 100}), pd.Series({"high": 100})) is False
    assert _entry_extreme_signal(short_setup, pd.Series({"close": 135}), pd.Series({"low": 140})) is True
    assert _entry_extreme_signal(short_setup, pd.Series({"close": 140}), pd.Series({"low": 140})) is False


def test_shadow_rsi_direction_uses_builder_rsi_and_missing_column_is_fail_safe():
    config = _config()
    config.rsi.period = 14
    config.rsi.method = "wilder"
    config.bollinger = SimpleNamespace(bb_period=20, bb_std_mult=2.0)
    index = pd.date_range("2030-01-01", periods=500, freq="5min", tz="UTC")
    close = [100 + (position % 2) for position in range(497)] + [100, 101, 103]
    ohlcv = pd.DataFrame(
        {"open": close, "high": [value + 1 for value in close], "low": [value - 1 for value in close], "close": close, "volume": 1},
        index=index,
    )
    setup = Setup("long", pd.Series({"close": 95, "lb": 100, "mb": 120, "ub": 140}), _ts("2030-01-01 09:00"), _ts("2030-01-01 10:00"))

    features_5m = build_trailing_features(ohlcv, ohlcv, ohlcv, config)[2]

    assert _entry_rsi_direction_signal(setup, features_5m) is True
    assert _entry_rsi_direction_signal(setup, features_5m.drop(columns=["rsi14"])) is False


def _setup_features(side, middle_values, rsi):
    rows = [{"close": middle, "lb": middle - 20, "mb": middle, "ub": middle + 20, "rsi14": 50} for middle in middle_values]
    if side == "long":
        rows[-1].update(close=95, lb=100, rsi14=rsi)
    else:
        rows[-1].update(close=105, ub=100, rsi14=rsi)
    return _frame([f"2026-01-01 {hour:02}:00" for hour in range(12 - len(rows), 12)], rows)


def _bandwidth_features(widths):
    return _frame(
        [f"2026-01-01 {hour:02}:00" for hour in range(len(widths))],
        [{"lb": 100 - width * 50, "mb": 100, "ub": 100 + width * 50} for width in widths],
    )
