import json

import pandas as pd
import pytest

from bbmr.live.config import load_live_config
from bbmr.live.hyperliquid_client import ExchangePosition, LiveBalance, MarketQuote
from bbmr.live.state_store import LiveShadowTrigger, LiveStateStore, MREntryIntent, TrendPendingOrder, TrendShadowTrade
from bbmr.live.trailing_runtime import LiveRuntime, _exchange_positions_notional, _mr_entry_client_order_id, _setup_rsi_passes_risk, latest_completed_features, live_updated_stop
from bbmr.trailing import Setup
from bbmr.trailing_features import build_trailing_features


class FakeExchange:
    def __init__(self):
        self.stop_orders = []
        self.cancelled = []
        self.entries = []
        self.limit_entries = []
        self.open_orders = []
        self.orders = {}
        self.closes = []
        self.leverage_calls = []
        self.positions = []
        self.market_quote = MarketQuote(104.9, 105.1, 105)
        self.entry_quotes = []

    def create_reduce_only_stop(self, symbol, side, qty, stop_price, client_order_id=None):
        order = {
            "id": f"stop-{len(self.stop_orders) + 1}",
            "symbol": symbol,
            "side": "sell" if side == "long" else "buy",
            "qty": qty,
            "amount": qty,
            "stop": stop_price,
            "triggerPrice": stop_price,
            "reduceOnly": True,
            "clientOrderId": client_order_id,
            "status": "open",
        }
        self.stop_orders.append(order)
        self.orders[order["id"]] = order
        return order

    def cancel_order(self, symbol, exchange_order_id):
        self.cancelled.append((symbol, exchange_order_id))
        self.open_orders = [order for order in self.open_orders if str(order.get("id")) != str(exchange_order_id)]
        if exchange_order_id in self.orders:
            self.orders[exchange_order_id]["status"] = "canceled"

    def create_ioc_entry(self, symbol, side, qty, quote, client_order_id=None):
        self.entries.append((symbol, side, qty))
        self.entry_quotes.append(quote)
        return {"id": "entry-1", "filled": qty}

    def create_limit_entry(self, symbol, side, qty, price, client_order_id):
        order = {"id": f"limit-{len(self.limit_entries) + 1}", "symbol": symbol, "side": side, "amount": qty, "price": price, "clientOrderId": client_order_id, "status": "open"}
        self.limit_entries.append((symbol, side, qty, price, client_order_id))
        self.open_orders.append(order)
        self.orders[order["id"]] = order
        return order

    def close_position_market(self, symbol, side, qty):
        self.closes.append((symbol, side, qty))
        return {"id": "close-1", "filled": qty, "price": 120}

    def set_leverage(self, symbol, leverage, margin_mode):
        self.leverage_calls.append((symbol, leverage, margin_mode))

    def format_qty(self, symbol, qty):
        return round(qty, 8)

    def format_price(self, symbol, price):
        return round(price, 8)

    def fetch_positions(self):
        return self.positions

    def fetch_open_orders(self, symbol):
        return list(self.open_orders)

    def fetch_order(self, symbol, order_id, client_order_id=None):
        if order_id in self.orders:
            return self.orders[order_id]
        for order in self.orders.values():
            if client_order_id and order.get("clientOrderId") == client_order_id:
                return order
        raise OrderNotFound("order not found")

    def fetch_market_quote(self, symbol):
        return self.market_quote


class ClockedExchange(FakeExchange):
    def __init__(self, now):
        super().__init__()
        self._now = now

    def now(self):
        return self._now


class ConfirmingEntryExchange(ClockedExchange):
    def __init__(self, now, entry_price=105):
        super().__init__(now)
        self.entry_price = entry_price

    def create_ioc_entry(self, symbol, side, qty, quote, client_order_id=None):
        order = super().create_ioc_entry(symbol, side, qty, quote, client_order_id)
        self.positions = [ExchangePosition(symbol, side, qty, self.entry_price, self.entry_price)]
        return order


class GuardProbeExchange(ConfirmingEntryExchange):
    def __init__(self, now):
        super().__init__(now)
        self.position_probes = 0
        self.open_order_probes = 0
        self.quote_probes = 0

    def fetch_positions(self):
        self.position_probes += 1
        return super().fetch_positions()

    def fetch_open_orders(self, symbol):
        self.open_order_probes += 1
        return super().fetch_open_orders(symbol)

    def fetch_market_quote(self, symbol):
        self.quote_probes += 1
        return super().fetch_market_quote(symbol)


class OrderNotFound(Exception):
    pass


class MissingStopExchange(FakeExchange):
    def cancel_order(self, symbol, exchange_order_id):
        raise OrderNotFound("Order was never placed, already canceled, or filled")


class PnlExchange(FakeExchange):
    def fetch_recent_realized_pnl(self, symbol, trade):
        return {"exit_price": 110, "realized_pnl": 9.5, "fees": 0.25, "pnl_source": "exchange"}


class ExactClosePnlExchange(FakeExchange):
    def fetch_recent_realized_pnl(self, symbol, trade, **kwargs):
        self.pnl_lookup = (symbol, trade.internal_trade_id, kwargs)
        return {"exit_price": 120, "realized_pnl": 9.5, "fees": 0.25, "pnl_source": "exchange"}


class FailingPnlExchange(FakeExchange):
    def fetch_recent_realized_pnl(self, symbol, trade):
        raise RuntimeError("trade history unavailable")


class FailingStopExchange(FakeExchange):
    def create_reduce_only_stop(self, symbol, side, qty, stop_price, client_order_id=None):
        raise RuntimeError("stop create failed")


class MissingStopIdExchange(FakeExchange):
    def create_reduce_only_stop(self, symbol, side, qty, stop_price, client_order_id=None):
        order = {"id": None, "symbol": symbol, "side": "sell" if side == "long" else "buy", "qty": qty, "amount": qty, "stop": stop_price, "triggerPrice": stop_price, "reduceOnly": True, "clientOrderId": client_order_id, "status": "open"}
        self.stop_orders.append(order)
        return order


class FailingLeverageExchange(ClockedExchange):
    def set_leverage(self, symbol, leverage, margin_mode):
        raise RuntimeError("leverage failed")


class FailingEntryExchange(ClockedExchange):
    def create_ioc_entry(self, symbol, side, qty, quote, client_order_id=None):
        raise RuntimeError("entry failed")


class LostEntryResponseExchange(ClockedExchange):
    def __init__(self, now):
        super().__init__(now)
        self.entry_client_ids = []
        self.lookup_missing = False

    def create_ioc_entry(self, symbol, side, qty, quote, client_order_id=None):
        self.entries.append((symbol, side, qty))
        self.entry_client_ids.append(client_order_id)
        raise TimeoutError("entry response lost")

    def fetch_order(self, symbol, order_id, client_order_id=None):
        if order_id in self.orders:
            return self.orders[order_id]
        if client_order_id not in self.entry_client_ids:
            raise OrderNotFound("order not found")
        if self.lookup_missing:
            raise OrderNotFound("order not found")
        raise TimeoutError("entry lookup timed out")


class TerminalNoFillExchange(ClockedExchange):
    def fetch_order(self, symbol, order_id, client_order_id=None):
        return {"id": order_id or "entry-1", "status": "canceled"}


class EntryStopFailExchange(ConfirmingEntryExchange):
    def create_reduce_only_stop(self, symbol, side, qty, stop_price, client_order_id=None):
        raise RuntimeError("entry stop failed")


class StopReadTimeoutExchange(FakeExchange):
    def fetch_order(self, symbol, order_id, client_order_id=None):
        raise TimeoutError("stop lookup timed out")


class LostStopCreateResponseExchange(FakeExchange):
    def __init__(self):
        super().__init__()
        self.raise_after_create = True

    def create_reduce_only_stop(self, symbol, side, qty, stop_price, client_order_id=None):
        order = super().create_reduce_only_stop(symbol, side, qty, stop_price, client_order_id)
        if self.raise_after_create:
            self.raise_after_create = False
            raise TimeoutError("create response lost")
        return order


class MissingCreateOutcomeExchange(FakeExchange):
    def __init__(self, lookup_unknown=False):
        super().__init__()
        self.create_calls = 0
        self.lookup_unknown = lookup_unknown

    def create_reduce_only_stop(self, symbol, side, qty, stop_price, client_order_id=None):
        self.create_calls += 1
        raise TimeoutError("create response lost")

    def fetch_order(self, symbol, order_id, client_order_id=None):
        if self.lookup_unknown and self.create_calls:
            raise TimeoutError("client-id lookup timed out")
        return super().fetch_order(symbol, order_id, client_order_id)


class CancelStopTimeoutExchange(FakeExchange):
    def __init__(self):
        super().__init__()
        self.raise_after_cancel = True

    def cancel_order(self, symbol, exchange_order_id):
        if self.raise_after_cancel:
            self.raise_after_cancel = False
            raise TimeoutError("cancel response lost")
        return super().cancel_order(symbol, exchange_order_id)


class CancelAppliedResponseLostExchange(FakeExchange):
    def __init__(self):
        super().__init__()
        self.raise_after_cancel = True

    def cancel_order(self, symbol, exchange_order_id):
        super().cancel_order(symbol, exchange_order_id)
        if self.raise_after_cancel:
            self.raise_after_cancel = False
            raise TimeoutError("cancel response lost")


class FailingCloseExchange(FakeExchange):
    def close_position_market(self, symbol, side, qty):
        raise RuntimeError("close failed")


class FailingFetchPositionsExchange(FakeExchange):
    def fetch_positions(self):
        raise RuntimeError("positions unavailable")


class AverageFillExchange(ClockedExchange):
    def create_ioc_entry(self, symbol, side, qty, quote, client_order_id=None):
        self.entries.append((symbol, side, qty))
        self.entry_quotes.append(quote)
        self.positions = [ExchangePosition(symbol, side, qty, 110, 110)]
        return {"id": "entry-1", "filled": qty, "average": 110}


class ExistingPositionExchange(ClockedExchange):
    def fetch_positions(self):
        return [ExchangePosition("BTC", "long", 1, 100, 101)]


class OpenOrderExchange(ClockedExchange):
    def fetch_open_orders(self, symbol):
        return [{"id": "manual-order"}]


class RecordingOhlcvExchange(FakeExchange):
    def __init__(self):
        super().__init__()
        self.calls = []

    def fetch_ohlcv(self, symbol, timeframe, limit):
        self.calls.append((symbol, timeframe, limit))
        return _frame(["2030-01-01 08:00"], [{"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])


def _config(tmp_path):
    config = load_live_config("configs/live_hyperliquid_testnet.yaml")
    config.storage.sqlite_path = str(tmp_path / "live.sqlite3")
    return config


def _runtime(tmp_path):
    config = _config(tmp_path)
    exchange = FakeExchange()
    return LiveRuntime(config, exchange, LiveStateStore(config.storage.sqlite_path)), exchange


def _runtime_with_exchange(tmp_path, exchange):
    config = _config(tmp_path)
    return LiveRuntime(config, exchange, LiveStateStore(config.storage.sqlite_path))


def _seed_verified_stop(runtime, exchange, *, stop_id="old-stop", qty=1, trigger=95):
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", qty, 100, "strategy", trigger)
    trade.system_stop_order_id = stop_id
    trade.protection_status = "protected"
    exchange.orders[stop_id] = {"id": stop_id, "symbol": "BTC", "side": "sell", "amount": qty, "triggerPrice": trigger, "reduceOnly": True, "status": "open"}
    runtime.store.update_trade(trade)
    return trade


def test_position_key_uses_bound_store_identity(tmp_path):
    config = _config(tmp_path)
    runtime = LiveRuntime(
        config,
        FakeExchange(),
        LiveStateStore(config.storage.sqlite_path, identity_fingerprint="a" * 64, environment="testnet"),
    )

    assert runtime.position_key("BTC/USDC:USDC", "long") == f"{'a' * 64}:testnet:BTC:long"


def _frame(index, rows):
    return pd.DataFrame(rows, index=[pd.Timestamp(value, tz="UTC") for value in index])


def _long_features_with_old_filter_columns():
    one_h = _one_h_history("2026-01-01 08:00", {"open": 120, "high": 121, "low": 90, "close": 95, "lb": 100, "mb": 120, "ub": 140, "rsi14": 20, "range_allowed": False, "lower_band_walking": True})
    fifteen_m = _frame(
        ["2026-01-01 08:45", "2026-01-01 09:00", "2026-01-01 09:15"],
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 20},
            {"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 25},
            {"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 30},
        ],
    )
    five_m = _frame(
        ["2026-01-01 09:25", "2026-01-01 09:30"],
        [
            {"open": 99, "high": 100, "low": 98, "close": 99, "mb": 100, "volume_ratio": 0, "rsi_flat_entry_block": True},
            {"open": 104, "high": 106, "low": 103, "close": 105, "mb": 100, "volume_ratio": 0, "rsi_flat_entry_block": True},
        ],
    )
    return one_h, fifteen_m, five_m


def _future_long_features(close_5m=99, close_time="2030-01-01 09:35"):
    close_ts = pd.Timestamp(close_time, tz="UTC")
    one_h = _one_h_history("2030-01-01 08:00", {"open": 120, "high": 121, "low": 90, "close": 95, "lb": 100, "mb": 120, "ub": 140, "rsi14": 20})
    fifteen_m = _frame(
        ["2030-01-01 08:45", "2030-01-01 09:00", "2030-01-01 09:15"],
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 20},
            {"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 25},
            {"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 30},
        ],
    )
    five_m = _frame(
        [(close_ts - pd.Timedelta(minutes=10)).isoformat(), (close_ts - pd.Timedelta(minutes=5)).isoformat()],
        [
            {"open": 99, "high": 100, "low": 98, "close": 99, "mb": 100, "rsi14": 50},
            {"open": close_5m, "high": close_5m + 1, "low": close_5m - 1, "close": close_5m, "mb": 100, "rsi14": 50},
        ],
    )
    return one_h, fifteen_m, five_m


def _adverse_long_features():
    one_h = _one_h_history("2030-01-01 08:00", {"open": 120, "high": 121, "low": 90, "close": 95, "lb": 100, "mb": 120, "ub": 140, "rsi14": 20})
    one_h.iloc[-4:, one_h.columns.get_loc("mb")] = [122, 121, 120, 120]
    _, fifteen_m, five_m = _future_long_features(close_5m=105)
    return one_h, fifteen_m, five_m


def _trend_features(*, continuing_episode=False):
    index = pd.date_range(end="2030-01-01 09:00Z", periods=120, freq="h")
    one_h = pd.DataFrame(
        [{"open": 100, "high": 121, "low": 99, "close": 100, "lb": 90, "mb": 100, "ub": 110, "rsi14": 50} for _ in index],
        index=index,
    )
    if continuing_episode:
        one_h.iloc[-2, one_h.columns.get_loc("mb")] = 101
        one_h.iloc[-2, one_h.columns.get_loc("close")] = 118
    one_h.iloc[-1, one_h.columns.get_loc("mb")] = 102 if continuing_episode else 101
    one_h.iloc[-1, one_h.columns.get_loc("close")] = 120
    one_h.iloc[-1, one_h.columns.get_loc("ub")] = 130
    five_m = _frame(
        ["2030-01-01 10:05", "2030-01-01 10:10"],
        [
            {"open": 120, "high": 121, "low": 119.5, "close": 120, "mb": 101},
            {"open": 120, "high": 121, "low": 119.2, "close": 120, "mb": 101},
        ],
    )
    return one_h, five_m


def test_entry_sizing_uses_margin_fraction_times_leverage(tmp_path):
    runtime, _ = _runtime(tmp_path)
    assert runtime.entry_notional(10000) == 10000 * runtime.live_config.execution.margin_fraction * runtime.live_config.execution.leverage
    assert runtime.entry_notional(10000, 2) == 10000 * runtime.live_config.execution.margin_fraction * 2


def test_invalid_exchange_position_valuation_fails_before_mean_reversion_or_trend_leverage(tmp_path):
    exchange = ConfirmingEntryExchange("2030-01-01 09:35Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    malformed = [ExchangePosition("ETH", "long", 1, 100, 0)]

    with pytest.raises(ValueError, match="invalid exchange position valuation"):
        runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, True, exchange_positions=malformed)

    assert exchange.leverage_calls == exchange.entries == exchange.stop_orders == []
    assert _exchange_positions_notional([ExchangePosition("BTC", "long", 1, 1, 100, 300)]) == 300

    trend_exchange = ClockedExchange("2030-01-01 10:15Z")
    trend_runtime = _runtime_with_exchange(tmp_path / "trend", trend_exchange)
    trend_runtime.trend_mode = "live"
    one_h, five_m = _trend_features()
    trend_runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])
    trend_runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])
    with pytest.raises(ValueError, match="invalid exchange position valuation"):
        trend_runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, malformed)
    assert trend_exchange.leverage_calls == trend_exchange.entries == trend_exchange.limit_entries == trend_exchange.cancelled == []


