import json
import uuid
import math
import socket
from dataclasses import dataclass

import pandas as pd
from requests.exceptions import ConnectionError, ReadTimeout
from urllib3.exceptions import ReadTimeoutError

from bbmr.trailing import (
    FIVE_MINUTES,
    Setup,
    _confirm_setup,
    _create_setup,
    _entry_signal,
    _entry_extreme_signal,
    _entry_rsi_direction_signal,
    _initial_stop_loss,
    _midpoint,
    adverse_slope_state,
    bandwidth_state,
    entry_risk_state as derive_entry_risk_state,
    latest_completed_row,
    trend_episode,
    trend_pending_cancel_reason,
)
from bbmr.config import load_config
from bbmr.live.state_store import LivePendingSetup, LiveShadowTrigger, LiveStateStore, LiveTrade, MREntryIntent, StopReplacementIntent, TrendPendingOrder, TrendShadowTrade
from bbmr.live.dashboard import archived_states, write_archive_svg
from bbmr.live.symbols import from_exchange_symbol


@dataclass
class LiveRuntime:
    live_config: object
    exchange: object
    store: LiveStateStore
    account: str | None = None

    def __post_init__(self) -> None:
        self.account = self.account or self.store.identity_fingerprint or "test-unbound"
        self.strategy_config = load_config(self.live_config.strategy_config)
        now = self._now()
        self.store.expire_pending_setups(now)
        self.setups: dict[str, Setup] = {}
        for pending_setup in self.store.load_pending_setups(now):
            setup, discard_reason = self._validated_pending_setup(pending_setup, now)
            if setup:
                self.setups[pending_setup.symbol] = setup
            elif discard_reason is None:
                if not self.store.has_event(
                    "pending_setup_validation_deferred",
                    pending_setup.symbol,
                    pending_setup.trigger_time,
                    setup_trigger_time=pending_setup.trigger_time,
                ):
                    self.store.append_event(
                        "pending_setup_validation_deferred",
                        pending_setup.symbol,
                        side=pending_setup.side,
                        setup_trigger_time=pending_setup.trigger_time,
                        event_time=pending_setup.trigger_time,
                        payload_json=json.dumps({"severity": "WARN", "reason": "completed candle transport unavailable"}, sort_keys=True),
                    )
            else:
                self._discard_pending_setup(pending_setup, discard_reason)
        self.dashboard_traces: dict[str, dict] = {}
        self.entry_risk_observations: dict[str, dict] = {}
        self.emergency_protect_reason: str | None = None
        self._account_mutated = False
        self.trend_mode = self.strategy_config.trend_riding.mode
        self.takeover_mode = self.strategy_config.trend_riding.opposite_mr_takeover_mode
        self.trend_episodes: dict[str, object] = {}
        self.trend_states: dict[str, dict] = {}
        self._trend_transition_messages: dict[str, list[str]] = {}
        self._new_trend_pending_ids: set[str] = set()
        if self.trend_mode == "live":
            self.store.truncate_trend_shadow_baseline(now)

    def trend_poll(self, symbol: str, features_1h: pd.DataFrame, features_5m: pd.DataFrame, balance, exchange_positions: list | None = None) -> object | None:
        """Advance one completed-candle trend episode without mutating the exchange."""
        self._update_trend_shadow(symbol, features_1h, features_5m)
        now = self._now()
        slope_config = self.strategy_config.adverse_slope_take_profit
        entry_config = self.strategy_config.trend_riding
        episode = trend_episode(
            features_1h,
            now,
            slope_config.slope_n,
            slope_config.exspecial_slope_threshold_pct,
            entry_config.entry_pullback_pct,
        )
        if episode is None:
            self.trend_episodes.pop(symbol, None)
        else:
            self.trend_episodes[symbol] = episode

        pending = self.store.trend_pending(symbol)
        completed_5m = _completed_features(features_5m, now, "5m")
        completed_1h = _completed_features(features_1h, now, "1h")
        positions = exchange_positions or []
        if pending and completed_1h is not None and not completed_1h.empty:
            latest_bucket = _utc_time(completed_1h.iloc[-1].name)
            if not _same_time(pending.last_1h_bucket, latest_bucket):
                pending.last_1h_bucket = latest_bucket
                self.store.update_trend_pending(pending)
        same_side_position = pending and _matching_exchange_position(positions, symbol, pending.side)

        if pending and not same_side_position:
            reason = self._trend_pending_cancel_reason(symbol, pending, episode, features_1h, positions)
            if reason:
                expired_pending = pending if reason == "pending_ttl_expired" else None
                self._request_trend_pending_cancel(pending, reason)
                self._record_trend_transition(symbol, self._trend_cancel_message(pending, reason, features_1h))
                pending = self.store.trend_pending(symbol)
                if pending is None and expired_pending is not None and self._renew_expired_trend_pending(symbol, episode, features_1h, balance, positions, expired_pending):
                    pending = self.store.trend_pending(symbol)
            elif pending.takeover_phase in {"takeover_triggered", "closing_mr", "flat_cleanup"}:
                entry_reason = self._trend_completed_invalidation_reason(pending.side, features_1h)[0]
                if entry_reason and pending.cancel_reason is None:
                    pending.cancel_reason = entry_reason
                    self.store.update_trend_pending(pending, "trend_takeover_entry_invalidated", {"reason": entry_reason})
                    self._record_trend_transition(symbol, self._trend_cancel_message(pending, entry_reason, features_1h))

        # Shadow uses completed-5m counterfactual truth only after the completed-1h
        # invalidation gate above. It never represents exchange fill timing.
        if pending and pending.mode == "shadow" and pending.status == "intent":
            self._fill_shadow_pending(pending, completed_5m, completed_1h)
            pending = self.store.trend_pending(symbol)

        state = self._trend_state_payload(symbol, episode, pending, features_1h)
        self.trend_states[symbol] = state
        if pending or self.trend_mode == "off" or episode is None:
            return episode

        # Late startup must not backfill an already-running EXSPECIAL episode.
        if episode.current_bucket != episode.episode_bucket:
            state["pending_status"] = "late_start_no_backfill"
            return episode
        if self.store.trend_pending_for_episode(symbol, episode.side, episode.episode_bucket):
            state["pending_status"] = "episode_attempt_already_used"
            return episode
        signal_reason, _details = self._trend_completed_invalidation_reason(episode.side, features_1h)
        if signal_reason:
            state["pending_status"] = "signal_row_invalidated"
            if not self.store.has_event("trend_pending_rejected", symbol, episode.episode_bucket):
                self.store.append_event(
                    "trend_pending_rejected",
                    symbol,
                    side=episode.side,
                    event_time=episode.episode_bucket,
                    payload_json=json.dumps({"reason": signal_reason, "signal_bucket": episode.episode_bucket.isoformat()}, sort_keys=True),
                )
                self._record_trend_transition(symbol, self._trend_cancel_message_for_values(symbol, episode.side, signal_reason, _details))
            return episode
        takeover_mr = self._eligible_opposite_strategy_mr(symbol, episode.side, positions)
        if self.takeover_mode == "off":
            takeover_mr = None
        if self.store.active_mr_entry_intent(symbol) is not None:
            state["pending_status"] = "mr_entry_intent_conflict"
            return episode
        if self.store.open_trend_shadow_trade(symbol) or (self._open_local_for_symbol(symbol) and takeover_mr is None):
            state["pending_status"] = "position_conflict"
            return episode
        if any(from_exchange_symbol(item.symbol) == from_exchange_symbol(symbol) for item in positions) and takeover_mr is None:
            state["pending_status"] = "position_conflict"
            return episode

        equity, _available = _balance_values(balance)
        leverage = self.live_config.execution.trend_riding_leverage
        notional = self.entry_notional(equity, leverage) if equity > 0 else 0.0
        qty = notional / episode.limit_price if notional > 0 and episode.limit_price > 0 else 0.0
        last_5m = None if completed_5m is None or completed_5m.empty else _utc_time(completed_5m.iloc[-1].name)
        snapshot = self._trend_payload(symbol, features_1h, episode, balance, positions)
        pending = TrendPendingOrder(
            pending_id=str(uuid.uuid4()),
            symbol=symbol,
            side=episode.side,
            mode="shadow" if takeover_mr is not None and self.takeover_mode == "shadow" else self.trend_mode,
            status="intent",
            episode_bucket=episode.episode_bucket,
            frozen_close=episode.frozen_close,
            limit_price=episode.limit_price,
            requested_qty=qty,
            notional=notional,
            stop_distance_pct=entry_config.initial_stop_distance_pct,
            client_order_id=_trend_client_order_id(symbol, episode.side, episode.episode_bucket),
            last_1h_bucket=episode.current_bucket,
            last_5m_bucket=last_5m,
            entry_snapshot_json=json.dumps(snapshot, sort_keys=True, default=str),
            expires_at=episode.episode_bucket + pd.Timedelta(hours=entry_config.pending_ttl_hours + 1),
            takeover_phase="waiting_opposite_mr" if takeover_mr else None,
            takeover_trade_id=None if takeover_mr is None else takeover_mr.internal_trade_id,
            takeover_side=None if takeover_mr is None else takeover_mr.side,
        )
        if not self.store.create_trend_pending(pending):
            return episode
        self._new_trend_pending_ids.add(pending.pending_id)
        self.store.append_event(
            "trend_pending_created",
            symbol,
            side=pending.side,
            event_time=episode.episode_bucket,
            payload_json=json.dumps({**snapshot, "pending_id": pending.pending_id}, sort_keys=True, default=str),
        )
        self._record_trend_transition(symbol, self._trend_signal_message(pending, episode, features_1h))
        if pending.mode == "shadow":
            self.store.append_event("trend_shadow_pending_created", symbol, side=pending.side, event_time=episode.episode_bucket, payload_json=json.dumps({"pending_id": pending.pending_id, "limit_price": pending.limit_price}, sort_keys=True))
        safety_reason = self._new_trend_pending_safety_reason(symbol, pending, positions, equity)
        if safety_reason:
            self._request_trend_pending_cancel(pending, safety_reason)
        elif takeover_mr is not None:
            self.store.update_trend_pending(
                pending,
                "trend_takeover_watch_armed",
                {"mr_trade_id": takeover_mr.internal_trade_id, "mr_side": takeover_mr.side, "mr_qty": takeover_mr.qty, "trend_reservation": pending.notional},
            )
            if self.takeover_mode == "shadow":
                self.store.append_event(
                    "trend_takeover_would_takeover",
                    symbol,
                    side=pending.side,
                    event_time=episode.episode_bucket,
                    payload_json=json.dumps({"pending_id": pending.pending_id, "mr_trade_id": takeover_mr.internal_trade_id}, sort_keys=True),
                )
        self.trend_states[symbol] = self._trend_state_payload(symbol, episode, self.store.trend_pending(symbol), features_1h)
        return episode

    def _renew_expired_trend_pending(self, symbol: str, episode, features_1h: pd.DataFrame, balance, positions: list, expired: TrendPendingOrder) -> bool:
        completed = _completed_features(features_1h, self._now(), "1h")
        if (
            episode is None
            or completed is None
            or completed.empty
            or episode.side != expired.side
            or episode.current_bucket != _utc_time(completed.iloc[-1].name)
            or episode.current_bucket + pd.Timedelta(hours=1) != expired.expires_at
            or self.store.trend_pending_for_episode(symbol, episode.side, episode.current_bucket) is not None
            or self._open_local_for_symbol(symbol) is not None
            or any(from_exchange_symbol(item.symbol) == from_exchange_symbol(symbol) for item in positions)
        ):
            return False
        try:
            frozen_close = float(completed.iloc[-1]["close"])
        except (KeyError, TypeError, ValueError):
            return False
        if not math.isfinite(frozen_close) or frozen_close <= 0:
            return False
        equity, _available = _balance_values(balance)
        leverage = self.live_config.execution.trend_riding_leverage
        notional = self.entry_notional(equity, leverage) if equity > 0 else 0.0
        limit_price = frozen_close * (1 - self.strategy_config.trend_riding.entry_pullback_pct if episode.side == "long" else 1 + self.strategy_config.trend_riding.entry_pullback_pct)
        qty = notional / limit_price if notional > 0 and limit_price > 0 else 0.0
        pending = TrendPendingOrder(
            pending_id=str(uuid.uuid4()),
            symbol=symbol,
            side=episode.side,
            mode=self.trend_mode,
            status="intent",
            episode_bucket=episode.current_bucket,
            frozen_close=frozen_close,
            limit_price=limit_price,
            requested_qty=qty,
            notional=notional,
            stop_distance_pct=self.strategy_config.trend_riding.initial_stop_distance_pct,
            client_order_id=_trend_client_order_id(symbol, episode.side, episode.current_bucket),
            last_1h_bucket=episode.current_bucket,
            entry_snapshot_json=json.dumps(self._trend_payload(symbol, features_1h, episode, balance, positions), sort_keys=True, default=str),
            expires_at=episode.current_bucket + pd.Timedelta(hours=self.strategy_config.trend_riding.pending_ttl_hours + 1),
        )
        if not self.store.create_trend_pending(pending):
            return False
        self._new_trend_pending_ids.add(pending.pending_id)
        safety_reason = self._new_trend_pending_safety_reason(symbol, pending, positions, equity)
        if safety_reason:
            self._request_trend_pending_cancel(pending, safety_reason)
            return False
        self.store.append_event(
            "trend_pending_renewed",
            symbol,
            side=pending.side,
            event_time=episode.current_bucket,
            payload_json=json.dumps({"pending_id": pending.pending_id, "replaces_pending_id": expired.pending_id, "frozen_close": frozen_close, "limit_price": limit_price, "expires_at": pending.expires_at.isoformat()}, sort_keys=True),
        )
        return True

    def _record_trend_transition(self, symbol: str, message: str) -> None:
        self._trend_transition_messages.setdefault(symbol, []).append(message)

    def consume_trend_transitions(self, symbol: str) -> list[str]:
        return self._trend_transition_messages.pop(symbol, [])

    def _trend_completed_invalidation_reason(self, side: str, features_1h: pd.DataFrame) -> tuple[str | None, dict]:
        completed = _completed_features(features_1h, self._now(), "1h")
        slope_n = self.strategy_config.adverse_slope_take_profit.slope_n
        if completed is None or len(completed) <= slope_n:
            return "invalid_pending_state", {}
        try:
            row = completed.iloc[-1]
            current_middle = float(row["mb"])
            past_middle = float(completed.iloc[-(slope_n + 1)]["mb"])
            close = float(row["close"])
            signed_slope = current_middle / past_middle - 1
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return "invalid_pending_state", {}
        reason = trend_pending_cancel_reason(
            side,
            signed_slope,
            self.strategy_config.adverse_slope_take_profit.special_slope_threshold_pct,
            close,
            current_middle,
        )
        return reason, {
            "signed_slope": signed_slope,
            "completed_close": close,
            "current_middle": current_middle,
            "completed_bucket": _utc_time(row.name),
        }

    def _trend_signal_message(self, pending: TrendPendingOrder, episode, features_1h: pd.DataFrame) -> str:
        _reason, details = self._trend_completed_invalidation_reason(pending.side, features_1h)
        phase = "WAITING_OPPOSITE_MR" if pending.takeover_phase == "waiting_opposite_mr" else "LOCAL_WAIT"
        return (
            f"TREND SIGNAL {pending.symbol} {pending.mode.upper()} {pending.side.upper()} "
            f"bucket={episode.episode_bucket.isoformat()} slope={episode.first_slope:.6f} "
            f"F={pending.frozen_close:.8f} L={pending.limit_price:.8f} middle={details.get('current_middle', float('nan')):.8f} "
            f"expires={pending.expires_at.isoformat() if pending.expires_at else 'unknown'} phase={phase}"
        )

    def _trend_cancel_message_for_values(self, symbol: str, side: str, reason: str, details: dict) -> str:
        fields = [f"TREND INVALIDATED/CANCEL {symbol} {side.upper()} reason={reason}"]
        if "signed_slope" in details:
            fields.append(f"slope={details['signed_slope']:.6f}")
        if "completed_close" in details:
            fields.append(f"close={details['completed_close']:.8f} middle={details['current_middle']:.8f}")
        return " ".join(fields)

    def _trend_cancel_message(self, pending: TrendPendingOrder, reason: str, features_1h: pd.DataFrame) -> str:
        _current_reason, details = self._trend_completed_invalidation_reason(pending.side, features_1h)
        return self._trend_cancel_message_for_values(pending.symbol, pending.side, reason, details)

    def trend_local_pending_status(self, symbol: str, features_1h: pd.DataFrame) -> str | None:
        pending = self.store.trend_pending(symbol)
        if pending is None or pending.status != "intent":
            return None
        _reason, details = self._trend_completed_invalidation_reason(pending.side, features_1h)
        phase = "WAITING_OPPOSITE_MR" if pending.takeover_phase == "waiting_opposite_mr" else "LOCAL_WAIT"
        return (
            f"TREND {pending.mode.upper()} local pending {pending.side.upper()} F={pending.frozen_close:.8f} "
            f"L={pending.limit_price:.8f} middle={details.get('current_middle', float('nan')):.8f} "
            f"expires={pending.expires_at.isoformat() if pending.expires_at else 'unknown'} "
            f"phase={phase} waiting=L first / middle invalidation"
        )

    def record_trend_mr_outcome(self, symbol: str, events: list[str]) -> None:
        episode = self.trend_episodes.get(symbol)
        if episode is None or self.store.has_event("trend_actual_mr_outcome", symbol, episode.episode_bucket):
            return
        order_opened = any("entry opened" in event for event in events)
        blocked_reason = next((event for event in events if "blocked" in event or "waiting" in event), None)
        outcome = {"status": "final", "events": events, "pending_or_setup_created": any("setup" in event for event in events), "order_opened": order_opened, "local_trade": self._open_local_for_symbol(symbol).source if self._open_local_for_symbol(symbol) else None, "actual_allow": order_opened or blocked_reason is None, "reason": None if order_opened else blocked_reason}
        pending = self.store.trend_pending_for_episode(symbol, episode.side, episode.episode_bucket)
        if pending is not None:
            try:
                snapshot = json.loads(pending.entry_snapshot_json or "{}")
            except json.JSONDecodeError:
                snapshot = {}
            snapshot["actual_mean_reversion"] = outcome
            pending.entry_snapshot_json = json.dumps(snapshot, sort_keys=True, default=str)
            self.store.update_trend_pending(pending, "trend_pending_mr_outcome_recorded", outcome)
        self.store.record_trend_shadow_mr_result(symbol, outcome)
        self.store.append_event("trend_actual_mr_outcome", symbol, side=episode.side, event_time=episode.episode_bucket, payload_json=json.dumps(outcome, sort_keys=True))

    def maybe_open_trend_trade(self, symbol: str, features_1h: pd.DataFrame, features_5m: pd.DataFrame, balance, allow_orders: bool, dry_run: bool, exchange_positions: list, account_orders: list | None = []) -> str | None:
        pending = self.store.trend_pending(symbol)
        if self.trend_mode != "live" or pending is None or pending.mode != "live":
            return None
        if pending.pending_id in self._new_trend_pending_ids:
            self._new_trend_pending_ids.discard(pending.pending_id)
            return self.trend_local_pending_status(symbol, features_1h)
        if pending.takeover_phase and pending.takeover_phase != "trend_entry_intent":
            return self._advance_trend_takeover(pending, allow_orders, dry_run, exchange_positions, features_1h)
        if pending.status == "cancel_requested":
            if not allow_orders or dry_run:
                return f"{symbol} trend pending cancellation waiting for order permission"
            return self._cancel_live_trend_pending(pending)
        if pending.status != "intent":
            return None
        completed_reason, details = self._trend_completed_invalidation_reason(pending.side, features_1h)
        if completed_reason:
            self._request_trend_pending_cancel(pending, completed_reason)
            return self._trend_cancel_message_for_values(symbol, pending.side, completed_reason, details)
        if not allow_orders or dry_run:
            return self.trend_local_pending_status(symbol, features_1h)
        quote, _reference, quote_error = self._entry_market_quality(symbol)
        if quote_error:
            return f"{self.trend_local_pending_status(symbol, features_1h)}; {quote_error}"
        side_price = _quote_value(quote, "ask" if pending.side == "long" else "bid")
        middle = details["current_middle"]
        if (pending.side == "long" and side_price <= middle) or (pending.side == "short" and side_price >= middle):
            self._request_trend_pending_cancel(pending, "live_middle_invalidated")
            return f"TREND INVALIDATED/CANCEL {symbol} {pending.side.upper()} reason=live_middle_invalidated quote={side_price:.8f} middle={middle:.8f}"
        touched = side_price <= pending.limit_price if pending.side == "long" else side_price >= pending.limit_price
        if not touched:
            return self.trend_local_pending_status(symbol, features_1h)
        if not self.store.has_event("trend_pending_touch", symbol, pending.episode_bucket):
            self.store.append_event(
                "trend_pending_touch",
                symbol,
                side=pending.side,
                event_time=pending.episode_bucket,
                payload_json=json.dumps({"pending_id": pending.pending_id, "quote": side_price, "middle": middle, "limit_price": pending.limit_price}, sort_keys=True),
            )
            self._record_trend_transition(
                symbol,
                f"TREND TOUCH {symbol} {pending.side.upper()} quote={side_price:.8f} L={pending.limit_price:.8f} middle={middle:.8f}",
            )
        equity, available = _balance_values(balance)
        leverage = self.live_config.execution.trend_riding_leverage
        if self.emergency_protect_reason or self.store.has_protection_recovery() or equity <= 0 or pending.requested_qty <= 0:
            self._request_trend_pending_cancel(pending, "invalid_or_emergency_state")
            return None
        if self._exchange_position_exists(symbol, exchange_positions) or self._conflicting_open_orders(symbol, pending):
            self._request_trend_pending_cancel(pending, "position_or_order_conflict")
            return None
        reservations = self.account_reservations(account_orders, exclude_trend_pending_id=pending.pending_id)
        if reservations["block_reason"]:
            self._request_trend_pending_cancel(pending, reservations["block_reason"])
            return None
        if available < reservations["margin"] + pending.notional / leverage or _exchange_positions_notional(exchange_positions) + reservations["notional"] + pending.notional > equity * self.live_config.execution.max_total_notional_fraction:
            self._request_trend_pending_cancel(pending, "insufficient_margin_or_notional_limit")
            return None
        try:
            self.exchange.set_leverage(symbol, leverage, self.live_config.exchange.margin_mode)
        except Exception as exc:
            self._request_trend_pending_cancel(pending, f"leverage_setup_failed:{exc}")
            return None
        try:
            qty = self.exchange.format_qty(symbol, pending.requested_qty)
            price = self.exchange.format_price(symbol, pending.limit_price)
            self._account_mutated = True
            order = self.exchange.create_limit_entry(symbol, pending.side, qty, price, pending.client_order_id)
        except Exception as exc:
            pending.status = "ambiguous"
            pending.cancel_reason = f"limit_submit_ambiguous:{exc}"
            self.store.update_trend_pending(pending, "trend_pending_ambiguous", {"reason": pending.cancel_reason})
            return _severity_message("CRITICAL", f"{symbol} trend limit result ambiguous; pending recovery record kept")
        order_id = _order_id(order)
        if order_id is None:
            pending.status = "ambiguous"
            pending.cancel_reason = "limit_submit_missing_order_id"
            self.store.update_trend_pending(pending, "trend_pending_ambiguous", {"reason": pending.cancel_reason})
            return _severity_message("CRITICAL", f"{symbol} trend limit missing order id; pending recovery record kept")
        pending.exchange_order_id = order_id
        pending.status = "open"
        self.store.update_trend_pending(pending, "trend_pending_opened", {"order_id": order_id, "limit_price": pending.limit_price, "qty": qty})
        return f"TREND ORDER {symbol} {pending.side.upper()} exact_L={pending.limit_price:.8f} qty={float(qty):.8f} status=open"

    def _advance_trend_takeover(self, pending: TrendPendingOrder, allow_orders: bool, dry_run: bool, exchange_positions: list, features_1h: pd.DataFrame) -> str | None:
        if pending.takeover_phase == "waiting_opposite_mr":
            if self.takeover_mode == "off":
                self._request_trend_pending_cancel(pending, "takeover_mode_disabled")
                return f"{pending.symbol} trend takeover disabled"
            if self.takeover_mode == "shadow":
                if not self.store.has_event("trend_takeover_would_takeover", pending.symbol, pending.episode_bucket):
                    self.store.append_event(
                        "trend_takeover_would_takeover",
                        pending.symbol,
                        side=pending.side,
                        event_time=pending.episode_bucket,
                        payload_json=json.dumps({"pending_id": pending.pending_id, "mr_trade_id": pending.takeover_trade_id}, sort_keys=True),
                    )
                return f"{pending.symbol} trend takeover shadow waiting"
            completed_reason, details = self._trend_completed_invalidation_reason(pending.side, features_1h)
            if completed_reason:
                self._request_trend_pending_cancel(pending, completed_reason)
                return self._trend_cancel_message_for_values(pending.symbol, pending.side, completed_reason, details)
            try:
                fresh_positions = self.exchange.fetch_positions()
            except Exception as exc:
                return _severity_message("CRITICAL", f"{pending.symbol} trend takeover waiting for fresh ownership truth: {exc}")
            trade = self._eligible_opposite_strategy_mr(pending.symbol, pending.side, fresh_positions)
            if trade is None or trade.internal_trade_id != pending.takeover_trade_id or trade.side != pending.takeover_side:
                self._request_trend_pending_cancel(pending, "takeover_eligibility_lost")
                return f"{pending.symbol} trend takeover eligibility lost; pending canceled"
            quote, _reference, quote_error = self._entry_market_quality(pending.symbol)
            if quote_error:
                return f"{pending.symbol} trend takeover waiting; {quote_error}"
            side_price = _quote_value(quote, "ask" if pending.side == "long" else "bid")
            middle = details["current_middle"]
            if (pending.side == "long" and side_price <= middle) or (pending.side == "short" and side_price >= middle):
                self._request_trend_pending_cancel(pending, "live_middle_invalidated")
                return f"TREND INVALIDATED/CANCEL {pending.symbol} {pending.side.upper()} reason=live_middle_invalidated quote={side_price:.8f} middle={middle:.8f}"
            touched = side_price is not None and (side_price <= pending.limit_price if pending.side == "long" else side_price >= pending.limit_price)
            if not touched:
                return f"{pending.symbol} trend takeover waiting for fresh touch"
            pending.takeover_phase = "takeover_triggered"
            self.store.update_trend_pending(
                pending,
                "trend_takeover_triggered",
                {"quote": side_price, "middle": middle, "limit_price": pending.limit_price, "mr_trade_id": pending.takeover_trade_id},
            )

        if pending.takeover_phase in {"takeover_triggered", "closing_mr"}:
            try:
                fresh_positions = self.exchange.fetch_positions()
            except Exception as exc:
                return _severity_message("CRITICAL", f"{pending.symbol} trend takeover waiting for fresh position truth: {exc}")
            symbol_positions = [item for item in fresh_positions if from_exchange_symbol(item.symbol) == from_exchange_symbol(pending.symbol)]
            if not symbol_positions:
                pending.takeover_phase = "flat_cleanup"
                self.store.update_trend_pending(pending, "trend_takeover_flat_confirmed", {"mr_trade_id": pending.takeover_trade_id})
                return self._complete_trend_takeover_cleanup(pending, dry_run)
            if len(symbol_positions) != 1 or symbol_positions[0].side != pending.takeover_side or symbol_positions[0].qty <= 0:
                return _severity_message("CRITICAL", f"{pending.symbol} trend takeover position ownership is ambiguous")
            trade = self._takeover_trade(pending)
            if trade is None:
                return _severity_message("CRITICAL", f"{pending.symbol} trend takeover local MR ownership missing")
            position = symbol_positions[0]
            if abs(trade.qty - position.qty) > 1e-8:
                trade.qty = position.qty
                self.store.update_trade_with_event(
                    trade,
                    "trend_takeover_partial_remaining",
                    pending.symbol,
                    event_kwargs={"event_time": self._now(), "payload_json": json.dumps({"remaining_qty": position.qty}, sort_keys=True)},
                )
            if not allow_orders or dry_run:
                return f"{pending.symbol} trend takeover close waiting for order permission"
            pending.takeover_phase = "closing_mr"
            pending.takeover_close_attempted = True
            self.store.update_trend_pending(
                pending,
                "trend_takeover_mr_close_requested",
                {"mr_trade_id": trade.internal_trade_id, "qty": position.qty},
            )
            try:
                self._account_mutated = True
                close_order = self.exchange.close_position_market(pending.symbol, trade.side, self.exchange.format_qty(pending.symbol, position.qty))
                pending.takeover_close_order_id = _order_id(close_order)
                self.store.update_trend_pending(pending, "trend_takeover_mr_close_submitted", {"close_order_id": pending.takeover_close_order_id, "qty": position.qty})
            except Exception as exc:
                self.store.update_trend_pending(pending, "trend_takeover_mr_close_ambiguous", {"reason": str(exc), "qty": position.qty})
                return _severity_message("CRITICAL", f"{pending.symbol} trend takeover close result ambiguous; fresh truth required")
            try:
                after_close = self.exchange.fetch_positions()
            except Exception as exc:
                return _severity_message("CRITICAL", f"{pending.symbol} trend takeover close submitted; fresh truth unavailable: {exc}")
            remaining = [item for item in after_close if from_exchange_symbol(item.symbol) == from_exchange_symbol(pending.symbol)]
            if remaining:
                remaining_position = remaining[0]
                trade.qty = remaining_position.qty
                self.store.update_trade_with_event(
                    trade,
                    "trend_takeover_mr_partial",
                    pending.symbol,
                    event_kwargs={"event_time": self._now(), "payload_json": json.dumps({"remaining_qty": remaining_position.qty}, sort_keys=True)},
                )
                return f"{pending.symbol} trend takeover partial close confirmed; remaining={remaining_position.qty}"
            pending.takeover_phase = "flat_cleanup"
            self.store.update_trend_pending(pending, "trend_takeover_flat_confirmed", {"mr_trade_id": trade.internal_trade_id})
            return self._complete_trend_takeover_cleanup(pending, dry_run)
        if pending.takeover_phase == "flat_cleanup":
            return self._complete_trend_takeover_cleanup(pending, dry_run)
        return None

    def _takeover_trade(self, pending: TrendPendingOrder) -> LiveTrade | None:
        trade = self._open_local_for_symbol(pending.symbol)
        if trade is None or trade.internal_trade_id != pending.takeover_trade_id or trade.source != "strategy":
            return None
        return trade

    def _complete_trend_takeover_cleanup(self, pending: TrendPendingOrder, dry_run: bool) -> str:
        trade = self._takeover_trade(pending)
        if trade is None:
            return _severity_message("CRITICAL", f"{pending.symbol} trend takeover cleanup missing local MR")
        try:
            positions = self.exchange.fetch_positions()
        except Exception as exc:
            return _severity_message("CRITICAL", f"{pending.symbol} trend takeover flat verification unavailable: {exc}")
        if any(from_exchange_symbol(item.symbol) == from_exchange_symbol(pending.symbol) for item in positions):
            return _severity_message("CRITICAL", f"{pending.symbol} trend takeover flat verification failed")
        if trade.system_stop_order_id and not dry_run:
            try:
                self.exchange.cancel_order(trade.symbol, trade.system_stop_order_id)
                fetch_order = getattr(self.exchange, "fetch_order", None)
                if callable(fetch_order):
                    stop = fetch_order(trade.symbol, trade.system_stop_order_id)
                    if _order_status(stop) not in {"canceled", "cancelled", "rejected", "expired"}:
                        raise RuntimeError("old system stop terminal state not confirmed")
            except Exception as exc:
                if not _is_missing_order_error(exc):
                    self.store.update_trend_pending(pending, "trend_takeover_stop_cleanup_pending", {"reason": str(exc)})
                    return _severity_message("CRITICAL", f"{pending.symbol} trend takeover flat; old-stop cleanup pending")
        self.store.update_trend_pending(pending, "trend_takeover_stop_cleanup_complete", {"mr_trade_id": trade.internal_trade_id})
        self._archive_trade(pending.symbol, trade, "trend_takeover")
        if pending.cancel_reason:
            pending.status = "canceled"
            self.store.update_trend_pending(
                pending,
                "trend_takeover_remained_flat",
                {"reason": pending.cancel_reason, "mr_trade_id": trade.internal_trade_id, "remained_flat": True},
            )
            return f"{pending.symbol} trend takeover flat cleanup complete; trend invalidated and remained flat"
        pending.takeover_phase = "trend_entry_intent"
        self.store.update_trend_pending(pending, "trend_takeover_mr_archived", {"mr_trade_id": trade.internal_trade_id, "remained_flat": True})
        return f"{pending.symbol} trend takeover flat cleanup complete; trend entry revalidation pending"

    def _fill_shadow_pending(self, pending: TrendPendingOrder, completed_5m: pd.DataFrame | None, completed_1h: pd.DataFrame | None) -> None:
        if completed_5m is None or completed_5m.empty or self.store.open_trend_shadow_trade(pending.symbol):
            return
        rows = completed_5m if pending.last_5m_bucket is None else completed_5m.loc[completed_5m.index > pending.last_5m_bucket]
        for _, row in rows.iterrows():
            pending.last_5m_bucket = _utc_time(row.name)
            # Never let historical 5m bars from before the signal fill a late-created order.
            if _utc_time(row.name + FIVE_MINUTES) <= pending.episode_bucket + pd.Timedelta(hours=1):
                self.store.update_trend_pending(pending)
                continue
            if completed_1h is None or completed_1h.empty:
                self.store.update_trend_pending(pending)
                continue
            middle = float(completed_1h.iloc[-1]["mb"])
            side_price = float(row["low"] if pending.side == "long" else row["high"])
            middle_invalidated = side_price <= middle if pending.side == "long" else side_price >= middle
            if middle_invalidated:
                self._request_trend_pending_cancel(pending, "shadow_middle_invalidated")
                self._record_trend_transition(
                    pending.symbol,
                    f"TREND INVALIDATED/CANCEL {pending.symbol} {pending.side.upper()} reason=shadow_middle_invalidated quote={side_price:.8f} middle={middle:.8f}",
                )
                return
            touched = side_price <= pending.limit_price if pending.side == "long" else side_price >= pending.limit_price
            if not touched:
                self.store.update_trend_pending(pending)
                continue
            stop = _initial_stop_loss(pending.side, pending.limit_price, pending.stop_distance_pct)
            entry_time = _utc_time(row.name + FIVE_MINUTES)
            shadow = TrendShadowTrade(
                str(uuid.uuid4()), pending.symbol, pending.side, "open", entry_time,
                pending.limit_price, pending.requested_qty, pending.notional, stop, stop,
                pending.episode_bucket, last_5m_bucket=_utc_time(row.name), favorable_price=pending.limit_price,
                entry_snapshot_json=pending.entry_snapshot_json,
            )
            pending.status = "filled"
            payload = {"fill_price": pending.limit_price, "qty": pending.requested_qty, "simulated_completed_5m": True, "entry_fee_bps": self.strategy_config.costs.taker_fee_bps, "liquidity_assumption": "taker_on_touch"}
            self.store.update_trend_pending(pending, "trend_pending_filled", payload)
            self.store.append_event("trend_shadow_pending_filled", pending.symbol, side=pending.side, event_time=entry_time, payload_json=json.dumps({"pending_id": pending.pending_id, **payload}, sort_keys=True))
            self.store.create_trend_shadow_trade(shadow, {**json.loads(pending.entry_snapshot_json), "pending_id": pending.pending_id, "fill_price": pending.limit_price, "simulated_completed_5m": True})
            return

    def _trend_pending_cancel_reason(self, symbol: str, pending: TrendPendingOrder, episode, features_1h: pd.DataFrame, positions: list) -> str | None:
        if pending.takeover_phase in {"takeover_triggered", "closing_mr", "flat_cleanup"}:
            return None
        if pending.expires_at is not None and _utc_time(self._now()) >= pending.expires_at:
            return "pending_ttl_expired"
        if self.trend_mode != pending.mode or self.trend_mode == "off":
            return "mode_changed_or_disabled"
        if self.emergency_protect_reason:
            return "emergency_protection_active"
        if pending.takeover_phase != "waiting_opposite_mr" and (self._open_local_for_symbol(symbol) or any(from_exchange_symbol(item.symbol) == from_exchange_symbol(symbol) for item in positions)):
            return "position_conflict"
        if pending.takeover_phase != "waiting_opposite_mr" and self._conflicting_open_orders(symbol, pending):
            return "open_order_conflict"
        return self._trend_completed_invalidation_reason(pending.side, features_1h)[0]

    def _new_trend_pending_safety_reason(self, symbol: str, pending: TrendPendingOrder, positions: list, equity: float) -> str | None:
        if pending.mode not in {"shadow", "live"} or equity <= 0 or pending.requested_qty <= 0 or pending.notional <= 0:
            return "invalid_sizing_or_mode"
        if self.emergency_protect_reason or self.store.has_protection_recovery():
            return "position_or_emergency_conflict"
        if pending.takeover_phase != "waiting_opposite_mr" and self._open_local_for_symbol(symbol):
            return "position_or_emergency_conflict"
        if pending.takeover_phase != "waiting_opposite_mr" and any(from_exchange_symbol(item.symbol) == from_exchange_symbol(symbol) for item in positions):
            return "position_conflict"
        if self._conflicting_open_orders(symbol, pending):
            return "open_order_conflict"
        return None

    def _request_trend_pending_cancel(self, pending: TrendPendingOrder, reason: str) -> None:
        pending.cancel_reason = reason
        if pending.mode == "live" and (pending.exchange_order_id or pending.status == "ambiguous"):
            pending.status = "cancel_requested"
            event = "trend_pending_cancel_requested"
        else:
            pending.status = "canceled"
            event = "trend_pending_canceled"
        self.store.update_trend_pending(pending, event, {"reason": reason})
        if pending.mode == "shadow":
            self.store.append_event("trend_shadow_pending_canceled", pending.symbol, side=pending.side, event_time=self._now(), payload_json=json.dumps({"pending_id": pending.pending_id, "reason": reason}, sort_keys=True))

    def _cancel_live_trend_pending(self, pending: TrendPendingOrder) -> str:
        try:
            positions = self.exchange.fetch_positions()
        except Exception as exc:
            return _severity_message("CRITICAL", f"{pending.symbol} trend cancel waiting for position check: {exc}")
        if _matching_exchange_position(positions, pending.symbol, pending.side):
            return f"{pending.symbol} trend fill detected; reconciliation pending"
        if not pending.exchange_order_id:
            fetch_order = getattr(self.exchange, "fetch_order", None)
            if not callable(fetch_order):
                return _severity_message("CRITICAL", f"{pending.symbol} trend pending cannot recover ambiguous order by client id")
            try:
                order = fetch_order(pending.symbol, None, pending.client_order_id)
            except Exception as exc:
                return _severity_message("CRITICAL", f"{pending.symbol} trend pending client-id lookup failed: {exc}")
            status = str(order.get("status", "")).lower() if isinstance(order, dict) else ""
            pending.exchange_order_id = _order_id(order)
            if status in {"canceled", "cancelled", "rejected", "expired"}:
                pending.status = "rejected" if status == "rejected" else "canceled"
                pending.cancel_reason = pending.cancel_reason or f"exchange_order_{status}"
                self.store.update_trend_pending(pending, "trend_pending_terminal", {"exchange_status": status})
                return f"{pending.symbol} trend pending terminal; {status}"
            if not pending.exchange_order_id:
                self.store.update_trend_pending(pending, "trend_pending_ambiguous", {"reason": "client-id lookup returned no order id"})
                return _severity_message("CRITICAL", f"{pending.symbol} trend pending client-id lookup returned no order id")
            self.store.update_trend_pending(pending, "trend_pending_recovered", {"order_id": pending.exchange_order_id, "exchange_status": status})
        try:
            self._account_mutated = True
            self.exchange.cancel_order(pending.symbol, pending.exchange_order_id)
        except Exception as exc:
            if not _is_missing_order_error(exc):
                return _severity_message("CRITICAL", f"{pending.symbol} trend pending cancel failed: {exc}")
        try:
            positions = self.exchange.fetch_positions()
        except Exception as exc:
            return _severity_message("CRITICAL", f"{pending.symbol} trend cancel unconfirmed: {exc}")
        if _matching_exchange_position(positions, pending.symbol, pending.side):
            return f"{pending.symbol} trend fill won cancel race; reconciliation pending"
        pending.status = "canceled"
        self.store.update_trend_pending(pending, "trend_pending_canceled", {"reason": pending.cancel_reason})
        return f"{pending.symbol} trend pending canceled; {pending.cancel_reason}"

    def _conflicting_open_orders(self, symbol: str, pending: TrendPendingOrder) -> bool:
        fetch = getattr(self.exchange, "fetch_open_orders", None)
        if not callable(fetch):
            return False
        try:
            orders = fetch(symbol)
        except Exception:
            return True
        for order in orders:
            order_id = str(order.get("id")) if isinstance(order, dict) and order.get("id") not in (None, "") else None
            client_id = None
            if isinstance(order, dict):
                client_id = order.get("clientOrderId") or order.get("client_order_id") or (order.get("info") or {}).get("cloid")
            if order_id == pending.exchange_order_id or (client_id and str(client_id) == pending.client_order_id):
                continue
            return True
        return False

    def _trend_state_payload(self, symbol: str, episode, pending: TrendPendingOrder | None, features_1h: pd.DataFrame) -> dict:
        bandwidth = self.bandwidth_guard_state(features_1h)
        return {
            "mode": self.trend_mode,
            "episode": None if episode is None else {
                "side": episode.side,
                "episode_bucket": episode.episode_bucket.isoformat(),
                "current_bucket": episode.current_bucket.isoformat(),
                "frozen_close": episode.frozen_close,
                "limit_price": episode.limit_price,
                "current_slope": episode.current_slope,
            },
            "pending_id": None if pending is None else pending.pending_id,
            "pending_status": None if pending is None else pending.status,
            "cancel_reason": None if pending is None else pending.cancel_reason,
            "expires_at": None if pending is None or pending.expires_at is None else pending.expires_at.isoformat(),
            "takeover_phase": None if pending is None else pending.takeover_phase,
            "takeover_trade_id": None if pending is None else pending.takeover_trade_id,
            "takeover_close_attempted": False if pending is None else pending.takeover_close_attempted,
            "bandwidth": {**_bandwidth_payload(bandwidth), "role": "mean_reversion_evidence_only", "trend_veto": False},
        }

    def _trend_payload(self, symbol: str, features_1h: pd.DataFrame, episode, balance, positions) -> dict:
        equity, available = _balance_values(balance)
        bandwidth = self.bandwidth_guard_state(features_1h)
        slope_config = self.strategy_config.adverse_slope_take_profit
        local = self._open_local_for_symbol(symbol)
        setup = self.setups.get(symbol)
        matching_positions = [item for item in positions or [] if from_exchange_symbol(item.symbol) == from_exchange_symbol(symbol)]
        risks = {side: self.entry_risk_state(side, features_1h) for side in ("long", "short")}
        try:
            open_order_conflict = self._exchange_open_orders_exist(symbol)
        except Exception:
            open_order_conflict = None
        return {
            "mode": self.trend_mode,
            "episode_bucket": episode.episode_bucket.isoformat(),
            "side": episode.side,
            "frozen_close": episode.frozen_close,
            "limit_price": episode.limit_price,
            "entry_pullback_pct": self.strategy_config.trend_riding.entry_pullback_pct,
            "canonical_slope": {"slope_n": slope_config.slope_n, "exspecial_threshold_pct": slope_config.exspecial_slope_threshold_pct, "first": episode.first_slope, "current": episode.current_slope},
            "bandwidth": {**_bandwidth_payload(bandwidth), "role": "mean_reversion_evidence_only", "trend_veto": False},
            "mean_reversion_filters": {
                "bandwidth": _bandwidth_payload(bandwidth),
                "slope": {side: {"state": risk.get("slow_slope_state"), "effective_state": risk.get("effective_state"), "allow": risk.get("allow"), "reason": risk.get("reason")} for side, risk in risks.items()},
            },
            "actual_mean_reversion": {"status": "pending", "pending_side": None if setup is None else setup.side, "stage": "confirmed_15m" if setup and setup.confirmed_15m else "baseline" if setup and setup.rsi_15m is not None else "pending" if setup else None},
            "real_baseline": {
                "exchange_positions": [{"side": item.side, "qty": item.qty, "entry_price": item.entry_price} for item in matching_positions],
                "open_order_conflict": open_order_conflict,
                "local_trade": None if local is None else {"internal_trade_id": local.internal_trade_id, "source": local.source, "side": local.side, "qty": local.qty, "entry_price": local.entry_price, "status": local.status, "current_stop_loss": local.current_stop_loss},
                "pending_mean_reversion": None if setup is None else {"side": setup.side, "trigger_time": setup.trigger_time, "expiry_time": setup.expiry_time, "confirmed_15m": setup.confirmed_15m},
            },
            "equity": equity,
            "available_margin": available,
            "exchange_position_count": len(matching_positions),
            "cost_assumptions": {"entry_fee_bps": self.strategy_config.costs.taker_fee_bps, "exit_fee_bps": self.strategy_config.costs.taker_fee_bps, "slippage_bps": self.strategy_config.costs.slippage_bps, "provenance": "local_watch_touch_limit_marketability"},
        }

    def update_trend_trade(self, trade: LiveTrade, features_1h: pd.DataFrame, allow_orders: bool, dry_run: bool = False) -> str | None:
        if trade.status == "exit_cleanup":
            return self._retry_trend_exit_cleanup(trade, dry_run)
        completed = _completed_features(features_1h, self._now(), "1h")
        slope_config = self.strategy_config.adverse_slope_take_profit
        trend_config = self.strategy_config.trend_riding
        if completed is None or len(completed) <= slope_config.slope_n:
            return None
        row = completed.iloc[-1]
        bucket = _utc_time(row.name)
        if _same_time(trade.midband_follow_bucket_start, bucket):
            return None
        previous_bucket = trade.midband_follow_bucket_start
        try: strength = float(row["mb"]) / float(completed.iloc[-(slope_config.slope_n + 1)]["mb"]) - 1
        except (KeyError, TypeError, ValueError, ZeroDivisionError): return None
        strength = strength if trade.side == "long" else -strength
        if not math.isfinite(strength):
            return None
        trade.midband_follow_bucket_start = bucket
        close, middle = float(row["close"]), float(row["mb"])
        if strength < slope_config.special_slope_threshold_pct:
            trade.midband_follow_bucket_start = previous_bucket
            return self._close_trend_market(trade, "trend_normal_fallback", allow_orders, dry_run)
        was_weakening = trade.special_tp_active
        trade.special_tp_active = strength < trend_config.weakening_slope_threshold_pct
        middle_cross = (trade.side == "long" and close <= middle) or (trade.side == "short" and close >= middle)
        if trade.special_tp_active and middle_cross:
            trade.midband_follow_bucket_start = previous_bucket
            self.store.update_trade(trade)
            return self._close_trend_market(trade, "trend_weakening_middle_cross", allow_orders, dry_run)
        if was_weakening != trade.special_tp_active:
            self.store.append_event(
                "trend_weakening_started" if trade.special_tp_active else "trend_weakening_cleared",
                trade.symbol,
                trade=trade,
                event_time=bucket,
                payload_json=json.dumps({"strength": strength, "threshold": trend_config.weakening_slope_threshold_pct}, sort_keys=True),
            )
        favorable = max(trade.adverse_slope_tp_price or trade.entry_price, close) if trade.side == "long" else min(trade.adverse_slope_tp_price or trade.entry_price, close)
        trade.adverse_slope_tp_price = favorable
        candidate = favorable * (1 - trend_config.initial_stop_distance_pct if trade.side == "long" else 1 + trend_config.initial_stop_distance_pct)
        if (trade.side == "long" and close >= float(row["ub"])) or (trade.side == "short" and close <= float(row["lb"])):
            trade.trend_break_even = True
        if trade.trend_break_even:
            candidate = max(candidate, trade.entry_price) if trade.side == "long" else min(candidate, trade.entry_price)
        if (trade.side == "long" and candidate > trade.current_stop_loss) or (trade.side == "short" and candidate < trade.current_stop_loss):
            try:
                mark = float(self.exchange.get_market_price(trade.symbol))
            except Exception as exc:
                reason = f"trend stop mark unavailable: {exc}"
                self.store.append_event("trend_stop_market_price_failed", trade.symbol, trade=trade, event_time=self._now(), payload_json=json.dumps(_severity_payload("CRITICAL", reason=reason), sort_keys=True))
                return _severity_message("CRITICAL", f"{trade.symbol} {reason}; old protective stop retained")
            crossed = candidate >= mark if trade.side == "long" else candidate <= mark
            if crossed:
                return self._close_trend_market(trade, "trend_stop_already_crossed", allow_orders, dry_run)
            old = trade.current_stop_loss; trade.current_stop_loss = candidate
            try: self._replace_stop(trade, allow_orders, dry_run, persist=False)
            except StopReplacementError: trade.current_stop_loss = old; self.store.update_trade(trade); return _severity_message("CRITICAL", f"{trade.symbol} trend protective stop replacement failed")
            self.store.update_trade_with_event(trade, "stop_updated", trade.symbol, event_kwargs={"event_time": self._now(), "payload_json": json.dumps({"reason":"trend_completed_1h","new_stop":candidate},sort_keys=True)}); return f"{trade.symbol} trend stop moved {old} -> {candidate}"
        self.store.update_trade(trade); return None

    def _close_trend_market(self, trade: LiveTrade, reason: str, allow_orders: bool, dry_run: bool) -> str | None:
        if not allow_orders or dry_run: return f"{trade.symbol} {reason}; close skipped"
        try:
            self.exchange.close_position_market(trade.symbol, trade.side, self.exchange.format_qty(trade.symbol, trade.qty))
            if _matching_exchange_position(self.exchange.fetch_positions(), trade.symbol, trade.side):
                raise RuntimeError("zero position not verified")
        except Exception as exc:
            failure = f"{reason}: {exc}"
            self.store.append_event("trend_market_close_failed", trade.symbol, trade=trade, event_time=self._now(), payload_json=json.dumps(_severity_payload("CRITICAL", reason=failure), sort_keys=True))
            return _severity_message("CRITICAL", f"{trade.symbol} trend close failed; old protective stop retained: {exc}")
        try:
            self._cancel_system_stop(trade, dry_run)
        except Exception as exc:
            trade.status = "exit_cleanup"
            self.store.update_trade_with_event(trade, "trend_exit_cleanup_pending", trade.symbol, event_kwargs={"event_time": self._now(), "payload_json": json.dumps(_severity_payload("CRITICAL", reason=f"{reason}: cancel old stop failed: {exc}"), sort_keys=True)})
            return _severity_message("CRITICAL", f"{trade.symbol} zero confirmed; old-stop cleanup pending")
        self._archive_trade(trade.symbol, trade, reason); return f"{trade.symbol} trend position closed; {reason}"

    def _retry_trend_exit_cleanup(self, trade: LiveTrade, dry_run: bool) -> str:
        try:
            self._cancel_system_stop(trade, dry_run)
        except Exception as exc:
            self.store.append_event("trend_exit_cleanup_pending", trade.symbol, trade=trade, event_time=self._now(), payload_json=json.dumps(_severity_payload("CRITICAL", reason=f"retry cancel old stop failed: {exc}"), sort_keys=True))
            return _severity_message("CRITICAL", f"{trade.symbol} old-stop cleanup retry pending")
        self._archive_trade(trade.symbol, trade, "trend_exit_cleanup")
        return f"{trade.symbol} trend exit cleanup completed"

    def trend_active(self, symbol: str) -> bool:
        local = self._open_local_for_symbol(symbol)
        return self.store.trend_pending(symbol) is not None or self.store.open_trend_shadow_trade(symbol) is not None or (local is not None and local.source == "trend_riding")

    def _shadow_baseline_end(self, shadow: TrendShadowTrade, end_time) -> dict:
        entry = json.loads(shadow.entry_snapshot_json)
        current = self._open_local_for_symbol(shadow.symbol)
        return {"baseline_end": {"signal_snapshot": entry, "actual_mr_result": self.store.trend_shadow_baseline(shadow.symbol).get("actual_mr_result") if self.store.trend_shadow_baseline(shadow.symbol) else {"status": "pending"}, "local_trade": None if current is None else {"source": current.source, "side": current.side, "qty": current.qty, "entry_price": current.entry_price, "current_stop_loss": current.current_stop_loss, "status": current.status}, "real_trades": self.store.trend_shadow_baseline_trades(shadow.symbol, shadow.entry_time, end_time)}}

    def _update_trend_shadow(self, symbol: str, features_1h: pd.DataFrame, features_5m: pd.DataFrame) -> None:
        shadow = self.store.open_trend_shadow_trade(symbol)
        if shadow is None:
            return
        completed_5m, completed_1h = _completed_features(features_5m, self._now(), "5m"), _completed_features(features_1h, self._now(), "1h")
        timeline = []
        if completed_5m is not None:
            rows = completed_5m if shadow.last_5m_bucket is None else completed_5m.loc[completed_5m.index > shadow.last_5m_bucket]
            timeline.extend((_utc_time(row.name + FIVE_MINUTES), 0, "5m", row) for _, row in rows.iterrows())
        if completed_1h is not None:
            rows = completed_1h if shadow.last_1h_bucket is None else completed_1h.loc[completed_1h.index > shadow.last_1h_bucket]
            timeline.extend(
                (_utc_time(row.name + pd.Timedelta(hours=1)), 1, "1h", row)
                for _, row in rows.iterrows()
                if _utc_time(row.name + pd.Timedelta(hours=1)) > shadow.entry_time
            )
        slope_config = self.strategy_config.adverse_slope_take_profit
        trend_config = self.strategy_config.trend_riding
        for _, _, timeframe, row in sorted(timeline, key=lambda item: (item[0], item[1])):
            if timeframe == "5m":
                shadow.last_5m_bucket = _utc_time(row.name)
                high, low = float(row["high"]), float(row["low"])
                shadow.mfe_pct = max(shadow.mfe_pct, ((high - shadow.entry_price) / shadow.entry_price if shadow.side == "long" else (shadow.entry_price - low) / shadow.entry_price) * 100)
                shadow.mae_pct = min(shadow.mae_pct, ((low - shadow.entry_price) / shadow.entry_price if shadow.side == "long" else (shadow.entry_price - high) / shadow.entry_price) * 100)
                crossed = low <= shadow.current_stop_loss if shadow.side == "long" else high >= shadow.current_stop_loss
                if crossed:
                    end_time = _utc_time(row.name + FIVE_MINUTES)
                    self.store.close_trend_shadow_trade(shadow, "protective_stop", shadow.current_stop_loss, end_time, {**self._shadow_baseline_end(shadow, end_time), "mfe_pct": shadow.mfe_pct, "mae_pct": shadow.mae_pct})
                    return
                self.store.update_trend_shadow_trade(shadow)
                continue
            shadow.last_1h_bucket = _utc_time(row.name)
            try:
                position = completed_1h.index.get_loc(row.name)
                current, past = float(row["mb"]), float(completed_1h.iloc[position - slope_config.slope_n]["mb"])
                close, upper, lower = float(row["close"]), float(row["ub"]), float(row["lb"])
            except (KeyError, IndexError, TypeError, ValueError):
                self.store.update_trend_shadow_trade(shadow); continue
            if not past:
                self.store.update_trend_shadow_trade(shadow); continue
            strength = current / past - 1
            strength = strength if shadow.side == "long" else -strength
            if strength < slope_config.special_slope_threshold_pct:
                end_time = _utc_time(row.name + pd.Timedelta(hours=1)); self.store.close_trend_shadow_trade(shadow, "normal_fallback", close, end_time, self._shadow_baseline_end(shadow, end_time)); return
            changed = shadow.weakening != (strength < trend_config.weakening_slope_threshold_pct)
            shadow.weakening = strength < trend_config.weakening_slope_threshold_pct
            if shadow.weakening and ((shadow.side == "long" and close <= current) or (shadow.side == "short" and close >= current)):
                end_time = _utc_time(row.name + pd.Timedelta(hours=1)); self.store.close_trend_shadow_trade(shadow, "weakening_middle_cross", close, end_time, self._shadow_baseline_end(shadow, end_time)); return
            if changed:
                event = "trend_shadow_weakening_started" if shadow.weakening else "trend_shadow_weakening_cleared"
                self.store.update_trend_shadow_trade(shadow, event, {"strength": strength, "threshold": trend_config.weakening_slope_threshold_pct}, row.name)
            favorable = max(shadow.favorable_price or close, close) if shadow.side == "long" else min(shadow.favorable_price or close, close)
            shadow.favorable_price = favorable
            candidate_stop = favorable * (1 - trend_config.initial_stop_distance_pct if shadow.side == "long" else 1 + trend_config.initial_stop_distance_pct)
            if (shadow.side == "long" and close >= upper) or (shadow.side == "short" and close <= lower): shadow.break_even = True
            candidate_stop = max(candidate_stop, shadow.entry_price) if shadow.side == "long" and shadow.break_even else min(candidate_stop, shadow.entry_price) if shadow.break_even else candidate_stop
            if (shadow.side == "long" and candidate_stop > shadow.current_stop_loss) or (shadow.side == "short" and candidate_stop < shadow.current_stop_loss):
                shadow.current_stop_loss = candidate_stop
                self.store.update_trend_shadow_trade(shadow, "trend_shadow_stop_updated", {"stop": candidate_stop}, row.name)
            else:
                self.store.update_trend_shadow_trade(shadow)

    def position_key(self, symbol: str, side: str) -> str:
        return f"{self.account}:{self.live_config.exchange.env}:{from_exchange_symbol(symbol)}:{side}"

    def can_place_orders(self, cli_allow_testnet_orders: bool) -> bool:
        if self.live_config.exchange.env == "testnet":
            return bool(self.live_config.execution.allow_testnet_orders and cli_allow_testnet_orders)
        return False

    def _reconcile_trend_pending(self, symbol: str, positions: list, allow_orders: bool, dry_run: bool) -> tuple[list[str], bool]:
        pending = self.store.trend_pending(symbol)
        if pending is None or pending.mode != "live":
            return [], False
        if pending.takeover_phase in {"waiting_opposite_mr", "takeover_triggered", "closing_mr", "flat_cleanup", "trend_entry_intent"}:
            return [], False
        same_side = _matching_exchange_position(positions, symbol, pending.side)
        symbol_position = next((item for item in positions if from_exchange_symbol(item.symbol) == from_exchange_symbol(symbol)), None)
        if pending.status == "cancel_requested" and same_side is None:
            if not allow_orders or dry_run:
                return [f"{symbol} trend pending cancellation waiting for order permission"], True
            message = self._cancel_live_trend_pending(pending)
            if self.store.trend_pending(symbol) is None:
                return [message], False
            try:
                fresh_positions = self.exchange.fetch_positions()
            except Exception:
                return [message], True
            if _matching_exchange_position(fresh_positions, symbol, pending.side):
                follow_up, _ = self._reconcile_trend_pending(symbol, fresh_positions, allow_orders, dry_run)
                return [message, *follow_up], True
            return [message], True
        if same_side is None:
            if symbol_position is not None:
                if pending.exchange_order_id and allow_orders and not dry_run:
                    try:
                        self.exchange.cancel_order(symbol, pending.exchange_order_id)
                    except Exception as exc:
                        if not _is_missing_order_error(exc):
                            return [_severity_message("CRITICAL", f"{symbol} opposite position found; owned trend order cancel failed: {exc}")], True
                    pending.status = "canceled"
                    pending.cancel_reason = "opposite_position_conflict"
                    self.store.update_trend_pending(pending, "trend_pending_canceled", {"reason": pending.cancel_reason})
                else:
                    self._request_trend_pending_cancel(pending, "opposite_position_conflict")
                return [f"{symbol} opposite position found; trend pending isolated before manual adoption"], True
            if pending.status in {"open", "ambiguous"} and pending.client_order_id:
                fetch_order = getattr(self.exchange, "fetch_order", None)
                if callable(fetch_order):
                    try:
                        order = fetch_order(symbol, pending.exchange_order_id, pending.client_order_id)
                    except Exception:
                        return [], False
                    recovered_id = _order_id(order)
                    if recovered_id:
                        pending.exchange_order_id = recovered_id
                    status = str(order.get("status", "")).lower() if isinstance(order, dict) else ""
                    if status in {"canceled", "cancelled", "rejected", "expired"}:
                        pending.status = "rejected" if status == "rejected" else "canceled"
                        pending.cancel_reason = f"exchange_order_{status}"
                        self.store.update_trend_pending(pending, "trend_pending_terminal", {"exchange_status": status})
                    elif status in {"open", "new"}:
                        pending.status = "open"
                        self.store.update_trend_pending(pending, "trend_pending_recovered", {"order_id": pending.exchange_order_id, "exchange_status": status})
                    elif status in {"closed", "filled"}:
                        pending.status = "ambiguous"
                        pending.cancel_reason = "exchange_reports_fill_without_position"
                        self.store.update_trend_pending(pending, "trend_pending_ambiguous", {"exchange_status": status})
            return [], False

        partial_fill = same_side.qty + 1e-12 < pending.requested_qty
        cancel_warning = None
        if partial_fill:
            cancel_attempt_warning = self._cancel_live_trend_remainder(pending, allow_orders, dry_run)
            same_side, cancel_warning = self._fresh_trend_fill_after_remainder_cancel(pending, same_side)
            if cancel_attempt_warning and cancel_warning:
                cancel_warning = f"{cancel_attempt_warning}; {cancel_warning}"

        open_local = self._open_local_for_symbol(symbol)
        if open_local is not None:
            if open_local.source == "trend_riding" and open_local.side == pending.side:
                open_local.qty = same_side.qty
                open_local.entry_price = same_side.entry_price
                new_initial_stop = _initial_stop_loss(pending.side, same_side.entry_price, pending.stop_distance_pct)
                open_local.initial_stop_loss = new_initial_stop
                open_local.current_stop_loss = max(open_local.current_stop_loss, new_initial_stop) if pending.side == "long" else min(open_local.current_stop_loss, new_initial_stop)
                if allow_orders and not dry_run:
                    try:
                        self._replace_stop(open_local, allow_orders, dry_run)
                        open_local.status = "open"
                    except StopReplacementError as exc:
                        open_local.status = "entry_unprotected"
                        self.store.update_trade(open_local)
                        return [_severity_message("CRITICAL", f"{symbol} additional trend fill protection failed: {exc}")], True
                self.store.update_trade(open_local)
                if cancel_warning:
                    pending.status = "cancel_requested"
                    pending.cancel_reason = f"partial_fill_remainder_cancel_failed:{cancel_warning}"
                    self.store.update_trend_pending(pending, "trend_pending_cancel_requested", {"reason": pending.cancel_reason, "actual_qty": same_side.qty})
                    return [_severity_message("CRITICAL", f"{symbol} trend partial fill protected; remainder cancel still pending: {cancel_warning}")], True
                pending.status = "filled"
                self.store.update_trend_pending(pending, "trend_pending_filled", {"qty": same_side.qty, "entry_price": same_side.entry_price, "recovered": True})
                return [f"{symbol} trend pending reconciled to existing trend position"], True
            return [_severity_message("CRITICAL", f"{symbol} trend fill conflicts with existing local trade; manual recovery required")], True

        stop = _initial_stop_loss(pending.side, same_side.entry_price, pending.stop_distance_pct)
        trade = self.store.create_trade_with_event(
            self.position_key(symbol, pending.side),
            symbol,
            pending.side,
            same_side.qty,
            same_side.entry_price,
            "trend_riding",
            stop,
            entry_time=self._now(),
            entry_slope_state="exspecial",
            status="entry_unprotected",
            event_type="entry_unprotected",
            event_symbol=symbol,
            event_kwargs={"event_time": self._now(), "payload_json": json.dumps(_severity_payload("CRITICAL", reason="trend fill awaiting protective stop"), sort_keys=True)},
        )
        trade.midband_follow_bucket_start = pending.last_1h_bucket
        pending.status = "cancel_requested" if cancel_warning else "filled"
        pending.cancel_reason = f"partial_fill_remainder_cancel_failed:{cancel_warning}" if cancel_warning else None
        self.store.update_trend_pending(
            pending,
            "trend_pending_cancel_requested" if cancel_warning else "trend_pending_filled",
            {"qty": same_side.qty, "entry_price": same_side.entry_price, "partial_fill": partial_fill, "remainder_cancel_warning": cancel_warning},
        )
        if not allow_orders or dry_run:
            return [_severity_message("CRITICAL", f"{symbol} trend fill found; protective stop permission unavailable")], True
        try:
            self._replace_stop(trade, allow_orders, dry_run, persist=False)
        except StopReplacementError as exc:
            return [_severity_message("CRITICAL", f"{symbol} trend fill found but protective stop failed")], True
        trade.status = "open"
        self.store.update_trade_with_event(trade, "entry_opened", symbol, event_kwargs={"event_time": self._now(), "payload_json": json.dumps({"source": "trend_riding", "pending_id": pending.pending_id, "actual_qty": same_side.qty, "actual_entry_price": same_side.entry_price}, sort_keys=True)})
        if cancel_warning:
            return [_severity_message("CRITICAL", f"{symbol} trend partial fill protected; remainder cancel still pending: {cancel_warning}")], True
        return [f"{symbol} trend limit fill reconciled and protected"], True

    def _cancel_live_trend_remainder(self, pending: TrendPendingOrder, allow_orders: bool, dry_run: bool) -> str | None:
        if not allow_orders or dry_run:
            return "order permission unavailable"
        if not pending.exchange_order_id:
            fetch_order = getattr(self.exchange, "fetch_order", None)
            if not callable(fetch_order):
                return "client-id lookup unavailable"
            try:
                pending.exchange_order_id = _order_id(fetch_order(pending.symbol, None, pending.client_order_id))
            except Exception as exc:
                return f"client-id lookup failed: {exc}"
            if not pending.exchange_order_id:
                return "client-id lookup returned no order id"
        try:
            self.exchange.cancel_order(pending.symbol, pending.exchange_order_id)
        except Exception as exc:
            if not _is_missing_order_error(exc):
                return str(exc)
        return None

    def _fresh_trend_fill_after_remainder_cancel(self, pending: TrendPendingOrder, original_position):
        warning = None
        fetch_order = getattr(self.exchange, "fetch_order", None)
        if callable(fetch_order):
            try:
                order = fetch_order(pending.symbol, pending.exchange_order_id, pending.client_order_id)
                recovered_id = _order_id(order)
                if recovered_id:
                    pending.exchange_order_id = recovered_id
                status = str(order.get("status", "")).lower() if isinstance(order, dict) else ""
                if status in {"open", "new"}:
                    warning = "order still open after cancel"
                elif status not in {"canceled", "cancelled", "rejected", "expired", "closed", "filled"}:
                    warning = f"order terminal state unknown: {status or 'missing'}"
            except Exception as exc:
                if not _is_missing_order_error(exc):
                    warning = f"order terminal check failed: {exc}"
        else:
            warning = "order terminal check unavailable"
        try:
            positions = self.exchange.fetch_positions()
        except Exception as exc:
            return original_position, warning or f"final position refresh failed: {exc}"
        final_position = _matching_exchange_position(positions, pending.symbol, pending.side)
        if final_position is None:
            return original_position, warning or "final position missing after remainder cancel"
        return final_position, warning

    def reconcile_symbol(self, symbol: str, positions: list, allow_orders: bool, dry_run: bool = False) -> list[str]:
        events: list[str] = []
        trend_events, stop_after_trend = self._reconcile_trend_pending(symbol, positions, allow_orders, dry_run)
        events.extend(trend_events)
        if stop_after_trend:
            return events
        exchange_position = next((item for item in positions if item.symbol == from_exchange_symbol(symbol)), None)
        open_local = self._open_local_for_symbol(symbol)
        takeover_pending = self.store.trend_pending(symbol)
        if (
            takeover_pending is not None
            and takeover_pending.takeover_phase in {"takeover_triggered", "closing_mr", "flat_cleanup"}
            and open_local is not None
            and open_local.internal_trade_id == takeover_pending.takeover_trade_id
        ):
            return events

        if exchange_position is None and open_local:
            self._cancel_system_stop(open_local, dry_run)
            self._archive_trade(symbol, open_local, "manual_or_exchange_closed")
            events.append(f"{symbol} exchange position disappeared; system stop cancelled and trade archived")
            return events

        if exchange_position is None:
            return events

        key = self.position_key(exchange_position.symbol, exchange_position.side)
        if open_local and open_local.side != exchange_position.side:
            self._cancel_system_stop(open_local, dry_run)
            self._archive_trade(symbol, open_local, "manual_or_exchange_closed")
            open_local = None

        managed_size_changed = False
        if open_local is not None:
            if open_local.status == "entry_unprotected" or not open_local.system_stop_order_id:
                open_local.qty = exchange_position.qty
                open_local.entry_price = exchange_position.entry_price
                stop_distance = self.strategy_config.trend_riding.initial_stop_distance_pct if open_local.source == "trend_riding" else self.strategy_config.trailing_stop.initial_stop_pct
                open_local.initial_stop_loss = _initial_stop_loss(exchange_position.side, exchange_position.entry_price, stop_distance)
                open_local.current_stop_loss = open_local.initial_stop_loss
            elif open_local.qty != exchange_position.qty or open_local.entry_price != exchange_position.entry_price:
                if not self.live_config.execution.manage_full_manual_added_size:
                    self._mark_protection_recovery(open_local, "recovery", "exchange position differs from managed stop quantity")
                    events.append(_severity_message("CRITICAL", f"{symbol} exchange position differs from managed stop quantity; recovery pending"))
                    return events
                open_local.qty = exchange_position.qty
                open_local.entry_price = exchange_position.entry_price
                managed_size_changed = True
            protection_event = self._reconcile_protection(open_local, exchange_position, allow_orders, dry_run)
            if protection_event is not None:
                events.append(protection_event)
                return events
            if managed_size_changed:
                self.store.update_trade_with_event(open_local, "manual_size_changed", symbol, event_kwargs={"event_time": self._now()})
                events.append(f"{symbol} manual position size changed; managing merged exchange quantity")

        if open_local is None:
            if not self.live_config.execution.adopt_manual_positions:
                events.append(f"{symbol} manual position detected; adoption disabled")
                return events
            stop = _initial_stop_loss(exchange_position.side, exchange_position.entry_price, self.strategy_config.trailing_stop.initial_stop_pct)
            trade = self.store.create_trade_with_event(key, exchange_position.symbol, exchange_position.side, exchange_position.qty, exchange_position.entry_price, "manual_adopted", stop, status="entry_unprotected", event_type="manual_adopted", event_symbol=symbol, event_kwargs={"event_time": self._now()})
            try:
                self._replace_stop(trade, allow_orders, dry_run)
            except StopReplacementError as exc:
                events.append(_severity_message("CRITICAL", f"{symbol} manual position adopted without confirmed protection: {exc}"))
                return events
            trade.status = "open"
            self.store.update_trade_with_event(trade, "protective_stop_verified", symbol, event_kwargs={"event_time": self._now()})
            events.append(f"{symbol} manual position detected; adopted into protected trailing stop management")
            return events

        return events

    def maybe_open_strategy_trade(
        self,
        symbol: str,
        features_1h: pd.DataFrame,
        features_15m: pd.DataFrame,
        features_5m: pd.DataFrame,
        balance,
        allow_orders: bool,
        dry_run: bool = False,
        exchange_positions: list | None = None,
        account_orders: list | None = None,
        account_orders_verified: bool = False,
    ) -> list[str]:
        events: list[str] = []
        self._record_entry_trace(symbol, ["current"] + ["muted"] * 7, "no_1h_setup")
        if self.emergency_protect_reason or self.store.has_protection_recovery():
            reason = self.emergency_protect_reason or "protective-stop recovery active"
            self._record_entry_trace(symbol, ["muted"] * 6 + ["current", "muted"], reason)
            events.append(_severity_message("CRITICAL", f"{symbol} strategy entry blocked: {reason}"))
            return events
        if self._open_local_for_symbol(symbol):
            return events
        active_intent = self.store.active_mr_entry_intent(symbol)
        if active_intent is not None:
            return self.reconcile_mr_entry_intent(symbol, exchange_positions or self.exchange.fetch_positions(), allow_orders, dry_run)
        completed_5m = _completed_features(features_5m, self._now(), "5m")
        if completed_5m is None:
            self._record_entry_trace(symbol, ["current", "muted", "muted", "current"] + ["muted"] * 4, "no_completed_5m")
            events.append(f"{symbol} waiting for completed 5m candle")
            return events
        row_5m = completed_5m.iloc[-1]
        close_time = _utc_time(row_5m.name + FIVE_MINUTES)
        setup = self.setups.get(symbol)
        if setup and close_time >= setup.expiry_time:
            self.store.append_event("setup_expired", symbol, side=setup.side, setup_trigger_time=setup.trigger_time, event_time=close_time)
            self.store.expire_pending_setups(close_time)
            self.setups.pop(symbol, None)
            setup = None
        created_setup = False
        if setup is None:
            setup = _create_setup(features_1h, features_15m, close_time, self.strategy_config)
            if setup:
                created_setup = True
                self.setups[symbol] = setup
                self.store.save_pending_setup(_from_setup(symbol, setup))
                self.store.append_event("setup_created", symbol, side=setup.side, setup_trigger_time=setup.trigger_time, event_time=close_time)
                if self.strategy_config.entry_confirmation.require_15m_rsi_reversal:
                    events.append(f"{symbol} 1h setup met; waiting for first 15m RSI baseline")
                else:
                    events.append(f"{symbol} 15m RSI reversal disabled; waiting for 5m entry")
        if not setup:
            completed_1h = _completed_features(features_1h, self._now(), "1h")
            states = ["passed", "current"] + ["muted"] * 6 if completed_1h is not None else ["current"] + ["muted"] * 7
            self._record_entry_trace(symbol, states, "no_1h_setup" if completed_1h is not None else "no_completed_1h", features_1h)
            events.append(f"{symbol} waiting for 1h setup")
            return events

        prior_intent = self.store.mr_intent_for_trigger(self.account, symbol, setup.side, setup.trigger_time, row_5m.name)
        if prior_intent is not None:
            if prior_intent.status == "terminal_no_fill":
                return events + [f"{symbol} completed 5m trigger already consumed by terminal MR no-fill"]
            return self.reconcile_mr_entry_intent(symbol, exchange_positions or self.exchange.fetch_positions(), allow_orders, dry_run)

        entry_risk = self.entry_risk_state(setup.side, features_1h)
        self._record_entry_trace(symbol, ["passed", "passed", "current"] + ["muted"] * 5, None, features_1h, entry_risk, setup.side)
        if not _setup_rsi_passes_risk(setup, entry_risk):
            self._record_entry_trace(symbol, ["passed", "passed", "current"] + ["muted"] * 5, "rsi_threshold", features_1h, entry_risk, setup.side)
            events.append(f"{symbol} entry risk tightened RSI threshold; entry blocked")
            return events

        if self.strategy_config.entry_confirmation.require_15m_rsi_reversal:
            was_confirmed = setup.confirmed_15m
            _confirm_setup(setup, features_15m, close_time)
            if setup.confirmed_15m and not was_confirmed:
                self.store.save_pending_setup(_from_setup(symbol, setup))
                self.store.append_event("setup_confirmed_15m", symbol, side=setup.side, setup_trigger_time=setup.trigger_time, event_time=setup.confirm_15m_time)
            if not setup.confirmed_15m:
                if not created_setup:
                    if setup.rsi_15m is None:
                        events.append(f"{symbol} 1h setup met; waiting for first 15m RSI baseline")
                    else:
                        events.append(f"{symbol} baseline captured; waiting for 15m RSI reversal")
                self._record_entry_trace(symbol, ["passed", "passed", "passed", "current"] + ["muted"] * 4, "15m_confirmation_pending", features_1h, entry_risk, setup.side)
                return events
            events.append(f"{symbol} 15m confirmed; waiting for 5m entry")
        else:
            if not created_setup:
                events.append(f"{symbol} 15m RSI reversal disabled; waiting for 5m entry")
        self._record_shadow_triggers(symbol, setup, completed_5m, close_time)
        if len(completed_5m) < 2 or not _entry_extreme_signal(setup, row_5m, completed_5m.iloc[-2]):
            self._record_entry_trace(symbol, ["passed"] * 4 + ["current"] + ["muted"] * 3, "5m_trigger_pending", features_1h, entry_risk, setup.side)
            return events

        if not entry_risk["allow"]:
            self._record_entry_trace(symbol, ["passed"] * 5 + ["current"] + ["muted"] * 2, entry_risk["reason"], features_1h, entry_risk, setup.side)
            self._record_bandwidth_entry_block(symbol, setup, entry_risk, row_5m, close_time)
            events.append(f"{symbol} BandWidth {entry_risk['linkage_state'].upper() if entry_risk['linkage_state'] != 'none' else entry_risk['bandwidth']['label']}; entry blocked")
            return events
        if self.store.has_event("bandwidth_entry_blocked", symbol, close_time, setup_trigger_time=setup.trigger_time):
            self._record_entry_trace(symbol, ["passed"] * 6 + ["current", "muted"], "bandwidth_entry_blocked", features_1h, entry_risk, setup.side)
            events.append(f"{symbol} completed 5m trigger was previously blocked by BandWidth; waiting for next 5m trigger")
            return events

        slope_state = entry_risk["slow_slope_state"]
        if slope_state == "exspecial":
            self._record_entry_trace(symbol, ["passed"] * 6 + ["current", "muted"], "exspecial", features_1h, entry_risk, setup.side)
            events.append(f"{symbol} EXSPECIAL slope state; strategy entry blocked")
            return events

        if exchange_positions is None:
            exchange_positions = self.exchange.fetch_positions()
        if self._exchange_position_exists(symbol, exchange_positions):
            self._record_entry_trace(symbol, ["passed"] * 6 + ["current", "muted"], "exchange_position_exists", features_1h, entry_risk, setup.side)
            events.append(f"{symbol} exchange position exists; waiting")
            return events
        if account_orders is None and not account_orders_verified:
            try:
                fetch_orders = getattr(self.exchange, "fetch_open_orders", None)
                if not callable(fetch_orders):
                    account_orders = []
                try:
                    account_orders = fetch_orders()
                except TypeError:
                    account_orders = fetch_orders(symbol)
            except Exception:
                account_orders = None
        reservations = self.account_reservations(account_orders)
        if reservations["block_reason"]:
            self._record_entry_trace(symbol, ["passed"] * 6 + ["current", "muted"], reservations["block_reason"], features_1h, entry_risk, setup.side)
            events.append(_severity_message("CRITICAL", f"{symbol} strategy entry blocked: {reservations['block_reason']}"))
            return events

        equity, available = _balance_values(balance)
        if equity <= 0:
            self._record_entry_trace(symbol, ["passed"] * 6 + ["current", "muted"], "account_equity_invalid", features_1h, entry_risk, setup.side)
            events.append(f"{symbol} account equity invalid; waiting")
            return events
        entry_price = float(row_5m["close"])
        selected_leverage = self.entry_leverage(setup.side, features_1h, entry_risk)
        notional = self.entry_notional(equity, selected_leverage)
        proposed_margin = notional / selected_leverage
        if available < reservations["margin"] + proposed_margin:
            self._record_entry_trace(symbol, ["passed"] * 6 + ["current", "muted"], "available_margin_insufficient", features_1h, entry_risk, setup.side)
            events.append(f"{symbol} available margin insufficient; waiting")
            return events
        max_notional = equity * self.live_config.execution.max_total_notional_fraction
        existing_notional = _exchange_positions_notional(exchange_positions)
        if existing_notional + reservations["notional"] + notional > max_notional:
            self._record_entry_trace(symbol, ["passed"] * 6 + ["current", "muted"], "risk_cap_exceeded", features_1h, entry_risk, setup.side)
            events.append(f"{symbol} risk cap exceeded; waiting")
            return events
        entry_quote = None
        entry_reference_price = None
        if allow_orders and not dry_run:
            entry_quote, entry_reference_price, quote_error = self._entry_market_quality(symbol)
            if quote_error:
                self._record_entry_trace(symbol, ["passed"] * 6 + ["current", "muted"], quote_error, features_1h, entry_risk, setup.side)
                events.append(f"{symbol} {quote_error}")
                return events
        qty = notional / entry_price
        stop = _initial_stop_loss(setup.side, entry_price, self.strategy_config.trailing_stop.initial_stop_pct)
        slippage_message = None
        slippage_payload = None
        if allow_orders and not dry_run:
            intent = MREntryIntent(
                intent_id=str(uuid.uuid4()), account_id=self.account, symbol=symbol, side=setup.side,
                setup_trigger_time=setup.trigger_time, trigger_bucket=_utc_time(row_5m.name), requested_qty=qty,
                notional=notional, leverage=selected_leverage, margin_reservation=proposed_margin,
                reference_price=entry_reference_price, ioc_boundary_price=_ioc_boundary_price(entry_quote, setup.side, self.live_config.execution.max_entry_slippage_bps),
                client_order_id=_mr_entry_client_order_id(self.account, symbol, setup.side, setup.trigger_time, row_5m.name),
            )
            self.store.create_mr_entry_intent_with_event(intent)
            self._account_mutated = True
            try:
                self.exchange.set_leverage(symbol, selected_leverage, self.live_config.exchange.margin_mode)
            except Exception as exc:
                intent.status = "ambiguous"
                intent.reason = f"leverage setup outcome unknown: {exc}"
                self.store.update_mr_entry_intent_with_event(intent, "mr_entry_intent_ambiguous")
                return events + [_severity_message("ERROR", f"{symbol} entry intent retained after leverage error: {exc}")]
            intent.submit_attempted = True
            intent.status = "submitted"
            self.store.update_mr_entry_intent_with_event(intent, "mr_entry_submit_started")
            try:
                order = self.exchange.create_ioc_entry(symbol, setup.side, self.exchange.format_qty(symbol, qty), entry_quote, intent.client_order_id)
                intent.exchange_order_id = _order_id(order)
                intent.status = "submitted" if intent.exchange_order_id else "ambiguous"
                intent.reason = None if intent.exchange_order_id else "submission response missing order id"
                self.store.update_mr_entry_intent_with_event(intent, "mr_entry_submitted" if intent.exchange_order_id else "mr_entry_intent_ambiguous")
                slippage_message, slippage_payload = self._entry_slippage_warning(symbol, entry_reference_price, _order_fill_price(order))
                positions = self.exchange.fetch_positions()
            except Exception as exc:
                intent.status = "ambiguous"
                intent.reason = f"entry submission/position result unknown: {exc}"
                self.store.update_mr_entry_intent_with_event(intent, "mr_entry_intent_ambiguous")
                return events + [_severity_message("ERROR", f"{symbol} entry result ambiguous; reservation retained")]
            exchange_position = _matching_exchange_position(positions, symbol, setup.side)
            if exchange_position is None or exchange_position.qty <= 0:
                return events + [f"{symbol} MR entry submitted; awaiting fill reconciliation"]
            events.extend(self._recover_mr_intent_fill(intent, exchange_position, allow_orders, dry_run))
            trade = self._open_local_for_symbol(symbol)
            if trade is None or trade.status != "open":
                return events
            if slippage_message:
                events.append(slippage_message)
                self.store.append_event("entry_slippage_exceeded", symbol, trade=trade, setup_trigger_time=setup.trigger_time, event_time=close_time, payload_json=json.dumps(slippage_payload, sort_keys=True))
        else:
            self._record_entry_trace(symbol, ["passed"] * 7 + ["current"], "order_permission_unavailable", features_1h, entry_risk, setup.side)
            events.append(f"{symbol} entry conditions passed; order permission unavailable")
            return events
        self.update_adverse_slope_take_profit(trade, features_1h)
        self._record_entry_trace(symbol, ["passed"] * 8, None, features_1h, entry_risk, setup.side)
        events.append(f"{symbol} entry opened; notional={notional:.2f}, qty={qty:.8f}")
        self.setups.pop(symbol, None)
        self.store.delete_pending_setup(symbol)
        return events

    def update_stop(self, trade: LiveTrade, row_1h: pd.Series, row_5m: pd.Series, allow_orders: bool, dry_run: bool = False) -> str | None:
        if trade.trailing_frozen:
            return None
        old_stage = trade.trailing_stage
        old_bucket = trade.midband_follow_bucket_start
        new_stop, reason = live_updated_stop(trade, row_1h, row_5m, self.strategy_config.trailing_stop.first_step_risk_reduction)
        if new_stop == trade.current_stop_loss and trade.trailing_stage == old_stage and _same_time(trade.midband_follow_bucket_start, old_bucket):
            return None
        old_stop = trade.current_stop_loss
        if new_stop != trade.current_stop_loss:
            trade.current_stop_loss = new_stop
            try:
                self._replace_stop(trade, allow_orders, dry_run, persist=False)
            except StopReplacementError as exc:
                if self.store.stop_replacement(trade.internal_trade_id) is None:
                    trade.current_stop_loss = old_stop
                    trade.trailing_stage = old_stage
                    trade.midband_follow_bucket_start = old_bucket
                self.store.update_trade(trade)
                return _severity_message("CRITICAL", f"{trade.symbol} protective stop replacement failed; new strategy entries blocked: {exc}")
        self.store.update_trade_with_event(trade, "stop_updated", trade.symbol, event_kwargs={"event_time": self._now(), "payload_json": json.dumps({"reason": reason, "old_stop": old_stop, "new_stop": new_stop, "trailing_stage": trade.trailing_stage}, sort_keys=True)})
        if new_stop == old_stop:
            if trade.trailing_stage != old_stage:
                return f"{trade.symbol} {reason}; trailing stage {old_stage} -> {trade.trailing_stage}"
            return f"{trade.symbol} {reason}; midband bucket refreshed"
        return f"{trade.symbol} {reason}; stop moved {old_stop} -> {new_stop}"

    def update_adverse_slope_take_profit(self, trade: LiveTrade, features_1h: pd.DataFrame) -> str | None:
        config = self.strategy_config.adverse_slope_take_profit
        if not config.enabled:
            return None
        completed_1h = _completed_features(features_1h, self._now(), "1h")
        if completed_1h is None:
            if trade.adverse_slope_tp_active:
                return self._activate_exspecial(trade, None)
            if trade.last_valid_slope_state == "normal":
                return None
            trade.trailing_frozen = False
            return self._activate_special(trade, None)
        state = adverse_slope_take_profit_state(trade.side, completed_1h, config)
        valid_state = None if state is None else state["state"]
        if valid_state is not None:
            trade.last_valid_slope_state = valid_state
        regime = "exspecial" if trade.adverse_slope_tp_active else (valid_state or trade.last_valid_slope_state or "special")
        if regime == "exspecial":
            return self._activate_exspecial(trade, state)
        trade.trailing_frozen = False
        if regime == "special":
            return self._activate_special(trade, state)
        if trade.special_tp_active:
            self._clear_special(trade)
            self.store.update_trade(trade)
            self.store.append_event("special_tp_cleared", trade.symbol, trade=trade, event_time=self._now())
            return f"{trade.symbol} SPECIAL 1h middle TP cleared; NORMAL trailing resumed"
        self.store.update_trade(trade)
        return None

    def _activate_special(self, trade: LiveTrade, state: dict | None) -> str | None:
        if state is None and trade.special_tp_active:
            return None
        if state is not None and trade.special_tp_active and _same_time(trade.special_tp_bucket_start, state["bucket_start"]):
            return None
        if state is None:
            target = trade.entry_price
            bucket_start = None
        else:
            current = state["current"]
            middle = float(current["mb"])
            lower = float(current["lb"])
            upper = float(current["ub"])
            fraction = self.strategy_config.adverse_slope_take_profit.special_near_middle_frac
            level = middle - (middle - lower) * fraction if trade.side == "long" else middle + (upper - middle) * fraction
            target = max(level, trade.entry_price) if trade.side == "long" else min(level, trade.entry_price)
            bucket_start = state["bucket_start"]
        first_activation = not trade.special_tp_active
        trade.special_tp_active = True
        trade.special_tp_bucket_start = bucket_start
        trade.special_tp_price = target
        self.store.update_trade(trade)
        if first_activation:
            self.store.append_event("special_tp_activated", trade.symbol, trade=trade, event_time=self._now())
        source = "fallback" if state is None else "rolling 1h middle"
        return f"{trade.symbol} SPECIAL {source} TP active; tp={target}"

    def _activate_exspecial(self, trade: LiveTrade, state: dict | None) -> str | None:
        if state is None:
            if trade.adverse_slope_tp_active and not trade.trailing_frozen:
                trade.trailing_frozen = True
                self.store.update_trade(trade)
            return None
        if trade.adverse_slope_tp_active and _same_time(trade.adverse_slope_tp_bucket_start, state["bucket_start"]):
            return None
        current = state["current"]
        middle = float(current["mb"])
        lower = float(current["lb"])
        upper = float(current["ub"])
        fraction = self.strategy_config.adverse_slope_take_profit.exspecial_near_middle_frac
        target = middle - (middle - lower) * fraction if trade.side == "long" else middle + (upper - middle) * fraction
        first_activation = not trade.adverse_slope_tp_active
        trade.adverse_slope_tp_active = True
        trade.adverse_slope_tp_bucket_start = state["bucket_start"]
        trade.adverse_slope_tp_price = target
        self._clear_special(trade)
        trade.trailing_frozen = True
        self.store.update_trade(trade)
        if first_activation:
            self.store.append_event("exspecial_defensive_mode_activated", trade.symbol, trade=trade, event_time=self._now())
            return f"{trade.symbol} EXSPECIAL defensive mode active; trailing frozen; tp={target}"
        return f"{trade.symbol} EXSPECIAL defensive target refreshed; tp={target}"

    @staticmethod
    def _clear_special(trade: LiveTrade) -> None:
        trade.special_tp_active = False
        trade.special_tp_bucket_start = None
        trade.special_tp_price = None

    def maybe_close_adverse_slope_take_profit(self, trade: LiveTrade, market_price: float, allow_orders: bool, dry_run: bool = False) -> str | None:
        if trade.adverse_slope_tp_active:
            target = trade.adverse_slope_tp_price
            label = "EXSPECIAL defensive"
            reason = "exspecial_defensive_exit"
        elif trade.special_tp_active:
            target = trade.special_tp_price
            label = "SPECIAL"
            reason = "special_take_profit"
        else:
            return None
        if target is None:
            return None
        triggered = market_price >= target if trade.side == "long" else market_price <= target
        if not triggered:
            return None
        if not allow_orders or dry_run:
            return f"{trade.symbol} {label} target triggered; close skipped"
        try:
            close_order = self.exchange.close_position_market(trade.symbol, trade.side, self.exchange.format_qty(trade.symbol, trade.qty))
            positions = self.exchange.fetch_positions()
        except Exception as exc:
            return f"{trade.symbol} {label} target close verification failed; trade remains open: {exc}"
        remaining = _matching_exchange_position(positions, trade.symbol, trade.side)
        if remaining is not None and remaining.qty > 0:
            trade.qty = remaining.qty
            try:
                self._replace_stop(trade, allow_orders, dry_run)
            except StopReplacementError as exc:
                self.store.update_trade(trade)
                return f"{trade.symbol} {label} target partially closed; protective stop replacement failed: {exc}"
            self.store.update_trade(trade)
            return f"{trade.symbol} {label} target partially closed; remaining qty protected"
        self._cancel_system_stop(trade, dry_run)
        self._archive_trade(trade.symbol, trade, reason, close_order, trade.qty)
        return f"{trade.symbol} {label} target triggered; position closed"

    def entry_leverage(self, side: str, features_1h: pd.DataFrame, entry_risk: dict | None = None) -> int:
        state = (entry_risk or self.entry_risk_state(side, features_1h))["effective_state"]
        if state in {"special", "exspecial"}:
            return self.live_config.execution.adverse_slope_leverage
        return self.live_config.execution.leverage

    def entry_slope_state(self, side: str, features_1h: pd.DataFrame) -> str | None:
        config = self.strategy_config.adverse_slope_take_profit
        if not config.enabled:
            return "normal"
        completed_1h = _completed_features(features_1h, self._now(), "1h")
        return adverse_slope_state(side, completed_1h, config) if completed_1h is not None else None

    def entry_risk_state(self, side: str, features_1h: pd.DataFrame) -> dict:
        completed_1h = _completed_features(features_1h, self._now(), "1h")
        if completed_1h is None:
            return {
                "slow_slope_state": None,
                "effective_state": "special",
                "rsi_threshold": self.strategy_config.rsi.adverse_slope_oversold if side == "long" else self.strategy_config.rsi.adverse_slope_overbought,
                "allow": False,
                "reason": "no_completed_1h",
                "bandwidth": self.bandwidth_guard_state(features_1h),
                "shock_direction": None,
                "linkage_state": "none",
                "source_shock_bucket": None,
                "shock_age": None,
            }
        risk = derive_entry_risk_state(side, completed_1h, self.strategy_config)
        return {**risk, "bandwidth": {**risk["bandwidth"], "bucket_start": completed_1h.index[-1]}}

    def bandwidth_guard_state(self, features_1h: pd.DataFrame) -> dict:
        config = self.strategy_config.bandwidth_entry_guard
        if not config.enabled:
            return {"raw": None, "percentile": None, "change_1h": None, "change_3h": None, "rapid_expanding": False, "shock_direction": None, "label": "DISABLED", "allow": True, "reason": None, "bucket_start": None, "linkage_state": "none", "source_shock_bucket": None, "shock_age": None}
        completed_1h = _completed_features(features_1h, self._now(), "1h")
        if completed_1h is None:
            state = {"raw": None, "percentile": None, "change_1h": None, "change_3h": None, "label": "UNAVAILABLE", "allow": False, "reason": "no_completed_1h"}
        else:
            state = bandwidth_state(completed_1h, config)
        linkage_state = "bw_shock_block" if state.get("shock_direction") else "none"
        return {**state, "bucket_start": completed_1h.index[-1] if completed_1h is not None else None, "linkage_state": linkage_state, "source_shock_bucket": completed_1h.index[-1] if state.get("shock_direction") and completed_1h is not None else None, "shock_age": 0 if state.get("shock_direction") else None}

    def observe_bandwidth_state(self, symbol: str, features_1h: pd.DataFrame) -> str | None:
        observation = self.entry_risk_observation(features_1h)
        self.entry_risk_observations[symbol] = observation
        state = observation["bandwidth"]
        bucket_start = state["bucket_start"]
        if bucket_start is None or self.store.has_event("bandwidth_state_observed", symbol, bucket_start):
            return None
        payload = {**_bandwidth_payload(state), "entry_risks": {side: _entry_risk_payload(risk, self.entry_leverage(side, features_1h, risk)) for side, risk in observation["entry_risks"].items()}}
        self.store.append_event("bandwidth_state_observed", symbol, event_time=bucket_start, payload_json=json.dumps(payload, sort_keys=True))
        return _bandwidth_message(symbol, state, payload["entry_risks"])

    def entry_risk_observation(self, features_1h: pd.DataFrame) -> dict:
        return {
            "bandwidth": self.bandwidth_guard_state(features_1h),
            "entry_risks": {side: self.entry_risk_state(side, features_1h) for side in ("long", "short")},
        }

    def _record_entry_trace(self, symbol: str, states: list[str], reason: str | None, features_1h: pd.DataFrame | None = None, entry_risk: dict | None = None, entry_side: str | None = None) -> None:
        observation = self.entry_risk_observations.get(symbol)
        entry_risks = {} if observation is None else observation["entry_risks"]
        source_bandwidth = {} if observation is None else observation["bandwidth"]
        bandwidth = {
            key: value
            for key, value in source_bandwidth.items()
            if key != "bucket_start"
        }
        if bandwidth.get("source_shock_bucket") is not None:
            bandwidth["source_shock_bucket"] = _utc_time(bandwidth["source_shock_bucket"]).isoformat()
        risks = {
            side: {
                "slow_slope_state": risk.get("slow_slope_state"),
                "slow_slope_pct": risk.get("slow_slope_pct"),
                "effective_state": risk.get("effective_state"),
                "rsi_threshold": risk.get("rsi_threshold"),
                "leverage": self.entry_leverage(side, features_1h, risk) if features_1h is not None else None,
                "allow": risk.get("allow"),
                "reason": risk.get("reason"),
                "linkage_state": risk.get("linkage_state", "none"),
                "shock_direction": risk.get("shock_direction"),
                "source_shock_bucket": None if risk.get("source_shock_bucket") is None else _utc_time(risk["source_shock_bucket"]).isoformat(),
                "shock_age": risk.get("shock_age"),
            }
            for side, risk in entry_risks.items()
        }
        self.dashboard_traces[symbol] = {
            "completed_1h_available": features_1h is not None and _completed_features(features_1h, self._now(), "1h") is not None,
            "entry_states": states,
            "entry_block_reason": reason,
            "entry_allowed": states[-1] == "passed",
            "entry_risk": None if entry_side is None else risks.get(entry_side),
            "entry_risks": risks,
            "bandwidth": bandwidth,
        }

    def record_management_trace(self, symbol: str) -> None:
        trade = self.managed_trade(symbol)
        if trade is None:
            return
        prior = self.dashboard_traces.get(symbol, {})
        self.dashboard_traces[symbol] = {
            **prior,
            "entry_states": ["muted"] * 7 + ["current" if trade.source == "manual_adopted" else "passed" if trade.status == "open" else "muted"],
            "entry_block_reason": "entry_unprotected" if trade.status != "open" or trade.protection_status != "protected" else None,
            "entry_allowed": False,
        }

    def update_shadow_outcomes(self, symbol: str, features_5m: pd.DataFrame) -> None:
        completed_5m = _completed_features(features_5m, self._now(), "5m")
        if completed_5m is None:
            return
        row = completed_5m.iloc[-1]
        close_time = _utc_time(row.name + FIVE_MINUTES)
        for trigger in self.store.open_shadow_triggers(symbol):
            if close_time <= trigger.trigger_time:
                continue
            high = float(row["high"])
            low = float(row["low"])
            if trigger.side == "long":
                trigger.mfe = max(trigger.mfe, high - trigger.entry_price)
                trigger.mae = min(trigger.mae, low - trigger.entry_price)
            else:
                trigger.mfe = max(trigger.mfe, trigger.entry_price - low)
                trigger.mae = min(trigger.mae, trigger.entry_price - high)
            if close_time >= trigger.expiry_time:
                trigger.status = "closed"
                self.store.append_event(
                    "shadow_entry_outcome",
                    symbol,
                    side=trigger.side,
                    setup_trigger_time=trigger.setup_trigger_time,
                    event_time=close_time,
                    payload_json=json.dumps({"trigger_id": trigger.trigger_id, "trigger_type": trigger.trigger_type, "mfe": trigger.mfe, "mae": trigger.mae}, sort_keys=True),
                )
            self.store.update_shadow_trigger(trigger)

    def _record_bandwidth_entry_block(self, symbol: str, setup: Setup, entry_risk: dict, row_5m: pd.Series, close_time: pd.Timestamp) -> None:
        state = entry_risk["bandwidth"]
        bucket_start = state.get("bucket_start") or entry_risk.get("source_shock_bucket")
        if bucket_start is None or self.store.has_event("bandwidth_entry_blocked", symbol, close_time, setup_trigger_time=setup.trigger_time):
            return
        payload = {**_bandwidth_payload({**state, "bucket_start": bucket_start}), "setup_side": setup.side, "setup_trigger_time": setup.trigger_time.isoformat(), "completed_5m_bucket": _utc_time(row_5m.name).isoformat(), "completed_5m_close": float(row_5m["close"]), "reason": entry_risk["reason"], "slow_slope_state": entry_risk["slow_slope_state"], "effective_entry_risk": entry_risk["effective_state"], "linkage_state": entry_risk["linkage_state"], "shock_direction": entry_risk["shock_direction"], "source_shock_bucket": None if entry_risk["source_shock_bucket"] is None else _utc_time(entry_risk["source_shock_bucket"]).isoformat(), "shock_age": entry_risk["shock_age"]}
        self.store.append_event("bandwidth_entry_blocked", symbol, side=setup.side, setup_trigger_time=setup.trigger_time, event_time=close_time, payload_json=json.dumps(payload, sort_keys=True))

    def _record_shadow_triggers(self, symbol: str, setup: Setup, completed_5m: pd.DataFrame, close_time: pd.Timestamp) -> None:
        row = completed_5m.iloc[-1]
        trigger_types = []
        if _entry_signal(setup, row):
            trigger_types.append("middle_band")
        if _entry_rsi_direction_signal(setup, completed_5m):
            trigger_types.append("rsi_direction")
        no_chase_boundary = _midpoint(float(setup.row_1h["lb"]), float(setup.row_1h["mb"])) if setup.side == "long" else _midpoint(float(setup.row_1h["mb"]), float(setup.row_1h["ub"]))
        for trigger_type in trigger_types:
            trigger = LiveShadowTrigger(
                str(uuid.uuid4()),
                symbol,
                setup.side,
                trigger_type,
                close_time,
                setup.expiry_time,
                setup.trigger_time,
                float(row["close"]),
                float(setup.row_1h["close"]),
                no_chase_boundary,
            )
            if self.store.record_shadow_trigger(trigger):
                payload = {
                    "trigger_id": trigger.trigger_id,
                    "trigger_type": trigger.trigger_type,
                    "entry_price": trigger.entry_price,
                    "setup_close": trigger.setup_close,
                    "distance_from_setup_close": trigger.entry_price - trigger.setup_close,
                    "no_chase_boundary": trigger.no_chase_boundary,
                    "distance_from_no_chase_boundary": trigger.entry_price - trigger.no_chase_boundary,
                }
                self.store.append_event("shadow_entry_triggered", symbol, side=setup.side, setup_trigger_time=setup.trigger_time, event_time=close_time, payload_json=json.dumps(payload, sort_keys=True))

    def entry_notional(self, equity: float, leverage: int | None = None) -> float:
        selected_leverage = self.live_config.execution.leverage if leverage is None else leverage
        return equity * self.live_config.execution.margin_fraction * selected_leverage

    def _entry_market_quality(self, symbol: str) -> tuple[object | None, float | None, str | None]:
        fetch = getattr(self.exchange, "fetch_market_quote", None)
        if not callable(fetch):
            return None, None, "market quote unavailable; waiting"
        try:
            quote = fetch(symbol)
        except Exception as exc:
            return None, None, f"market quote unavailable; waiting: {exc}"
        bid = _quote_value(quote, "bid")
        ask = _quote_value(quote, "ask")
        if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
            return None, None, "market quote unavailable; waiting"
        reference_price = (ask + bid) / 2
        spread_bps = (ask - bid) / reference_price * 10000
        if spread_bps > self.live_config.execution.max_market_spread_bps:
            return quote, reference_price, f"market spread too wide ({spread_bps:.1f} bps); waiting"
        return quote, reference_price, None

    def _entry_slippage_warning(self, symbol: str, reference_price: float | None, fill_price: float | None) -> tuple[str | None, dict | None]:
        if reference_price is None or fill_price is None or reference_price <= 0 or fill_price <= 0:
            return None, None
        slippage_bps = abs(fill_price - reference_price) / reference_price * 10000
        if slippage_bps <= self.live_config.execution.max_entry_slippage_bps:
            return None, None
        payload = {
            "severity": "WARN",
            "reference_price": reference_price,
            "fill_price": fill_price,
            "slippage_bps": slippage_bps,
            "max_entry_slippage_bps": self.live_config.execution.max_entry_slippage_bps,
        }
        return _severity_message("WARN", f"{symbol} entry fill slippage exceeded ({slippage_bps:.1f} bps); position protected and managed"), payload

    def _open_local_for_symbol(self, symbol: str) -> LiveTrade | None:
        for side in ("long", "short"):
            trade = self.store.open_trade(self.position_key(symbol, side))
            if trade:
                return trade
        return None

    def _eligible_opposite_strategy_mr(self, symbol: str, trend_side: str, positions: list) -> LiveTrade | None:
        trade = self._open_local_for_symbol(symbol)
        if trade is None or trade.source != "strategy" or trade.status != "open" or trade.protection_status != "protected":
            return None
        if trade.side == trend_side or self.store.has_trade_event(trade.internal_trade_id, "manual_size_changed"):
            return None
        position = _matching_exchange_position(positions, symbol, trade.side)
        if position is None or position.qty <= 0 or abs(position.qty - trade.qty) > 1e-8:
            return None
        return trade

    def managed_trade(self, symbol: str) -> LiveTrade | None:
        return self._open_local_for_symbol(symbol)

    def consume_account_mutation(self) -> bool:
        changed = self._account_mutated
        self._account_mutated = False
        return changed

    def account_reservations(self, account_orders: list | None, *, exclude_trend_pending_id: str | None = None) -> dict:
        if account_orders is None:
            return {"notional": 0.0, "margin": 0.0, "entries": [], "block_reason": "account-wide open-order truth unavailable"}
        entries = []
        for intent in self.store.active_mr_entry_intents():
            entries.append({"source": "mr_intent", "id": intent.intent_id, "notional": intent.notional, "margin": intent.margin_reservation})
        for pending in self.store.active_trend_pendings():
            if pending.mode == "live" and pending.pending_id != exclude_trend_pending_id:
                leverage = self.live_config.execution.trend_riding_leverage
                entries.append({"source": "trend_pending", "id": pending.pending_id, "notional": pending.notional, "margin": pending.notional / leverage})
        system_ids = self.store.active_system_stop_order_ids() | {intent.exchange_order_id for intent in self.store.active_mr_entry_intents() if intent.exchange_order_id}
        system_client_ids = {intent.client_order_id for intent in self.store.active_mr_entry_intents()}
        for pending in self.store.active_trend_pendings():
            if pending.mode == "live":
                if pending.exchange_order_id:
                    system_ids.add(pending.exchange_order_id)
                if pending.client_order_id:
                    system_client_ids.add(pending.client_order_id)
        for raw in account_orders:
            raw_id = raw.get("id") if isinstance(raw, dict) else getattr(raw, "id", None)
            raw_client_id = (
                raw.get("clientOrderId", raw.get("client_order_id"))
                if isinstance(raw, dict)
                else getattr(raw, "clientOrderId", getattr(raw, "client_order_id", None))
            )
            if (raw_id is not None and str(raw_id) in system_ids) or (raw_client_id is not None and str(raw_client_id) in system_client_ids):
                continue
            parsed = _open_order_fields(raw)
            if parsed is None:
                return {"notional": 0.0, "margin": 0.0, "entries": entries, "block_reason": "account-wide open-order truth invalid"}
            if parsed["reduce_only"]:
                continue
            entries.append({"source": "manual_order", "id": parsed["id"] or parsed["client_order_id"], "notional": parsed["remaining"] * parsed["price"], "margin": 0.0})
        return {"notional": sum(item["notional"] for item in entries), "margin": sum(item["margin"] for item in entries), "entries": entries, "block_reason": None}

    def reconcile_mr_entry_intent(self, symbol: str, positions: list, allow_orders: bool, dry_run: bool) -> list[str]:
        intent = self.store.active_mr_entry_intent(symbol)
        if intent is None:
            return []
        position = _matching_exchange_position(positions, symbol, intent.side)
        if position is not None and position.qty > 0:
            return self._recover_mr_intent_fill(intent, position, allow_orders, dry_run)
        fetch = getattr(self.exchange, "fetch_order", None)
        if not callable(fetch):
            return [_severity_message("CRITICAL", f"{symbol} MR entry intent order truth unavailable; reservation retained")]
        try:
            raw = fetch(symbol, intent.exchange_order_id, intent.client_order_id)
        except Exception as exc:
            if _is_missing_order_error(exc):
                intent.status = "ambiguous"
                intent.reason = "order lookup missing; submission outcome not confirmed"
                self.store.update_mr_entry_intent_with_event(intent, "mr_entry_intent_ambiguous")
                return [_severity_message("CRITICAL", f"{symbol} MR entry intent missing from lookup; reservation retained")]
            intent.status = "ambiguous"
            intent.reason = f"order truth unavailable: {exc}"
            self.store.update_mr_entry_intent_with_event(intent, "mr_entry_intent_ambiguous")
            return [_severity_message("CRITICAL", f"{symbol} MR entry intent truth unknown; reservation retained")]
        status = _order_status(raw)
        if status in {"canceled", "cancelled", "rejected", "expired"}:
            intent.status = "terminal_no_fill"
            intent.reason = f"exchange terminal status {status}"
            self.store.update_mr_entry_intent_with_event(intent, "mr_entry_intent_terminal_no_fill")
            self._account_mutated = True
            return [f"{symbol} MR entry no-fill confirmed; completed 5m trigger consumed"]
        if status != "open":
            intent.status = "ambiguous"
            intent.reason = "invalid order status"
            self.store.update_mr_entry_intent_with_event(intent, "mr_entry_intent_ambiguous")
            return [_severity_message("CRITICAL", f"{symbol} MR entry intent status invalid; reservation retained")]
        return [f"{symbol} MR entry intent awaiting fill reconciliation"]

    def _recover_mr_intent_fill(self, intent: MREntryIntent, position, allow_orders: bool, dry_run: bool) -> list[str]:
        trade = self._open_local_for_symbol(intent.symbol)
        if trade is None:
            stop = _initial_stop_loss(intent.side, position.entry_price, self.strategy_config.trailing_stop.initial_stop_pct)
            trade = LiveTrade(
                str(uuid.uuid4()), self.position_key(intent.symbol, intent.side), intent.symbol, intent.side,
                position.qty, position.entry_price, "strategy", "entry_unprotected", stop, stop,
                entry_time=self._now(), setup_trigger_time=intent.setup_trigger_time, entry_slope_state="special",
            )
            self.store.create_trade_and_fill_mr_intent_with_event(trade, intent)
            self._account_mutated = True
        if trade.status != "open" or trade.protection_status != "protected":
            try:
                self._replace_stop(trade, allow_orders, dry_run, persist=False)
            except StopReplacementError as exc:
                return [_severity_message("CRITICAL", f"{intent.symbol} recovered MR fill awaiting protective stop: {exc}")]
            self.store.update_trade_with_event(trade, "entry_opened", intent.symbol, event_kwargs={"setup_trigger_time": intent.setup_trigger_time, "event_time": self._now(), "payload_json": json.dumps({"source": "strategy", "recovered": True}, sort_keys=True)})
        self.setups.pop(intent.symbol, None)
        self.store.delete_pending_setup(intent.symbol)
        return [f"{intent.symbol} recovered MR entry fill; protective stop confirmed"]

    def _exchange_position_exists(self, symbol: str, positions: list | None = None) -> bool:
        if positions is not None:
            return any(from_exchange_symbol(position.symbol) == from_exchange_symbol(symbol) for position in positions)
        fetch = getattr(self.exchange, "fetch_positions", None)
        if not callable(fetch):
            return False
        return any(from_exchange_symbol(position.symbol) == from_exchange_symbol(symbol) for position in fetch())

    def _exchange_open_orders_exist(self, symbol: str) -> bool:
        fetch = getattr(self.exchange, "fetch_open_orders", None)
        return bool(fetch(symbol)) if callable(fetch) else False

    def _reconcile_protection(self, trade: LiveTrade, position, allow_orders: bool, dry_run: bool) -> str | None:
        intent = self.store.stop_replacement(trade.internal_trade_id)
        if intent is not None:
            message = self._resume_stop_replacement(trade, intent, allow_orders, dry_run)
            return None if trade.status == "open" and trade.protection_status == "protected" else message
        if trade.status == "entry_unprotected" or not trade.system_stop_order_id:
            try:
                message = self._start_stop_replacement(trade, allow_orders, dry_run, "protective stop missing")
            except StopReplacementError as exc:
                return _severity_message("CRITICAL", f"{trade.symbol} protective stop recovery waiting: {exc}")
            return None if trade.status == "open" and trade.protection_status == "protected" else message
        state, stop, reason = self._read_protective_stop(trade.symbol, trade.system_stop_order_id, None)
        if state == "unknown":
            self._mark_protection_recovery(trade, "unknown", reason or "protective stop read failed")
            return _severity_message("CRITICAL", f"{trade.symbol} protective stop truth unknown; new strategy entries blocked")
        if state != "open" or not self._valid_protective_stop(trade, position, stop, None):
            self._mark_protection_recovery(trade, "recovery", reason or "stored protective stop invalid")
            try:
                message = self._start_stop_replacement(trade, allow_orders, dry_run, "stored protective stop invalid")
            except StopReplacementError as exc:
                return _severity_message("CRITICAL", f"{trade.symbol} protective stop recovery waiting: {exc}")
            return None if trade.status == "open" and trade.protection_status == "protected" else message
        if trade.status != "open" or trade.protection_status != "protected":
            trade.status = "open"
            trade.protection_status = "protected"
            trade.protection_verified_at = self._now()
            trade.protection_reason = None
            self.store.update_trade_with_event(trade, "protective_stop_verified", trade.symbol, event_kwargs={"event_time": trade.protection_verified_at})
            return None
        return None

    def _start_stop_replacement(self, trade: LiveTrade, allow_orders: bool, dry_run: bool, reason: str) -> str:
        if not self.live_config.execution.maintain_exchange_stop or not allow_orders or dry_run:
            self._mark_protection_recovery(trade, "recovery", reason + "; order permission unavailable")
            raise StopReplacementError("protective stop order permission unavailable")
        intent = StopReplacementIntent(
            internal_trade_id=trade.internal_trade_id,
            old_stop_order_id=trade.system_stop_order_id,
            replacement_client_id=_stop_replacement_client_id(trade),
            symbol=trade.symbol,
            side=trade.side,
            qty=trade.qty,
            trigger_price=trade.current_stop_loss,
            reason=reason,
        )
        self._mark_protection_recovery(trade, "recovery", reason)
        self.store.create_stop_replacement_with_event(
            intent,
            trade,
            "protective_stop_replacement_started",
            payload={"old_stop_order_id": intent.old_stop_order_id, "replacement_client_id": intent.replacement_client_id, "qty": intent.qty, "trigger_price": intent.trigger_price, "reason": reason},
        )
        return self._resume_stop_replacement(trade, intent, allow_orders, dry_run)

    def _resume_stop_replacement(self, trade: LiveTrade, intent: StopReplacementIntent, allow_orders: bool, dry_run: bool) -> str:
        if not self.live_config.execution.maintain_exchange_stop or not allow_orders or dry_run:
            self._mark_protection_recovery(trade, "recovery", "protective stop recovery waiting for order permission")
            return _severity_message("CRITICAL", f"{trade.symbol} protective stop recovery waiting for order permission")
        if intent.phase == "create_pending":
            state, stop, reason = self._read_protective_stop(intent.symbol, intent.new_stop_order_id, intent.replacement_client_id)
            if state == "missing" and intent.new_stop_order_id is None and not intent.create_attempted:
                intent.create_attempted = True
                self.store.update_stop_replacement_with_event(
                    intent,
                    trade,
                    "protective_stop_replacement_submit_started",
                    payload={"replacement_client_id": intent.replacement_client_id},
                )
                try:
                    order = self.exchange.create_reduce_only_stop(intent.symbol, intent.side, intent.qty, intent.trigger_price, intent.replacement_client_id)
                except Exception as exc:
                    self._mark_protection_recovery(trade, "unknown", f"protective stop create result unknown: {exc}")
                    return _severity_message("CRITICAL", f"{trade.symbol} protective stop create result unknown; retrying only by persisted client id")
                intent.new_stop_order_id = _order_id(order)
                self.store.update_stop_replacement_with_event(intent, trade, "protective_stop_replacement_submitted", payload={"replacement_client_id": intent.replacement_client_id, "new_stop_order_id": intent.new_stop_order_id})
                if intent.new_stop_order_id is None:
                    self._mark_protection_recovery(trade, "unknown", "protective stop create response missing order id")
                    return _severity_message("CRITICAL", f"{trade.symbol} protective stop create result unknown; retrying by client id")
                state, stop, reason = self._read_protective_stop(intent.symbol, intent.new_stop_order_id, intent.replacement_client_id)
            elif state in {"missing", "unknown"} and intent.new_stop_order_id is None and intent.create_attempted:
                self._mark_protection_recovery(trade, "unknown", reason or "replacement create outcome not confirmed")
                return _severity_message("CRITICAL", f"{trade.symbol} replacement create outcome unknown; retrying only by persisted client id")
            if state == "unknown":
                self._mark_protection_recovery(trade, "unknown", reason or "replacement stop read failed")
                return _severity_message("CRITICAL", f"{trade.symbol} replacement stop truth unknown; retrying by persisted client id")
            if state != "open" or not self._valid_intent_stop(intent, stop):
                self._mark_protection_recovery(trade, "recovery", reason or "replacement stop missing or invalid")
                return _severity_message("CRITICAL", f"{trade.symbol} replacement stop not confirmed; old protection retained when available")
            intent.new_stop_order_id = stop["id"]
            intent.phase = "cancel_pending"
            intent.reason = None
            self.store.update_stop_replacement_with_event(intent, trade, "protective_stop_replacement_confirmed", payload={"new_stop_order_id": intent.new_stop_order_id})
        if intent.old_stop_order_id is None:
            return self._promote_replacement(trade, intent)
        state, _old, reason = self._read_protective_stop(intent.symbol, intent.old_stop_order_id, None)
        if state == "unknown":
            self._mark_protection_recovery(trade, "unknown", reason or "old stop cancel truth unknown")
            return _severity_message("CRITICAL", f"{trade.symbol} old protective stop truth unknown; recovery pending")
        if state == "open":
            try:
                self.exchange.cancel_order(intent.symbol, intent.old_stop_order_id)
            except Exception as exc:
                if not _is_missing_order_error(exc):
                    self._mark_protection_recovery(trade, "unknown", f"old protective stop cancel unknown: {exc}")
                    return _severity_message("CRITICAL", f"{trade.symbol} old protective stop cancel unknown; recovery pending")
            state, _old, reason = self._read_protective_stop(intent.symbol, intent.old_stop_order_id, None)
        if state in {"missing", "terminal"}:
            return self._promote_replacement(trade, intent)
        self._mark_protection_recovery(trade, "unknown" if state == "unknown" else "recovery", reason or "old protective stop cancellation pending")
        return _severity_message("CRITICAL", f"{trade.symbol} replacement stop confirmed; old-stop cancellation pending")

    def _promote_replacement(self, trade: LiveTrade, intent: StopReplacementIntent) -> str:
        trade.system_stop_order_id = intent.new_stop_order_id
        trade.status = "open"
        trade.protection_status = "protected"
        trade.protection_verified_at = self._now()
        trade.protection_reason = None
        self.store.promote_stop_replacement_with_event(trade, intent, "protective_stop_replacement_promoted", payload={"new_stop_order_id": intent.new_stop_order_id})
        return f"{trade.symbol} protective stop confirmed"

    def _mark_protection_recovery(self, trade: LiveTrade, status: str, reason: str) -> None:
        if trade.status == "entry_unprotected" and trade.protection_status == status and trade.protection_reason == reason:
            return
        trade.status = "entry_unprotected"
        trade.protection_status = status
        trade.protection_verified_at = None
        trade.protection_reason = reason
        self.store.update_trade_with_event(
            trade,
            "protective_stop_recovery",
            trade.symbol,
            event_kwargs={"event_time": self._now(), "payload_json": json.dumps(_severity_payload("CRITICAL", reason=reason), sort_keys=True)},
        )

    def _read_protective_stop(self, symbol: str, order_id: str | None, client_order_id: str | None) -> tuple[str, dict | None, str | None]:
        fetch = getattr(self.exchange, "fetch_protective_stop", None)
        if not callable(fetch):
            fetch = getattr(self.exchange, "fetch_order", None)
        if not callable(fetch):
            return "unknown", None, "protective stop lookup unavailable"
        try:
            raw = fetch(symbol, order_id, client_order_id)
        except Exception as exc:
            if _is_missing_order_error(exc):
                return "missing", None, None
            return "unknown", None, str(exc)
        stop = _stop_fields(raw)
        if stop is None:
            return "invalid", None, "malformed protective stop"
        if stop["status"] in {"closed", "canceled", "cancelled", "rejected", "expired"}:
            return "terminal", stop, None
        if stop["status"] != "open":
            return "invalid", stop, "invalid protective stop status"
        return "open", stop, None

    def _valid_protective_stop(self, trade: LiveTrade, position, stop: dict | None, client_order_id: str | None) -> bool:
        if stop is None or stop["id"] != trade.system_stop_order_id:
            return False
        return self._valid_stop_values(trade.symbol, trade.side, position.qty, trade.current_stop_loss, stop, client_order_id)

    def _valid_intent_stop(self, intent: StopReplacementIntent, stop: dict | None) -> bool:
        return stop is not None and self._valid_stop_values(intent.symbol, intent.side, intent.qty, intent.trigger_price, stop, intent.replacement_client_id)

    def _valid_stop_values(self, symbol: str, side: str, qty: float, trigger_price: float, stop: dict, client_order_id: str | None) -> bool:
        if stop["symbol"] != from_exchange_symbol(symbol) or stop["side"] != ("sell" if side == "long" else "buy") or stop["reduce_only"] is not True:
            return False
        if client_order_id is not None and stop["client_order_id"] != client_order_id:
            return False
        try:
            return self.exchange.format_qty(symbol, stop["qty"]) == self.exchange.format_qty(symbol, qty) and self.exchange.format_price(symbol, stop["trigger_price"]) == self.exchange.format_price(symbol, trigger_price)
        except Exception:
            return False

    def _cancel_system_stop(self, trade: LiveTrade, dry_run: bool) -> None:
        if trade.system_stop_order_id and not dry_run:
            try:
                self.exchange.cancel_order(trade.symbol, trade.system_stop_order_id)
            except Exception as exc:
                if not _is_missing_order_error(exc):
                    raise

    def _replace_stop(self, trade: LiveTrade, allow_orders: bool, dry_run: bool, *, persist: bool = True) -> None:
        if self.store.stop_replacement(trade.internal_trade_id) is not None:
            message = self._resume_stop_replacement(trade, self.store.stop_replacement(trade.internal_trade_id), allow_orders, dry_run)
        else:
            message = self._start_stop_replacement(trade, allow_orders, dry_run, "protective stop replacement requested")
        if trade.status != "open" or trade.protection_status != "protected":
            raise StopReplacementError(message)
        if persist:
            self.store.update_trade(trade)

    def _mark_emergency_protect(self, trade: LiveTrade, exc: Exception) -> None:
        reason = f"protective stop replacement failed for {trade.symbol}: {exc}"
        self.emergency_protect_reason = reason
        self.store.append_event(
            "protective_stop_failed",
            trade.symbol,
            trade=trade,
            event_time=self._now(),
            payload_json=json.dumps(_severity_payload("CRITICAL", reason=reason), sort_keys=True),
        )

    def _append_entry_order_not_confirmed(self, symbol: str, setup: Setup, event_time, reason: str) -> None:
        self.store.append_event(
            "entry_order_not_confirmed",
            symbol,
            side=setup.side,
            setup_trigger_time=setup.trigger_time,
            event_time=event_time,
            payload_json=json.dumps(_severity_payload("ERROR", reason=reason), sort_keys=True),
        )

    def _now(self):
        now = getattr(self.exchange, "now", None)
        if callable(now):
            return pd.Timestamp(now())
        return pd.Timestamp.now(tz="UTC")

    def _archive_trade(self, symbol: str, trade: LiveTrade, reason: str, close_order: dict | None = None, close_qty: float | None = None) -> None:
        pnl = self._exit_pnl(symbol, trade, close_order, close_qty)
        if pnl:
            self.store.archive_trade_with_event(
                trade,
                reason,
                "exit_archived",
                symbol,
                exit_time=self._now(),
                exit_price=pnl["exit_price"],
                realized_pnl=pnl["realized_pnl"],
                fees=pnl["fees"],
                pnl_source="exchange",
                event_kwargs={"event_time": self._now(), "payload_json": json.dumps({key: pnl[key] for key in ("pnl_source", "exit_price", "realized_pnl", "fees")}, sort_keys=True)},
            )
        else:
            self.store.archive_trade_with_event(trade, reason, "exit_archived", symbol, exit_time=self._now(), event_kwargs={"event_time": self._now(), "payload_json": json.dumps({"pnl_source": "unknown"}, sort_keys=True)})
        states = archived_states(self.store, trade, reason)
        if not write_archive_svg(self.live_config.storage.sqlite_path, trade, states):
            print(f"[WARN] {symbol} archive SVG unavailable; trade archive preserved")

    def _exit_pnl(self, symbol: str, trade: LiveTrade, close_order: dict | None, close_qty: float | None) -> dict | None:
        fetch = getattr(self.exchange, "fetch_recent_realized_pnl", None)
        if not callable(fetch) or not isinstance(close_order, dict) or close_qty is None:
            return None
        close_order_id = _order_id(close_order)
        close_client_id = _order_client_id(close_order)
        if close_order_id is None and close_client_id is None:
            return None
        try:
            pnl = fetch(symbol, trade, close_order_id=close_order_id, close_client_id=close_client_id, close_qty=close_qty)
        except Exception:
            return None
        if not pnl:
            return None
        try:
            return {
                "exit_price": float(pnl["exit_price"]),
                "realized_pnl": float(pnl["realized_pnl"]),
                "fees": float(pnl.get("fees") or 0),
                "pnl_source": "exchange",
            }
        except (KeyError, TypeError, ValueError):
            return None

    def _validated_pending_setup(self, pending_setup: LivePendingSetup, now) -> tuple[Setup | None, str | None]:
        try:
            features_1h, features_15m, features_5m = latest_completed_features(self.exchange, pending_setup.symbol, self.strategy_config)
        except Exception as exc:
            if _is_recoverable_network_error(exc):
                return None, None
            raise
        row_5m = latest_completed_row(features_5m, now, "5m")
        if row_5m is None:
            return None, "no completed 5m candle"
        close_time = _utc_time(row_5m.name + FIVE_MINUTES)
        if close_time < pending_setup.trigger_time:
            return None, "before setup trigger window"
        if close_time >= pending_setup.expiry_time:
            self.store.append_event(
                "setup_expired",
                pending_setup.symbol,
                side=pending_setup.side,
                setup_trigger_time=pending_setup.trigger_time,
                event_time=close_time,
            )
            return None, "setup expired"
        rebuilt = _create_setup(features_1h, features_15m, close_time, self.strategy_config)
        if rebuilt is None:
            return None, "1h setup no longer valid"
        if rebuilt.side != pending_setup.side or not _same_time(rebuilt.trigger_time, pending_setup.trigger_time):
            return None, "setup side or trigger changed"
        if not _same_time(rebuilt.expiry_time, pending_setup.expiry_time):
            return None, "setup expiry changed"
        if not _same_1h_snapshot(rebuilt.row_1h, pending_setup):
            return None, "1h setup snapshot changed"

        current = Setup(rebuilt.side, rebuilt.row_1h.copy(), rebuilt.trigger_time, rebuilt.expiry_time, confirmation_after=rebuilt.trigger_time)
        _confirm_setup(current, features_15m, close_time)
        if pending_setup.setup_rsi_15m is not None:
            if current.rsi_15m is None or not _same_number(current.rsi_15m, pending_setup.setup_rsi_15m):
                return None, "15m baseline changed"
        if pending_setup.confirmed_15m:
            if not current.confirmed_15m or not _same_time(current.confirm_15m_time, pending_setup.confirm_15m_time):
                return None, "15m confirmation changed"
        return _to_setup(pending_setup), ""

    def _discard_pending_setup(self, pending_setup: LivePendingSetup, reason: str) -> None:
        self.store.delete_pending_setup(pending_setup.symbol)
        self.store.append_event(
            "setup_discarded",
            pending_setup.symbol,
            side=pending_setup.side,
            setup_trigger_time=pending_setup.trigger_time,
            event_time=self._now(),
            payload_json=json.dumps({"reason": reason}, sort_keys=True),
        )
        print(f"{pending_setup.symbol} pending setup discarded on restart: {reason}")


