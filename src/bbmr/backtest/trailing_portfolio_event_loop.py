from dataclasses import dataclass

import pandas as pd

from bbmr.backtest.event_loop import BacktestResult
from bbmr.backtest.trailing_event_loop import (
    FIVE_MINUTES,
    PendingEntry,
    Position,
    Setup,
    _close_position,
    _confirm_setup,
    _create_setup,
    _entry_signal,
    _initial_stop_hit,
    _initial_stop_loss,
    _order,
    _reset_setup_confirmation,
    _trailing_stop_hit,
    _unrealized,
    _updated_stop,
    _mark_price,
    latest_completed_row,
    FIFTEEN_MINUTES,
    INITIAL_STOP_PCT,
    POSITION_FRACTION,
)


@dataclass
class SymbolState:
    setup: Setup | None = None
    pending: PendingEntry | None = None
    position: Position | None = None


def run_trailing_portfolio_event_loop(symbol_features: dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]], config, init_cash: float) -> BacktestResult:
    cash = init_cash
    states = {symbol: SymbolState() for symbol in symbol_features}
    setup_attempts: dict[tuple[str, str, pd.Timestamp], int] = {}
    initial_stop_reentry_allowed: set[tuple[str, str, pd.Timestamp]] = set()
    orders: list[dict] = []
    trades: list[dict] = []
    equity_curve: list[dict] = []
    fee_rate = config.costs.taker_fee_bps / 10000
    slippage_rate = config.costs.slippage_bps / 10000
    initial_stop_pct = getattr(getattr(config, "trailing_stop", None), "initial_stop_pct", INITIAL_STOP_PCT)
    last_marks: dict[str, float] = {}

    timeline = sorted(set().union(*(features_5m.index for _, _, features_5m in symbol_features.values())))
    for open_time in timeline:
        close_time = open_time + FIVE_MINUTES
        rows_5m = {
            symbol: features_5m.loc[open_time]
            for symbol, (_, _, features_5m) in symbol_features.items()
            if open_time in features_5m.index
        }
        open_marks = {symbol: float(row_5m["open"]) for symbol, row_5m in rows_5m.items()}

        for symbol, state in states.items():
            row_5m = rows_5m.get(symbol)
            if row_5m is None or not state.pending or state.pending.fill_time != open_time:
                continue
            raw_price = float(row_5m["open"])
            entry_price = _mark_price(state.pending.side, raw_price, "entry", slippage_rate)
            equity_before = _portfolio_equity(cash, states, {**last_marks, **open_marks})
            qty = equity_before * POSITION_FRACTION / entry_price
            fees = abs(qty * entry_price) * fee_rate
            cash -= fees
            initial_stop = _initial_stop_loss(state.pending.side, entry_price, initial_stop_pct)
            state.position = Position(
                side=state.pending.side,
                qty=qty,
                entry_time=open_time,
                entry_price=entry_price,
                entry_fees=fees,
                equity_before=equity_before,
                setup=state.pending.setup,
                entry_signal_5m_close_time=state.pending.signal_5m_close_time,
                initial_stop_loss=initial_stop,
                current_stop_loss=initial_stop,
                stop_update_time=open_time,
            )
            orders.append(_order(symbol, open_time, state.pending.side, "entry", "TRAILING_ENTRY", entry_price, qty, fees, state.position))
            key = _setup_key(symbol, state.position.setup)
            setup_attempts[key] = setup_attempts.get(key, 0) + 1
            state.pending = None

        for symbol, row_5m in rows_5m.items():
            last_marks[symbol] = float(row_5m["close"])

        for symbol, state in states.items():
            row_5m = rows_5m.get(symbol)
            if row_5m is None or not state.position:
                continue
            features_1h, features_15m, _ = symbol_features[symbol]
            close_5m = float(row_5m["close"])
            if _initial_stop_hit(state.position, close_5m):
                key = _setup_key(symbol, state.position.setup)
                exited_setup = state.position.setup
                cash = _close_position(symbol, state.position, close_time, close_5m, "initial_stop_5m_close", cash, fee_rate, slippage_rate, orders, trades)
                if close_time < exited_setup.expiry_time:
                    initial_stop_reentry_allowed.add(key)
                state.position = None
                if close_time < exited_setup.expiry_time and setup_attempts.get(key, 0) < 2:
                    state.setup = _reset_setup_confirmation(exited_setup, close_time)
                else:
                    state.setup = None
                continue

            row_1h = latest_completed_row(features_1h, close_time, "1h")
            if row_1h is not None:
                new_stop = _updated_stop(state.position, close_5m, row_1h)
                if new_stop != state.position.current_stop_loss:
                    state.position.current_stop_loss = new_stop
                    state.position.stop_update_time = close_time

            row_15m = latest_completed_row(features_15m, close_time, "15m")
            if row_15m is not None and row_15m.name + FIFTEEN_MINUTES > state.position.stop_update_time:
                close_15m = float(row_15m["close"])
                if _trailing_stop_hit(state.position, close_15m):
                    cash = _close_position(
                        symbol,
                        state.position,
                        row_15m.name + FIFTEEN_MINUTES,
                        close_15m,
                        "trailing_stop_15m_close",
                        cash,
                        fee_rate,
                        slippage_rate,
                        orders,
                        trades,
                    )
                    state.position = None
                    state.setup = None

        for symbol, state in states.items():
            row_5m = rows_5m.get(symbol)
            if row_5m is None or state.position or state.pending:
                continue
            features_1h, features_15m, _ = symbol_features[symbol]
            if state.setup and close_time >= state.setup.expiry_time:
                state.setup = None
            if state.setup is None:
                candidate = _create_setup(features_1h, features_15m, close_time, config)
                if candidate and _setup_can_trade(symbol, candidate, setup_attempts, initial_stop_reentry_allowed):
                    state.setup = candidate
            if state.setup and close_time < state.setup.expiry_time:
                _confirm_setup(state.setup, features_15m, close_time)
                if state.setup.confirmed_15m and _entry_signal(state.setup, row_5m):
                    state.pending = PendingEntry(state.setup.side, close_time, close_time, state.setup)

        equity_curve.append(
            {
                "timestamp": close_time,
                "symbol": ",".join(symbol_features),
                "cash": cash,
                "position_qty": sum(state.position.qty for state in states.values() if state.position),
                "position_side": "portfolio",
                "mark_price": 0.0,
                "unrealized_pnl": sum(_unrealized(state.position, last_marks.get(symbol, 0.0)) for symbol, state in states.items()),
                "equity": _portfolio_equity(cash, states, last_marks),
                "state": _portfolio_state(states),
            }
        )

    for symbol, state in states.items():
        if not state.position:
            continue
        _, _, features_5m = symbol_features[symbol]
        final_time = features_5m.index[-1] + FIVE_MINUTES
        final_close = float(features_5m.iloc[-1]["close"])
        cash = _close_position(symbol, state.position, final_time, final_close, "end_of_data", cash, fee_rate, slippage_rate, orders, trades)
        state.position = None

    if equity_curve:
        equity_curve.append(
            {
                "timestamp": max(features_5m.index[-1] + FIVE_MINUTES for _, _, features_5m in symbol_features.values()),
                "symbol": ",".join(symbol_features),
                "cash": cash,
                "position_qty": 0.0,
                "position_side": "portfolio",
                "mark_price": 0.0,
                "unrealized_pnl": 0.0,
                "equity": cash,
                "state": "flat",
            }
        )

    return BacktestResult(
        ",".join(symbol_features),
        pd.DataFrame(orders),
        pd.DataFrame(trades),
        pd.DataFrame(equity_curve),
    )


def _portfolio_equity(cash: float, states: dict[str, SymbolState], marks: dict[str, float]) -> float:
    return cash + sum(_unrealized(state.position, marks.get(symbol, 0.0)) for symbol, state in states.items())


def _portfolio_state(states: dict[str, SymbolState]) -> str:
    if any(state.position for state in states.values()):
        return "open"
    if any(state.pending for state in states.values()):
        return "pending_entry"
    if any(state.setup for state in states.values()):
        return "pending_setup"
    return "flat"


def _setup_key(symbol: str, setup: Setup) -> tuple[str, str, pd.Timestamp]:
    return symbol, setup.side, setup.trigger_time


def _setup_can_trade(
    symbol: str,
    setup: Setup,
    setup_attempts: dict[tuple[str, str, pd.Timestamp], int],
    initial_stop_reentry_allowed: set[tuple[str, str, pd.Timestamp]],
) -> bool:
    key = _setup_key(symbol, setup)
    attempts = setup_attempts.get(key, 0)
    if attempts == 0:
        return True
    if attempts == 1 and key in initial_stop_reentry_allowed:
        return True
    return False