def test_shadow_trend_episode_creates_frozen_limit_then_fills_future_completed_5m(tmp_path):
    exchange = ClockedExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    runtime.trend_mode = "shadow"
    runtime.setups["BTC"] = Setup("long", pd.Series({"close": 100, "lb": 90, "mb": 100, "ub": 110, "rsi14": 50}), pd.Timestamp("2030-01-01 10:00Z"), pd.Timestamp("2030-01-01 11:00Z"))
    one_h, five_m = _trend_features()

    episode = runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])

    pending = runtime.store.trend_pending("BTC")
    assert episode is not None and episode.side == "long"
    assert pending is not None and pending.status == "intent"
    expected_limit = 120 * (1 - runtime.strategy_config.trend_riding.entry_pullback_pct)
    assert pending.frozen_close == 120 and pending.limit_price == pytest.approx(expected_limit)
    assert runtime.store.open_trend_shadow_trade("BTC") is None
    assert runtime.trend_states["BTC"]["bandwidth"]["trend_veto"] is False
    runtime.record_trend_mr_outcome("BTC", ["BTC waiting for 1h setup"])
    snapshot = json.loads(runtime.store.trend_pending("BTC").entry_snapshot_json)
    assert snapshot["cost_assumptions"]["entry_fee_bps"] == runtime.strategy_config.costs.taker_fee_bps
    assert snapshot["actual_mean_reversion"]["status"] == "final"
    assert snapshot["real_baseline"]["pending_mean_reversion"]["side"] == "long"
    assert set(snapshot["mean_reversion_filters"]["slope"]) == {"long", "short"}

    exchange._now = pd.Timestamp("2030-01-01 10:20Z")
    future = _frame(["2030-01-01 10:15"], [{"open": 120, "high": 120, "low": 118, "close": 119, "mb": 101}])
    runtime.trend_poll("BTC", one_h, pd.concat([five_m, future]), LiveBalance(10000, 10000), [])

    shadow = runtime.store.open_trend_shadow_trade("BTC")
    assert shadow is not None and shadow.entry_price == pytest.approx(expected_limit)
    assert shadow.initial_stop_loss == pytest.approx(expected_limit * .95)
    assert runtime.store.trend_pending("BTC") is None
    assert {row["event_type"] for row in runtime.store.events()} >= {"trend_pending_created", "trend_pending_filled", "trend_shadow_opened"}
    assert exchange.leverage_calls == exchange.entries == exchange.stop_orders == exchange.cancelled == exchange.closes == []


def test_mr_outcome_opened_fact_overrides_earlier_waiting_event(tmp_path):
    exchange = ClockedExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    one_h, five_m = _trend_features()
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])

    runtime.record_trend_mr_outcome("BTC", ["BTC waiting for 1h setup", "BTC strategy entry opened; protected"])

    outcome = json.loads(runtime.store.events()[-1]["payload_json"])
    assert outcome["order_opened"] is True
    assert outcome["actual_allow"] is True
    assert outcome["reason"] is None


def test_shadow_restart_replays_completed_candles_in_timestamp_order(tmp_path):
    exchange = ClockedExchange("2030-01-01 10:10Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    shadow = TrendShadowTrade(
        "shadow-1", "BTC", "long", "open", pd.Timestamp("2030-01-01 09:30Z"),
        100, 1, 100, 95, 95, pd.Timestamp("2030-01-01 09:00Z"),
        last_1h_bucket=pd.Timestamp("2030-01-01 08:00Z"),
        last_5m_bucket=pd.Timestamp("2030-01-01 09:55Z"),
        favorable_price=100,
    )
    runtime.store.create_trend_shadow_trade(shadow, {})
    one_h = _frame(
        ["2030-01-01 06:00", "2030-01-01 07:00", "2030-01-01 08:00", "2030-01-01 09:00"],
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "lb": 90, "mb": 100, "ub": 130},
            {"open": 100, "high": 101, "low": 99, "close": 100, "lb": 90, "mb": 100, "ub": 130},
            {"open": 100, "high": 101, "low": 99, "close": 100, "lb": 90, "mb": 100, "ub": 130},
            {"open": 100, "high": 111, "low": 99, "close": 110, "lb": 90, "mb": 101, "ub": 130},
        ],
    )
    five_m = _frame(
        ["2030-01-01 10:00"],
        [{"open": 105, "high": 106, "low": 104, "close": 105, "mb": 101}],
    )

    runtime._update_trend_shadow("BTC", one_h, five_m)

    row = runtime.store.connection.execute(
        "SELECT status, exit_reason, exit_price FROM live_trend_shadow_trades WHERE shadow_trade_id = ?",
        ("shadow-1",),
    ).fetchone()
    assert row["status"] == "closed" and row["exit_reason"] == "protective_stop"
    assert row["exit_price"] == pytest.approx(110 * .95)


@pytest.mark.parametrize(("side", "middles", "entry", "old_stop", "mark"), [("long", [100, 100, 100, 110], 100, 95, 100), ("short", [100, 100, 100, 90], 100, 105, 96)])
def test_crossed_trend_stop_market_closes_before_stop_replacement(tmp_path, side, middles, entry, old_stop, mark):
    exchange = ClockedExchange("2030-01-01 12:00Z")
    exchange.get_market_price = lambda symbol: mark
    exchange.positions = [ExchangePosition("BTC", side, 1, entry, mark)]
    original_close = exchange.close_position_market
    def close(symbol, trade_side, qty):
        original_close(symbol, trade_side, qty)
        exchange.positions = []
    exchange.close_position_market = close
    runtime = _runtime_with_exchange(tmp_path, exchange)
    trade = runtime.store.create_trade(runtime.position_key("BTC", side), "BTC", side, 1, entry, "trend_riding", old_stop, entry_time="2030-01-01 08:00Z")
    trade.system_stop_order_id = "old-stop"
    runtime.store.update_trade(trade)

    event = runtime.update_trend_trade(trade, _slope_features(middles, side=side), True)

    assert "trend position closed" in event
    assert exchange.closes == [("BTC", side, 1)]
    assert exchange.stop_orders == []
    assert exchange.cancelled == [("BTC", "old-stop")]
    assert runtime.store.open_trade(trade.exchange_position_key) is None


@pytest.mark.parametrize("leave_position", [True, False])
def test_crossed_trend_stop_close_failure_retains_old_protection(tmp_path, leave_position):
    exchange = ClockedExchange("2030-01-01 12:00Z")
    exchange.get_market_price = lambda symbol: 100
    exchange.positions = [ExchangePosition("BTC", "long", 1, 100, 100)]
    if not leave_position:
        def fail_close(*_args):
            raise RuntimeError("close unavailable")
        exchange.close_position_market = fail_close
    runtime = _runtime_with_exchange(tmp_path, exchange)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "trend_riding", 95, entry_time="2030-01-01 08:00Z")
    trade.system_stop_order_id = "old-stop"
    runtime.store.update_trade(trade)

    event = runtime.update_trend_trade(trade, _slope_features([100, 100, 100, 110], side="long"), True)

    persisted = runtime.store.open_trade(trade.exchange_position_key)
    assert "old protective stop retained" in event
    assert persisted is not None and persisted.current_stop_loss == 95 and persisted.system_stop_order_id == "old-stop"
    assert exchange.cancelled == [] and exchange.stop_orders == []
    assert json.loads(runtime.store.events()[-1]["payload_json"])["severity"] == "CRITICAL"


def test_live_trend_places_gtc_limit_and_partial_fill_reconciles_before_manual_adoption(tmp_path):
    exchange = ClockedExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    runtime.trend_mode = "live"
    one_h, five_m = _trend_features()
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])

    waiting = runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])
    assert "local pending" in waiting and exchange.limit_entries == []
    event = runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])

    pending = runtime.store.trend_pending("BTC")
    assert "TREND ORDER" in event
    assert any(message.startswith("TREND TOUCH BTC LONG") for message in runtime.consume_trend_transitions("BTC"))
    assert exchange.entries == [] and len(exchange.limit_entries) == 1
    assert pending.status == "open" and pending.client_order_id.startswith("0x") and len(pending.client_order_id) == 34
    partial_qty = pending.requested_qty / 2
    exchange.positions = [ExchangePosition("BTC", "long", partial_qty, 118.7, 118.7)]

    reconciled = runtime.reconcile_symbol("BTC", exchange.positions, True)

    trade = runtime.managed_trade("BTC")
    assert "reconciled and protected" in reconciled[0]
    assert trade is not None and trade.source == "trend_riding" and trade.qty == partial_qty and trade.entry_price == 118.7
    assert trade.midband_follow_bucket_start == pending.last_1h_bucket
    assert trade.initial_stop_loss == pytest.approx(118.7 * .95)
    assert exchange.cancelled == [("BTC", pending.exchange_order_id)] and exchange.stop_orders


def test_live_trend_local_watch_invalidates_middle_before_limit_touch(tmp_path):
    exchange = ClockedExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    runtime.trend_mode = "live"
    one_h, five_m = _trend_features()

    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])
    pending = runtime.store.trend_pending("BTC")
    assert pending is not None and pending.status == "intent"
    assert exchange.leverage_calls == exchange.limit_entries == []

    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])
    exchange.market_quote = MarketQuote(99.9, 100.0, 99.95)
    event = runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])

    terminal = runtime.store.trend_pending_for_episode("BTC", pending.side, pending.episode_bucket)
    assert event == "TREND INVALIDATED/CANCEL BTC LONG reason=live_middle_invalidated quote=100.00000000 middle=101.00000000"
    assert terminal.status == "canceled" and terminal.cancel_reason == "live_middle_invalidated"
    assert exchange.leverage_calls == exchange.limit_entries == []


def test_live_trend_local_watch_completed_middle_cancels_before_quote_or_order(tmp_path):
    exchange = ClockedExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    runtime.trend_mode = "live"
    one_h, five_m = _trend_features()
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])
    pending = runtime.store.trend_pending("BTC")

    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])
    one_h.iloc[-1, one_h.columns.get_loc("close")] = 101
    event = runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])

    terminal = runtime.store.trend_pending_for_episode("BTC", pending.side, pending.episode_bucket)
    assert "reason=completed_1h_middle_invalidated" in event
    assert terminal.status == "canceled" and terminal.cancel_reason == "completed_1h_middle_invalidated"
    assert exchange.leverage_calls == exchange.limit_entries == []


def test_shadow_trend_uses_completed_5m_middle_invalidation_before_limit_touch(tmp_path):
    exchange = ClockedExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    runtime.trend_mode = "shadow"
    one_h, five_m = _trend_features()
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])
    pending = runtime.store.trend_pending("BTC")

    exchange._now = pd.Timestamp("2030-01-01 10:20Z")
    future = _frame(["2030-01-01 10:15"], [{"open": 120, "high": 120, "low": 100, "close": 119, "mb": 101}])
    runtime.trend_poll("BTC", one_h, pd.concat([five_m, future]), LiveBalance(10000, 10000), [])

    terminal = runtime.store.trend_pending_for_episode("BTC", pending.side, pending.episode_bucket)
    assert terminal.status == "canceled" and terminal.cancel_reason == "shadow_middle_invalidated"
    assert runtime.store.open_trend_shadow_trade("BTC") is None
    assert exchange.leverage_calls == exchange.limit_entries == exchange.closes == []


@pytest.mark.parametrize("restart_mode", ["off", "shadow"])
def test_restart_mode_change_cancels_only_owned_live_gtc_order(tmp_path, restart_mode):
    exchange = ClockedExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    runtime.trend_mode = "live"
    one_h, five_m = _trend_features()
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])
    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])
    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])
    owned = runtime.store.trend_pending("BTC")
    manual = {"id": "manual-order", "symbol": "BTC", "side": "sell", "status": "open"}
    exchange.open_orders.append(manual)
    exchange.orders[manual["id"]] = manual

    restarted = _runtime_with_exchange(tmp_path, exchange)
    restarted.trend_mode = restart_mode
    restarted.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])
    assert restarted.store.trend_pending("BTC").status == "cancel_requested"

    restarted.reconcile_symbol("BTC", [], True)

    assert exchange.cancelled == [("BTC", owned.exchange_order_id)]
    assert [order["id"] for order in exchange.open_orders] == ["manual-order"]
    assert restarted.store.trend_pending("BTC") is None
    terminal = restarted.store.trend_pending_for_episode("BTC", "long", owned.episode_bucket)
    assert terminal.status == "canceled"


def test_partial_fill_cancel_race_uses_final_exchange_qty_and_average(tmp_path):
    class CancelRaceExchange(ClockedExchange):
        final_position = None

        def cancel_order(self, symbol, exchange_order_id):
            if self.final_position is not None:
                self.positions = [self.final_position]
            super().cancel_order(symbol, exchange_order_id)

    exchange = CancelRaceExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    runtime.trend_mode = "live"
    one_h, five_m = _trend_features()
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])
    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])
    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])
    pending = runtime.store.trend_pending("BTC")
    exchange.positions = [ExchangePosition("BTC", "long", pending.requested_qty / 2, 118.7, 118.7)]
    exchange.final_position = ExchangePosition("BTC", "long", pending.requested_qty * .8, 119.1, 119.1)

    runtime.reconcile_symbol("BTC", list(exchange.positions), True)

    trade = runtime.managed_trade("BTC")
    assert trade.qty == pytest.approx(pending.requested_qty * .8)
    assert trade.entry_price == pytest.approx(119.1)
    assert trade.initial_stop_loss == pytest.approx(119.1 * .95)
    assert exchange.stop_orders[-1]["qty"] == pytest.approx(pending.requested_qty * .8)


def test_partial_fill_cancel_timeout_still_uses_fresh_fill_and_keeps_exact_retry_state(tmp_path):
    class TimeoutCancelRaceExchange(ClockedExchange):
        final_position = None

        def cancel_order(self, symbol, exchange_order_id):
            self.cancelled.append((symbol, exchange_order_id))
            if self.final_position is not None:
                self.positions = [self.final_position]
            raise TimeoutError("cancel response lost")

    exchange = TimeoutCancelRaceExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    runtime.trend_mode = "live"
    one_h, five_m = _trend_features()
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])
    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])
    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])
    pending = runtime.store.trend_pending("BTC")
    owned_order_id = pending.exchange_order_id
    exchange.positions = [ExchangePosition("BTC", "long", pending.requested_qty / 2, 118.7, 118.7)]
    exchange.final_position = ExchangePosition("BTC", "long", pending.requested_qty * .8, 119.2, 119.2)

    runtime.reconcile_symbol("BTC", list(exchange.positions), True)

    trade = runtime.managed_trade("BTC")
    retry = runtime.store.trend_pending("BTC")
    assert trade.qty == pytest.approx(pending.requested_qty * .8)
    assert trade.entry_price == pytest.approx(119.2)
    assert trade.initial_stop_loss == pytest.approx(119.2 * .95)
    assert exchange.stop_orders[-1]["qty"] == pytest.approx(pending.requested_qty * .8)
    assert retry.status == "cancel_requested" and retry.exchange_order_id == owned_order_id
    assert "order still open after cancel" in retry.cancel_reason


