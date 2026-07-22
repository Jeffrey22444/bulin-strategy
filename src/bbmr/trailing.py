from dataclasses import dataclass
import math

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


@dataclass
class SetupEvaluation:
    row_1h: pd.Series | None
    side: str | None
    trigger_time: pd.Timestamp | None
    expiry_time: pd.Timestamp | None
    price_outer_break: bool
    rsi_threshold: bool
    entry_risk: dict | None = None


@dataclass(frozen=True)
class TrendEpisode:
    side: str
    episode_bucket: pd.Timestamp
    current_bucket: pd.Timestamp
    first_slope: float
    current_slope: float
    frozen_close: float
    limit_price: float
    row_1h: pd.Series


def latest_completed_row(frame: pd.DataFrame, current_5m_time, timeframe: str):
    index = _utc_index(frame.index)
    completed_at = index + _TIMEFRAMES[timeframe]
    usable = completed_at <= _utc_timestamp(current_5m_time)
    if not usable.any():
        return None
    return frame.iloc[usable.nonzero()[0][-1]]


def trend_episode(
    features_1h: pd.DataFrame,
    close_time,
    slope_n: int,
    exspecial_threshold: float,
    entry_pullback_pct: float,
) -> TrendEpisode | None:
    """Rebuild the current completed-1h EXSPECIAL episode; invalid inputs fail closed."""
    if not isinstance(slope_n, int) or isinstance(slope_n, bool) or slope_n <= 0:
        return None
    try:
        exspecial_threshold = float(exspecial_threshold)
        entry_pullback_pct = float(entry_pullback_pct)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (exspecial_threshold, entry_pullback_pct)):
        return None
    if exspecial_threshold <= 0 or not 0 < entry_pullback_pct < 1:
        return None
    try:
        current = latest_completed_row(features_1h, close_time, "1h")
        if current is None:
            return None
        completed = features_1h.loc[: current.name]
        if len(completed) <= slope_n:
            return None
        current_position = len(completed) - 1
        current_slope = _middle_slope_at(completed, current_position, slope_n)
        side = _exspecial_side(current_slope, exspecial_threshold)
        if side is None:
            return None
        episode_position = current_position
        while episode_position > slope_n:
            previous_slope = _middle_slope_at(completed, episode_position - 1, slope_n)
            previous_side = _exspecial_side(previous_slope, exspecial_threshold)
            if previous_side != side:
                break
            episode_position -= 1
        episode_row = completed.iloc[episode_position]
        first_slope = _middle_slope_at(completed, episode_position, slope_n)
        frozen_close = float(episode_row["close"])
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError):
        return None
    if not all(math.isfinite(value) for value in (first_slope, current_slope, frozen_close)) or frozen_close <= 0:
        return None
    limit_price = frozen_close * (1 - entry_pullback_pct if side == "long" else 1 + entry_pullback_pct)
    if not math.isfinite(limit_price) or limit_price <= 0:
        return None
    return TrendEpisode(
        side,
        _utc_timestamp(episode_row.name),
        _utc_timestamp(current.name),
        first_slope,
        current_slope,
        frozen_close,
        limit_price,
        episode_row.copy(),
    )


def trend_pending_cancel_reason(
    side: str,
    signed_slope: float,
    special_slope_threshold_pct: float,
    completed_close: float | None = None,
    current_middle: float | None = None,
) -> str | None:
    if side not in {"long", "short"}:
        return "invalid_pending_state"
    try:
        signed_slope = float(signed_slope)
    except (TypeError, ValueError):
        return "invalid_pending_state"
    try:
        special_slope_threshold_pct = float(special_slope_threshold_pct)
    except (TypeError, ValueError):
        return "invalid_pending_state"
    if not math.isfinite(signed_slope) or not math.isfinite(special_slope_threshold_pct) or special_slope_threshold_pct < 0:
        return "invalid_pending_state"
    strength = signed_slope if side == "long" else -signed_slope
    if strength < special_slope_threshold_pct:
        return "directional_slope_normal"
    if completed_close is None and current_middle is None:
        return None
    try:
        completed_close, current_middle = float(completed_close), float(current_middle)
    except (TypeError, ValueError):
        return "invalid_pending_state"
    if not math.isfinite(completed_close) or not math.isfinite(current_middle):
        return "invalid_pending_state"
    if (side == "long" and completed_close <= current_middle) or (side == "short" and completed_close >= current_middle):
        return "completed_1h_middle_invalidated"
    return None


def _middle_slope_at(features_1h: pd.DataFrame, position: int, slope_n: int) -> float:
    current_middle = float(features_1h.iloc[position]["mb"])
    past_middle = float(features_1h.iloc[position - slope_n]["mb"])
    if not all(math.isfinite(value) for value in (current_middle, past_middle)) or past_middle == 0:
        raise ValueError("invalid middle-band slope inputs")
    slope = current_middle / past_middle - 1
    if not math.isfinite(slope):
        raise ValueError("invalid middle-band slope")
    return slope


