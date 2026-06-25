import pytest

from bbmr.risk import fixed_stop_loss, one_r
from bbmr.sizing import calculate_add_size, initial_position_size, total_risk_after_add


def test_fixed_stop_loss_and_one_r():
    fixed_sl = fixed_stop_loss("long", entry_price=100.0, frozen_atr=1.0, sl_atr_mult=2.5, min_stop_pct=0.025)
    assert fixed_sl == 97.5
    assert one_r("long", 100.0, fixed_sl) == 2.5
    assert fixed_stop_loss("short", 100.0, 1.0, 2.5, 0.025) == 102.5
    assert one_r("short", 100.0, 102.5) == 2.5


def test_one_r_rejects_invalid_stop():
    with pytest.raises(ValueError):
        one_r("long", 100.0, 101.0)


def test_initial_position_size_uses_risk_amount_over_one_r():
    assert initial_position_size(account_equity=10_000, risk_per_trade=0.005, one_R=2.5) == 20


def test_total_risk_after_add_uses_multileg_formula():
    assert total_risk_after_add("long", 20, 100, 10, 99, 97.5) == 65
    assert total_risk_after_add("short", 20, 100, 10, 101, 102.5) == 65


def test_add_size_shrinks_when_risk_limit_would_be_exceeded():
    size = calculate_add_size(
        "long",
        initial_position_size=20,
        initial_entry_price=100,
        add_entry_price=99,
        fixed_sl=97.5,
        initial_risk_amount=50,
        add_size_frac=1.0,
        add_max_total_r=1.5,
    )
    assert size == 50 / 3


def test_add_size_skips_when_below_exchange_min_order_size():
    size = calculate_add_size(
        "long",
        initial_position_size=20,
        initial_entry_price=100,
        add_entry_price=99,
        fixed_sl=97.5,
        initial_risk_amount=50,
        add_size_frac=1.0,
        add_max_total_r=1.5,
        exchange_min_order_size=20,
    )
    assert size == 0