@pytest.mark.parametrize(
    ("side", "final_entry", "existing_stop", "expected_initial"),
    [("long", 101, 98, 101 * .95), ("short", 99, 102, 99 * 1.05)],
)
def test_partial_fill_refresh_keeps_improved_trend_stop_monotonic(tmp_path, side, final_entry, existing_stop, expected_initial):
    exchange = ClockedExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    client_order_id = "0x" + "1" * 32
    pending = TrendPendingOrder(
        "pending-1", "BTC", side, "live", "open", pd.Timestamp("2030-01-01 09:00Z"),
        100, 99 if side == "long" else 101, 2, 200, .05,
        exchange_order_id="owned-limit", client_order_id=client_order_id,
    )
    runtime.store.create_trend_pending(pending)
    owned_order = {"id": "owned-limit", "symbol": "BTC", "side": side, "status": "open", "clientOrderId": client_order_id}
    exchange.orders["owned-limit"] = owned_order
    exchange.open_orders.append(owned_order)
    trade = runtime.store.create_trade(
        runtime.position_key("BTC", side), "BTC", side, 1, 100, "trend_riding",
        95 if side == "long" else 105, entry_time="2030-01-01 08:00Z",
    )
    trade.current_stop_loss = existing_stop
    trade.system_stop_order_id = "old-stop"
    trade.trend_break_even = True
    runtime.store.update_trade(trade)
    exchange.positions = [ExchangePosition("BTC", side, 1.5, final_entry, final_entry)]

    runtime.reconcile_symbol("BTC", list(exchange.positions), True)

    refreshed = runtime.managed_trade("BTC")
    assert refreshed.qty == pytest.approx(1.5)
    assert refreshed.entry_price == pytest.approx(final_entry)
    assert refreshed.initial_stop_loss == pytest.approx(expected_initial)
    assert refreshed.current_stop_loss == pytest.approx(existing_stop)
    assert refreshed.trend_break_even is True
    assert exchange.stop_orders[-1]["qty"] == pytest.approx(1.5)
    assert exchange.stop_orders[-1]["stop"] == pytest.approx(existing_stop)


def test_mode_switch_cancel_race_adopts_fill_instead_of_terminal_cancel(tmp_path):
    class CancelFillExchange(ClockedExchange):
        fill_position = None

        def cancel_order(self, symbol, exchange_order_id):
            if self.fill_position is not None:
                self.positions = [self.fill_position]
            super().cancel_order(symbol, exchange_order_id)

    exchange = CancelFillExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    runtime.trend_mode = "live"
    one_h, five_m = _trend_features()
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])
    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])
    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])
    pending = runtime.store.trend_pending("BTC")
    exchange.fill_position = ExchangePosition("BTC", "long", pending.requested_qty, 118.6, 118.6)

    runtime.trend_mode = "off"
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])
    runtime.reconcile_symbol("BTC", [], True)

    trade = runtime.managed_trade("BTC")
    assert trade is not None and trade.source == "trend_riding"
    assert trade.qty == pytest.approx(pending.requested_qty) and trade.entry_price == pytest.approx(118.6)
    assert trade.initial_stop_loss == pytest.approx(118.6 * .95)
    assert runtime.store.trend_pending_for_episode("BTC", "long", pending.episode_bucket).status == "filled"


def test_ambiguous_live_limit_recovers_by_deterministic_client_id_before_cancel(tmp_path):
    class AmbiguousLimitExchange(ClockedExchange):
        def create_limit_entry(self, symbol, side, qty, price, client_order_id):
            super().create_limit_entry(symbol, side, qty, price, client_order_id)
            raise TimeoutError("submit response lost")

    exchange = AmbiguousLimitExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    runtime.trend_mode = "live"
    one_h, five_m = _trend_features()
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])

    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])
    event = runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])
    pending = runtime.store.trend_pending("BTC")
    assert "ambiguous" in event and pending.status == "ambiguous" and pending.exchange_order_id is None
    assert pending.client_order_id.startswith("0x") and len(pending.client_order_id) == 34

    runtime._request_trend_pending_cancel(pending, "test_cancel")
    canceled = runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])
    assert "canceled" in canceled
    assert exchange.cancelled == [("BTC", "limit-1")]
    assert runtime.store.trend_pending("BTC") is None


def test_trend_entry_unprotected_recovery_keeps_trend_five_percent_stop(tmp_path):
    runtime, exchange = _runtime(tmp_path)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "trend_riding", 95, status="entry_unprotected")
    position = ExchangePosition("BTC", "long", 1, 120, 120)

    events = runtime.reconcile_symbol("BTC", [position], True)

    recovered = runtime.store.open_trade(trade.exchange_position_key)
    assert events == []
    assert recovered.initial_stop_loss == pytest.approx(114)
    assert recovered.current_stop_loss == pytest.approx(114)
    assert exchange.stop_orders[-1]["stop"] == pytest.approx(114)


def test_trend_episode_late_start_does_not_backfill_and_directional_normal_cancels_pending(tmp_path):
    exchange = ClockedExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    continuing, five_m = _trend_features(continuing_episode=True)
    runtime.trend_poll("BTC", continuing, five_m, LiveBalance(10000, 10000), [])
    assert runtime.store.trend_pending("BTC") is None
    assert runtime.trend_states["BTC"]["pending_status"] == "late_start_no_backfill"

    runtime2 = _runtime_with_exchange(tmp_path / "fresh", ClockedExchange("2030-01-01 10:15Z"))
    one_h, five_m = _trend_features()
    runtime2.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])
    one_h.iloc[-1, one_h.columns.get_loc("mb")] = 99
    runtime2.exchange._now = pd.Timestamp("2030-01-01 10:20Z")
    runtime2.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])
    original = runtime2.store.trend_pending_for_episode("BTC", "long", pd.Timestamp("2030-01-01 09:00Z"))
    assert original.status == "canceled"
    assert original.cancel_reason == "directional_slope_normal"


@pytest.mark.parametrize("bad_middle", [float("nan"), float("inf"), float("-inf")])
def test_invalid_trend_slope_preserves_live_management_state(tmp_path, bad_middle):
    runtime, _exchange = _runtime(tmp_path)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "trend_riding", 95, entry_time="2030-01-01 08:00Z")
    trade.special_tp_active, trade.adverse_slope_tp_price, trade.current_stop_loss, trade.midband_follow_bucket_start = True, 110, 99, pd.Timestamp("2030-01-01 07:00Z")
    runtime.store.update_trade(trade)
    features = _slope_features([100, 100, 100, bad_middle], side="long")

    assert runtime.update_trend_trade(trade, features, False) is None
    loaded = runtime.store.open_trade(trade.exchange_position_key)
    assert (loaded.special_tp_active, loaded.adverse_slope_tp_price, loaded.current_stop_loss, loaded.midband_follow_bucket_start) == (True, 110, 99, pd.Timestamp("2030-01-01 07:00Z"))


def test_first_weakening_row_can_close_on_middle_cross_same_hour(tmp_path):
    exchange = ClockedExchange("2030-01-01 12:00Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "trend_riding", 95, entry_time="2030-01-01 08:00Z")
    features = _slope_features([100.0, 100.0, 100.0, 100.15], side="long")
    features.iloc[-1, features.columns.get_loc("close")] = 100.1

    event = runtime.update_trend_trade(trade, features, False)

    assert "trend_weakening_middle_cross" in event
    assert runtime.store.open_trade(trade.exchange_position_key).special_tp_active is True


def test_canceled_trend_episode_never_refreshes_or_retries(tmp_path):
    exchange = ClockedExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    one_h, five_m = _trend_features()
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])
    original = runtime.store.trend_pending("BTC")
    original.cancel_reason = "test_terminal"
    original.status = "canceled"
    runtime.store.update_trend_pending(original, "trend_pending_canceled", {"reason": original.cancel_reason})

    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])

    assert runtime.store.trend_pending("BTC") is None
    stored = runtime.store.trend_pending_for_episode("BTC", "long", pd.Timestamp("2030-01-01 09:00Z"))
    assert stored.pending_id == original.pending_id and stored.status == "canceled"


def test_trend_pending_expires_six_hours_after_signal_completion(tmp_path):
    exchange = ClockedExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    one_h, five_m = _trend_features()

    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])
    pending = runtime.store.trend_pending("BTC")
    assert pending.expires_at == pd.Timestamp("2030-01-01 16:00Z")

    exchange._now = pd.Timestamp("2030-01-01 16:00Z")
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])

    assert runtime.store.trend_pending("BTC") is None
    terminal = runtime.store.trend_pending_for_episode("BTC", "long", pending.episode_bucket)
    assert terminal.status == "canceled"
    assert terminal.cancel_reason == "pending_ttl_expired"


def test_expiry_candle_renews_only_after_old_pending_is_terminal(tmp_path):
    exchange = ClockedExchange("2030-01-01 16:00Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    old = TrendPendingOrder(
        "expired-pending", "BTC", "long", "live", "intent", pd.Timestamp("2030-01-01 09:00Z"),
        120, 118.8, 1, 120, 0.05, expires_at=pd.Timestamp("2030-01-01 16:00Z"),
    )
    runtime.store.create_trend_pending(old)
    one_h, five_m = _trend_features()
    one_h.index = one_h.index + pd.Timedelta(hours=6)

    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])

    renewed = runtime.store.trend_pending("BTC")
    assert renewed.pending_id != old.pending_id
    assert renewed.episode_bucket == pd.Timestamp("2030-01-01 15:00Z")
    assert renewed.frozen_close == 120
    assert renewed.expires_at == pd.Timestamp("2030-01-01 22:00Z")
    assert runtime.store.trend_pending_for_episode("BTC", "long", old.episode_bucket).status == "canceled"
    assert any(row["event_type"] == "trend_pending_renewed" for row in runtime.store.events())


def test_opposite_protected_strategy_mr_arms_waiting_takeover_without_trend_order(tmp_path):
    exchange = ClockedExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    mr = runtime.store.create_trade(runtime.position_key("BTC", "short"), "BTC", "short", 1, 120, "strategy", 126)
    mr.system_stop_order_id = "mr-stop"
    mr.protection_status = "protected"
    runtime.store.update_trade(mr)
    exchange.positions = [ExchangePosition("BTC", "short", 1, 120, 120)]
    one_h, five_m = _trend_features()

    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), exchange.positions)

    pending = runtime.store.trend_pending("BTC")
    assert pending is not None
    assert pending.takeover_phase == "waiting_opposite_mr"
    assert pending.takeover_trade_id == mr.internal_trade_id
    assert pending.takeover_side == "short"
    assert runtime.trend_states["BTC"]["takeover_phase"] == "waiting_opposite_mr"
    assert runtime.trend_states["BTC"]["takeover_trade_id"] == mr.internal_trade_id
    assert runtime.trend_states["BTC"]["expires_at"] == pending.expires_at.isoformat()
    assert exchange.leverage_calls == exchange.limit_entries == exchange.closes == []


def test_waiting_takeover_cancels_when_linked_mr_is_manually_resized_before_touch(tmp_path):
    exchange = ClockedExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    mr = runtime.store.create_trade(runtime.position_key("BTC", "short"), "BTC", "short", 1, 120, "strategy", 126)
    mr.system_stop_order_id = "mr-stop"
    mr.protection_status = "protected"
    runtime.store.update_trade(mr)
    exchange.orders["mr-stop"] = {"id": "mr-stop", "status": "open"}
    exchange.positions = [ExchangePosition("BTC", "short", 1, 120, 120)]
    one_h, five_m = _trend_features()
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), exchange.positions)
    pending = runtime.store.trend_pending("BTC")

    mr.qty = 1.5
    runtime.store.update_trade_with_event(mr, "manual_size_changed", "BTC", event_kwargs={"event_time": exchange.now()})
    exchange.positions = [ExchangePosition("BTC", "short", 1.5, 120, 120)]

    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, exchange.positions)
    event = runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, exchange.positions)

    terminal = runtime.store.trend_pending_for_episode("BTC", pending.side, pending.episode_bucket)
    stored_mr = runtime.store.open_trade(mr.exchange_position_key)
    assert event == "BTC trend takeover eligibility lost; pending canceled"
    assert terminal.status == "canceled" and terminal.cancel_reason == "takeover_eligibility_lost"
    assert stored_mr is not None and stored_mr.source == "strategy" and stored_mr.side == "short" and stored_mr.status == "open"
    assert exchange.closes == exchange.leverage_calls == exchange.limit_entries == exchange.cancelled == []


def test_waiting_takeover_completed_middle_invalidation_keeps_mr_and_stop(tmp_path):
    exchange = ClockedExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    mr = runtime.store.create_trade(runtime.position_key("BTC", "short"), "BTC", "short", 1, 120, "strategy", 126)
    mr.system_stop_order_id = "mr-stop"
    mr.protection_status = "protected"
    runtime.store.update_trade(mr)
    exchange.orders["mr-stop"] = {"id": "mr-stop", "status": "open"}
    exchange.positions = [ExchangePosition("BTC", "short", 1, 120, 120)]
    one_h, five_m = _trend_features()
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), exchange.positions)
    pending = runtime.store.trend_pending("BTC")

    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, exchange.positions)
    one_h.iloc[-1, one_h.columns.get_loc("close")] = 101
    event = runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, exchange.positions)

    terminal = runtime.store.trend_pending_for_episode("BTC", pending.side, pending.episode_bucket)
    stored_mr = runtime.store.open_trade(mr.exchange_position_key)
    assert "reason=completed_1h_middle_invalidated" in event
    assert terminal.status == "canceled" and terminal.cancel_reason == "completed_1h_middle_invalidated"
    assert stored_mr is not None and stored_mr.status == "open" and stored_mr.system_stop_order_id == "mr-stop"
    assert exchange.closes == exchange.leverage_calls == exchange.limit_entries == exchange.cancelled == []


@pytest.mark.parametrize("takeover_mode", ["off", "shadow"])
def test_takeover_off_and_shadow_never_mutate_opposite_strategy_mr(tmp_path, takeover_mode):
    exchange = ClockedExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    runtime.takeover_mode = takeover_mode
    mr = runtime.store.create_trade(runtime.position_key("BTC", "short"), "BTC", "short", 1, 120, "strategy", 126)
    mr.protection_status = "protected"
    runtime.store.update_trade(mr)
    exchange.positions = [ExchangePosition("BTC", "short", 1, 120, 120)]
    one_h, five_m = _trend_features()

    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), exchange.positions)
    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, exchange.positions)

    assert exchange.leverage_calls == exchange.limit_entries == exchange.closes == exchange.cancelled == []
    if takeover_mode == "off":
        assert runtime.store.trend_pending("BTC") is None
    else:
        assert runtime.store.trend_pending("BTC").takeover_phase == "waiting_opposite_mr"
        assert runtime.store.trend_pending("BTC").mode == "shadow"
        assert sum(row["event_type"] == "trend_takeover_would_takeover" for row in runtime.store.events()) == 1


def test_takeover_actively_closes_partial_mr_before_fixed_trend_gtc(tmp_path):
    class PartialTakeoverExchange(ClockedExchange):
        def close_position_market(self, symbol, side, qty):
            order = super().close_position_market(symbol, side, qty)
            self.positions = [ExchangePosition(symbol, side, 0.4, 120, 120)] if len(self.closes) == 1 else []
            return order

    exchange = PartialTakeoverExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    mr = runtime.store.create_trade(runtime.position_key("BTC", "short"), "BTC", "short", 1, 120, "strategy", 126)
    mr.system_stop_order_id = "mr-stop"
    mr.protection_status = "protected"
    runtime.store.update_trade(mr)
    exchange.orders["mr-stop"] = {"id": "mr-stop", "symbol": "BTC", "side": "buy", "amount": 1, "triggerPrice": 126, "reduceOnly": True, "status": "open"}
    exchange.positions = [ExchangePosition("BTC", "short", 1, 120, 120)]
    one_h, five_m = _trend_features()
    assert runtime._eligible_opposite_strategy_mr("BTC", "long", exchange.positions) is not None
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), exchange.positions)

    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, exchange.positions)
    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, exchange.positions)

    pending = runtime.store.trend_pending("BTC")
    assert pending is not None
    assert pending.takeover_phase == "closing_mr"
    assert exchange.closes == [("BTC", "short", 1)]
    assert exchange.limit_entries == []
    assert exchange.cancelled == []

    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, exchange.positions)

    assert exchange.closes == [("BTC", "short", 1), ("BTC", "short", 0.4)]
    assert exchange.limit_entries == []
    assert exchange.cancelled == [("BTC", "mr-stop")]
    assert runtime.store.trend_pending("BTC").takeover_phase == "trend_entry_intent"
    closed = runtime.store.connection.execute("SELECT status, close_reason FROM live_trades WHERE internal_trade_id = ?", (mr.internal_trade_id,)).fetchone()
    assert dict(closed) == {"status": "closed", "close_reason": "trend_takeover"}

    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])

    assert len(exchange.limit_entries) == 1
    assert exchange.limit_entries[0][3] == pytest.approx(runtime.store.trend_pending("BTC").limit_price)