def _exspecial_side(slope: float, threshold: float) -> str | None:
    if slope > threshold or math.isclose(slope, threshold, abs_tol=1e-12):
        return "long"
    if slope < -threshold or math.isclose(slope, -threshold, abs_tol=1e-12):
        return "short"
    return None


def _create_setup(features_1h: pd.DataFrame, features_15m: pd.DataFrame, close_time: pd.Timestamp, config) -> Setup | None:
    evaluation = evaluate_setup(features_1h, close_time, config)
    if not (evaluation.row_1h is not None and evaluation.side and evaluation.trigger_time and evaluation.expiry_time and evaluation.price_outer_break and evaluation.rsi_threshold):
        return None
    return Setup(evaluation.side, evaluation.row_1h.copy(), evaluation.trigger_time, evaluation.expiry_time, confirmation_after=evaluation.trigger_time)


def evaluate_setup(features_1h: pd.DataFrame, close_time: pd.Timestamp, config) -> SetupEvaluation:
    row_1h = latest_completed_row(features_1h, close_time, "1h")
    if row_1h is None or pd.isna(row_1h.get("lb")) or pd.isna(row_1h.get("rsi14")):
        return SetupEvaluation(None, None, None, None, False, False)
    trigger_time = _utc_timestamp(row_1h.name) + ONE_HOUR
    expiry_time = trigger_time + ONE_HOUR
    if not (trigger_time <= close_time < expiry_time):
        return SetupEvaluation(row_1h, None, trigger_time, expiry_time, False, False)
    completed_1h = features_1h.loc[: row_1h.name]
    if float(row_1h["close"]) < float(row_1h["lb"]):
        risk = entry_risk_state("long", completed_1h, config)
        return SetupEvaluation(row_1h, "long", trigger_time, expiry_time, True, float(row_1h["rsi14"]) < risk["rsi_threshold"], risk)
    if float(row_1h["close"]) > float(row_1h["ub"]):
        risk = entry_risk_state("short", completed_1h, config)
        return SetupEvaluation(row_1h, "short", trigger_time, expiry_time, True, float(row_1h["rsi14"]) > risk["rsi_threshold"], risk)
    return SetupEvaluation(row_1h, None, trigger_time, expiry_time, False, False)


