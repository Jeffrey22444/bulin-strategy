import json
from uuid import uuid4

from bbmr.storage import ResearchStorage
from bbmr.trade_models import TradeEvent, utc_now_iso


EVENT_TYPES = {
    "SIGNAL_1H",
    "PENDING_ENTRY_CREATED",
    "PENDING_ENTRY_EXPIRED",
    "ENTRY_CONFIRMED_15M",
    "ORDER_ENTRY_SIMULATED",
    "ADD_CONFIRMED_15M",
    "ORDER_ADD_SIMULATED",
    "SOFT_FAIL_1H",
    "EARLY_FAIL_1H",
    "STOP_LOSS_5M",
    "TAKE_PROFIT_5M",
    "STATE_TRANSITION",
    "INVALID_SIGNAL",
    "RSI_FLAT_ENTRY_BLOCK_ON",
    "RSI_FLAT_ENTRY_BLOCK_OFF",
    "SIGNAL_BLOCKED_BY_RSI_FLAT",
}


def log_event(
    storage: ResearchStorage,
    run_id: str,
    event_type: str,
    *,
    event_id: str | None = None,
    trade_id: str | None = None,
    timestamp: str | None = None,
    symbol: str | None = None,
    state_before: str | None = None,
    state_after: str | None = None,
    price: float | None = None,
    reason: str | None = None,
    metadata: dict | None = None,
) -> TradeEvent:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unsupported event type: {event_type}")
    event = TradeEvent(
        event_id=event_id or str(uuid4()),
        run_id=run_id,
        trade_id=trade_id,
        timestamp=timestamp or utc_now_iso(),
        symbol=symbol,
        state_before=state_before,
        event_type=event_type,
        state_after=state_after,
        price=price,
        reason=reason,
        metadata_json=json.dumps(metadata or {}, sort_keys=True),
    )
    storage.insert_trade_event(event)
    return event
