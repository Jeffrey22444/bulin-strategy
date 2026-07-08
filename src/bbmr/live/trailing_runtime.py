import json
from dataclasses import dataclass

import pandas as pd

from bbmr.trailing import (
    FIVE_MINUTES,
    Setup,
    _confirm_setup,
    _create_setup,
    _entry_signal,
    _initial_stop_loss,
    _midpoint,
    latest_completed_row,
)
from bbmr.config import load_config
from bbmr.live.state_store import LivePendingSetup, LiveStateStore, LiveTrade
from bbmr.live.symbols import from_exchange_symbol


@dataclass
class LiveRuntime:
    live_config: object
    exchange: object
    store: LiveStateStore
    account: str = "default"

    def __post_init__(self) -> None:
        self.strategy_config = load_config(self.live_config.strategy_config)
        now = self._now()
        self.store.expire_pending_setups(now)
        self.setups: dict[str, Setup] = {}
        for pending_setup in self.store.load_pending_setups(now):
            setup, discard_reason = self._validated_pending_setup(pending_setup, now)
            if setup:
                self.setups[pending_setup.symbol] = setup
            else:
                self._discard_pending_setup(pending_setup, discard_reason)
        self.pending: dict[str, Setup] = {}
        self.emergency_protect_reason: str | None = None

    def position_key(self, symbol: str, side: str) -> str:
        return f"{self.account}:{self.live_config.exchange.env}:{from_exchange_symbol(symbol)}:{side}"

    def can_place_orders(self, cli_allow_testnet_orders: bool) -> bool:
        if self.live_config.exchange.env == "testnet":
            return bool(self.live_config.execution.allow_testnet_orders and cli_allow_testnet_orders)
        return False

    def reconcile_symbol(self, symbol: str, positions: list, allow_orders: bool, dry_run: bool = False) -> list[str]:
        events: list[str] = []
        exchange_position = next((item for item in positions if item.symbol == from_exchange_symbol(symbol)), None)
        open_local = self._open_local_for_symbol(symbol)

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

        if open_local is None:
            if not self.live_config.execution.adopt_manual_positions:
                events.append(f"{symbol} manual position detected; adoption disabled")
                return events
            stop = _initial_stop_loss(exchange_position.side, exchange_position.entry_price, self.strategy_config.trailing_stop.initial_stop_pct)
            trade = self.store.create_trade(key, exchange_position.symbol, exchange_position.side, exchange_position.qty, exchange_position.entry_price, "manual_adopted", stop)
            self._replace_stop(trade, allow_orders, dry_run)
            self.store.append_event("manual_adopted", symbol, trade=trade, event_time=self._now())
            events.append(f"{symbol} manual position detected; adopted into trailing stop management")
            return events

        if open_local.status == "entry_unprotected" or not open_local.system_stop_order_id:
            was_unprotected_entry = open_local.status == "entry_unprotected"
            open_local.qty = exchange_position.qty
            open_local.entry_price = exchange_position.entry_price
            open_local.initial_stop_loss = _initial_stop_loss(exchange_position.side, exchange_position.entry_price, self.strategy_config.trailing_stop.initial_stop_pct)
            open_local.current_stop_loss = open_local.initial_stop_loss
            try:
                self._replace_stop(open_local, allow_orders, dry_run)
            except StopReplacementError as exc:
                self.store.update_trade(open_local)
                events.append(f"{symbol} entry position found but protective stop missing: {exc}")
                return events
            open_local.status = "open"
            self.store.update_trade(open_local)
            if was_unprotected_entry and open_local.source == "strategy":
                self.setups.pop(symbol, None)
                self.store.delete_pending_setup(symbol)
                self.store.append_event("entry_opened", symbol, trade=open_local, setup_trigger_time=open_local.setup_trigger_time, event_time=self._now())
            events.append(f"{symbol} entry protected; managing open position")
            return events

        if open_local.qty != exchange_position.qty or open_local.entry_price != exchange_position.entry_price:
            if not self.live_config.execution.manage_full_manual_added_size:
                events.append(f"{symbol} manual size change ignored; management disabled")
                return events
            open_local.qty = exchange_position.qty
            open_local.entry_price = exchange_position.entry_price
            self._replace_stop(open_local, allow_orders, dry_run)
            self.store.update_trade(open_local)
            self.store.append_event("manual_size_changed", symbol, trade=open_local, event_time=self._now())
            events.append(f"{symbol} manual position size changed; managing merged exchange quantity")
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
    ) -> list[str]:
        events: list[str] = []
        if self.emergency_protect_reason:
            events.append(f"{symbol} strategy entry blocked: {self.emergency_protect_reason}")
            return events
        if self._open_local_for_symbol(symbol):
            return events
        if exchange_positions is None:
            exchange_positions = self.exchange.fetch_positions()
        if self._exchange_position_exists(symbol, exchange_positions):
            events.append(f"{symbol} exchange position exists; waiting")
            return events
        if self._exchange_open_orders_exist(symbol):
            events.append(f"{symbol} open order exists; waiting")
            return events
        row_5m = latest_completed_row(features_5m, self._now(), "5m")
        if row_5m is None:
            events.append(f"{symbol} waiting for completed 5m candle")
            return events
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
            events.append(f"{symbol} waiting for 1h setup")
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
                return events
            events.append(f"{symbol} 15m confirmed; waiting for 5m entry")
        else:
            if not created_setup:
                events.append(f"{symbol} 15m RSI reversal disabled; waiting for 5m entry")
        if not _entry_signal(setup, row_5m):
            return events

        equity, available = _balance_values(balance)
        if equity <= 0:
            events.append(f"{symbol} account equity invalid; waiting")
            return events
        entry_price = float(row_5m["close"])
        selected_leverage = self.entry_leverage(setup.side, features_1h)
        notional = self.entry_notional(equity, selected_leverage)
        proposed_margin = notional / selected_leverage
        if available < proposed_margin:
            events.append(f"{symbol} available margin insufficient; waiting")
            return events
        max_notional = equity * self.live_config.execution.max_total_notional_fraction
        existing_notional = _exchange_positions_notional(exchange_positions)
        if existing_notional + notional > max_notional:
            events.append(f"{symbol} risk cap exceeded; waiting")
            return events
        entry_reference_price = None
        if allow_orders and not dry_run:
            entry_reference_price, quote_error = self._entry_market_quality(symbol)
            if quote_error:
                events.append(f"{symbol} {quote_error}")
                return events
        qty = notional / entry_price
        stop = _initial_stop_loss(setup.side, entry_price, self.strategy_config.trailing_stop.initial_stop_pct)
        slippage_message = None
        slippage_payload = None
        if allow_orders and not dry_run:
            try:
                self.exchange.set_leverage(symbol, selected_leverage, self.live_config.exchange.margin_mode)
            except Exception as exc:
                return events + [f"{symbol} entry order not confirmed; setup retained: {exc}"]
            try:
                order = self.exchange.create_market_entry(symbol, setup.side, self.exchange.format_qty(symbol, qty))
                slippage_message, slippage_payload = self._entry_slippage_warning(symbol, entry_reference_price, _order_fill_price(order))
                positions = self.exchange.fetch_positions()
            except Exception as exc:
                try:
                    positions = self.exchange.fetch_positions()
                except Exception:
                    return events + [f"{symbol} entry order not confirmed; setup retained: {exc}"]
            exchange_position = _matching_exchange_position(positions, symbol, setup.side)
            if exchange_position is None or exchange_position.qty <= 0:
                return events + [f"{symbol} entry order not confirmed; setup retained"]
            entry_price = exchange_position.entry_price
            qty = exchange_position.qty
            stop = _initial_stop_loss(setup.side, entry_price, self.strategy_config.trailing_stop.initial_stop_pct)
            trade = self.store.create_trade(
                self.position_key(symbol, setup.side),
                symbol,
                setup.side,
                qty,
                entry_price,
                "strategy",
                stop,
                entry_time=close_time,
                setup_trigger_time=setup.trigger_time,
                setup_rsi_15m=setup.rsi_15m,
                confirm_15m_time=setup.confirm_15m_time,
                status="entry_unprotected",
            )
            if slippage_message:
                events.append(slippage_message)
                self.store.append_event(
                    "entry_slippage_exceeded",
                    symbol,
                    trade=trade,
                    setup_trigger_time=setup.trigger_time,
                    event_time=close_time,
                    payload_json=json.dumps(slippage_payload, sort_keys=True),
                )
            try:
                self._replace_stop(trade, allow_orders, dry_run)
            except StopReplacementError as exc:
                self.store.update_trade(trade)
                self.store.append_event("entry_unprotected", symbol, trade=trade, setup_trigger_time=setup.trigger_time, event_time=close_time)
                return events + [f"{symbol} entry filled but protective stop failed; local recovery record kept: {exc}"]
            trade.status = "open"
            self.store.update_trade(trade)
        else:
            trade = self.store.create_trade(
                self.position_key(symbol, setup.side),
                symbol,
                setup.side,
                qty,
                entry_price,
                "strategy",
                stop,
                entry_time=close_time,
                setup_trigger_time=setup.trigger_time,
                setup_rsi_15m=setup.rsi_15m,
                confirm_15m_time=setup.confirm_15m_time,
            )
        self.update_adverse_slope_take_profit(trade, features_1h)
        events.append(f"{symbol} entry opened; notional={notional:.2f}, qty={qty:.8f}")
        self.setups.pop(symbol, None)
        self.store.delete_pending_setup(symbol)
        self.store.append_event("entry_opened", symbol, trade=trade, setup_trigger_time=setup.trigger_time, event_time=close_time)
        return events

    def update_stop(self, trade: LiveTrade, row_1h: pd.Series, row_5m: pd.Series, allow_orders: bool, dry_run: bool = False) -> str | None:
        old_stage = trade.trailing_stage
        old_bucket = trade.midband_follow_bucket_start
        new_stop, reason = live_updated_stop(trade, row_1h, row_5m, self.strategy_config.trailing_stop.first_step_risk_reduction)
        if new_stop == trade.current_stop_loss and trade.trailing_stage == old_stage and _same_time(trade.midband_follow_bucket_start, old_bucket):
            return None
        old_stop = trade.current_stop_loss
        if new_stop != trade.current_stop_loss:
            trade.current_stop_loss = new_stop
            try:
                self._replace_stop(trade, allow_orders, dry_run)
            except StopReplacementError as exc:
                trade.current_stop_loss = old_stop
                trade.trailing_stage = old_stage
                trade.midband_follow_bucket_start = old_bucket
                self.store.update_trade(trade)
                return f"{trade.symbol} protective stop replacement failed; new strategy entries blocked: {exc}"
        self.store.update_trade(trade)
        self.store.append_event("stop_updated", trade.symbol, trade=trade, event_time=self._now())
        if new_stop == old_stop:
            if trade.trailing_stage != old_stage:
                return f"{trade.symbol} {reason}; trailing stage {old_stage} -> {trade.trailing_stage}"
            return f"{trade.symbol} {reason}; midband bucket refreshed"
        return f"{trade.symbol} {reason}; stop moved {old_stop} -> {new_stop}"

    def update_adverse_slope_take_profit(self, trade: LiveTrade, features_1h: pd.DataFrame) -> str | None:
        config = self.strategy_config.adverse_slope_take_profit
        if not config.enabled or trade.source != "strategy":
            return None
        completed_1h = _completed_features(features_1h, self._now(), "1h")
        if completed_1h is None:
            return None
        state = adverse_slope_take_profit_state(trade.side, completed_1h, config)
        if state is None:
            return None
        was_active = trade.adverse_slope_tp_active
        if state["active"]:
            if was_active and _same_time(trade.adverse_slope_tp_bucket_start, state["bucket_start"]):
                return None
            trade.adverse_slope_tp_bucket_start = state["bucket_start"]
            trade.adverse_slope_tp_active = True
            trade.adverse_slope_tp_price = state["tp_price"]
            self.store.update_trade(trade)
            return f"{trade.symbol} adverse 1h middle slope active; tp={state['tp_price']}"
        if was_active:
            trade.adverse_slope_tp_bucket_start = None
            trade.adverse_slope_tp_active = False
            trade.adverse_slope_tp_price = None
            self.store.update_trade(trade)
            return f"{trade.symbol} adverse 1h middle slope inactive; special TP cleared"
        return None

    def maybe_close_adverse_slope_take_profit(self, trade: LiveTrade, market_price: float, allow_orders: bool, dry_run: bool = False) -> str | None:
        if not trade.adverse_slope_tp_active or trade.adverse_slope_tp_price is None:
            return None
        triggered = market_price >= trade.adverse_slope_tp_price if trade.side == "long" else market_price <= trade.adverse_slope_tp_price
        if not triggered:
            return None
        if not allow_orders or dry_run:
            return f"{trade.symbol} adverse slope TP triggered; close skipped"
        try:
            self.exchange.close_position_market(trade.symbol, trade.side, self.exchange.format_qty(trade.symbol, trade.qty))
            positions = self.exchange.fetch_positions()
        except Exception as exc:
            return f"{trade.symbol} adverse slope TP close verification failed; trade remains open: {exc}"
        remaining = _matching_exchange_position(positions, trade.symbol, trade.side)
        if remaining is not None and remaining.qty > 0:
            trade.qty = remaining.qty
            try:
                self._replace_stop(trade, allow_orders, dry_run)
            except StopReplacementError as exc:
                self.store.update_trade(trade)
                return f"{trade.symbol} adverse slope TP partially closed; protective stop replacement failed: {exc}"
            self.store.update_trade(trade)
            return f"{trade.symbol} adverse slope TP partially closed; remaining qty protected"
        self._cancel_system_stop(trade, dry_run)
        self._archive_trade(trade.symbol, trade, "adverse_slope_take_profit")
        return f"{trade.symbol} adverse slope TP triggered; position closed"

    def entry_leverage(self, side: str, features_1h: pd.DataFrame) -> int:
        config = self.strategy_config.adverse_slope_take_profit
        if config.enabled:
            completed_1h = _completed_features(features_1h, self._now(), "1h")
            state = adverse_slope_take_profit_state(side, completed_1h, config) if completed_1h is not None else None
            if state and state["active"]:
                return self.live_config.execution.adverse_slope_leverage
        return self.live_config.execution.leverage

    def entry_notional(self, equity: float, leverage: int | None = None) -> float:
        selected_leverage = self.live_config.execution.leverage if leverage is None else leverage
        return equity * self.live_config.execution.margin_fraction * selected_leverage

    def _entry_market_quality(self, symbol: str) -> tuple[float | None, str | None]:
        fetch = getattr(self.exchange, "fetch_market_quote", None)
        if not callable(fetch):
            return None, "market quote unavailable; waiting"
        try:
            quote = fetch(symbol)
        except Exception as exc:
            return None, f"market quote unavailable; waiting: {exc}"
        bid = _quote_value(quote, "bid")
        ask = _quote_value(quote, "ask")
        last = _quote_value(quote, "last")
        if bid is None or ask is None or last is None or bid <= 0 or ask <= 0 or last <= 0 or ask < bid:
            return None, "market quote unavailable; waiting"
        spread_bps = (ask - bid) / last * 10000
        if spread_bps > self.live_config.execution.max_market_spread_bps:
            return last, f"market spread too wide ({spread_bps:.1f} bps); waiting"
        return last, None

    def _entry_slippage_warning(self, symbol: str, reference_price: float | None, fill_price: float | None) -> tuple[str | None, dict | None]:
        if reference_price is None or fill_price is None or reference_price <= 0 or fill_price <= 0:
            return None, None
        slippage_bps = abs(fill_price - reference_price) / reference_price * 10000
        if slippage_bps <= self.live_config.execution.max_entry_slippage_bps:
            return None, None
        payload = {
            "reference_price": reference_price,
            "fill_price": fill_price,
            "slippage_bps": slippage_bps,
            "max_entry_slippage_bps": self.live_config.execution.max_entry_slippage_bps,
        }
        return f"{symbol} entry fill slippage exceeded ({slippage_bps:.1f} bps); position protected and managed", payload

    def _open_local_for_symbol(self, symbol: str) -> LiveTrade | None:
        for side in ("long", "short"):
            trade = self.store.open_trade(self.position_key(symbol, side))
            if trade:
                return trade
        return None

    def managed_trade(self, symbol: str) -> LiveTrade | None:
        return self._open_local_for_symbol(symbol)

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

    def _cancel_system_stop(self, trade: LiveTrade, dry_run: bool) -> None:
        if trade.system_stop_order_id and not dry_run:
            try:
                self.exchange.cancel_order(trade.symbol, trade.system_stop_order_id)
            except Exception as exc:
                if not _is_missing_order_error(exc):
                    raise

    def _replace_stop(self, trade: LiveTrade, allow_orders: bool, dry_run: bool) -> None:
        if not self.live_config.execution.maintain_exchange_stop:
            return
        if allow_orders and not dry_run:
            old_stop_order_id = trade.system_stop_order_id
            try:
                order = self.exchange.create_reduce_only_stop(trade.symbol, trade.side, trade.qty, trade.current_stop_loss)
                new_stop_order_id = _order_id(order)
                if new_stop_order_id is None:
                    raise StopReplacementError("new stop order missing valid id")
            except Exception as exc:
                self._mark_emergency_protect(trade, exc)
                if isinstance(exc, StopReplacementError):
                    raise
                raise StopReplacementError(str(exc)) from exc
            self._cancel_system_stop(trade, dry_run)
            trade.system_stop_order_id = new_stop_order_id
            if old_stop_order_id and old_stop_order_id == new_stop_order_id:
                return
        self.store.update_trade(trade)

    def _mark_emergency_protect(self, trade: LiveTrade, exc: Exception) -> None:
        reason = f"protective stop replacement failed for {trade.symbol}: {exc}"
        self.emergency_protect_reason = reason
        self.store.append_event(
            "protective_stop_failed",
            trade.symbol,
            trade=trade,
            event_time=self._now(),
            payload_json=json.dumps({"reason": reason}, sort_keys=True),
        )

    def _now(self):
        now = getattr(self.exchange, "now", None)
        if callable(now):
            return pd.Timestamp(now())
        return pd.Timestamp.now(tz="UTC")

    def _archive_trade(self, symbol: str, trade: LiveTrade, reason: str) -> None:
        pnl = self._exit_pnl(symbol, trade)
        if pnl:
            self.store.archive_trade(
                trade,
                reason,
                exit_price=pnl["exit_price"],
                realized_pnl=pnl["realized_pnl"],
                fees=pnl["fees"],
                pnl_source="exchange",
            )
            payload_json = json.dumps({key: pnl[key] for key in ("pnl_source", "exit_price", "realized_pnl", "fees")}, sort_keys=True)
        else:
            self.store.archive_trade(trade, reason)
            payload_json = json.dumps({"pnl_source": "unknown"}, sort_keys=True)
        self.store.append_event("exit_archived", symbol, trade=trade, event_time=self._now(), payload_json=payload_json)

    def _exit_pnl(self, symbol: str, trade: LiveTrade) -> dict | None:
        fetch = getattr(self.exchange, "fetch_recent_realized_pnl", None)
        if not callable(fetch):
            return None
        try:
            pnl = fetch(symbol, trade)
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

    def _validated_pending_setup(self, pending_setup: LivePendingSetup, now) -> tuple[Setup | None, str]:
        try:
            features_1h, features_15m, features_5m = latest_completed_features(self.exchange, pending_setup.symbol, self.strategy_config)
        except Exception as exc:
            return None, f"current candles unavailable: {exc.__class__.__name__}"
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
    if len(features_1h) <= config.slope_n:
        return None
    current = features_1h.iloc[-1]
    past = features_1h.iloc[-(config.slope_n + 1)]
    past_middle = float(past["mb"])
    if past_middle == 0:
        return None
    current_middle = float(current["mb"])
    slope = current_middle / past_middle - 1
    active = slope <= -config.slope_threshold_pct if side == "long" else slope >= config.slope_threshold_pct
    tp_price = None
    if active:
        if side == "long":
            tp_price = current_middle - (current_middle - float(current["lb"])) * config.near_middle_frac
        else:
            tp_price = current_middle + (float(current["ub"]) - current_middle) * config.near_middle_frac
    return {"bucket_start": _midband_follow_bucket_start(current), "active": active, "tp_price": tp_price}


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
    five_m_limit = strategy_config.bollinger.bb_period + 1
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
        price = float(getattr(position, "mark_price", 0) or getattr(position, "entry_price", 0) or 0)
        total += abs(float(position.qty)) * price
    return total


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