def adverse_slope_state(side: str, features_1h: pd.DataFrame, config) -> str | None:
    if len(features_1h) <= config.slope_n:
        return None
    try:
        past_middle = float(features_1h.iloc[-(config.slope_n + 1)]["mb"])
        current_middle = float(features_1h.iloc[-1]["mb"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (past_middle, current_middle)) or past_middle == 0:
        return None
    slope = current_middle / past_middle - 1
    if not math.isfinite(slope):
        return None
    if side == "long":
        if slope <= -config.exspecial_slope_threshold_pct or math.isclose(slope, -config.exspecial_slope_threshold_pct, abs_tol=1e-12):
            return "exspecial"
        if slope <= -config.special_slope_threshold_pct or math.isclose(slope, -config.special_slope_threshold_pct, abs_tol=1e-12):
            return "special"
    else:
        if slope >= config.exspecial_slope_threshold_pct or math.isclose(slope, config.exspecial_slope_threshold_pct, abs_tol=1e-12):
            return "exspecial"
        if slope >= config.special_slope_threshold_pct or math.isclose(slope, config.special_slope_threshold_pct, abs_tol=1e-12):
            return "special"
    return "normal"


def bandwidth_state(features_1h: pd.DataFrame, config) -> dict:
    if len(features_1h) < max(config.percentile_lookback, 4):
        return _unavailable_bandwidth_state("insufficient_history")
    try:
        recent = features_1h.iloc[-config.percentile_lookback:]
        values = (recent["ub"] - recent["lb"]) / recent["mb"]
    except (KeyError, TypeError, ValueError):
        return _unavailable_bandwidth_state("missing_bandwidth_inputs")
    if not values.map(math.isfinite).all() or (values <= 0).any():
        return _unavailable_bandwidth_state("invalid_bandwidth")
    current = float(values.iloc[-1])
    previous = float(values.iloc[-2])
    three_hours_ago = float(values.iloc[-4])
    if previous == 0 or three_hours_ago == 0:
        return _unavailable_bandwidth_state("invalid_bandwidth_change")
    change_1h = current / previous - 1
    change_3h = current / three_hours_ago - 1
    if not all(math.isfinite(value) for value in (change_1h, change_3h)):
        return _unavailable_bandwidth_state("invalid_bandwidth_change")
    percentile = float((values <= current).mean() * 100)
    if percentile <= 20:
        label = "LOW"
    elif percentile < config.high_percentile:
        label = "NORMAL"
    elif change_1h >= config.min_1h_expansion_pct:
        label = "HIGH_EXPANDING"
    elif change_1h <= -config.min_1h_expansion_pct:
        label = "HIGH_CONTRACTING"
    else:
        label = "HIGH_STABLE"
    state = {
        "raw": current,
        "percentile": percentile,
        "change_1h": change_1h,
        "change_3h": change_3h,
        "rapid_expanding": change_1h >= config.min_1h_expansion_pct,
        "label": label,
        "allow": label != "HIGH_EXPANDING",
        "reason": None if label != "HIGH_EXPANDING" else "high_expanding",
    }
    return {**state, "shock_direction": _bandwidth_shock_direction(features_1h.iloc[-1], state)}


def _unavailable_bandwidth_state(reason: str) -> dict:
    return {
        "raw": None,
        "percentile": None,
        "change_1h": None,
        "change_3h": None,
        "rapid_expanding": False,
        "shock_direction": None,
        "label": "UNAVAILABLE",
        "allow": False,
        "reason": reason,
    }


def entry_risk_state(side: str, features_1h: pd.DataFrame, config) -> dict:
    """Derive one completed-candle entry-risk decision without persisting state."""
    slope_state = adverse_slope_state(side, features_1h, config.adverse_slope_take_profit)
    try:
        slow_slope_pct = _middle_slope_at(features_1h, len(features_1h) - 1, config.adverse_slope_take_profit.slope_n)
    except (KeyError, TypeError, ValueError, IndexError):
        slow_slope_pct = None
    bandwidth = bandwidth_state(features_1h, config.bandwidth_entry_guard)
    direction = bandwidth["shock_direction"]
    linkage_state, source_bucket, shock_age = "none", None, None
    if direction and _adverse_side(direction) == side:
        linkage_state, source_bucket, shock_age = "bw_shock_block", features_1h.index[-1], 0
    elif slope_state == "normal":
        for age in (1, 2):
            position = len(features_1h) - age - 1
            if position < 0:
                continue
            prior = bandwidth_state(features_1h.iloc[: position + 1], config.bandwidth_entry_guard)
            prior_direction = prior["shock_direction"]
            if prior_direction and _adverse_side(prior_direction) == side and _middle_continues(features_1h, position, prior_direction):
                linkage_state, direction, source_bucket, shock_age = "bw_continuation_special", prior_direction, features_1h.index[position], age
                break
    effective_state = slope_state if slope_state in {"special", "exspecial"} else "special" if slope_state is None or linkage_state == "bw_continuation_special" else "normal"
    reason = bandwidth["reason"] or ("bw_shock_block" if linkage_state == "bw_shock_block" else None)
    return {
        "slow_slope_state": slope_state,
        "slow_slope_pct": slow_slope_pct,
        "effective_state": effective_state,
        "rsi_threshold": config.rsi.oversold if side == "long" and effective_state == "normal" else config.rsi.adverse_slope_oversold if side == "long" else config.rsi.overbought if effective_state == "normal" else config.rsi.adverse_slope_overbought,
        "allow": bool(bandwidth["allow"]) and linkage_state != "bw_shock_block",
        "reason": reason,
        "bandwidth": bandwidth,
        "shock_direction": direction,
        "linkage_state": linkage_state,
        "source_shock_bucket": source_bucket,
        "shock_age": shock_age,
    }


def _bandwidth_shock_direction(row: pd.Series, state: dict) -> str | None:
    if not state.get("rapid_expanding"):
        return None
    try:
        close, lower, upper = (float(row[name]) for name in ("close", "lb", "ub"))
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (close, lower, upper)):
        return None
    return "up" if close > upper else "down" if close < lower else None


def _adverse_side(direction: str) -> str:
    return "short" if direction == "up" else "long"


def _middle_continues(features_1h: pd.DataFrame, start: int, direction: str) -> bool:
    for index in range(start + 1, len(features_1h)):
        try:
            previous, current = float(features_1h.iloc[index - 1]["mb"]), float(features_1h.iloc[index]["mb"])
        except (KeyError, TypeError, ValueError):
            return False
        if not all(math.isfinite(value) for value in (previous, current)) or current == previous:
            return False
        if (current > previous) != (direction == "up"):
            return False
    return True


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


def _entry_extreme_signal(setup: Setup, row_5m: pd.Series, previous_row_5m: pd.Series) -> bool:
    close_5m = float(row_5m["close"])
    if setup.side == "long":
        return close_5m > float(previous_row_5m["high"]) and close_5m < _midpoint(float(setup.row_1h["lb"]), float(setup.row_1h["mb"]))
    return close_5m < float(previous_row_5m["low"]) and close_5m > _midpoint(float(setup.row_1h["mb"]), float(setup.row_1h["ub"]))


def _entry_rsi_direction_signal(setup: Setup, rows_5m: pd.DataFrame) -> bool:
    if len(rows_5m) < 3 or "rsi14" not in rows_5m:
        return False
    values = rows_5m.iloc[-3:]["rsi14"]
    if values.isna().any():
        return False
    first, second, third = (float(value) for value in values)
    return first < second < third if setup.side == "long" else first > second > third


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