def test_started_takeover_latches_middle_invalidation_and_remains_flat_after_cleanup(tmp_path):
    exchange = ClockedExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    mr = runtime.store.create_trade(runtime.position_key("BTC", "short"), "BTC", "short", 1, 120, "strategy", 126)
    mr.system_stop_order_id = "mr-stop"
    mr.protection_status = "protected"
    runtime.store.update_trade(mr)
    exchange.orders["mr-stop"] = {"id": "mr-stop", "status": "open"}
    exchange.positions = [ExchangePosition("BTC", "short", 1, 120, 120)]
    one_h, five_m = _trend_features()
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), exchange.positions)

    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, exchange.positions)
    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, exchange.positions)
    pending = runtime.store.trend_pending("BTC")
    assert pending.takeover_phase == "closing_mr" and exchange.closes == [("BTC", "short", 1)]

    one_h.iloc[-1, one_h.columns.get_loc("close")] = 101
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), exchange.positions)
    assert runtime.store.trend_pending("BTC").cancel_reason == "completed_1h_middle_invalidated"

    exchange.positions = []
    event = runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])

    terminal = runtime.store.trend_pending_for_episode("BTC", pending.side, pending.episode_bucket)
    assert "trend invalidated and remained flat" in event
    assert terminal.status == "canceled" and terminal.cancel_reason == "completed_1h_middle_invalidated"
    assert exchange.limit_entries == []


def test_takeover_close_response_loss_waits_for_fresh_flat_truth_before_cleanup(tmp_path):
    class LostCloseResponseExchange(ClockedExchange):
        def close_position_market(self, symbol, side, qty):
            order = super().close_position_market(symbol, side, qty)
            self.positions = []
            raise TimeoutError("close response lost")

    exchange = LostCloseResponseExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    mr = runtime.store.create_trade(runtime.position_key("BTC", "short"), "BTC", "short", 1, 120, "strategy", 126)
    mr.system_stop_order_id = "mr-stop"
    mr.protection_status = "protected"
    runtime.store.update_trade(mr)
    exchange.orders["mr-stop"] = {"id": "mr-stop", "status": "open"}
    exchange.positions = [ExchangePosition("BTC", "short", 1, 120, 120)]
    one_h, five_m = _trend_features()
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), exchange.positions)

    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, exchange.positions)
    first = runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, exchange.positions)
    assert "ambiguous" in first
    assert exchange.closes == [("BTC", "short", 1)]
    assert exchange.cancelled == exchange.limit_entries == []

    restarted = _runtime_with_exchange(tmp_path, exchange)
    restarted.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])
    assert exchange.closes == [("BTC", "short", 1)]
    assert exchange.cancelled == [("BTC", "mr-stop")]
    assert exchange.limit_entries == []


def test_takeover_close_response_loss_retries_only_after_fresh_remainder(tmp_path):
    class LostPartialCloseResponseExchange(ClockedExchange):
        def close_position_market(self, symbol, side, qty):
            order = super().close_position_market(symbol, side, qty)
            if len(self.closes) == 1:
                self.positions = [ExchangePosition(symbol, side, 0.4, 120, 120)]
                raise TimeoutError("close response lost")
            self.positions = []
            return order

    exchange = LostPartialCloseResponseExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    mr = runtime.store.create_trade(runtime.position_key("BTC", "short"), "BTC", "short", 1, 120, "strategy", 126)
    mr.system_stop_order_id = "mr-stop"
    mr.protection_status = "protected"
    runtime.store.update_trade(mr)
    exchange.orders["mr-stop"] = {"id": "mr-stop", "status": "open"}
    exchange.positions = [ExchangePosition("BTC", "short", 1, 120, 120)]
    one_h, five_m = _trend_features()
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), exchange.positions)

    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, exchange.positions)
    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, exchange.positions)
    assert exchange.closes == [("BTC", "short", 1)]

    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, exchange.positions)
    assert exchange.closes == [("BTC", "short", 1), ("BTC", "short", 0.4)]
    assert exchange.limit_entries == []


def test_takeover_stop_cleanup_response_loss_blocks_trend_until_retry_is_terminal(tmp_path):
    class LostStopCleanupResponseExchange(ClockedExchange):
        def close_position_market(self, symbol, side, qty):
            order = super().close_position_market(symbol, side, qty)
            self.positions = []
            return order

        def cancel_order(self, symbol, exchange_order_id):
            super().cancel_order(symbol, exchange_order_id)
            if len(self.cancelled) == 1:
                raise TimeoutError("cancel response lost")

    exchange = LostStopCleanupResponseExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    mr = runtime.store.create_trade(runtime.position_key("BTC", "short"), "BTC", "short", 1, 120, "strategy", 126)
    mr.system_stop_order_id = "mr-stop"
    mr.protection_status = "protected"
    runtime.store.update_trade(mr)
    exchange.orders["mr-stop"] = {"id": "mr-stop", "status": "open"}
    exchange.positions = [ExchangePosition("BTC", "short", 1, 120, 120)]
    one_h, five_m = _trend_features()
    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), exchange.positions)

    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, exchange.positions)
    first = runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, exchange.positions)
    assert "old-stop cleanup pending" in first
    assert runtime.store.trend_pending("BTC").takeover_phase == "flat_cleanup"
    assert exchange.limit_entries == []

    runtime.maybe_open_trend_trade("BTC", one_h, five_m, LiveBalance(10000, 10000), True, False, [])
    assert exchange.limit_entries == []
    assert runtime.store.trend_pending("BTC").takeover_phase == "trend_entry_intent"


def test_trend_pending_does_not_start_while_same_symbol_mr_intent_is_active(tmp_path):
    exchange = ClockedExchange("2030-01-01 10:15Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    intent = MREntryIntent(
        "intent-1", runtime.account, "BTC", "short", pd.Timestamp("2030-01-01 09:00Z"),
        pd.Timestamp("2030-01-01 09:30Z"), 1, 120, 3, 40, 120, 121, "0x" + "1" * 32,
    )
    runtime.store.create_mr_entry_intent_with_event(intent)
    one_h, five_m = _trend_features()

    runtime.trend_poll("BTC", one_h, five_m, LiveBalance(10000, 10000), [])

    assert runtime.store.trend_pending("BTC") is None
    assert runtime.trend_states["BTC"]["pending_status"] == "mr_entry_intent_conflict"


def test_testnet_orders_require_config_and_cli(tmp_path):
    runtime, _ = _runtime(tmp_path)
    assert runtime.can_place_orders(False) is False
    assert runtime.can_place_orders(True) is True
    runtime.live_config.execution.allow_testnet_orders = False
    assert runtime.can_place_orders(True) is False


def test_trailing_features_use_configured_rsi_method(monkeypatch):
    calls = []

    def fake_rsi(close, period, method="sma"):
        calls.append(method)
        return pd.Series(50.0, index=close.index)

    monkeypatch.setattr("bbmr.trailing_features.compute_rsi", fake_rsi)
    config = __import__("bbmr.config", fromlist=["load_config"]).load_config("configs/strategy_bbmr_trailing_stop_v1.yaml")
    ohlcv = _frame(
        ["2030-01-01 08:00", "2030-01-01 08:15", "2030-01-01 08:30"],
        [
            {"open": 1, "high": 2, "low": 0, "close": 1, "volume": 1},
            {"open": 2, "high": 3, "low": 1, "close": 2, "volume": 1},
            {"open": 3, "high": 4, "low": 2, "close": 3, "volume": 1},
        ],
    )

    build_trailing_features(ohlcv, ohlcv, ohlcv, config)

    assert calls == ["wilder", "wilder", "wilder"]


def test_latest_completed_features_uses_rsi_warmup_bars(tmp_path):
    runtime, _ = _runtime(tmp_path)
    exchange = RecordingOhlcvExchange()

    latest_completed_features(exchange, "BTC", runtime.strategy_config)

    assert exchange.calls == [("BTC", "1h", 500), ("BTC", "15m", 500), ("BTC", "5m", 500)]


def test_live_strategy_ignores_old_v3_2_filter_columns(tmp_path):
    exchange = ConfirmingEntryExchange("2030-01-01 09:35Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    events = runtime.maybe_open_strategy_trade("BTC", *_long_features_with_old_filter_columns(), 10000, True)
    expected_qty = runtime.entry_notional(10000) / 105
    assert exchange.leverage_calls == [("BTC", 3, "cross")]
    assert exchange.entries == [("BTC", "long", round(expected_qty, 8))]
    assert any("entry opened" in event for event in events)


def test_strategy_entry_blocks_exspecial_slope_state(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ConfirmingEntryExchange("2030-01-01 09:35Z"))

    events = runtime.maybe_open_strategy_trade("SOL", *_adverse_long_features(), 10000, True)

    assert events[-1] == "SOL EXSPECIAL slope state; strategy entry blocked"
    assert runtime.exchange.leverage_calls == []
    assert runtime.exchange.entries == []


def test_bandwidth_guard_blocks_high_expanding_setup_and_records_identity(tmp_path):
    exchange = GuardProbeExchange("2030-01-01 09:35Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    one_h, fifteen_m, five_m = _future_long_features(close_5m=105)
    one_h[["lb", "ub", "close"]] = one_h[["lb", "ub", "close"]].astype(float)
    one_h.loc[one_h.index[-2], ["lb", "ub"]] = [110, 130]

    events = runtime.maybe_open_strategy_trade("BTC", one_h, fifteen_m, five_m, 10000, True)

    blocked = next(row for row in runtime.store.events() if row["event_type"] == "bandwidth_entry_blocked")
    assert events[-1] == "BTC BandWidth BW_SHOCK_BLOCK; entry blocked"
    assert runtime.exchange.entries == []
    assert json.loads(blocked["payload_json"])["setup_side"] == "long"
    assert json.loads(blocked["payload_json"])["reason"] == "high_expanding"
    assert json.loads(blocked["payload_json"])["linkage_state"] == "bw_shock_block"
    assert json.loads(blocked["payload_json"])["completed_5m_bucket"] == "2030-01-01T09:30:00+00:00"
    assert json.loads(blocked["payload_json"])["completed_5m_close"] == 105.0
    assert exchange.position_probes == exchange.open_order_probes == exchange.quote_probes == 0
    assert exchange.leverage_calls == exchange.entries == exchange.stop_orders == []


def test_bandwidth_block_is_not_recorded_without_a_completed_5m_trigger(tmp_path):
    exchange = GuardProbeExchange("2030-01-01 09:35Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    one_h, fifteen_m, five_m = _future_long_features(close_5m=99)
    one_h[["lb", "ub", "close"]] = one_h[["lb", "ub", "close"]].astype(float)
    one_h.loc[one_h.index[-2], ["lb", "ub"]] = [110, 130]

    runtime.maybe_open_strategy_trade("BTC", one_h, fifteen_m, five_m, 10000, True)

    assert not any(row["event_type"] == "bandwidth_entry_blocked" for row in runtime.store.events())
    assert exchange.position_probes == exchange.open_order_probes == exchange.quote_probes == 0
    assert exchange.leverage_calls == exchange.entries == exchange.stop_orders == []


def test_bandwidth_blocked_5m_trigger_requires_a_new_trigger_after_guard_recovers(tmp_path):
    exchange = ConfirmingEntryExchange("2030-01-01 09:35Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    one_h, fifteen_m, five_m = _future_long_features(close_5m=105)
    one_h[["lb", "ub", "close"]] = one_h[["lb", "ub", "close"]].astype(float)
    one_h.loc[one_h.index[-2], ["lb", "ub"]] = [110, 130]

    runtime.maybe_open_strategy_trade("BTC", one_h, fifteen_m, five_m, 10000, True)
    one_h.loc[one_h.index[-2], ["lb", "ub"]] = [90, 150]
    repeated = runtime.maybe_open_strategy_trade("BTC", one_h, fifteen_m, five_m, 10000, True)
    exchange._now = pd.Timestamp("2030-01-01 09:40Z")
    fresh = _frame(["2030-01-01 09:35"], [{"open": 106, "high": 108, "low": 105, "close": 107, "mb": 100, "rsi14": 50}])
    opened = runtime.maybe_open_strategy_trade("BTC", one_h, fifteen_m, pd.concat([five_m, fresh]), 10000, True)

    assert repeated[-1] == "BTC completed 5m trigger was previously blocked by BandWidth; waiting for next 5m trigger"
    assert exchange.entries == [("BTC", "long", round(runtime.entry_notional(10000) / 107, 8))]
    assert any("entry opened" in event for event in opened)


@pytest.mark.parametrize("guard", ["position", "open_order"])
def test_exchange_entry_guards_run_after_allowed_5m_trigger(tmp_path, guard):
    exchange = GuardProbeExchange("2030-01-01 09:35Z")
    if guard == "position":
        exchange.positions = [ExchangePosition("BTC", "long", 1, 100, 100)]
    else:
        exchange.open_orders = [{"id": "manual-order"}]
    runtime = _runtime_with_exchange(tmp_path, exchange)

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, True)

    assert events[-1] == ("BTC exchange position exists; waiting" if guard == "position" else "[CRITICAL] BTC strategy entry blocked: account-wide open-order truth invalid")
    assert exchange.position_probes == 1
    assert exchange.open_order_probes == (0 if guard == "position" else 1)
    assert exchange.quote_probes == 0
    assert exchange.leverage_calls == exchange.entries == exchange.stop_orders == []


def test_low_percentile_bandwidth_shock_blocks_before_leverage_or_order(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ConfirmingEntryExchange("2030-01-01 09:35Z"))
    one_h, fifteen_m, five_m = _future_long_features(close_5m=105)
    one_h[["lb", "ub", "close"]] = one_h[["lb", "ub", "close"]].astype(float)
    one_h.loc[one_h.index[:-2], ["lb", "ub"]] = [90, 150]
    one_h.loc[one_h.index[-2], ["lb", "ub"]] = [114, 126]
    one_h.loc[one_h.index[-1], ["lb", "ub", "close"]] = [112.8, 127.2, 95]

    events = runtime.maybe_open_strategy_trade("BTC", one_h, fifteen_m, five_m, 10000, True)

    assert events[-1] == "BTC BandWidth BW_SHOCK_BLOCK; entry blocked"
    assert runtime.exchange.leverage_calls == []
    assert runtime.exchange.entries == []


def test_existing_setup_rechecks_continuation_rsi_threshold_before_order(tmp_path):
    setup = Setup("short", pd.Series({"rsi14": 65}), pd.Timestamp("2030-01-01 08:00Z"), pd.Timestamp("2030-01-01 09:00Z"))

    assert _setup_rsi_passes_risk(setup, {"rsi_threshold": 68}) is False


def test_bandwidth_observation_uses_completed_1h_is_symbol_local_and_deduplicated(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:35Z"))
    btc, _, _ = _future_long_features()
    eth, _, _ = _future_long_features()
    eth.loc[eth.index[-2], ["lb", "ub"]] = [110, 130]
    btc.loc[pd.Timestamp("2030-01-01 09:00Z")] = {"lb": 110, "mb": 120, "ub": 130, "close": 95, "rsi14": 20}

    btc_line = runtime.observe_bandwidth_state("BTC", btc)
    eth_line = runtime.observe_bandwidth_state("ETH", eth)

    assert "HIGH_STABLE ALLOW" in btc_line
    assert "HIGH_EXPANDING BLOCK" in eth_line
    assert runtime.observe_bandwidth_state("BTC", btc) is None
    observed = [row for row in runtime.store.events() if row["event_type"] == "bandwidth_state_observed"]
    assert len(observed) == 2
    assert json.loads(observed[0]["payload_json"])["bucket_start"] == "2030-01-01T08:00:00+00:00"


@pytest.mark.parametrize(("age", "now"), [(1, "2026-01-01 07:05Z"), (2, "2026-01-01 08:05Z")])
def test_bandwidth_observation_reports_h1_h2_side_specific_entry_risks(tmp_path, age, now):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange(now))
    runtime.strategy_config.bandwidth_entry_guard.percentile_lookback = 6
    features = _continuation_1h_features("2026-01-01", age)

    line = runtime.observe_bandwidth_state("BTC", features)
    payload = json.loads(runtime.store.events()[-1]["payload_json"])

    assert "short=linkage:BW_CONTINUATION_SPECIAL" in line
    assert payload["entry_risks"]["short"] == {
        "allow": True,
        "effective_state": "special",
        "leverage": 2,
        "linkage_state": "bw_continuation_special",
        "reason": None,
        "rsi_threshold": 68,
        "shock_age": age,
        "shock_direction": "up",
        "slow_slope_state": "normal",
        "source_shock_bucket": "2026-01-01T05:00:00+00:00",
    }
    assert payload["entry_risks"]["long"]["effective_state"] == "normal"
    assert payload["entry_risks"]["long"]["leverage"] == 3
    assert runtime.observe_bandwidth_state("BTC", features) is None


def test_invalid_bandwidth_history_blocks_new_strategy_entry(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ConfirmingEntryExchange("2030-01-01 09:35Z"))
    one_h, fifteen_m, five_m = _future_long_features(close_5m=105)

    events = runtime.maybe_open_strategy_trade("BTC", one_h.iloc[-119:], fifteen_m, five_m, 10000, True)

    assert events[-1] == "BTC BandWidth UNAVAILABLE; entry blocked"
    assert runtime.exchange.entries == []


def test_shadow_triggers_do_not_place_orders_or_mutate_live_trade_state(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ConfirmingEntryExchange("2030-01-01 09:35Z"))
    one_h, fifteen_m, five_m = _future_long_features(close_5m=105)
    one_h[["lb", "ub", "close"]] = one_h[["lb", "ub", "close"]].astype(float)
    one_h.loc[one_h.index[-2], ["lb", "ub"]] = [110, 130]
    five_m.loc[five_m.index[-2], "high"] = 110

    runtime.maybe_open_strategy_trade("BTC", one_h, fifteen_m, five_m, 10000, True)

    trigger = next(row for row in runtime.store.events() if row["event_type"] == "shadow_entry_triggered")
    assert runtime.exchange.entries == []
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert json.loads(trigger["payload_json"])["trigger_type"] == "middle_band"
    assert not any(row["event_type"] == "bandwidth_entry_blocked" for row in runtime.store.events())


def test_invalid_slope_uses_two_x_and_persists_special_entry_marker(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ConfirmingEntryExchange("2030-01-01 09:35Z"))
    runtime.strategy_config.adverse_slope_take_profit.slope_n = 120

    runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, True)

    trade = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    assert runtime.exchange.leverage_calls == [("BTC", 2, "cross")]
    assert trade.entry_slope_state == "special"


def test_shadow_outcome_updates_after_restart(tmp_path):
    config = _config(tmp_path)
    store = LiveStateStore(config.storage.sqlite_path)
    store.record_shadow_trigger(
        LiveShadowTrigger(
            "shadow-1",
            "BTC",
            "long",
            "middle_band",
            pd.Timestamp("2030-01-01 09:25Z"),
            pd.Timestamp("2030-01-01 09:35Z"),
            pd.Timestamp("2030-01-01 09:00Z"),
            100,
            95,
            110,
        )
    )
    runtime = LiveRuntime(config, ClockedExchange("2030-01-01 09:35Z"), LiveStateStore(config.storage.sqlite_path))
    five_m = _frame(["2030-01-01 09:30"], [{"open": 100, "high": 108, "low": 96, "close": 105, "mb": 100, "rsi14": 50}])

    runtime.update_shadow_outcomes("BTC", five_m)

    row = runtime.store.connection.execute("SELECT mfe, mae, status FROM live_shadow_triggers WHERE trigger_id = 'shadow-1'").fetchone()
    outcome = next(event for event in runtime.store.events() if event["event_type"] == "shadow_entry_outcome")
    assert dict(row) == {"mfe": 8.0, "mae": -4.0, "status": "closed"}
    assert json.loads(outcome["payload_json"])["trigger_id"] == "shadow-1"


def test_strategy_entry_blocks_when_global_notional_cap_exceeded(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ConfirmingEntryExchange("2030-01-01 09:35Z"))
    positions = [ExchangePosition("ETH", "long", 13, 500, 600)]

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, True, exchange_positions=positions)

    assert events[-1] == "BTC risk cap exceeded; waiting"
    assert runtime.exchange.leverage_calls == []
    assert runtime.exchange.entries == []
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert "BTC" in runtime.setups
    assert runtime.store.events()[0]["event_type"] == "setup_created"


def test_strategy_entry_allows_notional_equal_to_global_cap(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ConfirmingEntryExchange("2030-01-01 09:35Z"))
    positions = [ExchangePosition("ETH", "long", 10, 550, 550)]

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, True, exchange_positions=positions)

    assert runtime.exchange.leverage_calls == [("BTC", 3, "cross")]
    assert any("entry opened" in event for event in events)