def live_updated_stop(trade: LiveTrade, row_1h: pd.Series, row_5m: pd.Series, first_step_risk_reduction: float = 1.0) -> tuple[float, str]:
    lb_1h = float(row_1h["lb"])
    mid_1h = float(row_1h["mb"])
    ub_1h = float(row_1h["ub"])
    close_5m = float(row_5m["close"])
    high_5m = float(row_5m["high"])
    low_5m = float(row_5m["low"])
    candidates: list[tuple[float, str]] = []
    bucket_start = _midband_follow_bucket_start(row_1h)
    if trade.side == "long":
        midband_follow = trade.trailing_stage >= 3
        stage_activated = False
        if not midband_follow and close_5m > _midpoint(lb_1h, mid_1h):
            first_step_stop = trade.initial_stop_loss + (trade.entry_price - trade.initial_stop_loss) * first_step_risk_reduction
            candidates.append((first_step_stop, "5m close > midpoint(1h lower, 1h middle); first-step risk reduced"))
        if not midband_follow and close_5m > mid_1h:
            candidates.append((trade.entry_price, "5m close > 1h middle"))
        if high_5m >= _midpoint(mid_1h, ub_1h):
            trade.trailing_stage = max(trade.trailing_stage, 3)
            midband_follow = True
            stage_activated = True
        if midband_follow and (stage_activated or _should_refresh_midband_bucket(trade, bucket_start)):
            trade.midband_follow_bucket_start = bucket_start
            reason = "5m high >= midpoint(1h middle, 1h upper); midband-follow activated" if stage_activated else "midband-follow active; following latest completed 1h middle"
            candidates.append((max(mid_1h, trade.entry_price), reason))
        if high_5m > ub_1h:
            candidates.append((close_5m, "5m high > 1h upper"))
        if midband_follow:
            return max(candidates, default=(trade.current_stop_loss, "no stop change"))
        valid = [(stop, reason) for stop, reason in candidates if stop > trade.current_stop_loss]
        return max(valid, default=(trade.current_stop_loss, "no stop change"))

    midband_follow = trade.trailing_stage >= 3
    stage_activated = False
    if not midband_follow and close_5m < _midpoint(ub_1h, mid_1h):
        first_step_stop = trade.initial_stop_loss - (trade.initial_stop_loss - trade.entry_price) * first_step_risk_reduction
        candidates.append((first_step_stop, "5m close < midpoint(1h upper, 1h middle); first-step risk reduced"))
    if not midband_follow and close_5m < mid_1h:
        candidates.append((trade.entry_price, "5m close < 1h middle"))
    if low_5m <= _midpoint(lb_1h, mid_1h):
        trade.trailing_stage = max(trade.trailing_stage, 3)
        midband_follow = True
        stage_activated = True
    if midband_follow and (stage_activated or _should_refresh_midband_bucket(trade, bucket_start)):
        trade.midband_follow_bucket_start = bucket_start
        reason = "5m low <= midpoint(1h lower, 1h middle); midband-follow activated" if stage_activated else "midband-follow active; following latest completed 1h middle"
        candidates.append((min(mid_1h, trade.entry_price), reason))
    if low_5m < lb_1h:
        candidates.append((close_5m, "5m low < 1h lower"))
    if midband_follow:
        return min(candidates, default=(trade.current_stop_loss, "no stop change"))
    valid = [(stop, reason) for stop, reason in candidates if stop < trade.current_stop_loss]
    return min(valid, default=(trade.current_stop_loss, "no stop change"))


