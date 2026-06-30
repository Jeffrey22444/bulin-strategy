from dataclasses import dataclass

import pandas as pd

from bbmr.backtest.alignment import count_completed_since, latest_completed_row
from bbmr.backtest.ledger import Ledger
from bbmr.decision_engine import evaluate_cycle
from bbmr.state_machine import TradeState
from bbmr.trade_models import TradeContext


@dataclass(frozen=True)
class BacktestResult:
    symbol: str
    orders: pd.DataFrame
    trades: pd.DataFrame
    equity_curve: pd.DataFrame


_EXIT_REASONS = {
    "STOP_LOSS_5M": "stop_loss",
    "TAKE_PROFIT_5M": "take_profit",
    "ADDED_TAKE_PROFIT_5M": "added_take_profit",
    "EARLY_FAIL_1H": "early_fail",
}


def run_event_loop(symbol: str, features_1h: pd.DataFrame, ohlcv_15m: pd.DataFrame, ohlcv_5m: pd.DataFrame, config, init_cash: float) -> BacktestResult:
    ledger = Ledger(
        symbol=symbol,
        cash=init_cash,
        fee_rate=config.costs.taker_fee_bps / 10000,
        slippage_rate=config.costs.slippage_bps / 10000,
    )
    context = TradeContext()
    pending_start = None
    last_15m_time = None

    for time, row_5m in ohlcv_5m.iterrows():
        row_1h = latest_completed_row(features_1h, time, "1h")
        row_15m = latest_completed_row(ohlcv_15m, time, "15m")
        if row_1h is None or row_15m is None:
            ledger.record_equity(time, float(row_5m["close"]), context.state)
            continue

        row_15m = row_15m.copy()
        if context.state == TradeState.PENDING_ENTRY:
            row_15m["waited_bars"] = count_completed_since(ohlcv_15m, pending_start, time)
        else:
            row_15m["waited_bars"] = 0

        row_1h = _side_fail_row(row_1h, context.side)
        equity = ledger.equity(float(row_5m["close"]))
        before = context
        result = evaluate_cycle(context, row_1h=row_1h, row_15m=row_15m, row_5m=row_5m, config=config, account_equity=equity)
        context = result.context

        if result.transition:
            event = result.transition.event
            if event in {"LONG_SIGNAL_1H", "SHORT_SIGNAL_1H"} and context.state == TradeState.PENDING_ENTRY:
                pending_start = time
            elif event == "ENTRY_CONFIRMED_15M":
                ledger.open_trade(time, context.side, float(row_15m["close"]), context.initial_size or 0.0, context, before.state, context.state)
                pending_start = None
            elif event == "ADD_CONFIRMED_15M":
                add_qty = max(context.add_size - ledger.position.add_qty, 0.0)
                ledger.add_trade(time, float(row_15m["close"]), add_qty, context, before.state, context.state)
            elif event in _EXIT_REASONS:
                ledger.close_trade(time, _exit_raw_price(event, row_5m), event, _EXIT_REASONS[event], before.state, result.transition.state)
                context = TradeContext()
                pending_start = None
            elif result.transition.state == TradeState.FLAT:
                context = TradeContext()
                pending_start = None

        if context.state == TradeState.PENDING_ENTRY and row_15m.name != last_15m_time:
            last_15m_time = row_15m.name
        ledger.record_equity(time, float(row_5m["close"]), context.state)

    if ledger.position.side:
        final_time = ohlcv_5m.index[-1]
        final_close = float(ohlcv_5m.iloc[-1]["close"])
        ledger.close_trade(final_time, final_close, "end_of_data", "end_of_data", context.state, TradeState.EXITED)
        context = TradeContext()
        ledger.record_equity(final_time, final_close, context.state)

    orders, trades, equity_curve = ledger.frames()
    return BacktestResult(symbol, orders, trades, equity_curve)


def _side_fail_row(row, side: str | None):
    row = row.copy()
    if side == "short":
        row["soft_fail"] = row.get("soft_fail_short", row.get("soft_fail", False))
        row["early_fail"] = row.get("early_fail_short", row.get("early_fail", False))
    else:
        row["soft_fail"] = row.get("soft_fail_long", row.get("soft_fail", False))
        row["early_fail"] = row.get("early_fail_long", row.get("early_fail", False))
    return row


def _exit_raw_price(event: str, row_5m) -> float:
    if event == "STOP_LOSS_5M":
        return float(row_5m["low"])
    if event in {"TAKE_PROFIT_5M", "ADDED_TAKE_PROFIT_5M"}:
        return float(row_5m["high"])
    return float(row_5m["close"])
