from dataclasses import dataclass

import pandas as pd

from bbmr.backtest.alignment import latest_completed_row
from bbmr.backtest.event_loop import BacktestResult


POSITION_FRACTION = 0.20
INITIAL_STOP_PCT = 0.02
FIVE_MINUTES = pd.Timedelta(minutes=5)
FIFTEEN_MINUTES = pd.Timedelta(minutes=15)
ONE_HOUR = pd.Timedelta(hours=1)


@dataclass
class Setup:
    side: str
    row_1h: pd.Series
    trigger_time: pd.Timestamp
    expiry_time: pd.Timestamp
    rsi_15m: float
    confirmation_after: pd.Timestamp | None = None
    confirmed_15m: bool = False
    confirm_15m_time: pd.Timestamp | None = None


@dataclass
class PendingEntry:
    side: str
    fill_time: pd.Timestamp
    signal_5m_close_time: pd.Timestamp
    setup: Setup


@dataclass
class Position:
    side: str
    qty: float
    entry_time: pd.Timestamp
    entry_price: float
    entry_fees: float
    equity_before: float
    setup: Setup
    entry_signal_5m_close_time: pd.Timestamp
    initial_stop_loss: float
    current_stop_loss: float
    stop_update_time: pd.Timestamp


def run_trailing_event_loop(
    symbol: str,
    features_1h: pd.DataFrame,
    features_15m: pd.DataFrame,
    features_5m: pd.DataFrame,
    config,
    init_cash: float,
) -> BacktestResult:
    cash = init_cash
    position: Position | None = None
    setup: Setup | None = None
    pending: PendingEntry | None = None
    setup_attempts: dict[tuple[str, pd.Timestamp], int] = {}
    orders: list[dict] = []
    trades: list[dict] = []
    equity_curve: list[dict] = []
    fee_rate = config.costs.taker_fee_bps / 10000
    slippage_rate = config.costs.slippage_bps / 10000
    initial_stop_pct = getattr(getattr(config, "trailing_stop", None), "initial_stop_pct", INITIAL_STOP_PCT)

    for open_time, row_5m in features_5m.iterrows():
        close_time = open_time + FIVE_MINUTES

        if pending and pending.fill_time == open_time:
            raw_price = float(row_5m["open"])
            entry_price = _mark_price(pending.side, raw_price, "entry", slippage_rate)
            equity_before = _equity(cash, position, raw_price)
            qty = equity_before * POSITION_FRACTION / entry_price
            fees = abs(qty * entry_price) * fee_rate
            cash -= fees
            initial_stop = _initial_stop_loss(pending.side, entry_price, initial_stop_pct)
            position = Position(
                side=pending.side,
                qty=qty,
                entry_time=open_time,
                entry_price=entry_price,
                entry_fees=fees,
                equity_before=equity_before,
                setup=pending.setup,
                entry_signal_5m_close_time=pending.signal_5m_close_time,
                initial_stop_loss=initial_stop,
                current_stop_loss=initial_stop,
                stop_update_time=open_time,
            )
            orders.append(_order(symbol, open_time, pending.side, "entry", "TRAILING_ENTRY", entry_price, qty, fees, position))
            key = _setup_key(position.setup)
            setup_attempts[key] = setup_attempts.get(key, 0) + 1
            pending = None

        if position:
            close_5m = float(row_5m["close"])
            if _initial_stop_hit(position, close_5m):
                exited_setup = position.setup
                cash = _close_position(symbol, position, close_time, close_5m, "initial_stop_5m_close", cash, fee_rate, slippage_rate, orders, trades)
                position = None
                if close_time < exited_setup.expiry_time and setup_attempts.get(_setup_key(exited_setup), 0) < 2:
                    setup = _reset_setup_confirmation(exited_setup, close_time)
                else:
                    setup = None
            else:
                row_1h = latest_completed_row(features_1h, close_time, "1h")
                if row_1h is not None:
                    new_stop = _updated_stop(position, close_5m, row_1h)
                    if new_stop != position.current_stop_loss:
                        position.current_stop_loss = new_stop
                        position.stop_update_time = close_time

                row_15m = latest_completed_row(features_15m, close_time, "15m")
                if row_15m is not None and row_15m.name + FIFTEEN_MINUTES > position.stop_update_time:
                    close_15m = float(row_15m["close"])
                    if _trailing_stop_hit(position, close_15m):
                        cash = _close_position(
                            symbol,
                            position,
                            row_15m.name + FIFTEEN_MINUTES,
                            close_15m,
                            "trailing_stop_15m_close",
                            cash,
                            fee_rate,
                            slippage_rate,
                            orders,
                            trades,
                        )
                        position = None
                        setup = None

        if not position and not pending:
            if setup and close_time >= setup.expiry_time:
                setup = None
            if setup is None:
                candidate = _create_setup(features_1h, features_15m, close_time, config)
                if candidate and setup_attempts.get(_setup_key(candidate), 0) == 0:
                    setup = candidate
            if setup and close_time < setup.expiry_time:
                _confirm_setup(setup, features_15m, close_time)
                if setup.confirmed_15m and _entry_signal(setup, row_5m):
                    pending = PendingEntry(setup.side, close_time, close_time, setup)

        mark_price = float(row_5m["close"])
        equity_curve.append(
            {
                "timestamp": close_time,
                "symbol": symbol,
                "cash": cash,
                "position_qty": 0.0 if position is None else position.qty,
                "position_side": None if position is None else position.side,
                "mark_price": mark_price,
                "unrealized_pnl": _unrealized(position, mark_price),
                "equity": _equity(cash, position, mark_price),
                "state": _state(position, pending, setup),
            }
        )

    if position:
        final_time = features_5m.index[-1] + FIVE_MINUTES
        final_close = float(features_5m.iloc[-1]["close"])
        cash = _close_position(symbol, position, final_time, final_close, "end_of_data", cash, fee_rate, slippage_rate, orders, trades)
        equity_curve.append(
            {
                "timestamp": final_time,
                "symbol": symbol,
                "cash": cash,
                "position_qty": 0.0,
                "position_side": None,
                "mark_price": final_close,
                "unrealized_pnl": 0.0,
                "equity": cash,
                "state": "flat",
            }
        )

    return BacktestResult(symbol, pd.DataFrame(orders), pd.DataFrame(trades), pd.DataFrame(equity_curve))