def adverse_slope_take_profit_state(side: str, features_1h: pd.DataFrame, config) -> dict | None:
    slope_state = adverse_slope_state(side, features_1h, config)
    current = features_1h.iloc[-1]
    return {"bucket_start": _midband_follow_bucket_start(current), "state": slope_state, "active": slope_state == "exspecial", "current": current}


def _bandwidth_payload(state: dict) -> dict:
    bucket_start = state["bucket_start"]
    return {
        "bucket_start": None if bucket_start is None else _utc_time(bucket_start).isoformat(),
        "raw": state["raw"],
        "percentile": state["percentile"],
        "change_1h": state["change_1h"],
        "change_3h": state["change_3h"],
        "units": {"raw": "ratio", "percentile": "rank_0_100", "change_1h": "relative_ratio", "change_3h": "relative_ratio"},
        "rapid_expanding": state.get("rapid_expanding", False),
        "shock_direction": state.get("shock_direction"),
        "linkage_state": state.get("linkage_state", "none"),
        "source_shock_bucket": None if state.get("source_shock_bucket") is None else _utc_time(state["source_shock_bucket"]).isoformat(),
        "shock_age": state.get("shock_age"),
        "label": state["label"],
        "guard": "ALLOW" if state["allow"] else "BLOCK",
        "reason": state["reason"],
    }


