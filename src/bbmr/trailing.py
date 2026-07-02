from dataclasses import dataclass

import pandas as pd


INITIAL_STOP_PCT = 0.02
FIVE_MINUTES = pd.Timedelta(minutes=5)
FIFTEEN_MINUTES = pd.Timedelta(minutes=15)
ONE_HOUR = pd.Timedelta(hours=1)
_TIMEFRAMES = {"1h": ONE_HOUR, "15m": FIFTEEN_MINUTES, "5m": FIVE_MINUTES}


@dataclass
class Setup:
    side: str
    row_1h: pd.Series
    trigger_time: pd.Timestamp
    expiry_time: pd.Timestamp
    rsi_15m: float | None = None
    confirmation_after: pd.Timestamp | None = None
    confirmed_15m: bool = False
    confirm_15m_time: pd.Timestamp | None = None


def latest_completed_row(frame: pd.DataFrame, current_5m_time, timeframe: str):
    index = _utc_index(frame.index)
    completed_at = index + _TIMEFRAMES[timeframe]
    usable = completed_at <= _utc_timestamp(current_5m_time)
    if not usable.any():
        return None
    return frame.iloc[usable.nonzero()[0][-1]]


def _create_setup(features_1h: pd.DataFrame, features_15m: pd.DataFrame, close_time: pd.Timestamp, config) -> Setup | None:
    row_1h = latest_completed_row(features_1h, close_time, "1h")
    if row_1h is None or pd.isna(row_1h.get("lb")) or pd.isna(row_1h.get("rsi14")):
        return None
    trigger_time = _utc_timestamp(row_1h.name) + ONE_HOUR
    expiry_time = trigger_time + ONE_HOUR
    if not (trigger_time <= close_time < expiry_time):
        return None
    if float(row_1h["close"]) < float(row_1h["lb"]) and float(row_1h["rsi14"]) < config.rsi.oversold:
        return Setup("long", row_1h.copy(), trigger_time, expiry_time, confirmation_after=trigger_time)
    if float(row_1h["close"]) > float(row_1h["ub"]) and float(row_1h["rsi14"]) > config.rsi.overbought:
        return Setup("short", row_1h.copy(), trigger_time, expiry_time, confirmation_after=trigger_time)
    return None


def _confirm_setup(setup: Setup, features_15m: pd.DataFrame, close_time: pd.Timestamp) -> None:
    rows = _setup_window_15m(setup, features_15m, close_time)
    if rows.empty:
        return
    if setup.rsi_15m is None:
        baseline = rows.iloc[0]
        if pd.isna(baseline.get("rsi14")):
            return
        setup.rsi_15m = float(baseline["rsi14"])
        setup.confirmation_after = baseline.name + FIFTEEN_MINUTES
        rows = rows.iloc[1:]
    if rows.empty:
        return
    row_15m = rows.iloc[-1]
    confirm_time = row_15m.name + FIFTEEN_MINUTES
    if confirm_time <= (setup.confirmation_after or setup.trigger_time) or pd.isna(row_15m.get("rsi14")):
        return
    rsi = float(row_15m["rsi14"])
    if setup.side == "long" and rsi > setup.rsi_15m:
        setup.confirmed_15m = True
        setup.confirm_15m_time = confirm_time
    elif setup.side == "short" and rsi < setup.rsi_15m:
        setup.confirmed_15m = True
        setup.confirm_15m_time = confirm_time


def _setup_window_15m(setup: Setup, features_15m: pd.DataFrame, close_time: pd.Timestamp) -> pd.DataFrame:
    index = _utc_index(features_15m.index)
    completed_at = index + FIFTEEN_MINUTES
    usable = (
        (index >= _utc_timestamp(setup.trigger_time))
        & (completed_at <= _utc_timestamp(close_time))
        & (completed_at <= _utc_timestamp(setup.expiry_time))
    )
    return features_15m.loc[usable]


def _entry_signal(setup: Setup, row_5m: pd.Series) -> bool:
    close_5m = float(row_5m["close"])
    mid_5m = float(row_5m["mb"])
    lb_1h = float(setup.row_1h["lb"])
    mid_1h = float(setup.row_1h["mb"])
    ub_1h = float(setup.row_1h["ub"])
    if pd.isna(mid_5m):
        return False
    if setup.side == "long":
        return close_5m > mid_5m and close_5m < _midpoint(lb_1h, mid_1h)
    return close_5m < mid_5m and close_5m > _midpoint(mid_1h, ub_1h)


def _initial_stop_loss(side: str, entry_price: float, initial_stop_pct: float = INITIAL_STOP_PCT) -> float:
    return entry_price * (1 - initial_stop_pct if side == "long" else 1 + initial_stop_pct)


def _midpoint(left: float, right: float) -> float:
    return (left + right) / 2


def _utc_timestamp(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _utc_index(index) -> pd.DatetimeIndex:
    timestamps = pd.DatetimeIndex(index)
    if timestamps.tz is None:
        return timestamps.tz_localize("UTC")
    return timestamps.tz_convert("UTC")
