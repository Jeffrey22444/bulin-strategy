from types import SimpleNamespace
from decimal import Decimal

import pytest

from bbmr.live.config import load_live_config
from bbmr.live.hyperliquid_client import AccountDataError, HyperliquidClient


class FakeExchange:
    def __init__(self):
        self.sandbox = None
        self.orders = []
        self.fetched_orders = []
        self.cancelled = []
        self.order_book = {"bids": [[123.40, 1]], "asks": [[123.50, 2]]}
        self.ticker_calls = 0
        self.open_order_calls = []

    def set_sandbox_mode(self, enabled):
        self.sandbox = enabled

    def load_markets(self):
        return {}

    def fetch_balance(self):
        return {"USDC": {"total": 10000, "free": 9000}, "info": {"withdrawable": 8000}}

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

    def fetch_ticker(self, symbol):
        self.ticker_calls += 1
        return {"bid": 123.40, "ask": 123.50, "last": 123.45}

    def fetch_order_book(self, symbol, limit=None):
        self.last_order_book = (symbol, limit)
        return self.order_book

    def fetch_open_orders(self, symbol=None):
        self.open_order_calls.append(symbol)
        return []

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

    def fetch_order(self, order_id, symbol, params):
        self.fetched_orders.append((order_id, symbol, params))
        return {"id": order_id, "symbol": symbol, "params": params}

    def fetch_ohlcv(self, symbol, timeframe, limit):
        return [[1_000, 1, 2, 0.5, 1.5, 10]]

    def amount_to_precision(self, symbol, qty):
        return f"{qty:.4f}"

    def price_to_precision(self, symbol, price):
        return f"{float(price):.2f}"

    def set_leverage(self, leverage, symbol, params):
        self.leverage = (leverage, symbol, params)


def test_client_enables_sandbox_and_maps_positions():
    client = HyperliquidClient(load_live_config("configs/live_hyperliquid_testnet.yaml"), FakeExchange())
    assert client.exchange.sandbox is True
    assert client.fetch_balance().equity == 10000
    assert client.fetch_balance().available == 8000
    assert client.fetch_positions()[0].symbol == "BTC"
    assert client.fetch_positions()[0].side == "long"


@pytest.mark.parametrize("unrealized_pnl", [100, -100])
def test_client_uses_account_value_without_adding_unrealized_pnl(unrealized_pnl):
    exchange = FakeExchange()
    exchange.fetch_positions = lambda: [
        {
            "symbol": "BTC/USDC:USDC",
            "side": "long",
            "contracts": 1,
            "positionValue": 100,
            "markPrice": 100,
            "unrealizedPnl": unrealized_pnl,
        }
    ]

    balance = HyperliquidClient(load_live_config("configs/live_hyperliquid_testnet.yaml"), exchange).fetch_balance()

    assert balance.equity == 10000
    assert balance.available == 8000


@pytest.mark.parametrize("free,withdrawable", [(None, 1), (1, None), ("not-a-number", 1), ("nan", 1), (1, -1)])
def test_client_balance_fails_closed_on_missing_or_invalid_available_values(free, withdrawable):
    exchange = FakeExchange()
    exchange.fetch_balance = lambda: {"USDC": {"total": 10000, "free": free}, "info": {"withdrawable": withdrawable}}

    with pytest.raises(AccountDataError):
        HyperliquidClient(load_live_config("configs/live_hyperliquid_testnet.yaml"), exchange).fetch_balance()


@pytest.mark.parametrize("notional_field", ["positionValue", "notional"])
def test_client_position_valuation_uses_notional_before_mark_and_rejects_invalid_schema(notional_field):
    exchange = FakeExchange()
    exchange.fetch_positions = lambda: [{"symbol": "BTC/USDC:USDC", "side": "long", "contracts": 2, notional_field: 300, "markPrice": None}]
    client = HyperliquidClient(load_live_config("configs/live_hyperliquid_testnet.yaml"), exchange)

    assert client.fetch_positions()[0].notional == 300

    exchange.fetch_positions = lambda: [{"symbol": "BTC/USDC:USDC", "side": "mystery", "contracts": 2, "markPrice": 100}]
    with pytest.raises(AccountDataError):
        client.fetch_positions()


def test_client_position_uses_qty_times_mark_only_when_notional_missing_and_never_contract_size_or_entry_price():
    exchange = FakeExchange()
    client = HyperliquidClient(load_live_config("configs/live_hyperliquid_testnet.yaml"), exchange)
    exchange.fetch_positions = lambda: [{"symbol": "BTC/USDC:USDC", "side": "long", "contracts": 2, "markPrice": 100, "entryPrice": 1}]

    assert client.fetch_positions()[0].notional == 200

    exchange.fetch_positions = lambda: [{"symbol": "BTC/USDC:USDC", "side": "long", "contracts": 0, "contractSize": 9, "markPrice": 100}]
    assert client.fetch_positions() == []
    exchange.fetch_positions = lambda: [{"symbol": "BTC/USDC:USDC", "side": "long", "contracts": 2, "markPrice": None, "entryPrice": 100}]
    with pytest.raises(AccountDataError):
        client.fetch_positions()


