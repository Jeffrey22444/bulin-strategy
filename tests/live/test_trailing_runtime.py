import json

import pandas as pd
import pytest

from bbmr.live.config import load_live_config
from bbmr.live.hyperliquid_client import ExchangePosition, LiveBalance, MarketQuote
from bbmr.live.state_store import LiveStateStore
from bbmr.live.trailing_runtime import LiveRuntime, latest_completed_features, live_updated_stop
from bbmr.trailing import Setup
from bbmr.trailing_features import build_trailing_features


class FakeExchange:
    def __init__(self):
        self.stop_orders = []
        self.cancelled = []
        self.entries = []
        self.closes = []
        self.leverage_calls = []
        self.positions = []
        self.market_quote = MarketQuote(104.9, 105.1, 105)

    def create_reduce_only_stop(self, symbol, side, qty, stop_price):
        order = {"id": f"stop-{len(self.stop_orders) + 1}", "symbol": symbol, "side": side, "qty": qty, "stop": stop_price}
        self.stop_orders.append(order)
        return order

    def cancel_order(self, symbol, exchange_order_id):
        self.cancelled.append((symbol, exchange_order_id))

    def create_market_entry(self, symbol, side, qty):
        self.entries.append((symbol, side, qty))
        return {"id": "entry-1", "filled": qty}

    def close_position_market(self, symbol, side, qty):
        self.closes.append((symbol, side, qty))
        return {"id": "close-1", "filled": qty, "price": 120}

    def set_leverage(self, symbol, leverage, margin_mode):
        self.leverage_calls.append((symbol, leverage, margin_mode))

    def format_qty(self, symbol, qty):
        return round(qty, 8)

    def fetch_positions(self):
        return self.positions

    def fetch_open_orders(self, symbol):
        return []

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

    def create_market_entry(self, symbol, side, qty):
        order = super().create_market_entry(symbol, side, qty)
        self.positions = [ExchangePosition(symbol, side, qty, self.entry_price, self.entry_price)]
        return order


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


class FailingStopExchange(FakeExchange):
    def create_reduce_only_stop(self, symbol, side, qty, stop_price):
        raise RuntimeError("stop create failed")


class MissingStopIdExchange(FakeExchange):
    def create_reduce_only_stop(self, symbol, side, qty, stop_price):
        order = {"id": None, "symbol": symbol, "side": side, "qty": qty, "stop": stop_price}
        self.stop_orders.append(order)
        return order


class FailingLeverageExchange(ClockedExchange):
    def set_leverage(self, symbol, leverage, margin_mode):
        raise RuntimeError("leverage failed")


class FailingEntryExchange(ClockedExchange):
    def create_market_entry(self, symbol, side, qty):
        raise RuntimeError("entry failed")


class EntryStopFailExchange(ConfirmingEntryExchange):
    def create_reduce_only_stop(self, symbol, side, qty, stop_price):
        raise RuntimeError("entry stop failed")


class FailingCloseExchange(FakeExchange):
    def close_position_market(self, symbol, side, qty):
        raise RuntimeError("close failed")


class FailingFetchPositionsExchange(FakeExchange):
    def fetch_positions(self):
        raise RuntimeError("positions unavailable")


class AverageFillExchange(ClockedExchange):
    def create_market_entry(self, symbol, side, qty):
        self.entries.append((symbol, side, qty))
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


def _adverse_long_features():
    one_h = _frame(
        ["2030-01-01 05:00", "2030-01-01 06:00", "2030-01-01 07:00", "2030-01-01 08:00"],
        [
            {"open": 122, "high": 123, "low": 101, "close": 122, "lb": 102, "mb": 122, "ub": 142, "rsi14": 50},
            {"open": 121, "high": 122, "low": 100, "close": 121, "lb": 101, "mb": 121, "ub": 141, "rsi14": 50},
            {"open": 120, "high": 121, "low": 99, "close": 120, "lb": 100, "mb": 120, "ub": 140, "rsi14": 50},
            {"open": 120, "high": 121, "low": 90, "close": 95, "lb": 100, "mb": 120, "ub": 140, "rsi14": 20},
        ],
    )
    _, fifteen_m, five_m = _future_long_features(close_5m=105)
    return one_h, fifteen_m, five_m


def test_entry_sizing_uses_margin_fraction_times_leverage(tmp_path):
    runtime, _ = _runtime(tmp_path)
    assert runtime.entry_notional(10000) == 10000 * runtime.live_config.execution.margin_fraction * runtime.live_config.execution.leverage
    assert runtime.entry_notional(10000, 2) == 10000 * runtime.live_config.execution.margin_fraction * 2


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
    exchange = ConfirmingEntryExchange("2030-01-01 09:35Z")
    runtime = _runtime_with_exchange(tmp_path, exchange)
    events = runtime.maybe_open_strategy_trade("BTC", *_long_features_with_old_filter_columns(), 10000, True)
    expected_qty = runtime.entry_notional(10000) / 105
    assert exchange.leverage_calls == [("BTC", 3, "cross")]
    assert exchange.entries == [("BTC", "long", round(expected_qty, 8))]
    assert any("entry opened" in event for event in events)


