from types import SimpleNamespace

import pytest

from bbmr.live.config import load_live_config
from bbmr.live.hyperliquid_client import HyperliquidClient


class FakeExchange:
    def __init__(self):
        self.sandbox = None
        self.orders = []
        self.cancelled = []

    def set_sandbox_mode(self, enabled):
        self.sandbox = enabled

    def load_markets(self):
        return {}

    def fetch_balance(self):
        return {"USDC": {"total": 10000, "free": 9000}}

    def fetch_positions(self):
        return [
            {
                "symbol": "BTC/USDC:USDC",
                "side": "long",
                "contracts": 0.2,
                "entryPrice": 100,
                "markPrice": 105,
                "unrealizedPnl": 10,
            }
        ]

    def fetch_my_trades(self, symbol, since=None, limit=None):
        self.last_my_trades = (symbol, since, limit)
        return [
            {"side": "sell", "amount": 0.1, "price": 110, "fee": {"cost": 0.05}, "info": {"closedPnl": "1.5"}},
            {"side": "sell", "amount": 0.2, "price": 111, "fee": {"cost": 0.10}, "info": {"closedPnl": "3.0"}},
        ]

    def create_order(self, symbol, order_type, side, amount, price, params):
        order = {"id": str(len(self.orders) + 1), "symbol": symbol, "side": side, "amount": amount, "price": price, "params": params}
        self.orders.append(order)
        return order

    def cancel_order(self, order_id, symbol):
        self.cancelled.append((order_id, symbol))

    def fetch_ohlcv(self, symbol, timeframe, limit):
        return [[1_000, 1, 2, 0.5, 1.5, 10]]

    def amount_to_precision(self, symbol, qty):
        return f"{qty:.4f}"

    def set_leverage(self, leverage, symbol, params):
        self.leverage = (leverage, symbol, params)


def test_client_enables_sandbox_and_maps_positions():
    client = HyperliquidClient(load_live_config("configs/live_hyperliquid_testnet.yaml"), FakeExchange())
    assert client.exchange.sandbox is True
    assert client.fetch_balance().equity == 10010
    assert client.fetch_positions()[0].symbol == "BTC"
    assert client.fetch_positions()[0].side == "long"


def test_client_places_reduce_only_stop_and_cancels_by_id():
    client = HyperliquidClient(load_live_config("configs/live_hyperliquid_testnet.yaml"), FakeExchange())
    order = client.create_reduce_only_stop("BTC", "long", 0.1, 95)
    client.cancel_order("BTC", order["id"])
    assert order["params"] == {"stopLossPrice": 95, "reduceOnly": True}
    assert client.exchange.cancelled == [("1", "BTC/USDC:USDC")]


def test_client_fetches_recent_realized_pnl_from_my_trades():
    exchange = FakeExchange()
    client = HyperliquidClient(load_live_config("configs/live_hyperliquid_testnet.yaml"), exchange)

    pnl = client.fetch_recent_realized_pnl("BTC", SimpleNamespace(side="long", entry_time="2026-01-01T00:00:00Z"))

    assert exchange.last_my_trades == ("BTC/USDC:USDC", 1767225600000, 50)
    assert pnl == {"exit_price": pytest.approx(110.66666666666667), "realized_pnl": 4.5, "fees": pytest.approx(0.15), "pnl_source": "exchange"}