def test_client_places_reduce_only_stop_and_cancels_by_id():
    client = HyperliquidClient(load_live_config("configs/live_hyperliquid_testnet.yaml"), FakeExchange())
    order = client.create_reduce_only_stop("BTC", "long", 0.1, 95)
    client.cancel_order("BTC", order["id"])
    assert order["params"] == {"stopLossPrice": 95, "reduceOnly": True}
    assert client.exchange.cancelled == [("1", "BTC/USDC:USDC")]


def test_client_stop_uses_client_id_and_strictly_parses_current_ccxt_shape():
    exchange = FakeExchange()
    client = HyperliquidClient(load_live_config("configs/live_hyperliquid_testnet.yaml"), exchange)
    order = client.create_reduce_only_stop("BTC", "long", 0.1, 95, "0x" + "a" * 32)
    assert order["params"]["clientOrderId"] == "0x" + "a" * 32

    exchange.fetch_order = lambda *args: {
        "id": "stop-1", "clientOrderId": "0x" + "a" * 32,
        "symbol": "BTC/USDC:USDC", "status": "open", "side": "sell",
        "reduceOnly": True, "amount": "0.1", "triggerPrice": "95",
    }
    stop = client.fetch_protective_stop("BTC", "stop-1")
    assert (stop.order_id, stop.symbol, stop.side, stop.reduce_only, stop.qty, stop.trigger_price) == ("stop-1", "BTC", "sell", True, 0.1, 95)

    exchange.fetch_order = lambda *args: {"id": "stop-1", "status": "open"}
    with pytest.raises(AccountDataError, match="incomplete"):
        client.fetch_protective_stop("BTC", "stop-1")


def test_client_submits_side_aware_ioc_entry_within_l2_boundary():
    exchange = FakeExchange()
    client = HyperliquidClient(load_live_config("configs/live_hyperliquid_testnet.yaml"), exchange)

    long_entry = client.create_ioc_entry("BTC", "long", 0.1, {"bid": 123.40, "ask": 123.50}, "0x" + "1" * 32)
    short_entry = client.create_ioc_entry("BTC", "short", 0.1, {"bid": 123.40, "ask": 123.50})

    assert long_entry["side"] == "buy"
    assert long_entry["params"] == {"timeInForce": "IOC", "clientOrderId": "0x" + "1" * 32}
    assert Decimal(str(long_entry["price"])) <= Decimal("123.50") * Decimal("1.01")
    assert short_entry["side"] == "sell"
    assert short_entry["params"] == {"timeInForce": "IOC"}
    assert Decimal(str(short_entry["price"])) >= Decimal("123.40") * Decimal("0.99")
    assert exchange.ticker_calls == 0

    close = client.close_position_market("BTC", "long", 0.1)

    assert close["price"] == 123.45
    assert close["params"] == {"reduceOnly": True}
    assert exchange.ticker_calls == 1


def test_client_fetches_account_wide_open_orders_when_symbol_is_none():
    exchange = FakeExchange()
    client = HyperliquidClient(load_live_config("configs/live_hyperliquid_testnet.yaml"), exchange)

    assert client.fetch_open_orders() == []
    assert client.fetch_open_orders("BTC") == []
    assert exchange.open_order_calls == [None, "BTC/USDC:USDC"]


def test_current_ccxt_contract_skips_builder_referrer_and_builder_order_action(monkeypatch):
    pytest.importorskip("ccxt")
    client = object.__new__(HyperliquidClient)
    client.config = load_live_config("configs/live_hyperliquid_testnet.yaml")
    exchange = client._create_exchange()
    client.exchange = exchange
    market = {"id": "BTC", "symbol": "BTC/USDC:USDC", "baseId": "0", "precision": {"price": 0.1, "amount": 0.001}, "spot": False, "swap": True, "future": False, "option": False, "settle": "USDC", "type": "swap"}
    actions = []
    assert exchange.options["builderFee"] is False
    assert exchange.options["approvedBuilderFee"] is False
    assert exchange.options["refSet"] is True
    monkeypatch.setattr(exchange, "markets", {market["symbol"]: market})
    monkeypatch.setattr(exchange, "symbols", [market["symbol"]])
    monkeypatch.setattr(exchange, "market", lambda symbol: market)
    monkeypatch.setattr(exchange, "load_markets", lambda *args, **kwargs: exchange.markets)
    monkeypatch.setattr(exchange, "check_required_credentials", lambda: None)
    monkeypatch.setattr(exchange, "amount_to_precision", lambda symbol, amount: str(amount))
    monkeypatch.setattr(exchange, "sign_l1_action", lambda *args, **kwargs: {"r": "0x1", "s": "0x2", "v": 27})
    monkeypatch.setattr(exchange, "is_unified_enabled", lambda *args, **kwargs: False)
    monkeypatch.setattr(exchange, "approve_builder_fee", lambda *args: pytest.fail("approveBuilderFee must not be called"))
    monkeypatch.setattr(exchange, "privatePostExchange", lambda request: (actions.append(request["action"]), {"response": {"data": {"statuses": [{"filled": {"totalSz": "1", "avgPx": "101"}}]}}})[1])

    client.create_ioc_entry("BTC", "long", 1, {"bid": 100, "ask": 100.05})
    client.create_ioc_entry("BTC", "short", 1, {"bid": 100.05, "ask": 100.10})

    assert len(actions) == 2
    assert all(action["type"] == "order" and "builder" not in action for action in actions)
    assert actions[0]["orders"][0]["t"] == {"limit": {"tif": "Ioc"}}
    assert actions[1]["orders"][0]["t"] == {"limit": {"tif": "Ioc"}}
    assert Decimal(actions[0]["orders"][0]["p"]) <= Decimal("100.05") * Decimal("1.01")
    assert Decimal(actions[1]["orders"][0]["p"]) >= Decimal("100.05") * Decimal("0.99")