def test_strategy_entry_blocks_when_equity_invalid(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ConfirmingEntryExchange("2030-01-01 09:35Z"))

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), LiveBalance(0, 1000), True)

    assert events[-1] == "BTC account equity invalid; waiting"
    assert runtime.exchange.leverage_calls == []
    assert runtime.exchange.entries == []
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert "BTC" in runtime.setups
    assert runtime.store.events()[0]["event_type"] == "setup_created"


def test_strategy_entry_blocks_when_available_margin_insufficient(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ConfirmingEntryExchange("2030-01-01 09:35Z"))

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), LiveBalance(10000, 1000), True)

    assert events[-1] == "BTC available margin insufficient; waiting"
    assert runtime.exchange.leverage_calls == []
    assert runtime.exchange.entries == []
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert "BTC" in runtime.setups
    assert runtime.store.events()[0]["event_type"] == "setup_created"


def test_strategy_entry_allows_when_available_margin_is_sufficient(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ConfirmingEntryExchange("2030-01-01 09:35Z"))

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), LiveBalance(10000, 1500), True)

    assert runtime.exchange.leverage_calls == [("BTC", 3, "cross")]
    assert any("entry opened" in event for event in events)


def test_strategy_entry_blocks_when_market_quote_missing(tmp_path):
    exchange = ConfirmingEntryExchange("2030-01-01 09:35Z")
    exchange.market_quote = MarketQuote(None, 105.1, 105)
    runtime = _runtime_with_exchange(tmp_path, exchange)

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), LiveBalance(10000, 1500), True)

    assert events[-1] == "BTC market quote unavailable; waiting"
    assert exchange.leverage_calls == []
    assert exchange.entries == []
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert "BTC" in runtime.setups
    assert runtime.store.events()[0]["event_type"] == "setup_created"


def test_strategy_entry_blocks_when_market_spread_too_wide(tmp_path):
    exchange = ConfirmingEntryExchange("2030-01-01 09:35Z")
    exchange.market_quote = MarketQuote(100, 102, 101)
    runtime = _runtime_with_exchange(tmp_path, exchange)

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), LiveBalance(10000, 1500), True)

    assert "market spread too wide" in events[-1]
    assert exchange.leverage_calls == []
    assert exchange.entries == []
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert "BTC" in runtime.setups
    assert runtime.store.events()[0]["event_type"] == "setup_created"


def test_strategy_entry_uses_top_book_mid_for_market_spread(tmp_path):
    exchange = GuardProbeExchange("2030-01-01 09:35Z")
    exchange.market_quote = MarketQuote(100, 100.057, 2.3)
    runtime = _runtime_with_exchange(tmp_path, exchange)

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), LiveBalance(10000, 1500), True)

    assert not any("market spread too wide" in event for event in events)
    assert exchange.leverage_calls == [("BTC", 3, "cross")]
    assert any("entry opened" in event for event in events)
    assert exchange.quote_probes == 1
    assert exchange.entry_quotes == [exchange.market_quote]


def test_ioc_entry_without_confirmed_position_does_not_retry_or_create_open_trade(tmp_path):
    exchange = ClockedExchange("2030-01-01 09:35Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), LiveBalance(10000, 1500), True)

    assert exchange.entries and len(exchange.entries) == 1
    assert exchange.leverage_calls == [("BTC", 3, "cross")]
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert events[-1] == "BTC MR entry submitted; awaiting fill reconciliation"
    assert runtime.store.events()[-1]["event_type"] == "mr_entry_submitted"


def test_mr_entry_response_loss_reconciles_once_across_restart_then_recovers_actual_fill(tmp_path, monkeypatch):
    path = tmp_path / "live.sqlite3"
    exchange = LostEntryResponseExchange("2030-01-01 09:35Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    features = _future_long_features(close_5m=105)

    first = runtime.maybe_open_strategy_trade("BTC", *features, LiveBalance(10000, 1500), True)
    intent = runtime.store.active_mr_entry_intent("BTC")
    assert "entry result ambiguous" in first[-1]
    assert intent is not None and intent.submit_attempted and intent.status == "ambiguous"
    assert len(exchange.entries) == 1
    client_order_id = intent.client_order_id

    monkeypatch.setattr("bbmr.live.trailing_runtime.latest_completed_features", lambda *args: features)
    restarted = LiveRuntime(runtime.live_config, exchange, LiveStateStore(str(path)))
    exchange.lookup_missing = True
    second = restarted.maybe_open_strategy_trade("BTC", *features, LiveBalance(10000, 1500), True)
    restored = restarted.store.active_mr_entry_intent("BTC")
    assert "missing from lookup" in second[-1]
    assert len(exchange.entries) == 1
    assert restored is not None and restored.client_order_id == client_order_id and restored.submit_attempted

    exchange.positions = [ExchangePosition("BTC", "long", 1.25, 104.5, 104.5)]
    recovered = restarted.maybe_open_strategy_trade("BTC", *features, LiveBalance(10000, 1500), True)
    trade = restarted.store.open_trade(restarted.position_key("BTC", "long"))
    assert len(exchange.entries) == 1
    assert restarted.store.active_mr_entry_intent("BTC") is None
    assert trade is not None and trade.status == "open" and trade.qty == pytest.approx(1.25) and trade.entry_price == pytest.approx(104.5)
    assert any("recovered MR entry fill" in event for event in recovered)


def test_mr_entry_client_order_id_is_deterministic_and_trigger_scoped():
    setup = pd.Timestamp("2030-01-01 09:00Z")
    trigger = pd.Timestamp("2030-01-01 09:30Z")
    first = _mr_entry_client_order_id("account", "BTC/USDC:USDC", "long", setup, trigger)
    assert first == _mr_entry_client_order_id("account", "BTC", "long", setup, trigger)
    assert first.startswith("0x") and len(first) == 34
    assert first != _mr_entry_client_order_id("account", "BTC", "long", setup, pd.Timestamp("2030-01-01 09:35Z"))
    assert first != _mr_entry_client_order_id("other-account", "BTC", "long", setup, trigger)


def test_mr_entry_persistence_failure_prevents_leverage_and_order_calls(tmp_path, monkeypatch):
    exchange = ConfirmingEntryExchange("2030-01-01 09:35Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    monkeypatch.setattr(runtime.store, "create_mr_entry_intent_with_event", lambda intent: (_ for _ in ()).throw(RuntimeError("intent persistence failed")))

    with pytest.raises(RuntimeError, match="intent persistence failed"):
        runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), LiveBalance(10000, 1500), True)

    assert exchange.leverage_calls == []
    assert exchange.entries == []


def test_mr_entry_terminal_no_fill_consumes_trigger_but_allows_new_5m_trigger(tmp_path):
    exchange = TerminalNoFillExchange("2030-01-01 09:35Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    one_h, fifteen_m, five_m = _future_long_features(close_5m=105)

    runtime.maybe_open_strategy_trade("BTC", one_h, fifteen_m, five_m, LiveBalance(10000, 1500), True)
    terminal = runtime.maybe_open_strategy_trade("BTC", one_h, fifteen_m, five_m, LiveBalance(10000, 1500), True)
    consumed = runtime.maybe_open_strategy_trade("BTC", one_h, fifteen_m, five_m, LiveBalance(10000, 1500), True)
    assert "no-fill confirmed" in terminal[-1]
    assert "trigger already consumed" in consumed[-1]
    assert len(exchange.entries) == 1

    exchange._now = pd.Timestamp("2030-01-01 09:40Z")
    fresh = _frame(["2030-01-01 09:35"], [{"open": 106, "high": 108, "low": 105, "close": 107, "mb": 100, "rsi14": 50}])
    runtime.maybe_open_strategy_trade("BTC", one_h, fifteen_m, pd.concat([five_m, fresh]), LiveBalance(10000, 1500), True)
    assert len(exchange.entries) == 2


def test_account_reservations_include_real_orders_and_block_invalid_manual_truth(tmp_path):
    runtime, _exchange = _runtime(tmp_path)
    intent = MREntryIntent(
        "intent-1", runtime.account, "BTC", "long", pd.Timestamp("2030-01-01 09:00Z"),
        pd.Timestamp("2030-01-01 09:30Z"), 1, 300, 3, 100, 100, 101, "0x" + "1" * 32,
    )
    runtime.store.create_mr_entry_intent_with_event(intent)
    protected = runtime.store.create_trade(runtime.position_key("ETH", "long"), "ETH", "long", 1, 100, "strategy", 95)
    protected.system_stop_order_id = "system-stop"
    runtime.store.update_trade(protected)
    pending = TrendPendingOrder(
        "trend-1", "ETH", "long", "live", "intent", pd.Timestamp("2030-01-01 09:00Z"),
        100, 100, 2, 200, .05,
    )
    runtime.store.create_trend_pending(pending)
    reservations = runtime.account_reservations([
        {"id": "manual-entry", "symbol": "SOL", "side": "buy", "reduceOnly": False, "remaining": 2, "price": 50},
        {"id": "manual-stop", "symbol": "SOL", "side": "sell", "reduceOnly": True, "remaining": 2, "price": 45},
        {"id": "system-stop"},
    ])
    assert reservations["block_reason"] is None
    assert reservations["notional"] == pytest.approx(600)
    assert reservations["margin"] == pytest.approx(100 + 200 / runtime.live_config.execution.trend_riding_leverage)
    assert {entry["source"] for entry in reservations["entries"]} == {"mr_intent", "trend_pending", "manual_order"}
    assert runtime.account_reservations([{"id": "manual-unknown"}])["block_reason"] == "account-wide open-order truth invalid"


def test_entry_fill_slippage_is_recorded_without_leaving_position_unprotected(tmp_path):
    exchange = AverageFillExchange("2030-01-01 09:35Z")
    exchange.market_quote = MarketQuote(104.9, 105.1, 2.3)
    runtime = _runtime_with_exchange(tmp_path, exchange)

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), LiveBalance(10000, 1500), True)

    trade = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    event_types = [row["event_type"] for row in runtime.store.events()]
    slippage_event = next(row for row in runtime.store.events() if row["event_type"] == "entry_slippage_exceeded")
    assert any("entry fill slippage exceeded" in event for event in events)
    assert trade.status == "open"
    assert trade.system_stop_order_id == "stop-1"
    assert event_types[-2] == "entry_opened"
    assert "entry_slippage_exceeded" in event_types
    assert json.loads(slippage_event["payload_json"]) == {
        "fill_price": 110.0,
        "max_entry_slippage_bps": 100.0,
        "reference_price": 105.0,
        "severity": "WARN",
        "slippage_bps": pytest.approx(476.19047619047615),
    }