def test_strategy_entry_uses_adverse_slope_leverage_when_active(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ConfirmingEntryExchange("2030-01-01 09:35Z"))

    events = runtime.maybe_open_strategy_trade("SOL", *_adverse_long_features(), 10000, True)

    expected_qty = runtime.entry_notional(10000, 2) / 105
    assert runtime.exchange.leverage_calls == [("SOL", 2, "cross")]
    assert runtime.exchange.entries == [("SOL", "long", round(expected_qty, 8))]
    assert any("entry opened" in event for event in events)


def test_strategy_entry_blocks_when_global_notional_cap_exceeded(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ConfirmingEntryExchange("2030-01-01 09:35Z"))
    positions = [ExchangePosition("ETH", "long", 10, 500, 600)]

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, True, exchange_positions=positions)

    assert events[-1] == "BTC risk cap exceeded; waiting"
    assert runtime.exchange.leverage_calls == []
    assert runtime.exchange.entries == []
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert "BTC" in runtime.setups
    assert runtime.store.events()[-1]["event_type"] == "setup_created"


def test_strategy_entry_allows_notional_equal_to_global_cap(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ConfirmingEntryExchange("2030-01-01 09:35Z"))
    positions = [ExchangePosition("ETH", "long", 10, 550, 0)]

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
    assert runtime.store.events()[-1]["event_type"] == "setup_created"


def test_strategy_entry_blocks_when_available_margin_insufficient(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ConfirmingEntryExchange("2030-01-01 09:35Z"))

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), LiveBalance(10000, 1000), True)

    assert events[-1] == "BTC available margin insufficient; waiting"
    assert runtime.exchange.leverage_calls == []
    assert runtime.exchange.entries == []
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert "BTC" in runtime.setups
    assert runtime.store.events()[-1]["event_type"] == "setup_created"


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
    assert runtime.store.events()[-1]["event_type"] == "setup_created"


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
    assert runtime.store.events()[-1]["event_type"] == "setup_created"


def test_entry_fill_slippage_is_recorded_without_leaving_position_unprotected(tmp_path):
    exchange = AverageFillExchange("2030-01-01 09:35Z")
    exchange.market_quote = MarketQuote(104.9, 105.1, 105)
    runtime = _runtime_with_exchange(tmp_path, exchange)

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), LiveBalance(10000, 1500), True)

    trade = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    event_types = [row["event_type"] for row in runtime.store.events()]
    slippage_event = next(row for row in runtime.store.events() if row["event_type"] == "entry_slippage_exceeded")
    assert any("entry fill slippage exceeded" in event for event in events)
    assert trade.status == "open"
    assert trade.system_stop_order_id == "stop-1"
    assert event_types[-2:] == ["entry_slippage_exceeded", "entry_opened"]
    assert json.loads(slippage_event["payload_json"]) == {
        "fill_price": 110.0,
        "max_entry_slippage_bps": 100.0,
        "reference_price": 105.0,
        "slippage_bps": pytest.approx(476.19047619047615),
    }


def test_entry_leverage_uses_setup_side_adverse_slope(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 12:05Z"))

    assert runtime.entry_leverage("long", _slope_features([121, 120, 119, 118], side="long")) == 2
    assert runtime.entry_leverage("short", _slope_features([118, 119, 120, 121], side="short")) == 2
    assert runtime.entry_leverage("long", _slope_features([118, 118, 118, 118], side="long")) == 3


def test_requires_15m_reversal_when_enabled(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:05Z"))
    runtime.strategy_config.entry_confirmation.require_15m_rsi_reversal = True

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105, close_time="2030-01-01 09:05"), 10000, False)

    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert events == ["BTC 1h setup met; waiting for first 15m RSI baseline"]


def test_skips_15m_reversal_when_disabled(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:05Z"))

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105, close_time="2030-01-01 09:05"), 10000, False)

    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is not None
    assert events[0] == "BTC 15m RSI reversal disabled; waiting for 5m entry"
    assert "BTC 15m RSI reversal disabled; waiting for 5m entry" in events
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

    assert runtime.setups == {}
    assert runtime.store.connection.execute("SELECT COUNT(*) AS count FROM live_pending_setups").fetchone()["count"] == 0
    assert runtime.store.events()[-1]["event_type"] == "entry_opened"


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

    assert "entry order not confirmed" in events[-1]
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert "BTC" in runtime.setups
    assert runtime.store.connection.execute("SELECT COUNT(*) AS count FROM live_pending_setups").fetchone()["count"] == 1
    assert [row["event_type"] for row in runtime.store.events()] == ["setup_created"]