def test_client_places_gtc_limit_entry_and_fetches_by_client_order_id():
    exchange = FakeExchange()
    client = HyperliquidClient(load_live_config("configs/live_hyperliquid_testnet.yaml"), exchange)

    order = client.create_limit_entry("BTC", "long", 0.1, 123.456, "client-1")
    fetched = client.fetch_order("BTC", None, "client-1")

    assert order == {
        "id": "1",
        "symbol": "BTC/USDC:USDC",
        "side": "buy",
        "amount": 0.1,
        "price": 123.46,
        "params": {"timeInForce": "Gtc", "clientOrderId": "client-1"},
    }
    assert client.format_price("BTC", 123.456) == 123.46
    assert fetched["id"] == "client-1"
    assert exchange.fetched_orders == [
        ("client-1", "BTC/USDC:USDC", {"clientOrderId": "client-1"})
    ]


def test_client_fetch_order_requires_an_order_identifier():
    client = HyperliquidClient(load_live_config("configs/live_hyperliquid_testnet.yaml"), FakeExchange())

    with pytest.raises(ValueError, match="order_id or client_order_id"):
        client.fetch_order("BTC", None)


def test_client_fetches_market_quote_from_l2_top_of_book():
    exchange = FakeExchange()
    client = HyperliquidClient(load_live_config("configs/live_hyperliquid_testnet.yaml"), exchange)

    quote = client.fetch_market_quote("BTC")

    assert exchange.last_order_book == ("BTC/USDC:USDC", 1)
    assert quote.bid == 123.40
    assert quote.ask == 123.50
    assert quote.last == 123.45


def test_client_fetches_only_exact_close_order_realized_pnl_from_my_trades():
    exchange = FakeExchange()
    exchange.fetch_my_trades = lambda *args, **kwargs: [
        {"order": "other", "side": "sell", "amount": 1, "price": 200, "fee": {"cost": 4}, "info": {"closedPnl": "99"}},
        {"order": "close-1", "side": "sell", "amount": 0.1, "price": 110, "fee": {"cost": 0.05}, "info": {"closedPnl": "1.5"}},
        {"order": "close-1", "side": "sell", "amount": 0.2, "price": 111, "fee": {"cost": 0.10}, "info": {"closedPnl": "3.0"}},
    ]
    client = HyperliquidClient(load_live_config("configs/live_hyperliquid_testnet.yaml"), exchange)

    pnl = client.fetch_recent_realized_pnl("BTC", SimpleNamespace(side="long", entry_time="2026-01-01T00:00:00Z"), close_order_id="close-1", close_client_id=None, close_qty=0.3)

    assert pnl == {"exit_price": pytest.approx(110.66666666666667), "realized_pnl": 4.5, "fees": pytest.approx(0.15), "pnl_source": "exchange"}


def test_client_realized_pnl_requires_exact_close_quantity_and_identity():
    exchange = FakeExchange()
    exchange.fetch_my_trades = lambda *args, **kwargs: [
        {"order": "close-1", "side": "sell", "amount": 0.2, "price": 110, "fee": {"cost": 0.05}, "info": {"closedPnl": "1.5"}},
    ]
    client = HyperliquidClient(load_live_config("configs/live_hyperliquid_testnet.yaml"), exchange)
    trade = SimpleNamespace(side="long", entry_time="2026-01-01T00:00:00Z")

    assert client.fetch_recent_realized_pnl("BTC", trade, close_order_id="close-1", close_client_id=None, close_qty=0.3) is None
    assert client.fetch_recent_realized_pnl("BTC", trade, close_order_id=None, close_client_id=None, close_qty=0.2) is None
