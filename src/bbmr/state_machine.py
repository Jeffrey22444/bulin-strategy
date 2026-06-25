from dataclasses import dataclass
from enum import Enum


class TradeState(str, Enum):
    FLAT = "FLAT"
    PENDING_ENTRY = "PENDING_ENTRY"
    OPEN_NORMAL = "OPEN_NORMAL"
    OPEN_ADDED = "OPEN_ADDED"
    SOFT_FAIL_NORMAL = "SOFT_FAIL_NORMAL"
    SOFT_FAIL_ADDED = "SOFT_FAIL_ADDED"
    EXITED = "EXITED"


class StateMachineError(ValueError):
    pass


@dataclass(frozen=True)
class Transition:
    state: TradeState
    event: str
    log_event: str | None = None


PRIORITY = {
    "STOP_LOSS_5M": 1,
    "TAKE_PROFIT_5M": 2,
    "ADDED_TAKE_PROFIT_5M": 2,
    "MARKET_STATE_1H": 3,
    "RSI_FLAT_ENTRY_BLOCK_ON": 3,
    "RSI_FLAT_ENTRY_BLOCK_OFF": 3,
    "EARLY_FAIL_1H": 4,
    "SOFT_FAIL_1H": 5,
    "ADD_CONFIRMED_15M": 6,
    "ENTRY_CONFIRMED_15M": 7,
    "LONG_SIGNAL_1H": 8,
    "SHORT_SIGNAL_1H": 8,
    "INVALID_SIGNAL": 8,
    "SIGNAL_EXPIRED": 8,
    "SQUEEZE_1H": 8,
    "EXPANSION_1H": 8,
    "LOWER_BAND_WALKING_1H": 8,
    "UPPER_BAND_WALKING_1H": 8,
    "VOLUME_REJECT_1H": 8,
    "OPPOSITE_SIGNAL_1H": 8,
    "TRADE_RECORDED": 9,
}


def select_priority_event(events: list[str] | tuple[str, ...]) -> str:
    if not events:
        raise StateMachineError("no event provided")
    unknown = [event for event in events if event not in PRIORITY]
    if unknown:
        raise StateMachineError(f"undefined event: {unknown[0]}")
    return min(events, key=lambda event: PRIORITY[event])


def reduce_state(state: TradeState, event: str, *, rsi_flat_blocked: bool = False) -> Transition:
    if event not in PRIORITY:
        raise StateMachineError(f"undefined event: {event}")

    if event in {"RSI_FLAT_ENTRY_BLOCK_ON", "RSI_FLAT_ENTRY_BLOCK_OFF", "MARKET_STATE_1H"}:
        return Transition(state, event, event if event.startswith("RSI_FLAT") else None)

    if state == TradeState.FLAT:
        if event in {"LONG_SIGNAL_1H", "SHORT_SIGNAL_1H"}:
            if rsi_flat_blocked:
                return Transition(TradeState.FLAT, event, "SIGNAL_BLOCKED_BY_RSI_FLAT")
            return Transition(TradeState.PENDING_ENTRY, event, "PENDING_ENTRY_CREATED")
        if event == "INVALID_SIGNAL":
            return Transition(TradeState.FLAT, event, "INVALID_SIGNAL")
        raise StateMachineError(f"undefined transition: {state.value} + {event}")

    if state == TradeState.PENDING_ENTRY:
        if event == "ENTRY_CONFIRMED_15M":
            return Transition(TradeState.OPEN_NORMAL, event, "ENTRY_CONFIRMED_15M")
        if event in {"SIGNAL_EXPIRED", "SQUEEZE_1H", "EXPANSION_1H", "LOWER_BAND_WALKING_1H", "UPPER_BAND_WALKING_1H", "VOLUME_REJECT_1H"}:
            return Transition(TradeState.FLAT, event, "PENDING_ENTRY_EXPIRED")
        if event == "OPPOSITE_SIGNAL_1H":
            return Transition(TradeState.PENDING_ENTRY, event)
        raise StateMachineError(f"undefined transition: {state.value} + {event}")

    if state == TradeState.OPEN_NORMAL:
        if event in {"STOP_LOSS_5M", "TAKE_PROFIT_5M"}:
            return Transition(TradeState.EXITED, event, event)
        if event == "SOFT_FAIL_1H":
            return Transition(TradeState.SOFT_FAIL_NORMAL, event, event)
        if event == "ADD_CONFIRMED_15M":
            return Transition(TradeState.OPEN_ADDED, event, event)
        if event == "OPPOSITE_SIGNAL_1H":
            return Transition(TradeState.OPEN_NORMAL, event)
        raise StateMachineError(f"undefined transition: {state.value} + {event}")

    if state == TradeState.OPEN_ADDED:
        if event in {"STOP_LOSS_5M", "ADDED_TAKE_PROFIT_5M"}:
            return Transition(TradeState.EXITED, event, event)
        if event == "SOFT_FAIL_1H":
            return Transition(TradeState.SOFT_FAIL_ADDED, event, event)
        if event in {"ADD_CONFIRMED_15M", "OPPOSITE_SIGNAL_1H"}:
            return Transition(TradeState.OPEN_ADDED, event)
        raise StateMachineError(f"undefined transition: {state.value} + {event}")

    if state == TradeState.SOFT_FAIL_NORMAL:
        if event in {"STOP_LOSS_5M", "TAKE_PROFIT_5M", "EARLY_FAIL_1H"}:
            return Transition(TradeState.EXITED, event, event)
        if event in {"ADD_CONFIRMED_15M", "SOFT_FAIL_1H"}:
            return Transition(TradeState.SOFT_FAIL_NORMAL, event)
        raise StateMachineError(f"undefined transition: {state.value} + {event}")

    if state == TradeState.SOFT_FAIL_ADDED:
        if event in {"STOP_LOSS_5M", "ADDED_TAKE_PROFIT_5M", "EARLY_FAIL_1H"}:
            return Transition(TradeState.EXITED, event, event)
        if event in {"ADD_CONFIRMED_15M", "SOFT_FAIL_1H"}:
            return Transition(TradeState.SOFT_FAIL_ADDED, event)
        raise StateMachineError(f"undefined transition: {state.value} + {event}")

    if state == TradeState.EXITED:
        if event == "TRADE_RECORDED":
            return Transition(TradeState.FLAT, event)
        return Transition(TradeState.EXITED, event)

    raise StateMachineError(f"undefined state: {state}")


def reduce_events(state: TradeState, events: list[str] | tuple[str, ...], *, rsi_flat_blocked: bool = False) -> Transition:
    return reduce_state(state, select_priority_event(events), rsi_flat_blocked=rsi_flat_blocked)