def _create_setup(features_1h: pd.DataFrame, features_15m: pd.DataFrame, close_time: pd.Timestamp, config) -> Setup | None:
    row_1h = latest_completed_row(features_1h, close_time, "1h")
    if row_1h is None or pd.isna(row_1h.get("lb")) or pd.isna(row_1h.get("rsi14")):
        return None
    trigger_time = row_1h.name + ONE_HOUR
    expiry_time = trigger_time + ONE_HOUR
    if not (trigger_time <= close_time < expiry_time):
        return None
    row_15m = latest_completed_row(features_15m, trigger_time, "15m")
    if row_15m is None or pd.isna(row_15m.get("rsi14")):
        return None
    if float(row_1h["close"]) < float(row_1h["lb"]) and float(row_1h["rsi14"]) < config.rsi.oversold:
        return Setup("long", row_1h.copy(), trigger_time, expiry_time, float(row_15m["rsi14"]), trigger_time)
    if float(row_1h["close"]) > float(row_1h["ub"]) and float(row_1h["rsi14"]) > config.rsi.overbought:
        return Setup("short", row_1h.copy(), trigger_time, expiry_time, float(row_15m["rsi14"]), trigger_time)
    return None


def _confirm_setup(setup: Setup, features_15m: pd.DataFrame, close_time: pd.Timestamp) -> None:
    row_15m = latest_completed_row(features_15m, close_time, "15m")
    if row_15m is None:
        return
    confirm_time = row_15m.name + FIFTEEN_MINUTES
    if confirm_time <= (setup.confirmation_after or setup.trigger_time):
        return
    rsi = float(row_15m["rsi14"])
    if setup.side == "long" and rsi > setup.rsi_15m:
        setup.confirmed_15m = True
        setup.confirm_15m_time = confirm_time
    elif setup.side == "short" and rsi < setup.rsi_15m:
        setup.confirmed_15m = True
        setup.confirm_15m_time = confirm_time


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


def _updated_stop(position: Position, close_5m: float, row_1h: pd.Series) -> float:
    lb_1h = float(row_1h["lb"])
    mid_1h = float(row_1h["mb"])
    ub_1h = float(row_1h["ub"])
    entry = position.entry_price
    candidates = []
    if position.side == "long":
        if close_5m > _midpoint(lb_1h, mid_1h):
            candidates.append(entry)
        if close_5m > mid_1h:
            candidates.append(_midpoint(entry, mid_1h))
        if close_5m >= _midpoint(mid_1h, ub_1h):
            candidates.append(mid_1h)
        if close_5m > ub_1h:
            candidates.append(close_5m)
        valid = [stop for stop in candidates if stop > position.current_stop_loss]
        return max(valid) if valid else position.current_stop_loss

    if close_5m < _midpoint(ub_1h, mid_1h):
        candidates.append(entry)
    if close_5m < mid_1h:
        candidates.append(_midpoint(entry, mid_1h))
    if close_5m <= _midpoint(mid_1h, lb_1h):
        candidates.append(mid_1h)
    if close_5m < lb_1h:
        candidates.append(close_5m)
    valid = [stop for stop in candidates if stop < position.current_stop_loss]
    return min(valid) if valid else position.current_stop_loss


