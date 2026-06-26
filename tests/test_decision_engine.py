from bbmr.config import load_config
from bbmr.decision_engine import evaluate_cycle
from bbmr.state_machine import TradeState
from bbmr.trade_models import TradeContext


def _config():
    return load_config("configs/strategy_bbmr_v3_2.yaml")


def _row_1h(**overrides):
    row = {
        "lb": 90.0,
        "mb": 100.0,
        "ub": 110.0,
        "atr": 1.0,
        "volume_ratio": 1.0,
        "squeeze": False,
        "expansion": False,
        "lower_band_walking": False,
        "upper_band_walking": False,
        "rsi_flat_entry_block": False,
        "long_signal_1h": False,
        "short_signal_1h": False,
        "invalid_signal": False,
        "soft_fail": False,
        "early_fail": False,
    }
    row.update(overrides)
    return row


def test_flat_valid_signal_creates_pending():
    result = evaluate_cycle(TradeContext(), row_1h=_row_1h(long_signal_1h=True), config=_config())
    assert result.context.state == TradeState.PENDING_ENTRY
    assert result.context.side == "long"
    assert result.log_events == ["PENDING_ENTRY_CREATED"]


def test_pending_confirm_opens_normal_with_fixed_sl_and_one_r():
    config = _config()
    pending = evaluate_cycle(TradeContext(), row_1h=_row_1h(long_signal_1h=True), config=config).context
    result = evaluate_cycle(
        pending,
        row_1h=_row_1h(),
        row_15m={"close": 91.0, "waited_bars": 1},
        config=config,
        account_equity=10_000,
    )
    assert result.context.state == TradeState.OPEN_NORMAL
    assert result.context.fixed_sl == 88.5
    assert result.context.one_r == 2.5
    assert result.context.initial_size > 0


def _open_context(config):
    pending = evaluate_cycle(TradeContext(), row_1h=_row_1h(long_signal_1h=True), config=config).context
    return evaluate_cycle(
        pending,
        row_1h=_row_1h(),
        row_15m={"close": 91.0, "waited_bars": 1},
        config=config,
        account_equity=10_000,
    ).context


def test_open_normal_soft_fail_to_early_fail_exit():
    config = _config()
    opened = _open_context(config)
    soft = evaluate_cycle(opened, row_1h=_row_1h(soft_fail=True), row_5m={"low": 90, "high": 100}, config=config)
    assert soft.context.state == TradeState.SOFT_FAIL_NORMAL
    exited = evaluate_cycle(soft.context, row_1h=_row_1h(early_fail=True), row_5m={"low": 90, "high": 100}, config=config)
    assert exited.context.state == TradeState.EXITED
    assert exited.transition.event == "EARLY_FAIL_1H"


def test_sl_priority_beats_tp_in_same_5m_row():
    config = _config()
    opened = _open_context(config)
    result = evaluate_cycle(opened, row_1h=_row_1h(), row_5m={"low": 88, "high": 106}, config=config)
    assert result.transition.event == "STOP_LOSS_5M"
    assert result.context.state == TradeState.EXITED


def test_open_normal_add_allowed_opens_added():
    config = _config()
    opened = _open_context(config)
    result = evaluate_cycle(
        opened,
        row_1h=_row_1h(lb=89),
        row_15m={"low": 88, "close": 89.5},
        row_5m={"low": 89, "high": 100},
        config=config,
    )
    assert result.context.state == TradeState.OPEN_ADDED
    assert result.context.add_count == 1
