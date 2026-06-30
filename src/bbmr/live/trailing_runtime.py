import json
from dataclasses import dataclass

import pandas as pd

from bbmr.backtest.trailing_event_loop import (
    FIVE_MINUTES,
    Setup,
    _confirm_setup,
    _create_setup,
    _entry_signal,
    _initial_stop_loss,
    _midpoint,
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
        self.setups: dict[str, Setup] = {setup.symbol: _to_setup(setup) for setup in self.store.load_pending_setups(now)}
        self.pending: dict[str, Setup] = {}

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
            stop = _initial_stop_loss(exchange_position.side, exchange_position.entry_price, self.strategy_config.trailing_stop.initial_stop_pct)
            trade = self.store.create_trade(key, exchange_position.symbol, exchange_position.side, exchange_position.qty, exchange_position.entry_price, "manual_adopted", stop)
            self._replace_stop(trade, allow_orders, dry_run)
            self.store.append_event("manual_adopted", symbol, trade=trade, event_time=self._now())
            events.append(f"{symbol} manual position detected; adopted into trailing stop management")
            return events

        if open_local.qty != exchange_position.qty or open_local.entry_price != exchange_position.entry_price:
            open_local.qty = exchange_position.qty
            open_local.entry_price = exchange_position.entry_price
            self._replace_stop(open_local, allow_orders, dry_run)
            self.store.update_trade(open_local)
            self.store.append_event("manual_size_changed", symbol, trade=open_local, event_time=self._now())
            events.append(f"{symbol} manual position size changed; managing merged exchange quantity")
        return events

    def maybe_open_strategy_trade(self, symbol: str, features_1h: pd.DataFrame, features_15m: pd.DataFrame, features_5m: pd.DataFrame, equity: float, allow_orders: bool, dry_run: bool = False) -> list[str]:
        events: list[str] = []
        if self._open_local_for_symbol(symbol):
            return events
        close_time = features_5m.index[-1] + FIVE_MINUTES
        setup = self.setups.get(symbol)
        if setup and close_time >= setup.expiry_time:
            self.store.append_event("setup_expired", symbol, side=setup.side, setup_trigger_time=setup.trigger_time, event_time=close_time)
            self.store.expire_pending_setups(close_time)
            self.setups.pop(symbol, None)
            setup = None
        if setup is None:
            setup = _create_setup(features_1h, features_15m, close_time, self.strategy_config)
            if setup:
                self.setups[symbol] = setup
                self.store.save_pending_setup(_from_setup(symbol, setup))
                self.store.append_event("setup_created", symbol, side=setup.side, setup_trigger_time=setup.trigger_time, event_time=close_time)
                events.append(f"{symbol} 1h close and RSI met {setup.side} setup; waiting for 15m RSI reversal")
        if not setup:
            events.append(f"{symbol} no live setup; waiting")
            return events

        was_confirmed = setup.confirmed_15m
        _confirm_setup(setup, features_15m, close_time)
        if setup.confirmed_15m and not was_confirmed:
            self.store.save_pending_setup(_from_setup(symbol, setup))
            self.store.append_event("setup_confirmed_15m", symbol, side=setup.side, setup_trigger_time=setup.trigger_time, event_time=setup.confirm_15m_time)
        if not setup.confirmed_15m:
            events.append(f"{symbol} waiting for 15m RSI reversal")
            return events
        events.append(f"{symbol} 15m RSI reversed; waiting for 5m entry")
        if not _entry_signal(setup, features_5m.iloc[-1]):
            return events

        entry_price = float(features_5m.iloc[-1]["close"])
        notional = self.entry_notional(equity)
        qty = notional / entry_price
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
        )
        if allow_orders and not dry_run:
            self.exchange.set_leverage(symbol, self.live_config.execution.leverage, self.live_config.exchange.margin_mode)
            order = self.exchange.create_market_entry(symbol, setup.side, self.exchange.format_qty(symbol, qty))
            if order.get("filled"):
                trade.qty = float(order["filled"])
            self._replace_stop(trade, allow_orders, dry_run)
            self.store.update_trade(trade)
        events.append(f"{symbol} 5m entry signal; notional={notional:.2f}, qty={qty:.8f}")
        self.setups.pop(symbol, None)
        self.store.delete_pending_setup(symbol)
        self.store.append_event("entry_opened", symbol, trade=trade, setup_trigger_time=setup.trigger_time, event_time=close_time)
        return events

    def update_stop(self, trade: LiveTrade, row_1h: pd.Series, row_5m: pd.Series, allow_orders: bool, dry_run: bool = False) -> str | None:
        new_stop, reason = live_updated_stop(trade, row_1h, row_5m)
        if new_stop == trade.current_stop_loss:
            return None
        old_stop = trade.current_stop_loss
        trade.current_stop_loss = new_stop
        self._replace_stop(trade, allow_orders, dry_run)
        self.store.update_trade(trade)
        self.store.append_event("stop_updated", trade.symbol, trade=trade, event_time=self._now())
        return f"{trade.symbol} {reason}; stop moved {old_stop} -> {new_stop}"

    def entry_notional(self, equity: float) -> float:
        return equity * self.live_config.execution.margin_fraction * self.live_config.execution.leverage

    def _open_local_for_symbol(self, symbol: str) -> LiveTrade | None:
        for side in ("long", "short"):
            trade = self.store.open_trade(self.position_key(symbol, side))
            if trade:
                return trade
        return None

    def managed_trade(self, symbol: str) -> LiveTrade | None:
        return self._open_local_for_symbol(symbol)

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
        self._cancel_system_stop(trade, dry_run)
        if allow_orders and not dry_run:
            order = self.exchange.create_reduce_only_stop(trade.symbol, trade.side, trade.qty, trade.current_stop_loss)
            trade.system_stop_order_id = str(order.get("id"))
        self.store.update_trade(trade)

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