def _entry_risk_payload(risk: dict, leverage: int) -> dict:
    return {
        "slow_slope_state": risk["slow_slope_state"],
        "effective_state": risk["effective_state"],
        "rsi_threshold": risk["rsi_threshold"],
        "leverage": leverage,
        "allow": risk["allow"],
        "reason": risk["reason"],
        "linkage_state": risk["linkage_state"],
        "shock_direction": risk["shock_direction"],
        "source_shock_bucket": None if risk["source_shock_bucket"] is None else _utc_time(risk["source_shock_bucket"]).isoformat(),
        "shock_age": risk["shock_age"],
    }


def _bandwidth_message(symbol: str, state: dict, entry_risks: dict | None = None) -> str:
    payload = _bandwidth_payload(state)
    if state["label"] == "UNAVAILABLE":
        return f"{symbol} BandWidth bucket={payload['bucket_start']} raw=UNAVAILABLE percentile_120h=UNAVAILABLE change_1h=UNAVAILABLE change_3h=UNAVAILABLE linkage=NONE direction=NONE state=UNAVAILABLE BLOCK reason={state['reason']}"
    message = (
        f"{symbol} BandWidth bucket={payload['bucket_start']} raw={state['raw'] * 100:.6f}% "
        f"percentile_120h={state['percentile']:.1f}/100 change_1h={state['change_1h'] * 100:+.6f}% "
        f"change_3h={state['change_3h'] * 100:+.6f}% linkage={state.get('linkage_state', 'none').upper()} "
        f"direction={(state.get('shock_direction') or 'none').upper()} state={state['label']} "
        f"{'ALLOW' if state['allow'] else 'BLOCK'}"
    )
    if not entry_risks:
        return message
    return message + " " + " ".join(
        f"{side}=linkage:{risk['linkage_state'].upper()},source:{risk['source_shock_bucket'] or 'none'},age:{risk['shock_age'] if risk['shock_age'] is not None else 'none'},risk:{risk['effective_state'].upper()},rsi:{risk['rsi_threshold']},leverage:{risk['leverage']}x"
        for side, risk in entry_risks.items()
    )