def test_entry_leverage_uses_setup_side_slope_tier(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 12:05Z"))

    assert runtime.entry_leverage("long", _slope_features([100, 100, 100, 100], side="long")) == 3
    assert runtime.entry_leverage("short", _slope_features([100, 100, 100, 100], side="short")) == 3
    assert runtime.entry_leverage("long", _slope_features([100, 100, 100, 99.9], side="long")) == 2
    assert runtime.entry_leverage("short", _slope_features([100, 100, 100, 100.1], side="short")) == 2
    assert runtime.entry_leverage("long", _slope_features([121, 120, 119, 118], side="long")) == 2
    assert runtime.entry_leverage("short", _slope_features([118, 119, 120, 121], side="short")) == 2


def test_requires_15m_reversal_when_enabled(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:05Z"))
    runtime.strategy_config.entry_confirmation.require_15m_rsi_reversal = True

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105, close_time="2030-01-01 09:05"), 10000, False)

    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert events == ["BTC 1h setup met; waiting for first 15m RSI baseline"]


def test_skips_15m_reversal_when_disabled(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:05Z"))

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105, close_time="2030-01-01 09:05"), 10000, False)

    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert events[0] == "BTC 15m RSI reversal disabled; waiting for 5m entry"
    assert "BTC 15m RSI reversal disabled; waiting for 5m entry" in events
    assert events[-1] == "BTC entry conditions passed; order permission unavailable"


def test_pending_setup_recovers_after_restart(tmp_path, monkeypatch):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:05Z"))
    runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=99, close_time="2030-01-01 09:05"), 10000, False)
    monkeypatch.setattr("bbmr.live.trailing_runtime.latest_completed_features", lambda exchange, symbol, config: _future_long_features(close_5m=99, close_time="2030-01-01 09:05"))

    restarted = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:06Z"))

    assert "BTC" in restarted.setups
    assert restarted.setups["BTC"].confirmed_15m is False
    assert restarted.setups["BTC"].rsi_15m is None


def test_pending_setup_transport_failure_is_retained_and_warned_once(tmp_path, monkeypatch):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:05Z"))
    runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=99, close_time="2030-01-01 09:05"), 10000, False)
    monkeypatch.setattr(
        "bbmr.live.trailing_runtime.latest_completed_features",
        lambda *args: (_ for _ in ()).throw(TimeoutError("candle read timed out")),
    )

    restarted = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:06Z"))
    restarted_again = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:07Z"))

    assert restarted.setups == {}
    assert restarted_again.setups == {}
    row = restarted.store.connection.execute("SELECT status FROM live_pending_setups WHERE symbol = 'BTC'").fetchone()
    assert row["status"] == "pending"
    events = [event for event in restarted.store.events() if event["event_type"] == "pending_setup_validation_deferred"]
    assert len(events) == 1
    assert json.loads(events[0]["payload_json"])["severity"] == "WARN"


def test_pending_setup_unexpected_validation_failure_propagates_without_discard(tmp_path, monkeypatch):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:05Z"))
    runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=99, close_time="2030-01-01 09:05"), 10000, False)
    monkeypatch.setattr(
        "bbmr.live.trailing_runtime.latest_completed_features",
        lambda *args: (_ for _ in ()).throw(AttributeError("adapter contract broken")),
    )

    with pytest.raises(AttributeError, match="adapter contract broken"):
        _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:06Z"))

    row = runtime.store.connection.execute("SELECT status FROM live_pending_setups WHERE symbol = 'BTC'").fetchone()
    assert row["status"] == "pending"


def test_confirmed_setup_state_recovers_after_restart(tmp_path, monkeypatch):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:35Z"))
    runtime.strategy_config.entry_confirmation.require_15m_rsi_reversal = True
    runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=99), 10000, False)
    monkeypatch.setattr("bbmr.live.trailing_runtime.latest_completed_features", lambda exchange, symbol, config: _future_long_features(close_5m=99))

    restarted = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:36Z"))

    assert restarted.setups["BTC"].confirmed_15m is True
    assert restarted.setups["BTC"].rsi_15m == 25
    assert restarted.setups["BTC"].confirm_15m_time == pd.Timestamp("2030-01-01 09:30Z")


def test_mismatched_pending_setup_is_discarded_after_restart(tmp_path, monkeypatch):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:05Z"))
    runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=99, close_time="2030-01-01 09:05"), 10000, False)
    one_h, fifteen_m, five_m = _future_long_features(close_5m=99, close_time="2030-01-01 09:05")
    one_h.loc[pd.Timestamp("2030-01-01 08:00Z"), "close"] = 96
    monkeypatch.setattr("bbmr.live.trailing_runtime.latest_completed_features", lambda exchange, symbol, config: (one_h, fifteen_m, five_m))

    restarted = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:06Z"))

    assert restarted.setups == {}
    assert restarted.store.connection.execute("SELECT COUNT(*) AS count FROM live_pending_setups").fetchone()["count"] == 0
    assert restarted.store.events()[-1]["event_type"] == "setup_discarded"


def test_expired_setup_is_not_recovered_and_is_marked_expired(tmp_path, monkeypatch):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:35Z"))
    runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=99), 10000, False)
    monkeypatch.setattr("bbmr.live.trailing_runtime.latest_completed_features", lambda exchange, symbol, config: _future_long_features(close_5m=99))

    restarted = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 10:00Z"))

    assert restarted.setups == {}
    row = restarted.store.connection.execute("SELECT status FROM live_pending_setups WHERE symbol = 'BTC'").fetchone()
    assert row["status"] == "expired"


def test_entry_opened_clears_pending_setup(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:35Z"))
    runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, False)

    assert "BTC" in runtime.setups
    assert runtime.store.connection.execute("SELECT COUNT(*) AS count FROM live_pending_setups").fetchone()["count"] == 1


def test_forming_5m_does_not_trigger_entry(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:32Z"))
    runtime.strategy_config.entry_confirmation.require_15m_rsi_reversal = True
    runtime.setups["BTC"] = _confirmed_setup()
    one_h, fifteen_m, _ = _future_long_features()
    five_m = _frame(
        ["2030-01-01 09:25", "2030-01-01 09:30"],
        [
            {"open": 99, "high": 100, "low": 98, "close": 99, "mb": 100},
            {"open": 104, "high": 106, "low": 103, "close": 105, "mb": 100},
        ],
    )

    events = runtime.maybe_open_strategy_trade("BTC", one_h, fifteen_m, five_m, 10000, True)

    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert events == ["BTC 15m confirmed; waiting for 5m entry"]


def test_market_entry_average_updates_entry_and_stop(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, AverageFillExchange("2030-01-01 09:35Z"))

    runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, True)

    trade = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    assert trade.entry_price == 110
    assert trade.initial_stop_loss == pytest.approx(104.5)
    assert trade.current_stop_loss == pytest.approx(104.5)
    assert runtime.exchange.stop_orders[-1]["stop"] == pytest.approx(104.5)


def test_set_leverage_failure_does_not_create_open_trade_or_clear_setup(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, FailingLeverageExchange("2030-01-01 09:35Z"))

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, True)

    assert "entry intent retained" in events[-1]
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert "BTC" in runtime.setups
    assert runtime.store.connection.execute("SELECT COUNT(*) AS count FROM live_pending_setups").fetchone()["count"] == 1
    assert [row["event_type"] for row in runtime.store.events()] == ["setup_created", "shadow_entry_triggered", "mr_entry_intent_prepared", "mr_entry_intent_ambiguous"]
    assert json.loads(runtime.store.events()[-1]["payload_json"])["severity"] == "ERROR"


def test_market_entry_failure_without_position_does_not_create_open_trade(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, FailingEntryExchange("2030-01-01 09:35Z"))

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, True)

    assert "entry result ambiguous" in events[-1]
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert "BTC" in runtime.setups
    assert runtime.store.events()[-1]["event_type"] == "mr_entry_intent_ambiguous"
    assert json.loads(runtime.store.events()[-1]["payload_json"])["severity"] == "ERROR"


def test_market_entry_without_confirmed_position_does_not_create_open_trade(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:35Z"))

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, True)

    assert "awaiting fill reconciliation" in events[-1]
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert "BTC" in runtime.setups
    assert runtime.store.events()[-1]["event_type"] == "mr_entry_submitted"
    assert json.loads(runtime.store.events()[-1]["payload_json"])["severity"] == "ERROR"


def test_market_entry_filled_but_stop_failure_keeps_unprotected_record(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, EntryStopFailExchange("2030-01-01 09:35Z"))

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, True)

    trade = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    assert "recovered MR fill awaiting protective stop" in events[-1]
    assert trade.status == "entry_unprotected"
    assert trade.system_stop_order_id is None
    assert "BTC" in runtime.setups
    assert "entry_unprotected" in [row["event_type"] for row in runtime.store.events()]
    assert "protective_stop_replacement_started" in [row["event_type"] for row in runtime.store.events()]


def test_reconcile_protects_unprotected_entry_before_open_management(tmp_path):
    runtime, exchange = _runtime(tmp_path)
    trade = runtime.store.create_trade(
        runtime.position_key("BTC", "long"),
        "BTC",
        "long",
        1,
        105,
        "strategy",
        99.75,
        setup_trigger_time=pd.Timestamp("2030-01-01 08:00Z"),
        status="entry_unprotected",
    )

    events = runtime.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 1, 105, 105)], True)

    loaded = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    assert loaded.internal_trade_id == trade.internal_trade_id
    assert loaded.status == "open"
    assert loaded.system_stop_order_id == "stop-1"
    assert exchange.stop_orders[-1]["qty"] == 1
    assert events == []
    assert runtime.store.events()[-1]["event_type"] == "protective_stop_replacement_promoted"


@pytest.mark.parametrize(
    "field,value",
    [
        ("symbol", "ETH"),
        ("side", "buy"),
        ("reduceOnly", False),
        ("amount", 2),
        ("triggerPrice", 94),
        ("status", "rejected"),
    ],
)
def test_invalid_persisted_stop_never_remains_protected(tmp_path, field, value):
    runtime, exchange = _runtime(tmp_path)
    trade = _seed_verified_stop(runtime, exchange)
    exchange.orders["old-stop"][field] = value

    runtime.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 1, 100, 101)], True)

    loaded = runtime.store.open_trade(trade.exchange_position_key)
    assert loaded.status == "open"
    assert loaded.protection_status == "protected"
    assert loaded.system_stop_order_id == "stop-1"
    assert "protective_stop_replacement_started" in [row["event_type"] for row in runtime.store.events()]


def test_stop_read_timeout_preserves_id_and_blocks_all_strategy_entries(tmp_path):
    exchange = StopReadTimeoutExchange()
    runtime = _runtime_with_exchange(tmp_path, exchange)
    trade = _seed_verified_stop(runtime, exchange)

    events = runtime.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 1, 100, 101)], True)
    loaded = runtime.store.open_trade(trade.exchange_position_key)
    blocked = runtime.maybe_open_strategy_trade("SOL", *_future_long_features(close_5m=105), 10000, True)

    assert events == ["[CRITICAL] BTC protective stop truth unknown; new strategy entries blocked"]
    assert loaded.system_stop_order_id == "old-stop"
    assert loaded.status == "entry_unprotected"
    assert loaded.protection_status == "unknown"
    assert exchange.stop_orders == []
    assert blocked == ["[CRITICAL] SOL strategy entry blocked: protective-stop recovery active"]


def test_closed_unknown_history_reaches_next_entry_guard(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ExistingPositionExchange("2030-01-01 09:35Z"))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.protection_status = "unknown"
    runtime.store.update_trade(trade)
    runtime.store.archive_trade(trade, "closed")

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, True)

    assert events[-1] == "BTC exchange position exists; waiting"
    assert all("protective-stop recovery active" not in event for event in events)


def test_lost_stop_create_response_recovers_by_persisted_client_id_after_restart(tmp_path):
    exchange = LostStopCreateResponseExchange()
    runtime = _runtime_with_exchange(tmp_path, exchange)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95, status="entry_unprotected")

    runtime.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 1, 100, 101)], True)
    intent = runtime.store.stop_replacement(trade.internal_trade_id)
    restarted = _runtime_with_exchange(tmp_path, exchange)
    events = restarted.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 1, 100, 101)], True)
    loaded = restarted.store.open_trade(trade.exchange_position_key)

    assert intent is not None and intent.new_stop_order_id is None
    assert len(exchange.stop_orders) == 1
    assert loaded.status == "open" and loaded.protection_status == "protected"
    assert restarted.store.stop_replacement(trade.internal_trade_id) is None
    assert events == []


@pytest.mark.parametrize("lookup_unknown", [False, True])
def test_ambiguous_stop_create_is_never_resubmitted_when_client_id_is_unconfirmed(tmp_path, lookup_unknown):
    exchange = MissingCreateOutcomeExchange(lookup_unknown)
    runtime = _runtime_with_exchange(tmp_path, exchange)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95, status="entry_unprotected")

    runtime.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 1, 100, 101)], True)
    first = runtime.store.stop_replacement(trade.internal_trade_id)
    restarted = _runtime_with_exchange(tmp_path, exchange)
    events = restarted.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 1, 100, 101)], True)
    second = restarted.store.stop_replacement(trade.internal_trade_id)
    blocked = restarted.maybe_open_strategy_trade("SOL", *_future_long_features(close_5m=105), 10000, True)

    assert first is not None and first.create_attempted is True and first.new_stop_order_id is None
    assert second is not None and second.replacement_client_id == first.replacement_client_id
    assert exchange.create_calls == 1
    assert events == ["[CRITICAL] BTC replacement create outcome unknown; retrying only by persisted client id"]
    assert blocked == ["[CRITICAL] SOL strategy entry blocked: protective-stop recovery active"]


def test_cancel_timeout_persists_replacement_and_restart_converges_without_new_stop(tmp_path):
    exchange = CancelStopTimeoutExchange()
    runtime = _runtime_with_exchange(tmp_path, exchange)
    trade = _seed_verified_stop(runtime, exchange)
    trade.current_stop_loss = 96

    with pytest.raises(Exception):
        runtime._replace_stop(trade, True, False)
    intent = runtime.store.stop_replacement(trade.internal_trade_id)
    restarted = _runtime_with_exchange(tmp_path, exchange)
    restarted.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 1, 100, 101)], True)
    loaded = restarted.store.open_trade(trade.exchange_position_key)

    assert intent is not None and intent.phase == "cancel_pending"
    assert len(exchange.stop_orders) == 1
    assert loaded.system_stop_order_id == "stop-1"
    assert loaded.status == "open" and loaded.protection_status == "protected"
    assert restarted.store.stop_replacement(trade.internal_trade_id) is None
    assert exchange.cancelled == [("BTC", "old-stop")]


def test_cancel_response_loss_after_server_applies_cancel_promotes_without_third_stop(tmp_path):
    exchange = CancelAppliedResponseLostExchange()
    runtime = _runtime_with_exchange(tmp_path, exchange)
    trade = _seed_verified_stop(runtime, exchange)
    trade.current_stop_loss = 96

    with pytest.raises(Exception):
        runtime._replace_stop(trade, True, False)
    pending = runtime.store.stop_replacement(trade.internal_trade_id)
    restarted = _runtime_with_exchange(tmp_path, exchange)
    restarted.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 1, 100, 101)], True)
    loaded = restarted.store.open_trade(trade.exchange_position_key)

    assert pending is not None and pending.phase == "cancel_pending" and pending.new_stop_order_id == "stop-1"
    assert exchange.orders["old-stop"]["status"] == "canceled"
    assert len(exchange.stop_orders) == 1
    assert loaded.system_stop_order_id == "stop-1"
    assert loaded.status == "open" and loaded.protection_status == "protected"
    assert restarted.store.stop_replacement(trade.internal_trade_id) is None