def live_updated_stop(trade: LiveTrade, row_1h: pd.Series, row_5m: pd.Series) -> tuple[float, str]:
    lb_1h = float(row_1h["lb"])
    mid_1h = float(row_1h["mb"])
    ub_1h = float(row_1h["ub"])
    close_5m = float(row_5m["close"])
    high_5m = float(row_5m["high"])
    low_5m = float(row_5m["low"])
    candidates: list[tuple[float, str]] = []
    if trade.side == "long":
        if close_5m > _midpoint(lb_1h, mid_1h):
            candidates.append((trade.entry_price, "5m close > midpoint(1h lower, 1h middle)"))
        if close_5m > mid_1h:
            candidates.append((_midpoint(trade.entry_price, mid_1h), "5m close > 1h middle"))
        if high_5m >= _midpoint(mid_1h, ub_1h):
            candidates.append((mid_1h, "5m high >= midpoint(1h middle, 1h upper)"))
        if high_5m > ub_1h:
            candidates.append((close_5m, "5m high > 1h upper"))
        valid = [(stop, reason) for stop, reason in candidates if stop > trade.current_stop_loss]
        return max(valid, default=(trade.current_stop_loss, "no stop change"))

    if close_5m < _midpoint(ub_1h, mid_1h):
        candidates.append((trade.entry_price, "5m close < midpoint(1h upper, 1h middle)"))
    if close_5m < mid_1h:
        candidates.append((_midpoint(trade.entry_price, mid_1h), "5m close < 1h middle"))
    if low_5m <= _midpoint(lb_1h, mid_1h):
        candidates.append((mid_1h, "5m low <= midpoint(1h lower, 1h middle)"))
    if low_5m < lb_1h:
        candidates.append((close_5m, "5m low < 1h lower"))
    valid = [(stop, reason) for stop, reason in candidates if stop < trade.current_stop_loss]
    return min(valid, default=(trade.current_stop_loss, "no stop change"))


def latest_completed_features(exchange, symbol: str, strategy_config) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    from bbmr.backtest.trailing_features import build_trailing_features

    return build_trailing_features(
        exchange.fetch_ohlcv(symbol, "1h", 100),
        exchange.fetch_ohlcv(symbol, "15m", 100),
        exchange.fetch_ohlcv(symbol, "5m", 100),
        strategy_config,
    )


def _is_missing_order_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return exc.__class__.__name__ == "OrderNotFound" or any(
        marker in text for marker in ("never placed", "already canceled", "already cancelled", "filled", "not found")
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
