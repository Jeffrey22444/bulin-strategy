from dataclasses import dataclass, replace

from bbmr.add_rules import long_add_allowed, short_add_allowed
from bbmr.entry_confirmation import (
    long_entry_confirmed,
    long_second_reentry_confirmed,
    pending_expired,
    pending_invalidated,
    short_entry_confirmed,
    short_second_reentry_confirmed,
)
from bbmr.exit_rules import added_take_profit_price, fixed_sl_triggered, take_profit_price, take_profit_triggered
from bbmr.risk import fixed_stop_loss, one_r
from bbmr.signals import EntryReference
from bbmr.sizing import calculate_add_size, initial_position_size
from bbmr.state_machine import TradeState, Transition, reduce_events
from bbmr.trade_models import TradeContext


@dataclass(frozen=True)
class DecisionResult:
    context: TradeContext
    events: list[str]
    transition: Transition | None
    log_events: list[str]


def _value(row, key, default=None):
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, row[key] if key in row else default)


def _signal_event(row_1h) -> str | None:
    if bool(_value(row_1h, "invalid_signal", False)):
        return "INVALID_SIGNAL"
    if bool(_value(row_1h, "long_signal_1h", False)):
        return "LONG_SIGNAL_1H"
    if bool(_value(row_1h, "short_signal_1h", False)):
        return "SHORT_SIGNAL_1H"
    return None


def _entry_reference(row_1h, side: str) -> EntryReference:
    return EntryReference(
        signal_time=_value(row_1h, "signal_time", _value(row_1h, "name", None)),
        entry_reference_LB=float(_value(row_1h, "lb")),
        entry_reference_MB=float(_value(row_1h, "mb")),
        entry_reference_UB=float(_value(row_1h, "ub")),
        frozen_ATR=float(_value(row_1h, "atr")),
        signal_side=side,
    )


def _exit_events(context: TradeContext, row_5m, row_1h, config) -> list[str]:
    if row_5m is None or context.side is None or context.fixed_sl is None:
        return []
    events = []
    low_5m = float(_value(row_5m, "low"))
    high_5m = float(_value(row_5m, "high"))
    if fixed_sl_triggered(context.side, low_5m, high_5m, context.fixed_sl):
        events.append("STOP_LOSS_5M")

    if context.state in {TradeState.OPEN_ADDED, TradeState.SOFT_FAIL_ADDED}:
        tp = added_take_profit_price(
            context.side,
            float(_value(row_1h, "mb")),
            float(context.weighted_avg_entry),
            float(context.one_r),
            config.profit_target.min_profit_r_after_add,
        )
        if take_profit_triggered(context.side, high_5m, low_5m, tp):
            events.append("ADDED_TAKE_PROFIT_5M")
    else:
        tp = take_profit_price(
            context.side,
            float(_value(row_1h, "mb")),
            float(_value(row_1h, "lb")),
            float(_value(row_1h, "ub")),
            config.profit_target.tp_mid_frac,
        )
        if take_profit_triggered(context.side, high_5m, low_5m, tp):
            events.append("TAKE_PROFIT_5M")
    return events


def _floating_pnl_r(context: TradeContext, price: float) -> float:
    if context.side == "long":
        return (price - context.entry_price) / context.one_r
    return (context.entry_price - price) / context.one_r


