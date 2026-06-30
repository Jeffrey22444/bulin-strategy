from types import SimpleNamespace

import pandas as pd

from bbmr.trailing import (
    _confirm_setup,
    _create_setup,
    _entry_signal,
    _initial_stop_loss,
)


def _ts(value: str) -> pd.Timestamp:
    return pd.Timestamp(value, tz="UTC")


def _frame(index, rows):
    return pd.DataFrame(rows, index=[_ts(value) for value in index])


def _config():
    return SimpleNamespace(rsi=SimpleNamespace(oversold=30, overbought=70))


def test_long_setup_uses_latest_completed_15m_baseline_rsi():
    setup = _create_setup(
        _frame(["2026-01-01 08:00"], [{"close": 95, "lb": 100, "mb": 120, "ub": 140, "rsi14": 20}]),
        _frame(["2026-01-01 08:30", "2026-01-01 08:45"], [{"rsi14": 15}, {"rsi14": 20}]),
        _ts("2026-01-01 09:05"),
        _config(),
    )

    assert setup.side == "long"
    assert setup.trigger_time == _ts("2026-01-01 09:00")
    assert setup.expiry_time == _ts("2026-01-01 10:00")
    assert setup.rsi_15m == 20


def test_confirmation_compares_against_setup_baseline_and_honors_after_boundary():
    setup = _create_setup(
        _frame(["2026-01-01 08:00"], [{"close": 95, "lb": 100, "mb": 120, "ub": 140, "rsi14": 20}]),
        _frame(["2026-01-01 08:45"], [{"rsi14": 30}]),
        _ts("2026-01-01 09:05"),
        _config(),
    )

    _confirm_setup(setup, _frame(["2026-01-01 09:00"], [{"rsi14": 25}]), _ts("2026-01-01 09:15"))
    assert setup.confirmed_15m is False

    _confirm_setup(setup, _frame(["2026-01-01 09:00"], [{"rsi14": 31}]), _ts("2026-01-01 09:15"))
    assert setup.confirmed_15m is True
    assert setup.confirm_15m_time == _ts("2026-01-01 09:15")

    setup.confirmed_15m = False
    setup.confirm_15m_time = None
    setup.confirmation_after = _ts("2026-01-01 09:15")
    _confirm_setup(setup, _frame(["2026-01-01 09:00", "2026-01-01 09:15"], [{"rsi14": 31}, {"rsi14": 32}]), _ts("2026-01-01 09:30"))
    assert setup.confirm_15m_time == _ts("2026-01-01 09:30")


def test_short_setup_and_entry_signal_boundaries():
    setup = _create_setup(
        _frame(["2026-01-01 08:00"], [{"close": 145, "lb": 100, "mb": 120, "ub": 140, "rsi14": 80}]),
        _frame(["2026-01-01 08:45", "2026-01-01 09:00"], [{"rsi14": 70}, {"rsi14": 65}]),
        _ts("2026-01-01 09:15"),
        _config(),
    )

    _confirm_setup(setup, _frame(["2026-01-01 09:00"], [{"rsi14": 65}]), _ts("2026-01-01 09:15"))

    assert setup.side == "short"
    assert setup.confirmed_15m is True
    assert _entry_signal(setup, pd.Series({"close": 135, "mb": 136})) is True
    assert _entry_signal(setup, pd.Series({"close": 141, "mb": 136})) is False


def test_initial_stop_loss_uses_configured_percent_for_both_sides():
    assert _initial_stop_loss("long", 100, 0.03) == 97
    assert _initial_stop_loss("short", 100, 0.03) == 103