def test_strategy_entry_skips_when_exchange_position_exists(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ExistingPositionExchange("2030-01-01 09:35Z"))

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, True)

    assert events[-1] == "BTC exchange position exists; waiting"
    assert runtime.exchange.entries == []
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None


def test_strategy_entry_skips_when_exchange_open_order_exists(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, OpenOrderExchange("2030-01-01 09:35Z"))

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, True)

    assert events[-1] == "[CRITICAL] BTC strategy entry blocked: account-wide open-order truth invalid"
    assert runtime.exchange.entries == []
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None


def test_manual_position_is_adopted_and_stop_is_created(tmp_path):
    runtime, exchange = _runtime(tmp_path)
    events = runtime.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 1, 100, 101)], True)
    trade = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    assert trade.source == "manual_adopted"
    assert trade.qty == 1
    assert exchange.stop_orders[-1]["qty"] == 1
    assert "manual position detected" in events[0]


def test_manual_position_adoption_can_be_disabled(tmp_path):
    runtime, exchange = _runtime(tmp_path)
    runtime.live_config.execution.adopt_manual_positions = False

    events = runtime.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 1, 100, 101)], True)

    assert events == ["BTC manual position detected; adoption disabled"]
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert exchange.stop_orders == []
    assert runtime.store.events() == []


def test_trade_journal_records_state_changes_and_appends(tmp_path):
    runtime, exchange = _runtime(tmp_path)

    runtime.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 1, 100, 101)], True)
    runtime.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 2, 98, 101)], True)
    trade = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    runtime.update_stop(trade, pd.Series({"lb": 80, "mb": 120, "ub": 160}), pd.Series({"close": 130, "high": 140, "low": 125}), True)
    runtime.reconcile_symbol("BTC", [], True)

    event_types = [row["event_type"] for row in runtime.store.events()]
    assert event_types[0] == "manual_adopted"
    assert "manual_size_changed" in event_types
    assert "stop_updated" in event_types
    assert event_types[-1] == "exit_archived"


def test_manual_close_archives_and_cancels_only_system_stop(tmp_path):
    runtime, exchange = _runtime(tmp_path)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.system_stop_order_id = "system-stop"
    exchange.orders["system-stop"] = {"id": "system-stop", "symbol": "BTC", "side": "sell", "amount": 1, "triggerPrice": 95, "reduceOnly": True, "status": "open"}
    runtime.store.update_trade(trade)

    runtime.reconcile_symbol("BTC", [], True)

    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert exchange.cancelled == [("BTC", "system-stop")]


def test_manual_close_archives_unknown_pnl_without_exact_owned_close_identity(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, PnlExchange())
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)

    runtime.reconcile_symbol("BTC", [], True)

    row = runtime.store.connection.execute("SELECT exit_price, realized_pnl, fees, pnl_source FROM live_trades WHERE internal_trade_id = ?", (trade.internal_trade_id,)).fetchone()
    event = runtime.store.events()[-1]
    assert dict(row) == {"exit_price": None, "realized_pnl": None, "fees": None, "pnl_source": "unknown"}
    assert json.loads(event["payload_json"]) == {"pnl_source": "unknown"}


def test_manual_close_archives_with_unknown_pnl_when_lookup_fails(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, FailingPnlExchange())
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)

    runtime.reconcile_symbol("BTC", [], True)

    row = runtime.store.connection.execute("SELECT status, realized_pnl, pnl_source FROM live_trades WHERE internal_trade_id = ?", (trade.internal_trade_id,)).fetchone()
    assert row["status"] == "closed"
    assert row["realized_pnl"] is None
    assert row["pnl_source"] == "unknown"
    assert json.loads(runtime.store.events()[-1]["payload_json"]) == {"pnl_source": "unknown"}


def test_manual_close_archives_when_system_stop_is_already_gone(tmp_path):
    config = _config(tmp_path)
    runtime = LiveRuntime(config, MissingStopExchange(), LiveStateStore(config.storage.sqlite_path))
    trade = runtime.store.create_trade(runtime.position_key("SOL", "short"), "SOL", "short", 1, 73.926, "strategy", 73.926)
    trade.system_stop_order_id = "55762129063"
    runtime.store.update_trade(trade)

    events = runtime.reconcile_symbol("SOL", [], True)

    assert runtime.store.open_trade(runtime.position_key("SOL", "short")) is None
    assert "exchange position disappeared" in events[0]


def test_manual_orders_are_not_cancelled_by_default(tmp_path):
    runtime, exchange = _runtime(tmp_path)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.system_stop_order_id = "system-stop"
    exchange.orders["system-stop"] = {"id": "system-stop", "symbol": "BTC", "side": "sell", "amount": 1, "triggerPrice": 95, "reduceOnly": True, "status": "open"}
    runtime.store.update_trade(trade)

    runtime.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 2, 100, 101)], True)

    assert exchange.cancelled == [("BTC", "system-stop")]


def test_manual_addon_updates_merged_quantity(tmp_path):
    runtime, exchange = _runtime(tmp_path)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)

    runtime.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 2, 98, 101)], True)

    trade = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    assert trade.qty == 2
    assert trade.entry_price == 98
    assert exchange.stop_orders[-1]["qty"] == 2


def test_manual_addon_management_can_be_disabled(tmp_path):
    runtime, exchange = _runtime(tmp_path)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.system_stop_order_id = "stop-1"
    exchange.orders["stop-1"] = {"id": "stop-1", "symbol": "BTC", "side": "sell", "amount": 1, "triggerPrice": 95, "reduceOnly": True, "status": "open"}
    runtime.store.update_trade(trade)
    runtime.live_config.execution.manage_full_manual_added_size = False

    events = runtime.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 2, 98, 101)], True)

    loaded = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    assert events == ["[CRITICAL] BTC exchange position differs from managed stop quantity; recovery pending"]
    assert loaded.qty == 1
    assert loaded.entry_price == 100
    assert loaded.internal_trade_id == trade.internal_trade_id
    assert loaded.status == "entry_unprotected"
    assert exchange.stop_orders == []
    assert runtime.store.events()[-1]["event_type"] == "protective_stop_recovery"


def test_unprotected_strategy_entry_recovery_ignores_manual_adoption_setting(tmp_path):
    runtime, exchange = _runtime(tmp_path)
    runtime.live_config.execution.adopt_manual_positions = False
    runtime.store.create_trade(
        runtime.position_key("BTC", "long"),
        "BTC",
        "long",
        1,
        105,
        "strategy",
        99.75,
        setup_trigger_time=pd.Timestamp("2030-01-01 08:00Z"),
        status="entry_unprotected",
    )

    events = runtime.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 1, 105, 105)], True)

    loaded = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    assert events == []
    assert loaded.status == "open"
    assert loaded.system_stop_order_id == "stop-1"
    assert exchange.stop_orders[-1]["qty"] == 1


def test_stop_replacement_failure_keeps_old_stop_and_blocks_new_entries(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, FailingStopExchange())
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.system_stop_order_id = "old-stop"
    runtime.store.update_trade(trade)

    event = runtime.update_stop(trade, pd.Series({"lb": 80, "mb": 120, "ub": 160}), pd.Series({"close": 130, "high": 140, "low": 125}), True)

    loaded = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    assert "protective stop replacement failed" in event
    assert loaded.current_stop_loss == 120
    assert loaded.system_stop_order_id == "old-stop"
    assert runtime.exchange.cancelled == []
    assert runtime.store.stop_replacement(loaded.internal_trade_id) is not None
    assert "protective_stop_replacement_started" in [row["event_type"] for row in runtime.store.events()]

    events = runtime.maybe_open_strategy_trade("SOL", *_future_long_features(close_5m=105), 10000, True)

    assert events == ["[CRITICAL] SOL strategy entry blocked: protective-stop recovery active"]
    assert runtime.exchange.entries == []


def test_stop_replacement_missing_id_does_not_write_string_none(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, MissingStopIdExchange())
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.system_stop_order_id = "old-stop"
    runtime.store.update_trade(trade)

    event = runtime.update_stop(trade, pd.Series({"lb": 80, "mb": 120, "ub": 160}), pd.Series({"close": 130, "high": 140, "low": 125}), True)

    loaded = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    assert "protective stop replacement failed" in event
    assert loaded.system_stop_order_id == "old-stop"
    assert loaded.system_stop_order_id != "None"
    assert runtime.exchange.cancelled == []