def test_market_entry_failure_without_position_does_not_create_open_trade(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, FailingEntryExchange("2030-01-01 09:35Z"))

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, True)

    assert "entry order not confirmed" in events[-1]
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert "BTC" in runtime.setups
    assert runtime.store.events()[-1]["event_type"] == "setup_created"


def test_market_entry_without_confirmed_position_does_not_create_open_trade(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 09:35Z"))

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, True)

    assert "entry order not confirmed" in events[-1]
    assert runtime.store.open_trade(runtime.position_key("BTC", "long")) is None
    assert "BTC" in runtime.setups
    assert runtime.store.events()[-1]["event_type"] == "setup_created"


def test_market_entry_filled_but_stop_failure_keeps_unprotected_record(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, EntryStopFailExchange("2030-01-01 09:35Z"))

    events = runtime.maybe_open_strategy_trade("BTC", *_future_long_features(close_5m=105), 10000, True)

    trade = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    assert "entry filled but protective stop failed" in events[-1]
    assert trade.status == "entry_unprotected"
    assert trade.system_stop_order_id is None
    assert "BTC" in runtime.setups
    assert [row["event_type"] for row in runtime.store.events()][-2:] == ["protective_stop_failed", "entry_unprotected"]


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
    assert "entry protected" in events[0]
    assert runtime.store.events()[-1]["event_type"] == "entry_opened"


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


def test_manual_addon_management_can_be_disabled(tmp_path):
    runtime, exchange = _runtime(tmp_path)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.system_stop_order_id = "stop-1"
    runtime.store.update_trade(trade)
    runtime.live_config.execution.manage_full_manual_added_size = False

    events = runtime.reconcile_symbol("BTC", [ExchangePosition("BTC", "long", 2, 98, 101)], True)

    loaded = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    assert events == ["BTC manual size change ignored; management disabled"]
    assert loaded.qty == 1
    assert loaded.entry_price == 100
    assert loaded.internal_trade_id == trade.internal_trade_id
    assert exchange.stop_orders == []
    assert runtime.store.events() == []


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
    assert "entry protected" in events[0]
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
    assert loaded.current_stop_loss == 95
    assert loaded.system_stop_order_id == "old-stop"
    assert runtime.exchange.cancelled == []
    assert runtime.store.events()[-1]["event_type"] == "protective_stop_failed"
    assert "stop create failed" in runtime.emergency_protect_reason

    events = runtime.maybe_open_strategy_trade("SOL", *_future_long_features(close_5m=105), 10000, True)

    assert events == [f"SOL strategy entry blocked: {runtime.emergency_protect_reason}"]
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


def test_adverse_slope_take_profit_long_active_and_inactive(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 12:05Z"))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)

    event = runtime.update_adverse_slope_take_profit(trade, _slope_features([121, 120, 119, 118], side="long"))

    assert "adverse 1h middle slope active" in event
    assert trade.adverse_slope_tp_active is True
    assert trade.adverse_slope_tp_price == 118

    runtime.exchange._now = "2030-01-01 13:05Z"
    event = runtime.update_adverse_slope_take_profit(trade, _slope_features([118, 118, 118, 118], side="long", start="2030-01-01 09:00Z"))

    assert "special TP cleared" in event
    assert trade.adverse_slope_tp_active is False
    assert trade.adverse_slope_tp_bucket_start is None
    assert trade.adverse_slope_tp_price is None


def test_adverse_slope_take_profit_short_active(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 12:05Z"))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "short"), "BTC", "short", 1, 100, "strategy", 105)

    event = runtime.update_adverse_slope_take_profit(trade, _slope_features([118, 119, 120, 121], side="short"))

    assert "adverse 1h middle slope active" in event
    assert trade.adverse_slope_tp_active is True
    assert trade.adverse_slope_tp_price == 121


def test_adverse_slope_take_profit_does_not_enable_manual_adopted(tmp_path):
    runtime = _runtime_with_exchange(tmp_path, ClockedExchange("2030-01-01 12:05Z"))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "manual_adopted", 95)

    event = runtime.update_adverse_slope_take_profit(trade, _slope_features([121, 120, 119, 118], side="long"))

    assert event is None
    assert trade.adverse_slope_tp_active is False


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
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
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

    runtime.update_stop(trade, _row_1h("2030-01-01 08:00Z", lb=80, mb=120, ub=160), pd.Series({"close": 130, "high": 140, "low": 125}), False)

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
