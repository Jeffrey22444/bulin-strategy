from dataclasses import dataclass, field

import pandas as pd


ORDER_COLUMNS = ["symbol", "time", "side", "order_type", "event", "state_before", "state_after", "price", "qty", "fees"]
TRADE_COLUMNS = [
    "symbol",
    "side",
    "signal_time",
    "entry_time",
    "entry_price",
    "exit_time",
    "exit_price",
    "qty",
    "add_time",
    "add_price",
    "add_qty",
    "weighted_avg_entry",
    "fixed_sl",
    "tp_price",
    "exit_reason",
    "gross_pnl",
    "fees",
    "net_pnl",
    "r_multiple",
    "equity_before",
    "equity_after",
]
EQUITY_COLUMNS = ["timestamp", "symbol", "cash", "position_qty", "position_side", "mark_price", "unrealized_pnl", "equity", "state"]


@dataclass
class Position:
    side: str | None = None
    qty: float = 0.0
    entry_price: float | None = None
    signal_time: object | None = None
    entry_time: object | None = None
    add_time: object | None = None
    add_price: float | None = None
    add_qty: float = 0.0
    weighted_avg_entry: float | None = None
    fixed_sl: float | None = None
    one_r: float | None = None
    entry_fees: float = 0.0
    equity_before: float | None = None


@dataclass
class Ledger:
    symbol: str
    cash: float
    fee_rate: float
    slippage_rate: float
    orders: list[dict] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    position: Position = field(default_factory=Position)

    def mark_price(self, side: str, raw_price: float, action: str) -> float:
        if side == "long":
            return raw_price * (1 + self.slippage_rate if action in {"entry", "add"} else 1 - self.slippage_rate)
        return raw_price * (1 - self.slippage_rate if action in {"entry", "add"} else 1 + self.slippage_rate)

    def fee(self, qty: float, price: float) -> float:
        return abs(qty * price) * self.fee_rate

    def open_trade(self, time, side: str, raw_price: float, qty: float, context, state_before, state_after) -> None:
        price = self.mark_price(side, raw_price, "entry")
        fees = self.fee(qty, price)
        self.cash -= fees
        self.position = Position(
            side=side,
            qty=qty,
            entry_price=price,
            signal_time=context.entry_reference.signal_time if context.entry_reference else None,
            entry_time=time,
            weighted_avg_entry=price,
            fixed_sl=context.fixed_sl,
            one_r=context.one_r,
            entry_fees=fees,
            equity_before=self.cash + fees,
        )
        self._order(time, side, "entry", "ENTRY_CONFIRMED_15M", state_before, state_after, price, qty, fees)

    def add_trade(self, time, raw_price: float, qty: float, context, state_before, state_after) -> None:
        price = self.mark_price(self.position.side, raw_price, "add")
        fees = self.fee(qty, price)
        self.cash -= fees
        total_qty = self.position.qty + qty
        weighted = self.position.weighted_avg_entry if total_qty == 0 else (
            self.position.weighted_avg_entry * self.position.qty + price * qty
        ) / total_qty
        self.position.qty = total_qty
        self.position.add_time = time
        self.position.add_price = price
        self.position.add_qty = qty
        self.position.weighted_avg_entry = weighted
        self.position.entry_fees += fees
        self._order(time, self.position.side, "add", "ADD_CONFIRMED_15M", state_before, state_after, price, qty, fees)

    def close_trade(self, time, raw_price: float, event: str, reason: str, state_before, state_after) -> None:
        if not self.position.side:
            return
        price = self.mark_price(self.position.side, raw_price, "exit")
        qty = self.position.qty
        fees = self.fee(qty, price)
        gross = (price - self.position.weighted_avg_entry) * qty
        if self.position.side == "short":
            gross = -gross
        net = gross - self.position.entry_fees - fees
        self.cash += net
        equity_before = self.position.equity_before if self.position.equity_before is not None else self.cash - net
        self._order(time, self.position.side, "exit", event, state_before, state_after, price, qty, fees)
        self.trades.append(
            {
                "symbol": self.symbol,
                "side": self.position.side,
                "signal_time": self.position.signal_time,
                "entry_time": self.position.entry_time,
                "entry_price": self.position.entry_price,
                "exit_time": time,
                "exit_price": price,
                "qty": qty,
                "add_time": self.position.add_time,
                "add_price": self.position.add_price,
                "add_qty": self.position.add_qty,
                "weighted_avg_entry": self.position.weighted_avg_entry,
                "fixed_sl": self.position.fixed_sl,
                "tp_price": None,
                "exit_reason": reason,
                "gross_pnl": gross,
                "fees": self.position.entry_fees + fees,
                "net_pnl": net,
                "r_multiple": net / (self.position.one_r * qty) if self.position.one_r and qty else 0.0,
                "equity_before": equity_before,
                "equity_after": self.cash,
            }
        )
        self.position = Position()

    def record_equity(self, time, mark_price: float, state) -> None:
        unrealized = 0.0
        if self.position.side:
            unrealized = (mark_price - self.position.weighted_avg_entry) * self.position.qty
            if self.position.side == "short":
                unrealized = -unrealized
        self.equity_curve.append(
            {
                "timestamp": time,
                "symbol": self.symbol,
                "cash": self.cash,
                "position_qty": self.position.qty,
                "position_side": self.position.side,
                "mark_price": mark_price,
                "unrealized_pnl": unrealized,
                "equity": self.cash + unrealized,
                "state": getattr(state, "value", state),
            }
        )

    def equity(self, mark_price: float) -> float:
        if not self.position.side:
            return self.cash
        pnl = (mark_price - self.position.weighted_avg_entry) * self.position.qty
        return self.cash + (-pnl if self.position.side == "short" else pnl)

    def frames(self):
        return (
            pd.DataFrame(self.orders, columns=ORDER_COLUMNS),
            pd.DataFrame(self.trades, columns=TRADE_COLUMNS),
            pd.DataFrame(self.equity_curve, columns=EQUITY_COLUMNS),
        )

    def _order(self, time, side, order_type, event, state_before, state_after, price, qty, fees) -> None:
        self.orders.append(
            {
                "symbol": self.symbol,
                "time": time,
                "side": side,
                "order_type": order_type,
                "event": event,
                "state_before": getattr(state_before, "value", state_before),
                "state_after": getattr(state_after, "value", state_after),
                "price": price,
                "qty": qty,
                "fees": fees,
            }
        )
