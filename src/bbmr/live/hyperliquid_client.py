import os
import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

import pandas as pd

from bbmr.live.symbols import from_exchange_symbol, to_exchange_symbol


@dataclass
class LiveBalance:
    equity: float
    available: float


@dataclass
class ExchangePosition:
    symbol: str
    side: str
    qty: float
    entry_price: float
    mark_price: float
    notional: float | None = None


@dataclass
class MarketQuote:
    bid: float | None
    ask: float | None
    last: float | None


@dataclass
class ExchangeStopOrder:
    order_id: str | None
    client_order_id: str | None
    symbol: str | None
    status: str
    side: str | None
    reduce_only: bool | None
    qty: float | None
    trigger_price: float | None


class AccountDataError(ValueError):
    pass


class HyperliquidClient:
    def __init__(self, config, exchange=None):
        self.config = config
        self.exchange = exchange or self._create_exchange()
        self.exchange.set_sandbox_mode(config.exchange.env == "testnet")
        self.exchange.load_markets()

    def _create_exchange(self):
        import ccxt

        return ccxt.hyperliquid(
            {
                "walletAddress": os.environ.get(self.config.exchange.wallet_address_env),
                "privateKey": os.environ.get(self.config.exchange.private_key_env),
                "enableRateLimit": self.config.exchange.enable_rate_limit,
                "timeout": self.config.exchange.timeout_ms,
                "options": {
                    "defaultType": "swap",
                    "builderFee": False,
                    "approvedBuilderFee": False,
                    "refSet": True,
                },
            }
        )

    def fetch_balance(self) -> LiveBalance:
        payload = self.exchange.fetch_balance()
        usdc = payload.get("USDC") if isinstance(payload, dict) else None
        info = payload.get("info") if isinstance(payload, dict) else None
        equity = _valid_nonnegative(usdc.get("total") if isinstance(usdc, dict) else None)
        free = _valid_nonnegative(usdc.get("free") if isinstance(usdc, dict) else None)
        withdrawable = _valid_nonnegative(info.get("withdrawable") if isinstance(info, dict) else None)
        if equity is None or free is None or withdrawable is None:
            raise AccountDataError("invalid Hyperliquid balance schema")
        return LiveBalance(equity, min(free, withdrawable))

    def fetch_positions(self) -> list[ExchangePosition]:
        positions = []
        raw_positions = self.exchange.fetch_positions()
        if not isinstance(raw_positions, list):
            raise AccountDataError("invalid Hyperliquid positions schema")
        for raw in raw_positions:
            if not isinstance(raw, dict):
                raise AccountDataError("invalid Hyperliquid position")
            qty = _valid_nonnegative(raw.get("contracts"))
            if qty is None:
                raise AccountDataError("invalid Hyperliquid position contracts")
            if qty == 0:
                continue
            side = str(raw.get("side") or "").lower()
            if side not in {"long", "short"}:
                raise AccountDataError("invalid Hyperliquid position side")
            symbol = raw.get("symbol")
            if not isinstance(symbol, str) or not symbol:
                raise AccountDataError("invalid Hyperliquid position symbol")
            notional = _first_valid_positive(raw.get("positionValue"), raw.get("notional"))
            mark_price = _valid_positive(raw.get("markPrice"))
            if notional is None:
                if mark_price is None:
                    raise AccountDataError("invalid Hyperliquid position valuation")
                notional = qty * mark_price
            positions.append(
                ExchangePosition(
                    symbol=from_exchange_symbol(symbol),
                    side=side,
                    qty=qty,
                    entry_price=_valid_nonnegative(raw.get("entryPrice")) or 0,
                    mark_price=mark_price or 0,
                    notional=notional,
                )
            )
        return positions

    def fetch_open_orders(self, symbol: str | None = None) -> list[dict]:
        return self.exchange.fetch_open_orders(None if symbol is None else to_exchange_symbol(symbol))

    def get_market_price(self, symbol: str) -> float:
        return float(self.exchange.fetch_ticker(to_exchange_symbol(symbol))["last"])

    def fetch_market_quote(self, symbol: str) -> MarketQuote:
        order_book = self.exchange.fetch_order_book(to_exchange_symbol(symbol), limit=1)
        bid = _top_book_price(order_book.get("bids"))
        ask = _top_book_price(order_book.get("asks"))
        mid = (bid + ask) / 2 if bid is not None and ask is not None else None
        return MarketQuote(
            bid=bid,
            ask=ask,
            last=mid,
        )

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        rows = self.exchange.fetch_ohlcv(to_exchange_symbol(symbol), timeframe, limit=limit)
        frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
        return frame.set_index("timestamp")

    def fetch_recent_realized_pnl(self, symbol: str, trade, *, close_order_id: str | None, close_client_id: str | None, close_qty: float | None) -> dict | None:
        if not hasattr(self.exchange, "fetch_my_trades") or (not close_order_id and not close_client_id):
            return None
        expected_qty = _valid_positive(close_qty)
        if expected_qty is None:
            return None
        since = None
        if trade.entry_time is not None:
            since = int(pd.Timestamp(trade.entry_time).timestamp() * 1000)
        trades = self.exchange.fetch_my_trades(to_exchange_symbol(symbol), since=since, limit=50)
        close_side = "sell" if trade.side == "long" else "buy"
        candidates = []
        for item in trades:
            if not isinstance(item, dict):
                return None
            info = item.get("info") or {}
            if not isinstance(info, dict):
                return None
            order_id = _first_text(item, info, ("order", "orderId", "order_id", "oid"))
            client_id = _first_text(item, info, ("clientOrderId", "client_order_id", "cloid"))
            if not ((close_order_id is not None and order_id == close_order_id) or (close_client_id is not None and client_id == close_client_id)):
                continue
            side = str(item.get("side") or info.get("side") or "").lower()
            if side != close_side:
                return None
            pnl = _first_float(item, info, ("realizedPnl", "realized_pnl", "closedPnl", "closed_pnl", "pnl"))
            amount = _first_valid_positive(item.get("amount"), item.get("contracts"), info.get("sz"), info.get("size"))
            price = _first_valid_positive(item.get("price"), info.get("px"), info.get("price"))
            if pnl is None or not math.isfinite(pnl) or amount is None or price is None:
                return None
            fee = _fee(item)
            if not math.isfinite(fee):
                return None
            candidates.append((amount, price, pnl, fee))
        if not candidates:
            return None
        amount_sum = sum(amount for amount, _, _, _ in candidates)
        if not math.isclose(amount_sum, expected_qty, rel_tol=1e-9, abs_tol=1e-12):
            return None
        return {
            "exit_price": sum(amount * price for amount, price, _, _ in candidates) / amount_sum if amount_sum else candidates[-1][1],
            "realized_pnl": sum(pnl for _, _, pnl, _ in candidates),
            "fees": sum(fee for _, _, _, fee in candidates),
            "pnl_source": "exchange",
        }

    def set_leverage(self, symbol: str, leverage: int, margin_mode: str) -> None:
        self.exchange.set_leverage(leverage, to_exchange_symbol(symbol), {"marginMode": margin_mode})

    def create_ioc_entry(self, symbol: str, side: str, qty: float, quote: MarketQuote | dict, client_order_id: str | None = None) -> dict:
        order_side = "buy" if side == "long" else "sell"
        price = self._ioc_entry_price(symbol, side, quote)
        params = {"timeInForce": "IOC"}
        if client_order_id:
            params["clientOrderId"] = client_order_id
        return self.exchange.create_order(
            to_exchange_symbol(symbol),
            "limit",
            order_side,
            qty,
            price,
            params,
        )

    def _ioc_entry_price(self, symbol: str, side: str, quote: MarketQuote | dict) -> str:
        bid = _quote_price(quote, "bid")
        ask = _quote_price(quote, "ask")
        if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
            raise ValueError("market quote unavailable")
        slippage = Decimal(str(self.config.execution.max_entry_slippage_bps)) / Decimal("10000")
        if side == "long":
            boundary = Decimal(str(ask)) * (Decimal("1") + slippage)
        elif side == "short":
            boundary = Decimal(str(bid)) * (Decimal("1") - slippage)
        else:
            raise ValueError("side must be long or short")
        try:
            price = Decimal(str(self.exchange.price_to_precision(to_exchange_symbol(symbol), str(boundary))))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("invalid IOC entry price precision") from exc
        if not price.is_finite():
            raise ValueError("invalid IOC entry price precision")
        if (side == "long" and price > boundary) or (side == "short" and price < boundary):
            step = Decimal("1").scaleb(price.as_tuple().exponent)
            corrected = price - step if side == "long" else price + step
            try:
                price = Decimal(str(self.exchange.price_to_precision(to_exchange_symbol(symbol), str(corrected))))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValueError("invalid IOC entry price precision") from exc
        if not price.is_finite() or price <= 0 or (side == "long" and price > boundary) or (side == "short" and price < boundary):
            raise ValueError("IOC entry price exceeds approved boundary")
        return format(price, "f")

    def create_limit_entry(self, symbol: str, side: str, qty: float, price: float, client_order_id: str) -> dict:
        order_side = "buy" if side == "long" else "sell"
        return self.exchange.create_order(
            to_exchange_symbol(symbol),
            "limit",
            order_side,
            qty,
            self.format_price(symbol, price),
            {"timeInForce": "Gtc", "clientOrderId": client_order_id},
        )

    def close_position_market(self, symbol: str, side: str, qty: float) -> dict:
        order_side = "sell" if side == "long" else "buy"
        return self.exchange.create_order(
            to_exchange_symbol(symbol),
            "market",
            order_side,
            qty,
            self.get_market_price(symbol),
            {"reduceOnly": True},
        )

    def create_reduce_only_stop(self, symbol: str, side: str, qty: float, stop_price: float, client_order_id: str | None = None) -> dict:
        close_side = "sell" if side == "long" else "buy"
        params = {"stopLossPrice": stop_price, "reduceOnly": True}
        if client_order_id:
            params["clientOrderId"] = client_order_id
        return self.exchange.create_order(
            to_exchange_symbol(symbol),
            "market",
            close_side,
            qty,
            stop_price,
            params,
        )

    def cancel_order(self, symbol: str, exchange_order_id: str) -> None:
        self.exchange.cancel_order(exchange_order_id, to_exchange_symbol(symbol))

    def fetch_order(self, symbol: str, order_id: str | None, client_order_id: str | None = None) -> dict:
        lookup_id = order_id or client_order_id
        if not lookup_id:
            raise ValueError("order_id or client_order_id is required")
        params = {"clientOrderId": client_order_id} if client_order_id else {}
        return self.exchange.fetch_order(lookup_id, to_exchange_symbol(symbol), params)

    def fetch_protective_stop(self, symbol: str, order_id: str | None, client_order_id: str | None = None) -> ExchangeStopOrder:
        raw = self.fetch_order(symbol, order_id, client_order_id)
        if not isinstance(raw, dict):
            raise AccountDataError("invalid Hyperliquid stop order schema")
        status = str(raw.get("status") or "").lower()
        if status not in {"open", "closed", "canceled", "cancelled", "rejected", "expired"}:
            raise AccountDataError("invalid Hyperliquid stop order status")
        order = ExchangeStopOrder(
            order_id=_order_text(raw.get("id")),
            client_order_id=_order_text(raw.get("clientOrderId")),
            symbol=_order_symbol(raw.get("symbol")),
            status=status,
            side=_order_side(raw.get("side")),
            reduce_only=raw.get("reduceOnly") if isinstance(raw.get("reduceOnly"), bool) else None,
            qty=_valid_positive(raw.get("amount")),
            trigger_price=_valid_positive(raw.get("triggerPrice")),
        )
        if status == "open" and (
            order.order_id is None or order.symbol is None or order.side is None
            or order.reduce_only is None or order.qty is None or order.trigger_price is None
        ):
            raise AccountDataError("incomplete Hyperliquid protective stop")
        return order

    def format_qty(self, symbol: str, qty: float) -> float:
        return float(self.exchange.amount_to_precision(to_exchange_symbol(symbol), qty))

    def format_price(self, symbol: str, price: float) -> float:
        return float(self.exchange.price_to_precision(to_exchange_symbol(symbol), price))

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def missing_credential_names(config) -> list[str]:
    names = [config.exchange.wallet_address_env, config.exchange.private_key_env]
    return [name for name in names if not os.environ.get(name)]


