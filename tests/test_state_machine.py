import pytest

from bbmr.state_machine import StateMachineError, TradeState, reduce_events, reduce_state


def test_trade_state_does_not_contain_rsi_flat_trade_state():
    assert "ENTRY_BLOCKED_BY_RSI_FLAT" not in {state.value for state in TradeState}


def test_rsi_flat_signal_block_stays_flat():
    transition = reduce_state(TradeState.FLAT, "LONG_SIGNAL_1H", rsi_flat_blocked=True)
    assert transition.state == TradeState.FLAT
    assert transition.log_event == "SIGNAL_BLOCKED_BY_RSI_FLAT"


def test_rsi_flat_on_off_events_do_not_create_trade_states():
    assert reduce_state(TradeState.FLAT, "RSI_FLAT_ENTRY_BLOCK_ON").state == TradeState.FLAT
    assert reduce_state(TradeState.OPEN_NORMAL, "RSI_FLAT_ENTRY_BLOCK_OFF").state == TradeState.OPEN_NORMAL


def test_valid_signal_creates_pending_entry():
    transition = reduce_state(TradeState.FLAT, "LONG_SIGNAL_1H")
    assert transition.state == TradeState.PENDING_ENTRY
    assert transition.log_event == "PENDING_ENTRY_CREATED"


def test_pending_confirmed_opens_normal():
    assert reduce_state(TradeState.PENDING_ENTRY, "ENTRY_CONFIRMED_15M").state == TradeState.OPEN_NORMAL


def test_pending_expiry_returns_flat():
    assert reduce_state(TradeState.PENDING_ENTRY, "SIGNAL_EXPIRED").state == TradeState.FLAT


def test_pending_ignores_rsi_flat_block():
    assert reduce_state(TradeState.PENDING_ENTRY, "RSI_FLAT_ENTRY_BLOCK_ON").state == TradeState.PENDING_ENTRY


def test_take_profit_and_stop_loss_exit():
    assert reduce_state(TradeState.OPEN_NORMAL, "TAKE_PROFIT_5M").state == TradeState.EXITED
    assert reduce_state(TradeState.OPEN_ADDED, "STOP_LOSS_5M").state == TradeState.EXITED


def test_soft_fail_before_add_when_simultaneous():
    transition = reduce_events(TradeState.OPEN_NORMAL, ["ADD_CONFIRMED_15M", "SOFT_FAIL_1H"])
    assert transition.event == "SOFT_FAIL_1H"
    assert transition.state == TradeState.SOFT_FAIL_NORMAL


def test_open_added_rejects_second_add():
    assert reduce_state(TradeState.OPEN_ADDED, "ADD_CONFIRMED_15M").state == TradeState.OPEN_ADDED


def test_soft_fail_states_reject_add():
    assert reduce_state(TradeState.SOFT_FAIL_NORMAL, "ADD_CONFIRMED_15M").state == TradeState.SOFT_FAIL_NORMAL
    assert reduce_state(TradeState.SOFT_FAIL_ADDED, "ADD_CONFIRMED_15M").state == TradeState.SOFT_FAIL_ADDED


def test_early_fail_only_exits_after_soft_fail():
    with pytest.raises(StateMachineError):
        reduce_state(TradeState.OPEN_NORMAL, "EARLY_FAIL_1H")
    assert reduce_state(TradeState.SOFT_FAIL_NORMAL, "EARLY_FAIL_1H").state == TradeState.EXITED


def test_same_5m_take_profit_and_stop_loss_chooses_stop_loss():
    transition = reduce_events(TradeState.OPEN_NORMAL, ["TAKE_PROFIT_5M", "STOP_LOSS_5M"])
    assert transition.event == "STOP_LOSS_5M"
    assert transition.state == TradeState.EXITED


def test_undefined_transition_raises_clear_error():
    with pytest.raises(StateMachineError, match="undefined transition"):
        reduce_state(TradeState.FLAT, "ENTRY_CONFIRMED_15M")