def _setup_rsi_passes_risk(setup: Setup, entry_risk: dict) -> bool:
    try:
        rsi = float(setup.row_1h["rsi14"])
    except (KeyError, TypeError, ValueError):
        return False
    return rsi < entry_risk["rsi_threshold"] if setup.side == "long" else rsi > entry_risk["rsi_threshold"]


def _completed_features(features: pd.DataFrame, now, timeframe: str) -> pd.DataFrame | None:
    row = latest_completed_row(features, now, timeframe)
    if row is None:
        return None
    return features.loc[: row.name]


def _should_refresh_midband_bucket(trade: LiveTrade, bucket_start: pd.Timestamp | None) -> bool:
    return bucket_start is None or not _same_time(trade.midband_follow_bucket_start, bucket_start)


def _midband_follow_bucket_start(row_1h: pd.Series) -> pd.Timestamp | None:
    name = getattr(row_1h, "name", None)
    if name is None:
        return None
    try:
        return _utc_time(name).floor("h")
    except Exception:
        return None


def latest_completed_features(exchange, symbol: str, strategy_config) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    from bbmr.trailing_features import build_trailing_features

    rsi_limit = strategy_config.rsi.warmup_bars
    five_m_limit = max(strategy_config.bollinger.bb_period + 1, rsi_limit)
    return build_trailing_features(
        exchange.fetch_ohlcv(symbol, "1h", rsi_limit),
        exchange.fetch_ohlcv(symbol, "15m", rsi_limit),
        exchange.fetch_ohlcv(symbol, "5m", five_m_limit),
        strategy_config,
    )