def _events(context: TradeContext, row_1h, row_15m, row_5m, config) -> list[str]:
    if context.state == TradeState.FLAT:
        event = _signal_event(row_1h)
        return [event] if event else []

    if context.state == TradeState.PENDING_ENTRY:
        if pending_expired(int(_value(row_15m, "waited_bars", 0)), config.entry_confirmation.reentry_bars):
            return ["SIGNAL_EXPIRED"]
        if pending_invalidated(
            context.side,
            bool(_value(row_1h, "squeeze", False)),
            bool(_value(row_1h, "expansion", False)),
            bool(_value(row_1h, "lower_band_walking", False)),
            bool(_value(row_1h, "upper_band_walking", False)),
            float(_value(row_1h, "volume_ratio", 0)),
            config.volume.reject,
        ):
            return ["SIGNAL_EXPIRED"]
        if row_15m is None:
            return []
        close_15m = float(_value(row_15m, "close"))
        if context.side == "long" and long_entry_confirmed(close_15m, context.entry_reference):
            return ["ENTRY_CONFIRMED_15M"]
        if context.side == "short" and short_entry_confirmed(close_15m, context.entry_reference):
            return ["ENTRY_CONFIRMED_15M"]
        return []

    events = _exit_events(context, row_5m, row_1h, config)
    if context.state in {TradeState.SOFT_FAIL_NORMAL, TradeState.SOFT_FAIL_ADDED}:
        if bool(_value(row_1h, "early_fail", False)):
            events.append("EARLY_FAIL_1H")
        return events

    if bool(_value(row_1h, "soft_fail", False)):
        events.append("SOFT_FAIL_1H")

    if context.state == TradeState.OPEN_NORMAL and row_15m is not None and row_5m is not None:
        sl_now = context.fixed_sl is not None and fixed_sl_triggered(
            context.side, float(_value(row_5m, "low")), float(_value(row_5m, "high")), context.fixed_sl
        )
        if context.side == "long":
            second = long_second_reentry_confirmed(float(_value(row_15m, "low")), float(_value(row_15m, "close")), float(_value(row_1h, "lb")))
            allowed = long_add_allowed(
                has_long_position=True,
                add_count=context.add_count,
                floating_pnl_R=_floating_pnl_r(context, float(_value(row_15m, "close"))),
                add_trigger_loss_r=config.add_position.add_trigger_loss_r,
                fixed_sl_triggered=sl_now,
                soft_fail_long=bool(_value(row_1h, "soft_fail", False)),
                squeeze=bool(_value(row_1h, "squeeze", False)),
                expansion=bool(_value(row_1h, "expansion", False)),
                lower_band_walking=bool(_value(row_1h, "lower_band_walking", False)),
                volume_ratio=float(_value(row_1h, "volume_ratio", 0)),
                volume_reject=config.volume.reject,
                long_second_reentry_confirmed=second,
            )
        else:
            second = short_second_reentry_confirmed(float(_value(row_15m, "high")), float(_value(row_15m, "close")), float(_value(row_1h, "ub")))
            allowed = short_add_allowed(
                has_short_position=True,
                add_count=context.add_count,
                floating_pnl_R=_floating_pnl_r(context, float(_value(row_15m, "close"))),
                add_trigger_loss_r=config.add_position.add_trigger_loss_r,
                fixed_sl_triggered=sl_now,
                soft_fail_short=bool(_value(row_1h, "soft_fail", False)),
                squeeze=bool(_value(row_1h, "squeeze", False)),
                expansion=bool(_value(row_1h, "expansion", False)),
                upper_band_walking=bool(_value(row_1h, "upper_band_walking", False)),
                volume_ratio=float(_value(row_1h, "volume_ratio", 0)),
                volume_reject=config.volume.reject,
                short_second_reentry_confirmed=second,
            )
        if config.add_position.enabled and allowed:
            events.append("ADD_CONFIRMED_15M")
    return events


def evaluate_cycle(
    context: TradeContext,
    *,
    row_1h,
    row_15m=None,
    row_5m=None,
    config,
    account_equity: float | None = None,
) -> DecisionResult:
    events = _events(context, row_1h, row_15m, row_5m, config)
    if not events:
        return DecisionResult(context, [], None, [])

    transition = reduce_events(context.state, events, rsi_flat_blocked=bool(_value(row_1h, "rsi_flat_entry_block", False)))
    new_context = _apply_transition(context, transition, row_1h, row_15m, config, account_equity)
    return DecisionResult(new_context, events, transition, [transition.log_event] if transition.log_event else [])


def _apply_transition(context, transition, row_1h, row_15m, config, account_equity):
    if transition.event in {"LONG_SIGNAL_1H", "SHORT_SIGNAL_1H"} and transition.state == TradeState.PENDING_ENTRY:
        side = "long" if transition.event == "LONG_SIGNAL_1H" else "short"
        return replace(context, state=transition.state, side=side, entry_reference=_entry_reference(row_1h, side))

    if transition.event == "ENTRY_CONFIRMED_15M" and transition.state == TradeState.OPEN_NORMAL:
        entry_price = float(_value(row_15m, "close"))
        fixed_sl = fixed_stop_loss(context.side, entry_price, context.entry_reference.frozen_ATR, config.stop_loss.sl_atr_mult_mr, config.stop_loss.min_stop_pct)
        one_r_value = one_r(context.side, entry_price, fixed_sl)
        initial_size = None if account_equity is None else initial_position_size(account_equity, config.position_sizing.risk_per_trade, one_r_value)
        return replace(
            context,
            state=transition.state,
            entry_price=entry_price,
            fixed_sl=fixed_sl,
            one_r=one_r_value,
            initial_size=initial_size,
            weighted_avg_entry=entry_price,
        )

    if transition.event == "ADD_CONFIRMED_15M" and transition.state == TradeState.OPEN_ADDED:
        add_entry_price = float(_value(row_15m, "close"))
        initial_risk = (context.initial_size or 0) * context.one_r
        add_size = calculate_add_size(
            context.side,
            context.initial_size or 0,
            context.entry_price,
            add_entry_price,
            context.fixed_sl,
            initial_risk,
            config.add_position.add_size_frac,
            config.add_position.add_max_total_r,
        )
        total_size = (context.initial_size or 0) + add_size
        weighted = context.weighted_avg_entry if total_size == 0 else ((context.entry_price or 0) * (context.initial_size or 0) + add_entry_price * add_size) / total_size
        return replace(context, state=transition.state, add_size=add_size, add_count=context.add_count + 1, weighted_avg_entry=weighted)

    if transition.event == "SOFT_FAIL_1H":
        return replace(context, state=transition.state, soft_fail_triggered=True)

    if transition.state == TradeState.EXITED:
        return replace(context, state=transition.state)

    if transition.state == TradeState.FLAT:
        return TradeContext()

    return replace(context, state=transition.state)
