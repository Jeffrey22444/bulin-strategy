from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class RunSession:
    run_id: str
    strategy_name: str
    config_hash: str
    started_at: str
    mode: str
    ended_at: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class TradeRecord:
    trade_id: str
    run_id: str
    symbol: str
    side: str
    state: str
    created_at: str
    updated_at: str
    entry_time: str | None = None
    exit_time: str | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    initial_size: float | None = None
    add_size: float = 0.0
    weighted_avg_entry: float | None = None
    fixed_sl: float | None = None
    one_r: float | None = None
    add_count: int = 0
    soft_fail_triggered: int = 0
    soft_fail_time: str | None = None
    early_fail_triggered: int = 0
    early_fail_time: str | None = None
    early_fail_confirmation_count: int = 0
    early_fail_bw_expansion: int = 0
    early_fail_shock_volume: int = 0
    early_fail_band_walking: int = 0
    exit_reason: str | None = None
    realized_pnl: float | None = None
    realized_pnl_r: float | None = None


@dataclass(frozen=True)
class TradeEvent:
    event_id: str
    run_id: str
    timestamp: str
    event_type: str
    trade_id: str | None = None
    symbol: str | None = None
    state_before: str | None = None
    state_after: str | None = None
    price: float | None = None
    reason: str | None = None
    metadata_json: str | None = None


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