def _is_missing_order_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return exc.__class__.__name__ == "OrderNotFound" or any(
        marker in text for marker in ("never placed", "already canceled", "already cancelled", "filled", "not found")
    )


def _is_recoverable_network_error(exc: Exception) -> bool:
    try:
        from ccxt.base.errors import NetworkError, RequestTimeout
    except Exception:
        NetworkError = ()
        RequestTimeout = ()
    return isinstance(exc, (NetworkError, RequestTimeout, ConnectionError, ReadTimeout, ReadTimeoutError, TimeoutError, socket.timeout))


def _order_fill_price(order: dict) -> float | None:
    for key in ("average", "price"):
        value = order.get(key)
        if value not in (None, ""):
            return float(value)
    return None


def _order_id(order: dict) -> str | None:
    value = order.get("id")
    if value in (None, "", "None"):
        return None
    return str(value)


def _order_client_id(order: dict) -> str | None:
    value = order.get("clientOrderId") or order.get("client_order_id") or (order.get("info") or {}).get("cloid")
    return None if value in (None, "", "None") else str(value)


def _order_status(order) -> str | None:
    value = order.get("status") if isinstance(order, dict) else getattr(order, "status", None)
    return None if value in (None, "") else str(value).lower()


def _open_order_fields(raw) -> dict | None:
    def value(*names):
        for name in names:
            found = raw.get(name) if isinstance(raw, dict) else getattr(raw, name, None)
            if found not in (None, ""):
                return found
        return None

    try:
        order_id = value("id")
        client_order_id = value("clientOrderId", "client_order_id")
        symbol = value("symbol")
        side = value("side")
        reduce_only = value("reduceOnly", "reduce_only")
        remaining = value("remaining")
        if remaining is None:
            amount, filled = _finite_positive(value("amount", "qty")), value("filled")
            filled_number = 0.0 if filled in (None, "") else float(filled)
            remaining = None if amount is None or not math.isfinite(filled_number) else amount - filled_number
        remaining = _finite_positive(remaining)
        price = _finite_positive(value("price"))
        if order_id is None and client_order_id is None or symbol is None or side not in {"buy", "sell"} or not isinstance(reduce_only, bool) or remaining is None or price is None:
            return None
        return {"id": None if order_id is None else str(order_id), "client_order_id": None if client_order_id is None else str(client_order_id), "symbol": from_exchange_symbol(str(symbol)), "side": str(side), "reduce_only": reduce_only, "remaining": remaining, "price": price}
    except (TypeError, ValueError):
        return None


