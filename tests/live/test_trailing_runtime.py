import json

import pandas as pd
import pytest

from bbmr.live.config import load_live_config
from bbmr.live.hyperliquid_client import ExchangePosition
from bbmr.live.state_store import LiveStateStore
from bbmr.live.trailing_runtime import LiveRuntime, latest_completed_features, live_updated_stop
from bbmr.trailing import Setup
from bbmr.trailing_features import build_trailing_features


class FakeExchange:
    def __init__(self):
        self.stop_orders = []
        self.cancelled = []
        self.entries = []
        self.leverage_calls = []

    def create_reduce_only_stop(self, symbol, side, qty, stop_price):
        order = {"id": f"stop-{len(self.stop_orders) + 1}", "symbol": symbol, "side": side, "qty": qty, "stop": stop_price}
        self.stop_orders.append(order)
        return order

    def cancel_order(self, symbol, exchange_order_id):
        self.cancelled.append((symbol, exchange_order_id))

    def create_market_entry(self, symbol, side, qty):
        self.entries.append((symbol, side, qty))
        return {"id": "entry-1", "filled": qty}

    def set_leverage(self, symbol, leverage, margin_mode):
        self.leverage_calls.append((symbol, leverage, margin_mode))

    def format_qty(self, symbol, qty):
        return round(qty, 8)

    def fetch_positions(self):
        return []

    def fetch_open_orders(self, symbol):
        return []


class ClockedExchange(FakeExchange):
    def __init__(self, now):
        super().__init__()
        self._now = now

    def now(self):
        return self._now


class OrderNotFound(Exception):
    pass


class MissingStopExchange(FakeExchange):
    def cancel_order(self, symbol, exchange_order_id):
        raise OrderNotFound("Order was never placed, already canceled, or filled")


class PnlExchange(FakeExchange):
    def fetch_recent_realized_pnl(self, symbol, trade):
        return {"exit_price": 110, "realized_pnl": 9.5, "fees": 0.25, "pnl_source": "exchange"}


class FailingPnlExchange(FakeExchange):
    def fetch_recent_realized_pnl(self, symbol, trade):
        raise RuntimeError("trade history unavailable")


class AverageFillExchange(ClockedExchange):
    def create_market_entry(self, symbol, side, qty):
        self.entries.append((symbol, side, qty))
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


def _frame(index, rows):
    return pd.DataFrame(rows, index=[pd.Timestamp(value, tz="UTC") for value in index])


def _long_features_with_old_filter_columns():
    one_h = _frame(
        ["2026-01-01 08:00"],
        [{"open": 120, "high": 121, "low": 90, "close": 95, "lb": 100, "mb": 120, "ub": 140, "rsi14": 20, "range_allowed": False, "lower_band_walking": True}],
    )
    fifteen_m = _frame(
        ["2026-01-01 08:45", "2026-01-01 09:00", "2026-01-01 09:15"],
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 20},
            {"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 25},
            {"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 30},
        ],
    )
    five_m = _frame(
        ["2026-01-01 09:30"],
        [{"open": 104, "high": 106, "low": 103, "close": 105, "mb": 100, "volume_ratio": 0, "rsi_flat_entry_block": True}],
    )
    return one_h, fifteen_m, five_m


def _future_long_features(close_5m=99, close_time="2030-01-01 09:35"):
    close_ts = pd.Timestamp(close_time, tz="UTC")
    one_h = _frame(
        ["2030-01-01 08:00"],
        [{"open": 120, "high": 121, "low": 90, "close": 95, "lb": 100, "mb": 120, "ub": 140, "rsi14": 20}],
    )
    fifteen_m = _frame(
        ["2030-01-01 08:45", "2030-01-01 09:00", "2030-01-01 09:15"],
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 20},
            {"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 25},
            {"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 30},
        ],
    )
    five_m = _frame(
        [(close_ts - pd.Timedelta(minutes=5)).isoformat()],
        [{"open": close_5m, "high": close_5m + 1, "low": close_5m - 1, "close": close_5m, "mb": 100}],
    )
    return one_h, fifteen_m, five_m


def test_entry_sizing_uses_margin_fraction_times_leverage(tmp_path):
    runtime, _ = _runtime(tmp_path)
    assert runtime.entry_notional(10000) == 3000


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

    assert calls == ["wilder", "wilder"]


def test_latest_completed_features_uses_rsi_warmup_bars(tmp_path):
    runtime, _ = _runtime(tmp_path)
    exchange = RecordingOhlcvExchange()

    latest_completed_features(exchange, "BTC", runtime.strategy_config)

    assert exchange.calls == [("BTC", "1h", 500), ("BTC", "15m", 500), ("BTC", "5m", 21)]