def _first_float(item: dict, info: dict, names: tuple[str, ...]) -> float | None:
    for name in names:
        value = item.get(name, info.get(name))
        if value not in (None, ""):
            return float(value)
    return None


def _first_text(item: dict, info: dict, names: tuple[str, ...]) -> str | None:
    for name in names:
        value = item.get(name, info.get(name))
        if value not in (None, ""):
            return str(value)
    return None


def _optional_float(value) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _valid_nonnegative(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _valid_positive(value) -> float | None:
    number = _valid_nonnegative(value)
    return number if number is not None and number > 0 else None


def _quote_price(quote: MarketQuote | dict, name: str) -> float | None:
    value = quote.get(name) if isinstance(quote, dict) else getattr(quote, name, None)
    return _valid_positive(value)


def _first_valid_positive(*values) -> float | None:
    for value in values:
        number = _valid_positive(value)
        if number is not None:
            return number
    return None


def _top_book_price(levels: list | None) -> float | None:
    if not levels:
        return None
    return _optional_float(levels[0][0])


def _fee(item: dict) -> float:
    fee = item.get("fee") or {}
    if isinstance(fee, dict):
        return float(fee.get("cost") or 0)
    return 0.0


def _order_text(value) -> str | None:
    return None if value in (None, "") else str(value)


def _order_symbol(value) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return from_exchange_symbol(value)
    except ValueError:
        return None


def _order_side(value) -> str | None:
    side = str(value or "").lower()
    return side if side in {"buy", "sell"} else None