def _mr_entry_client_order_id(account: str, symbol: str, side: str, setup_trigger_time, trigger_bucket) -> str:
    seed = ":".join(
        (
            "bbmr-mr-entry",
            account,
            from_exchange_symbol(symbol),
            side,
            _utc_time(setup_trigger_time).isoformat(),
            _utc_time(trigger_bucket).isoformat(),
        )
    )
    return "0x" + uuid.uuid5(uuid.NAMESPACE_URL, seed).hex


def _ioc_boundary_price(quote, side: str, max_slippage_bps: float) -> float:
    price = _quote_value(quote, "ask" if side == "long" else "bid")
    if price is None or price <= 0:
        raise ValueError("valid top-of-book price required for MR entry intent")
    multiplier = 1 + max_slippage_bps / 10000 if side == "long" else 1 - max_slippage_bps / 10000
    return price * multiplier


def _stop_replacement_client_id(trade: LiveTrade) -> str:
    seed = ":".join(
        (
            "bbmr-stop",
            trade.internal_trade_id,
            from_exchange_symbol(trade.symbol),
            trade.side,
            f"{trade.qty:.12g}",
            f"{trade.current_stop_loss:.12g}",
        )
    )
    return "0x" + uuid.uuid5(uuid.NAMESPACE_URL, seed).hex