def test_live_strategy_ignores_old_v3_2_filter_columns(tmp_path):
    runtime, exchange = _runtime(tmp_path)
    events = runtime.maybe_open_strategy_trade("BTC", *_long_features_with_old_filter_columns(), 10000, True)
    assert exchange.entries == [("BTC", "long", 28.57142857)]
    assert any("entry opened" in event for event in events)


def test_pending_setup_recovers_after_restart(tmp_path, monkeypatch):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:05Z"))
    runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=99, close_time="2030-01-01 09:05"), 10000, False)
    monkeypatch.setattr("bbmr.live.trailing_runtime.latest_completed_features", lambda exchange, symbol, config: _future_long_features(close_5m=99, close_time="2030-01-01 09:05"))

    restarted = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:06Z"))

    assert "BTC" in restarted.setups
    assert restarted.setups["BTC"].confirmed_15m is False
    assert restarted.setups["BTC"].rsi_15m is None


def test_confirmed_setup_state_recovers_after_restart(tmp_path, monkeypatch):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:35Z"))
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

    assert runtime.setups == {}
    assert runtime.store.connection.execute("SELECT COUNT(*) AS count FROM live_pending_setups").fetchone()["count"] == 0
    assert runtime.store.events()[-1]["event_type"] == "entry_opened"


def test_forming_5m_does_not_trigger_entry(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:32Z"))
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


def test_strategy_entry_skips_when_exchange_position_exists(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ExistingPositionExchange("2030-01-01 09:35Z"))

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, True)

    assert events == ["BTC exchange position exists; waiting"]
    assert runtime.exchange.entries == []
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None


def test_strategy_entry_skips_when_exchange_open_order_exists(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, OpenOrderExchange("2030-01-01 09:35Z"))

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, True)

    assert events == ["BTC open order exists; waiting"]
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


def test_trade_journal_records_state_changes_and_appends(tmp_path):
    runtime, exchange = _runtime(tmp_path)

    runtime.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 1, 100, 101)], True)
    runtime.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 2, 98, 101)], True)
    trade = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    runtime.update_stop(trade, pd.Series({"lb": 80, "mb": 120, "ub": 160}), pd.Series({"close": 130, "high": 140, "low": 125}), True)
    runtime.reconcile_symbol("BTC", [], True)

    event_types = [row["event_type"] for row in runtime.store.events()]
    assert event_types == ["manual_adopted", "manual_size_changed", "stop_updated", "exit_archived"]
    assert [row["event_id"] for row in runtime.store.events()] == [1, 2, 3, 4]


def test_manual_close_archives_and_cancels_only_system_stop(tmp_path):
    runtime, exchange = _runtime(tmp_path)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.system_stop_order_id = "system-stop"
    runtime.store.update_trade(trade)

    runtime.reconcile_symbol("BTC", [], True)

    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert exchange.cancelled == [("BTC", "system-stop")]


def test_manual_close_archives_exchange_realized_pnl(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, PnlExchange())
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)

    runtime.reconcile_symbol("BTC", [], True)

    row = runtime.store.connection.execute("SELECT exit_price, realized_pnl, fees, pnl_source FROM live_trades WHERE internal_trade_id = ?", (trade.internal_trade_id,)).fetchone()
    event = runtime.store.events()[-1]
    assert dict(row) == {"exit_price": 110, "realized_pnl": 9.5, "fees": 0.25, "pnl_source": "exchange"}
    assert json.loads(event["payload_json"]) == {"exit_price": 110.0, "fees": 0.25, "pnl_source": "exchange", "realized_pnl": 9.5}


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
    runtime.store.update_trade(trade)

    runtime.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 2, 100, 101)], True)

    assert exchange.cancelled == [("BTC", "system-stop")]


def test_manual_addon_updates_merged_quantity(tmp_path):
    runtime, exchange = _runtime(tmp_path)
    runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)

    runtime.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 2, 98, 101)], True)

    trade = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    assert trade.qty == 2
    assert trade.entry_price == 98
    assert exchange.stop_orders[-1]["qty"] == 2


def test_long_high_based_stop_rules():
    trade = _trade("long", 100, 95)
    row_1h = pd.Series({"lb": 80, "mb": 120, "ub": 160})
    stop, reason = live_updated_stop(trade, row_1h, pd.Series({"close": 130, "high": 140, "low": 125}))
    assert stop == 120
    assert "5m high >=" in reason
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
    trade.current_stop_loss = 80
    stop, reason = live_updated_stop(trade, row_1h, pd.Series({"close": 50, "high": 55, "low": 39}))
    assert stop == 50
    assert "5m low <" in reason


def _trade(side, entry, stop):
    runtime_trade = LiveStateStore(":memory:").create_trade(f"acct:testnet:BTC:{side}", "BTC", side, 1, entry, "strategy", stop)
    return runtime_trade


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