def _initial_stop_hit(position: Position, close_5m: float) -> bool:
    return close_5m < position.initial_stop_loss if position.side == "long" else close_5m > position.initial_stop_loss


def _initial_stop_loss(side: str, entry_price: float, initial_stop_pct: float) -> float:
    return entry_price * (1 - initial_stop_pct if side == "long" else 1 + initial_stop_pct)


def _trailing_stop_hit(position: Position, close_15m: float) -> bool:
    return close_15m < position.current_stop_loss if position.side == "long" else close_15m > position.current_stop_loss


def _reset_setup_confirmation(setup: Setup, confirmation_after: pd.Timestamp) -> Setup:
    setup.confirmed_15m = False
    setup.confirm_15m_time = None
    setup.confirmation_after = confirmation_after
    return setup


def _setup_key(setup: Setup) -> tuple[str, pd.Timestamp]:
    return setup.side, setup.trigger_time


def _close_position(symbol, position, time, raw_price, reason, cash, fee_rate, slippage_rate, orders, trades) -> float:
    exit_price = _mark_price(position.side, raw_price, "exit", slippage_rate)
    fees = abs(position.qty * exit_price) * fee_rate
    gross = (exit_price - position.entry_price) * position.qty
    if position.side == "short":
        gross = -gross
    net = gross - position.entry_fees - fees
    cash += net
    orders.append(_order(symbol, time, position.side, "exit", reason, exit_price, position.qty, fees, position))
    trades.append(
        {
            "symbol": symbol,
            "side": position.side,
            "signal_time": position.setup.trigger_time,
            "setup_trigger_time": position.setup.trigger_time,
            "setup_expiry_time": position.setup.expiry_time,
            "setup_rsi_15m": position.setup.rsi_15m,
            "confirm_15m_time": position.setup.confirm_15m_time,
            "entry_signal_5m_close_time": position.entry_signal_5m_close_time,
            "entry_time": position.entry_time,
            "entry_price": position.entry_price,
            "initial_stop_loss": position.initial_stop_loss,
            "exit_time": time,
            "exit_price": exit_price,
            "qty": position.qty,
            "add_time": None,
            "add_price": None,
            "add_qty": 0.0,
            "weighted_avg_entry": position.entry_price,
            "fixed_sl": position.initial_stop_loss,
            "tp_price": None,
            "exit_reason": reason,
            "gross_pnl": gross,
            "fees": position.entry_fees + fees,
            "net_pnl": net,
            "r_multiple": 0.0 if position.entry_price == position.initial_stop_loss else net / abs(position.entry_price - position.initial_stop_loss) / position.qty,
            "equity_before": position.equity_before,
            "equity_after": cash,
        }
    )
    return cash


def _order(symbol, time, side, order_type, event, price, qty, fees, position) -> dict:
    return {
        "symbol": symbol,
        "time": time,
        "side": side,
        "order_type": order_type,
        "event": event,
        "state_before": None,
        "state_after": None,
        "price": price,
        "qty": qty,
        "fees": fees,
        "setup_trigger_time": position.setup.trigger_time,
        "setup_expiry_time": position.setup.expiry_time,
        "setup_rsi_15m": position.setup.rsi_15m,
        "confirm_15m_time": position.setup.confirm_15m_time,
        "entry_signal_5m_close_time": position.entry_signal_5m_close_time,
        "entry_time": position.entry_time,
        "entry_price": position.entry_price,
        "initial_stop_loss": position.initial_stop_loss,
    }


def _mark_price(side: str, raw_price: float, action: str, slippage_rate: float) -> float:
    if side == "long":
        return raw_price * (1 + slippage_rate if action == "entry" else 1 - slippage_rate)
    return raw_price * (1 - slippage_rate if action == "entry" else 1 + slippage_rate)


def _unrealized(position: Position | None, mark_price: float) -> float:
    if position is None:
        return 0.0
    pnl = (mark_price - position.entry_price) * position.qty
    return -pnl if position.side == "short" else pnl


def _equity(cash: float, position: Position | None, mark_price: float) -> float:
    return cash + _unrealized(position, mark_price)


def _state(position: Position | None, pending: PendingEntry | None, setup: Setup | None) -> str:
    if position:
        return "open"
    if pending:
        return "pending_entry"
    if setup:
        return "pending_setup"
    return "flat"


def _midpoint(left: float, right: float) -> float:
    return (left + right) / 2