def _stop_fields(raw) -> dict | None:
    def value(*names):
        for name in names:
            found = raw.get(name) if isinstance(raw, dict) else getattr(raw, name, None)
            if found not in (None, ""):
                return found
        return None

    status = value("status")
    if status is None:
        return None
    try:
        symbol = value("symbol")
        return {
            "id": None if value("id", "order_id") is None else str(value("id", "order_id")),
            "client_order_id": None if value("clientOrderId", "client_order_id") is None else str(value("clientOrderId", "client_order_id")),
            "symbol": None if symbol is None else from_exchange_symbol(str(symbol)),
            "status": str(status).lower(),
            "side": None if value("side") is None else str(value("side")).lower(),
            "reduce_only": value("reduceOnly", "reduce_only"),
            "qty": _finite_positive(value("amount", "qty")),
            "trigger_price": _finite_positive(value("triggerPrice", "trigger_price", "stop")),
        }
    except (TypeError, ValueError):
        return None


def _finite_positive(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _trend_client_order_id(symbol: str, side: str, episode_bucket) -> str:
    seed = f"bbmr-trend:{from_exchange_symbol(symbol)}:{side}:{_utc_time(episode_bucket).isoformat()}"
    return "0x" + uuid.uuid5(uuid.NAMESPACE_URL, seed).hex


def _matching_exchange_position(positions: list, symbol: str, side: str):
    target_symbol = from_exchange_symbol(symbol)
    return next(
        (
            position
            for position in positions
            if from_exchange_symbol(position.symbol) == target_symbol and position.side == side
        ),
        None,
    )


def _exchange_positions_notional(positions: list) -> float:
    total = 0.0
    for position in positions:
        notional = _valid_position_value(getattr(position, "notional", None))
        if notional is None:
            qty = _valid_position_value(getattr(position, "qty", None))
            mark_price = _valid_position_value(getattr(position, "mark_price", None))
            if qty is None or mark_price is None:
                raise ValueError("invalid exchange position valuation")
            notional = qty * mark_price
        total += notional
    return total


def _valid_position_value(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _balance_values(balance) -> tuple[float, float]:
    if hasattr(balance, "equity"):
        return float(balance.equity), float(getattr(balance, "available", float("inf")))
    return float(balance), float("inf")


def _quote_value(quote, name: str) -> float | None:
    value = getattr(quote, name, None)
    if isinstance(quote, dict):
        value = quote.get(name)
    if value in (None, ""):
        return None
    return float(value)


def _severity_payload(severity: str, **payload) -> dict:
    return {"severity": severity, **payload}


def _severity_message(severity: str, message: str) -> str:
    return f"[{severity}] {message}"


class StopReplacementError(RuntimeError):
    pass


def _same_time(left, right) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return _utc_time(left) == _utc_time(right)


def _utc_time(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _same_number(left, right) -> bool:
    return abs(float(left) - float(right)) <= 1e-6


def _same_1h_snapshot(row_1h: pd.Series, setup: LivePendingSetup) -> bool:
    return (
        _same_number(row_1h["close"], setup.close_1h)
        and _same_number(row_1h["lb"], setup.lb_1h)
        and _same_number(row_1h["mb"], setup.mb_1h)
        and _same_number(row_1h["ub"], setup.ub_1h)
        and _same_number(row_1h["rsi14"], setup.rsi_1h)
    )


def _from_setup(symbol: str, setup: Setup) -> LivePendingSetup:
    row_1h = setup.row_1h
    return LivePendingSetup(
        symbol=symbol,
        side=setup.side,
        status="pending",
        trigger_time=setup.trigger_time,
        expiry_time=setup.expiry_time,
        setup_rsi_15m=setup.rsi_15m,
        confirmation_after=setup.confirmation_after,
        confirmed_15m=setup.confirmed_15m,
        confirm_15m_time=setup.confirm_15m_time,
        close_1h=float(row_1h["close"]),
        lb_1h=float(row_1h["lb"]),
        mb_1h=float(row_1h["mb"]),
        ub_1h=float(row_1h["ub"]),
        rsi_1h=float(row_1h["rsi14"]),
        created_at="",
        updated_at="",
    )


def _to_setup(setup: LivePendingSetup) -> Setup:
    row_1h = pd.Series(
        {
            "close": setup.close_1h,
            "lb": setup.lb_1h,
            "mb": setup.mb_1h,
            "ub": setup.ub_1h,
            "rsi14": setup.rsi_1h,
        }
    )
    return Setup(
        setup.side,
        row_1h,
        setup.trigger_time,
        setup.expiry_time,
        setup.setup_rsi_15m,
        setup.confirmation_after,
        setup.confirmed_15m,
        setup.confirm_15m_time,
    )
