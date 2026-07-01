import os
from dataclasses import dataclass
from datetime import datetime

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
                "options": {"defaultType": "swap"},
            }
        )

    def missing_credentials(self) -> list[str]:
        return missing_credential_names(self.config)

    def fetch_balance(self) -> LiveBalance:
        payload = self.exchange.fetch_balance()
        usdc = payload.get("USDC", {})
        total = float(usdc.get("total") or 0)
        return LiveBalance(total + self._unrealized_pnl(), float(usdc.get("free") or 0))

    def _unrealized_pnl(self) -> float:
        return sum(float(raw.get("unrealizedPnl") or 0) for raw in self.exchange.fetch_positions())

    def fetch_positions(self) -> list[ExchangePosition]:
        positions = []
        for raw in self.exchange.fetch_positions():
            qty = float(raw.get("contracts") or raw.get("contractSize") or 0)
            if qty <= 0:
                continue
            side = str(raw.get("side") or "").lower()
            positions.append(
                ExchangePosition(
                    symbol=from_exchange_symbol(raw["symbol"]),
                    side="long" if side in {"long", "buy"} else "short",
                    qty=qty,
                    entry_price=float(raw.get("entryPrice") or 0),
                    mark_price=float(raw.get("markPrice") or raw.get("entryPrice") or 0),
                )
            )
        return positions

    def fetch_open_orders(self, symbol: str) -> list[dict]:
        return self.exchange.fetch_open_orders(to_exchange_symbol(symbol))

    def get_market_price(self, symbol: str) -> float:
        return float(self.exchange.fetch_ticker(to_exchange_symbol(symbol))["last"])

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        rows = self.exchange.fetch_ohlcv(to_exchange_symbol(symbol), timeframe, limit=limit)
        frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
        return frame.set_index("timestamp")

    def fetch_recent_realized_pnl(self, symbol: str, trade) -> dict | None:
        if not hasattr(self.exchange, "fetch_my_trades"):
            return None
        since = None
        if trade.entry_time is not None:
            since = int(pd.Timestamp(trade.entry_time).timestamp() * 1000)
        trades = self.exchange.fetch_my_trades(to_exchange_symbol(symbol), since=since, limit=50)
        close_side = "sell" if trade.side == "long" else "buy"
        candidates = []
        for item in trades:
            info = item.get("info") or {}
            side = str(item.get("side") or info.get("side") or "").lower()
            if side and side != close_side:
                continue
            pnl = _first_float(item, info, ("realizedPnl", "realized_pnl", "closedPnl", "closed_pnl", "pnl"))
            if pnl is None:
                continue
            amount = float(item.get("amount") or item.get("contracts") or info.get("sz") or info.get("size") or 0)
            price = float(item.get("price") or info.get("px") or info.get("price") or 0)
            fee = _fee(item)
            candidates.append((amount, price, pnl, fee))
        if not candidates:
            return None
        amount_sum = sum(amount for amount, _, _, _ in candidates)
        return {
            "exit_price": sum(amount * price for amount, price, _, _ in candidates) / amount_sum if amount_sum else candidates[-1][1],
            "realized_pnl": sum(pnl for _, _, pnl, _ in candidates),
            "fees": sum(fee for _, _, _, fee in candidates),
            "pnl_source": "exchange",
        }

    def set_leverage(self, symbol: str, leverage: int, margin_mode: str) -> None:
        self.exchange.set_leverage(leverage, to_exchange_symbol(symbol), {"marginMode": margin_mode})

    def create_market_entry(self, symbol: str, side: str, qty: float) -> dict:
        order_side = "buy" if side == "long" else "sell"
        return self.exchange.create_order(
            to_exchange_symbol(symbol),
            "market",
            order_side,
            qty,
            self.get_market_price(symbol),
            {},
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

    def create_reduce_only_stop(self, symbol: str, side: str, qty: float, stop_price: float) -> dict:
        close_side = "sell" if side == "long" else "buy"
        return self.exchange.create_order(
            to_exchange_symbol(symbol),
            "market",
            close_side,
            qty,
            stop_price,
            {"stopLossPrice": stop_price, "reduceOnly": True},
        )

    def cancel_order(self, symbol: str, exchange_order_id: str) -> None:
        self.exchange.cancel_order(exchange_order_id, to_exchange_symbol(symbol))

    def format_qty(self, symbol: str, qty: float) -> float:
        return float(self.exchange.amount_to_precision(to_exchange_symbol(symbol), qty))

    def now(self) -> datetime:
        return datetime.now()


def missing_credential_names(config) -> list[str]:
    names = [config.exchange.wallet_address_env, config.exchange.private_key_env]
    return [name for name in names if not os.environ.get(name)]


def _first_float(item: dict, info: dict, names: tuple[str, ...]) -> float | None:
    for name in names:
        value = item.get(name, info.get(name))
        if value not in (None, ""):
            return float(value)
    return None


def _fee(item: dict) -> float:
    fee = item.get("fee") or {}
    if isinstance(fee, dict):
        return float(fee.get("cost") or 0)
    return 0.0