def test_exspecial_activates_half_band_target_and_stays_sticky(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 12:05Z"))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)

    event = runtime.update_adverse_slope_take_profit(trade, _slope_features([121, 120, 119, 118], side="long"))

    assert "EXSPECIAL defensive mode active" in event
    assert trade.adverse_slope_tp_active is True
    assert trade.adverse_slope_tp_price == 108
    assert trade.trailing_frozen is True

    runtime.exchange._now = "2030-01-01 13:05Z"
    event = runtime.update_adverse_slope_take_profit(trade, _slope_features([118, 118, 118, 117.88], side="long", start="2030-01-01 09:00Z"))

    assert "EXSPECIAL defensive target refreshed" in event
    assert trade.adverse_slope_tp_active is True
    assert trade.trailing_frozen is True


def test_exspecial_short_uses_half_band_target(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 12:05Z"))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "short"), "BTC", "short", 1, 100, "strategy", 105)

    event = runtime.update_adverse_slope_take_profit(trade, _slope_features([118, 119, 120, 121], side="short"))

    assert "EXSPECIAL defensive mode active" in event
    assert trade.adverse_slope_tp_active is True
    assert trade.adverse_slope_tp_price == 131


def test_exspecial_applies_to_manual_adopted(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 12:05Z"))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "manual_adopted", 95)

    event = runtime.update_adverse_slope_take_profit(trade, _slope_features([121, 120, 119, 118], side="long"))

    assert "EXSPECIAL defensive mode active" in event
    assert trade.adverse_slope_tp_active is True
    assert trade.adverse_slope_tp_price == 108
    assert trade.trailing_frozen is True


def test_special_uses_entry_floor_and_clears_on_normal(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 12:05Z"))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)

    event = runtime.update_adverse_slope_take_profit(trade, _slope_features([100, 100, 100, 99.9], side="long"))

    assert "SPECIAL rolling 1h middle TP active" in event
    assert trade.special_tp_active is True
    assert trade.special_tp_price == 100
    assert trade.trailing_frozen is False

    runtime.exchange._now = "2030-01-01 13:05Z"
    event = runtime.update_adverse_slope_take_profit(trade, _slope_features([100, 100, 100, 100], side="long", start="2030-01-01 09:00Z"))

    assert "NORMAL trailing resumed" in event
    assert trade.special_tp_active is False
    assert trade.special_tp_price is None


def test_special_short_uses_entry_floor_and_refreshes_once_per_bucket(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 12:05Z"))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "short"), "BTC", "short", 1, 100, "strategy", 105)
    features = _slope_features([100, 100, 100, 100.1], side="short")

    event = runtime.update_adverse_slope_take_profit(trade, features)

    assert "SPECIAL rolling" in event
    assert trade.special_tp_price == 100
    assert runtime.update_adverse_slope_take_profit(trade, features) is None


def test_regime_targets_use_independent_yaml_fractions(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 12:05Z"))
    runtime.strategy_config.adverse_slope_take_profit.special_near_middle_frac = 0.5
    special = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 80, "strategy", 75)

    runtime.update_adverse_slope_take_profit(special, _slope_features([100, 100, 100, 99.9], side="long"))

    assert special.special_tp_price == 89.9
    runtime.strategy_config.adverse_slope_take_profit.exspecial_near_middle_frac = 0.25
    exspecial = runtime.store.create_trade(runtime.position_key("ETH", "long"), "ETH", "long", 1, 100, "manual_adopted", 95)

    runtime.update_adverse_slope_take_profit(exspecial, _slope_features([121, 120, 119, 118], side="long"))

    assert exspecial.adverse_slope_tp_price == 113


def test_special_refreshes_on_new_completed_1h_bucket(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 12:05Z"))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 80, "manual_adopted", 75)

    runtime.update_adverse_slope_take_profit(trade, _slope_features([100, 100, 100, 99.9], side="long"))
    first_bucket = trade.special_tp_bucket_start
    runtime.exchange._now = "2030-01-01 13:05Z"
    event = runtime.update_adverse_slope_take_profit(trade, _slope_features([100, 100, 100, 99.8], side="long", start="2030-01-01 09:00Z"))

    assert "SPECIAL rolling" in event
    assert trade.special_tp_bucket_start > first_bucket
    assert trade.special_tp_price == 99.8


def test_special_target_live_price_crossing_uses_existing_safe_close(tmp_path):
    runtime, exchange = _runtime(tmp_path)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "manual_adopted", 95)
    trade.system_stop_order_id = "stop-1"
    trade.special_tp_active = True
    trade.special_tp_price = 120
    runtime.store.update_trade(trade)
    exchange.positions = []

    event = runtime.maybe_close_adverse_slope_take_profit(trade, 121, True)

    assert "SPECIAL target triggered; position closed" in event
    assert exchange.closes == [("BTC", "long", 1)]
    assert exchange.cancelled == [("BTC", "stop-1")]


def test_strategy_close_archives_pnl_only_with_its_exact_close_identity(tmp_path):
    exchange = ExactClosePnlExchange()
    runtime = _runtime_with_exchange(tmp_path, exchange)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.system_stop_order_id = "stop-1"
    trade.special_tp_active = True
    trade.special_tp_price = 120
    runtime.store.update_trade(trade)
    exchange.positions = []

    runtime.maybe_close_adverse_slope_take_profit(trade, 121, True)

    row = runtime.store.connection.execute("SELECT exit_price, realized_pnl, fees, pnl_source FROM live_trades WHERE internal_trade_id = ?", (trade.internal_trade_id,)).fetchone()
    assert exchange.pnl_lookup == ("BTC", trade.internal_trade_id, {"close_order_id": "close-1", "close_client_id": None, "close_qty": 1})
    assert dict(row) == {"exit_price": 120, "realized_pnl": 9.5, "fees": 0.25, "pnl_source": "exchange"}


def test_special_escalates_to_exspecial_without_resizing_trade(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 12:05Z"))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 2, 100, "manual_adopted", 95)
    runtime.update_adverse_slope_take_profit(trade, _slope_features([100, 100, 100, 99.9], side="long"))

    runtime.exchange._now = "2030-01-01 13:05Z"
    event = runtime.update_adverse_slope_take_profit(trade, _slope_features([121, 120, 119, 118], side="long", start="2030-01-01 09:00Z"))

    assert "EXSPECIAL defensive mode active" in event
    assert trade.special_tp_active is False
    assert trade.adverse_slope_tp_active is True
    assert trade.trailing_frozen is True
    assert trade.qty == 2
    assert trade.entry_price == 100


def test_exspecial_freezes_staged_stop_without_removing_protective_stop(tmp_path):
    exchange = ClockedExchange("2030-01-01 12:05Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.system_stop_order_id = "stop-1"
    runtime.update_adverse_slope_take_profit(trade, _slope_features([121, 120, 119, 118], side="long"))

    event = runtime.update_stop(trade, pd.Series({"lb": 80, "mb": 120, "ub": 160}), pd.Series({"close": 130, "high": 140, "low": 125}), True)

    assert event is None
    assert trade.current_stop_loss == 95
    assert trade.system_stop_order_id == "stop-1"
    assert exchange.cancelled == []


def test_missing_slope_uses_special_target_unless_exspecial_already_sticky(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 12:05Z"))
    runtime.strategy_config.adverse_slope_take_profit.slope_n = 120
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)

    runtime.update_adverse_slope_take_profit(trade, _slope_features([100, 100, 100, 100], side="long"))

    assert trade.special_tp_active is True
    assert trade.special_tp_price == 100


def test_no_completed_1h_without_history_persists_special_entry_price_fallback(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 12:30Z"))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "manual_adopted", 95)
    forming_only = _slope_features([100], side="long", start="2030-01-01 12:00Z")

    event = runtime.update_adverse_slope_take_profit(trade, forming_only)
    loaded = LiveStateStore(runtime.store.path).open_trade(runtime.position_key("BTC", "long"))

    assert event == "BTC SPECIAL fallback TP active; tp=100"
    assert loaded.special_tp_active is True
    assert loaded.special_tp_bucket_start is None
    assert loaded.special_tp_price == 100
    assert loaded.last_valid_slope_state is None
    assert loaded.trailing_frozen is False
    assert runtime.store.events()[-1]["event_type"] == "special_tp_activated"


def test_no_completed_1h_keeps_existing_exspecial_target_and_freeze(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 12:30Z"))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.adverse_slope_tp_active = True
    trade.adverse_slope_tp_bucket_start = pd.Timestamp("2030-01-01 11:00Z")
    trade.adverse_slope_tp_price = 108
    trade.trailing_frozen = True
    runtime.store.update_trade(trade)

    event = runtime.update_adverse_slope_take_profit(trade, _slope_features([100], side="long", start="2030-01-01 12:00Z"))

    assert event is None
    assert trade.adverse_slope_tp_active is True
    assert trade.adverse_slope_tp_bucket_start == pd.Timestamp("2030-01-01 11:00Z")
    assert trade.adverse_slope_tp_price == 108
    assert trade.trailing_frozen is True


def test_missing_slope_never_clears_existing_exspecial(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 12:05Z"))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    runtime.update_adverse_slope_take_profit(trade, _slope_features([121, 120, 119, 118], side="long"))
    runtime.strategy_config.adverse_slope_take_profit.slope_n = 120

    runtime.update_adverse_slope_take_profit(trade, _slope_features([100, 100, 100, 100], side="long"))

    assert trade.adverse_slope_tp_active is True
    assert trade.trailing_frozen is True


def test_adverse_slope_take_profit_ignores_forming_1h(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 12:30Z"))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)

    event = runtime.update_adverse_slope_take_profit(trade, _slope_features([118, 118, 118, 118, 100], side="long"))

    assert event is None
    assert trade.adverse_slope_tp_active is False
    assert trade.adverse_slope_tp_bucket_start is None
    assert trade.adverse_slope_tp_price is None


def test_adverse_slope_take_profit_closes_when_triggered(tmp_path):
    runtime, exchange = _runtime(tmp_path)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.system_stop_order_id = "stop-1"
    trade.adverse_slope_tp_active = True
    trade.adverse_slope_tp_price = 120
    runtime.store.update_trade(trade)
    exchange.positions = [ExchangePosition("BTC", "short", 2, 100, 99), ExchangePosition("ETH", "long", 1, 100, 101)]

    event = runtime.maybe_close_adverse_slope_take_profit(trade, 121, True)

    assert "position closed" in event
    assert exchange.closes == [("BTC", "long", 1)]
    assert exchange.cancelled == [("BTC", "stop-1")]
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None


def test_adverse_slope_take_profit_keeps_trade_open_until_position_zero(tmp_path):
    runtime, exchange = _runtime(tmp_path)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "manual_adopted", 95)
    trade.system_stop_order_id = "stop-1"
    trade.adverse_slope_tp_active = True
    trade.adverse_slope_tp_price = 120
    runtime.store.update_trade(trade)
    exchange.positions = [ExchangePosition("BTC", "long", 0.25, 100, 121)]

    event = runtime.maybe_close_adverse_slope_take_profit(trade, 121, True)

    loaded = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    assert "partially closed" in event
    assert loaded.qty == 0.25
    assert loaded.status == "open"
    assert exchange.stop_orders[-1]["qty"] == 0.25
    assert exchange.cancelled == [("BTC", "stop-1")]


def test_adverse_slope_take_profit_close_error_keeps_trade_open(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, FailingCloseExchange())
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.system_stop_order_id = "stop-1"
    trade.adverse_slope_tp_active = True
    trade.adverse_slope_tp_price = 120
    runtime.store.update_trade(trade)

    event = runtime.maybe_close_adverse_slope_take_profit(trade, 121, True)

    assert "close verification failed" in event
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is not None
    assert runtime.exchange.cancelled == []


def test_adverse_slope_take_profit_fetch_positions_error_keeps_trade_open(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, FailingFetchPositionsExchange())
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.system_stop_order_id = "stop-1"
    trade.adverse_slope_tp_active = True
    trade.adverse_slope_tp_price = 120
    runtime.store.update_trade(trade)

    event = runtime.maybe_close_adverse_slope_take_profit(trade, 121, True)

    assert "close verification failed" in event
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is not None
    assert runtime.exchange.cancelled == []


def test_adverse_slope_take_profit_inactive_does_not_close(tmp_path):
    runtime, exchange = _runtime(tmp_path)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)

    event = runtime.maybe_close_adverse_slope_take_profit(trade, 121, True)

    assert event is None
    assert exchange.closes == []


def test_long_high_based_stop_rules():
    trade = _trade("long", 100, 95)
    row_1h = pd.Series({"lb": 80, "mb": 120, "ub": 160})
    stop, reason = live_updated_stop(trade, row_1h, pd.Series({"close": 130, "high": 140, "low": 125}))
    assert stop == 120
    assert "5m high >=" in reason
    assert trade.trailing_stage == 3
    trade.current_stop_loss = 120
    stop, reason = live_updated_stop(trade, row_1h, pd.Series({"close": 150, "high": 161, "low": 145}))
    assert stop == 150
    assert "5m high >" in reason


def test_short_low_based_stop_rules():
    trade = _trade("short", 100, 105)
    row_1h = pd.Series({"lb": 40, "mb": 80, "ub": 120})
    stop, reason = live_updated_stop(trade, row_1h, pd.Series({"close": 70, "high": 75, "low": 60}))
    assert stop == 80
    assert "5m low <=" in reason
    assert trade.trailing_stage == 3
    trade.current_stop_loss = 80
    stop, reason = live_updated_stop(trade, row_1h, pd.Series({"close": 50, "high": 55, "low": 39}))
    assert stop == 50
    assert "5m low <" in reason


def test_second_trailing_step_moves_to_entry_price():
    trade = _trade("long", 100, 95)
    trade.current_stop_loss = 97.5
    stop, reason = live_updated_stop(trade, pd.Series({"lb": 80, "mb": 120, "ub": 160}), pd.Series({"close": 125, "high": 130, "low": 124}), 0.5)
    assert stop == 100
    assert reason == "5m close > 1h middle"

    trade = _trade("short", 100, 105)
    trade.current_stop_loss = 102.5
    stop, reason = live_updated_stop(trade, pd.Series({"lb": 40, "mb": 80, "ub": 120}), pd.Series({"close": 75, "high": 76, "low": 70}), 0.5)
    assert stop == 100
    assert reason == "5m close < 1h middle"


def test_third_trailing_step_persists_midband_follow_state(tmp_path):
    runtime, _ = _runtime(tmp_path)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)

    runtime.update_stop(trade, _row_1h("2030-01-01 08:00Z", lb=80, mb=120, ub=160), pd.Series({"close": 130, "high": 140, "low": 125}), True)

    loaded = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    assert loaded.trailing_stage == 3
    assert loaded.current_stop_loss == 120
    assert loaded.midband_follow_bucket_start == pd.Timestamp("2030-01-01 08:00Z")


def test_midband_follow_long_can_relax_but_not_below_entry():
    trade = _trade("long", 100, 95)
    trade.current_stop_loss = 105
    trade.trailing_stage = 3

    stop, reason = live_updated_stop(trade, pd.Series({"lb": 80, "mb": 103, "ub": 160}), pd.Series({"close": 104, "high": 104, "low": 102}))
    assert stop == 103
    assert "midband-follow active" in reason

    stop, _ = live_updated_stop(trade, pd.Series({"lb": 80, "mb": 99, "ub": 160}), pd.Series({"close": 100, "high": 100, "low": 98}))
    assert stop == 100


def test_midband_follow_short_can_relax_but_not_above_entry():
    trade = _trade("short", 100, 105)
    trade.current_stop_loss = 95
    trade.trailing_stage = 3

    stop, reason = live_updated_stop(trade, pd.Series({"lb": 40, "mb": 97, "ub": 120}), pd.Series({"close": 96, "high": 98, "low": 96}))
    assert stop == 97
    assert "midband-follow active" in reason

    stop, _ = live_updated_stop(trade, pd.Series({"lb": 40, "mb": 101, "ub": 120}), pd.Series({"close": 100, "high": 102, "low": 100}))
    assert stop == 100


def test_fourth_trailing_step_still_overrides_midband_follow():
    trade = _trade("long", 100, 95)
    trade.current_stop_loss = 105
    trade.trailing_stage = 3
    stop, reason = live_updated_stop(trade, pd.Series({"lb": 80, "mb": 103, "ub": 160}), pd.Series({"close": 150, "high": 161, "low": 145}))
    assert stop == 150
    assert "5m high >" in reason

    trade = _trade("short", 100, 105)
    trade.current_stop_loss = 95
    trade.trailing_stage = 3
    stop, reason = live_updated_stop(trade, pd.Series({"lb": 40, "mb": 97, "ub": 120}), pd.Series({"close": 50, "high": 55, "low": 39}))
    assert stop == 50
    assert "5m low <" in reason


def test_midband_follow_refreshes_only_once_per_1h_bucket():
    trade = _trade("long", 100, 95)
    stop, reason = live_updated_stop(trade, _row_1h("2030-01-01 08:00Z", lb=80, mb=120, ub=160), pd.Series({"close": 130, "high": 140, "low": 125}))
    assert stop == 120
    assert "midband-follow activated" in reason
    assert trade.midband_follow_bucket_start == pd.Timestamp("2030-01-01 08:00Z")

    trade.current_stop_loss = 120
    stop, reason = live_updated_stop(trade, _row_1h("2030-01-01 08:00Z", lb=80, mb=103, ub=160), pd.Series({"close": 104, "high": 104, "low": 102}))
    assert stop == 120
    assert reason == "no stop change"

    stop, reason = live_updated_stop(trade, _row_1h("2030-01-01 09:00Z", lb=80, mb=103, ub=160), pd.Series({"close": 104, "high": 104, "low": 102}))
    assert stop == 103
    assert "midband-follow active" in reason
    assert trade.midband_follow_bucket_start == pd.Timestamp("2030-01-01 09:00Z")


def test_midband_follow_short_refreshes_only_once_per_1h_bucket():
    trade = _trade("short", 100, 105)
    stop, reason = live_updated_stop(trade, _row_1h("2030-01-01 08:00Z", lb=40, mb=80, ub=120), pd.Series({"close": 70, "high": 75, "low": 60}))
    assert stop == 80
    assert "midband-follow activated" in reason
    assert trade.midband_follow_bucket_start == pd.Timestamp("2030-01-01 08:00Z")

    trade.current_stop_loss = 80
    stop, reason = live_updated_stop(trade, _row_1h("2030-01-01 08:00Z", lb=40, mb=97, ub=120), pd.Series({"close": 96, "high": 98, "low": 96}))
    assert stop == 80
    assert reason == "no stop change"

    stop, reason = live_updated_stop(trade, _row_1h("2030-01-01 09:00Z", lb=40, mb=97, ub=120), pd.Series({"close": 96, "high": 98, "low": 96}))
    assert stop == 97
    assert "midband-follow active" in reason
    assert trade.midband_follow_bucket_start == pd.Timestamp("2030-01-01 09:00Z")


def test_midband_follow_same_bucket_survives_restart(tmp_path):
    config = _config(tmp_path)
    store = LiveStateStore(config.storage.sqlite_path)
    trade = store.create_trade("default:testnet:BTC:long", "BTC", "long", 1, 100, "strategy", 95)
    trade.trailing_stage = 3
    trade.current_stop_loss = 120
    trade.midband_follow_bucket_start = pd.Timestamp("2030-01-01 08:00Z")
    store.update_trade(trade)
    restarted = LiveRuntime(config, FakeExchange(), LiveStateStore(config.storage.sqlite_path))

    loaded = restarted.store.open_trade("default:testnet:BTC:long")
    event = restarted.update_stop(loaded, _row_1h("2030-01-01 08:00Z", lb=80, mb=103, ub=160), pd.Series({"close": 104, "high": 104, "low": 102}), False)

    assert event is None
    assert restarted.store.open_trade("default:testnet:BTC:long").current_stop_loss == 120


def test_fourth_trailing_step_still_works_inside_refreshed_midband_bucket():
    trade = _trade("long", 100, 95)
    trade.current_stop_loss = 120
    trade.trailing_stage = 3
    trade.midband_follow_bucket_start = pd.Timestamp("2030-01-01 08:00Z")

    stop, reason = live_updated_stop(trade, _row_1h("2030-01-01 08:00Z", lb=80, mb=103, ub=160), pd.Series({"close": 150, "high": 161, "low": 145}))

    assert stop == 150
    assert "5m high >" in reason


def test_first_trailing_step_full_reduction_matches_old_behavior():
    row_1h = pd.Series({"lb": 80, "mb": 120, "ub": 160})
    stop, _ = live_updated_stop(_trade("long", 100, 95), row_1h, pd.Series({"close": 101, "high": 102, "low": 100}), 1.0)
    assert stop == 100

    row_1h = pd.Series({"lb": 40, "mb": 80, "ub": 120})
    stop, _ = live_updated_stop(_trade("short", 100, 105), row_1h, pd.Series({"close": 99, "high": 100, "low": 98}), 1.0)
    assert stop == 100


def test_first_trailing_step_half_reduces_initial_risk():
    row_1h = pd.Series({"lb": 80, "mb": 120, "ub": 160})
    stop, reason = live_updated_stop(_trade("long", 100, 95), row_1h, pd.Series({"close": 101, "high": 102, "low": 100}), 0.5)
    assert stop == 97.5
    assert "first-step risk reduced" in reason

    row_1h = pd.Series({"lb": 40, "mb": 80, "ub": 120})
    stop, reason = live_updated_stop(_trade("short", 100, 105), row_1h, pd.Series({"close": 99, "high": 100, "low": 98}), 0.5)
    assert stop == 102.5
    assert "first-step risk reduced" in reason


def _trade(side, entry, stop):
    runtime_trade = LiveStateStore(":memory:").create_trade(f"acct:testnet:BTC:{side}", "BTC", side, 1, entry, "strategy", stop)
    return runtime_trade


def _one_h_history(latest_time, latest_row):
    index = pd.date_range(end=pd.Timestamp(latest_time, tz="UTC"), periods=120, freq="h")
    rows = [{"open": 120, "high": 121, "low": 99, "close": 120, "lb": 100, "mb": 120, "ub": 140, "rsi14": 50} for _ in index]
    rows[-1].update(latest_row)
    return pd.DataFrame(rows, index=index)


def _continuation_1h_features(start, age=1):
    widths = [0.05] * 5 + [0.06] + [0.05] * age
    middles = [100] * 6 + [100 + 0.02 * step for step in range(1, age + 1)]
    closes = [100] * 5 + [200] + [100] * age
    return pd.DataFrame(
        [{"lb": middle - width * middle / 2, "mb": middle, "ub": middle + width * middle / 2, "close": close, "rsi14": 50} for width, middle, close in zip(widths, middles, closes)],
        index=pd.date_range(start, periods=len(widths), freq="h", tz="UTC"),
    )


def _row_1h(time, *, lb, mb, ub):
    return pd.Series({"lb": lb, "mb": mb, "ub": ub}, name=pd.Timestamp(time))


def _slope_features(middle_values, *, side, start="2030-01-01 08:00Z"):
    index = pd.date_range(pd.Timestamp(start), periods=len(middle_values), freq="h")
    rows = []
    for middle in middle_values:
        rows.append({"lb": middle - 20, "mb": middle, "ub": middle + 20, "close": middle, "rsi14": 50})
    return pd.DataFrame(rows, index=index)


def _confirmed_setup():
    return Setup(
        "long",
        pd.Series({"close": 95, "lb": 100, "mb": 120, "ub": 140, "rsi14": 20}),
        pd.Timestamp("2030-01-01 09:00Z"),
        pd.Timestamp("2030-01-01 10:00Z"),
        25,
        pd.Timestamp("2030-01-01 09:15Z"),
        True,
        pd.Timestamp("2030-01-01 09:30Z"),
    )
