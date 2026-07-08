from types import SimpleNamespace
import json

import pandas as pd
import pytest
import yaml

from bbmr.live.hyperliquid_client import ExchangePosition
from bbmr.live.env import load_project_env
from bbmr.live.run import (
    _light_guard_detects_active_state,
    _live_runner_lock,
    _next_1h_wake_time,
    _next_poll_time_after_full_poll,
    _next_sleep_seconds,
    _poll_once,
    _should_full_poll,
    main,
)
from bbmr.live.state_store import LiveStateStore
from bbmr.live.trailing_runtime import LiveRuntime


def test_mainnet_requires_cli_flag_even_when_config_allows(tmp_path):
    data = yaml.safe_load(open("configs/live_hyperliquid_testnet.yaml", encoding="utf-8"))
    data["exchange"]["env"] = "mainnet"
    data["exchange"]["allow_mainnet"] = True
    path = tmp_path / "live_mainnet.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(ValueError, match="--allow-mainnet"):
        main(["--live-config", str(path), "--once", "--dry-run"])


def test_live_run_loads_credentials_from_env_file(tmp_path, monkeypatch, capsys):
    env_path = tmp_path / ".env"
    env_path.write_text("HYPERLIQUID_WALLET_ADDRESS=env-wallet\nHYPERLIQUID_PRIVATE_KEY=env-private\n", encoding="utf-8")
    config_path = _live_config_path(tmp_path)
    captured = {}

    class FakeClient(_Client):
        def __init__(self, config):
            captured["wallet"] = __import__("os").environ.get("HYPERLIQUID_WALLET_ADDRESS")
            captured["private"] = __import__("os").environ.get("HYPERLIQUID_PRIVATE_KEY")

    monkeypatch.delenv("HYPERLIQUID_WALLET_ADDRESS", raising=False)
    monkeypatch.delenv("HYPERLIQUID_PRIVATE_KEY", raising=False)
    monkeypatch.setattr("bbmr.live.run.load_project_env", lambda: load_project_env(env_path))
    monkeypatch.setattr("bbmr.live.run.HyperliquidClient", FakeClient)
    monkeypatch.setattr("bbmr.live.run._poll_once", lambda *args, **kwargs: None)

    assert main(["--live-config", str(config_path), "--once"]) == 0

    output = capsys.readouterr()
    assert captured == {"wallet": "env-wallet", "private": "env-private"}
    assert "env-wallet" not in output.out + output.err
    assert "env-private" not in output.out + output.err


def test_live_run_exported_credentials_are_not_overwritten_by_env_file(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("HYPERLIQUID_WALLET_ADDRESS=env-wallet\nHYPERLIQUID_PRIVATE_KEY=env-private\n", encoding="utf-8")
    config_path = _live_config_path(tmp_path)
    captured = {}

    class FakeClient(_Client):
        def __init__(self, config):
            captured["wallet"] = __import__("os").environ.get("HYPERLIQUID_WALLET_ADDRESS")
            captured["private"] = __import__("os").environ.get("HYPERLIQUID_PRIVATE_KEY")

    monkeypatch.setenv("HYPERLIQUID_WALLET_ADDRESS", "export-wallet")
    monkeypatch.setenv("HYPERLIQUID_PRIVATE_KEY", "export-private")
    monkeypatch.setattr("bbmr.live.run.load_project_env", lambda: load_project_env(env_path))
    monkeypatch.setattr("bbmr.live.run.HyperliquidClient", FakeClient)
    monkeypatch.setattr("bbmr.live.run._poll_once", lambda *args, **kwargs: None)

    assert main(["--live-config", str(config_path), "--once"]) == 0
    assert captured == {"wallet": "export-wallet", "private": "export-private"}


def test_live_run_once_still_full_polls_immediately(tmp_path, monkeypatch):
    config_path = _live_config_path(tmp_path)
    calls = []

    monkeypatch.setattr("bbmr.live.run.load_project_env", lambda: None)
    monkeypatch.setattr("bbmr.live.run.missing_credential_names", lambda config: [])
    monkeypatch.setattr("bbmr.live.run.HyperliquidClient", _NoPositionClient)
    monkeypatch.setattr("bbmr.live.run._poll_once", lambda *args, **kwargs: calls.append("full"))

    assert main(["--live-config", str(config_path), "--once"]) == 0
    assert calls == ["full"]


def test_live_run_rejects_second_instance(tmp_path, monkeypatch):
    config_path = _live_config_path(tmp_path)

    monkeypatch.setattr("bbmr.live.run.load_project_env", lambda: None)
    monkeypatch.setattr("bbmr.live.run.missing_credential_names", lambda config: [])

    with _live_runner_lock(str(tmp_path / "live.sqlite3")):
        with pytest.raises(RuntimeError, match="live runner already running"):
            main(["--live-config", str(config_path), "--once"])


@pytest.mark.parametrize("timeout_at", ["balance", "positions"])
def test_live_run_continues_next_cycle_on_poll_timeout(tmp_path, monkeypatch, capsys, timeout_at):
    config_path = _live_config_path(tmp_path)

    class TimeoutClient(_Client):
        def fetch_balance(self):
            if timeout_at == "balance":
                raise TimeoutError("read timed out")
            return super().fetch_balance()

        def fetch_positions(self):
            if timeout_at == "positions":
                raise TimeoutError("read timed out")
            return super().fetch_positions()

    monkeypatch.setattr("bbmr.live.run.load_project_env", lambda: None)
    monkeypatch.setattr("bbmr.live.run.missing_credential_names", lambda config: [])
    monkeypatch.setattr("bbmr.live.run.HyperliquidClient", TimeoutClient)

    assert main(["--live-config", str(config_path), "--once"]) == 0

    output = capsys.readouterr().out
    assert "2026-01-01 17:15:00+08:00 [WARN] live poll network error; waiting for next cycle" in output
    row = LiveStateStore(str(tmp_path / "live.sqlite3")).events()[-1]
    assert row["event_type"] == "recoverable_network_error"
    assert json.loads(row["payload_json"])["severity"] == "WARN"


def test_live_run_continues_next_cycle_on_ccxt_network_error(tmp_path, monkeypatch, capsys):
    from ccxt.base.errors import NetworkError

    config_path = _live_config_path(tmp_path)

    class NetworkFailingClient(_Client):
        def fetch_balance(self):
            raise NetworkError("name resolution failed")

    monkeypatch.setattr("bbmr.live.run.load_project_env", lambda: None)
    monkeypatch.setattr("bbmr.live.run.missing_credential_names", lambda config: [])
    monkeypatch.setattr("bbmr.live.run.HyperliquidClient", NetworkFailingClient)

    assert main(["--live-config", str(config_path), "--once"]) == 0

    output = capsys.readouterr().out
    assert "2026-01-01 17:15:00+08:00 [WARN] live poll network error; waiting for next cycle" in output
    row = LiveStateStore(str(tmp_path / "live.sqlite3")).events()[-1]
    assert row["event_type"] == "recoverable_network_error"
    assert json.loads(row["payload_json"])["severity"] == "WARN"


def test_live_run_unknown_poll_error_still_raises(tmp_path, monkeypatch):
    config_path = _live_config_path(tmp_path)

    class FailingClient(_Client):
        def fetch_balance(self):
            raise RuntimeError("bad state")

    monkeypatch.setattr("bbmr.live.run.load_project_env", lambda: None)
    monkeypatch.setattr("bbmr.live.run.missing_credential_names", lambda config: [])
    monkeypatch.setattr("bbmr.live.run.HyperliquidClient", FailingClient)

    with pytest.raises(RuntimeError, match="bad state"):
        main(["--live-config", str(config_path), "--once"])


def test_poll_once_feature_timeout_happens_before_state_changes(tmp_path, monkeypatch):
    config = _live_config(tmp_path)
    runtime = LiveRuntime(config, _Exchange(), LiveStateStore(config.storage.sqlite_path))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: (_ for _ in ()).throw(TimeoutError("read timed out")))

    _poll_once(runtime, _NoPositionClient(), ["BTC"], cli_allow_testnet_orders=False, dry_run=True)

    assert runtime.store.open_trade(runtime.position_key("BTC", "long")).internal_trade_id == trade.internal_trade_id


def test_next_1h_wake_time_uses_grace():
    assert _next_1h_wake_time(pd.Timestamp("2026-01-01 09:15:00Z"), 10) == pd.Timestamp("2026-01-01 10:00:10Z")
    assert _next_1h_wake_time(pd.Timestamp("2026-01-01 09:00:05Z"), 10) == pd.Timestamp("2026-01-01 09:00:10Z")
    assert _next_1h_wake_time(pd.Timestamp("2026-01-01 09:00:11Z"), 10) == pd.Timestamp("2026-01-01 10:00:10Z")


def test_idle_light_guard_does_not_fetch_ohlcv(tmp_path):
    runtime = LiveRuntime(_live_config(tmp_path), _Exchange(), LiveStateStore(_live_config(tmp_path).storage.sqlite_path))
    client = _NoPositionClient()

    assert _light_guard_detects_active_state(runtime, client, ["BTC", "ETH"]) is False
    assert client.open_order_calls == ["BTC", "ETH"]
    assert client.ohlcv_calls == 0


def test_idle_waits_until_1h_wake_for_full_poll(tmp_path):
    config = _live_config(tmp_path)
    runtime = LiveRuntime(config, _Exchange(), LiveStateStore(config.storage.sqlite_path))
    client = _NoPositionClient()
    next_full = pd.Timestamp("2026-01-01 10:00:10Z")

    assert _should_full_poll(runtime, client, ["BTC"], config, next_full) is False
    client._now = pd.Timestamp("2026-01-01 10:00:10Z")
    assert _should_full_poll(runtime, client, ["BTC"], config, next_full) is True


def test_idle_sleep_caps_at_guard_and_full_poll(tmp_path):
    config = _live_config(tmp_path)
    assert _next_sleep_seconds(pd.Timestamp("2026-01-01 09:59:55Z"), pd.Timestamp("2026-01-01 10:00:10Z"), config) == 15
    assert _next_sleep_seconds(pd.Timestamp("2026-01-01 09:15:00Z"), pd.Timestamp("2026-01-01 10:00:10Z"), config) == 30


def test_active_states_trigger_full_poll(tmp_path):
    config = _live_config(tmp_path)
    runtime = LiveRuntime(config, _Exchange(), LiveStateStore(config.storage.sqlite_path))
    future = pd.Timestamp("2026-01-01 10:00:10Z")

    runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    assert _should_full_poll(runtime, _NoPositionClient(), ["BTC"], config, future) is True

    runtime = LiveRuntime(config, _Exchange(), LiveStateStore(str(tmp_path / "pending.sqlite3")))
    runtime.setups["BTC"] = object()
    assert _should_full_poll(runtime, _NoPositionClient(), ["BTC"], config, future) is True

    runtime = LiveRuntime(config, _Exchange(), LiveStateStore(str(tmp_path / "position.sqlite3")))
    assert _should_full_poll(runtime, _PositionClient(), ["BTC"], config, future) is True

    runtime = LiveRuntime(config, _Exchange(), LiveStateStore(str(tmp_path / "order.sqlite3")))
    assert _should_full_poll(runtime, _OpenOrderClient(), ["BTC"], config, future) is True


def test_manual_close_archived_then_scheduler_returns_to_idle(tmp_path, monkeypatch):
    config = _live_config(tmp_path)
    runtime = LiveRuntime(config, _Exchange(), LiveStateStore(config.storage.sqlite_path))
    runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: _flat_features())

    _poll_once(runtime, _NoPositionClient(), ["BTC"], cli_allow_testnet_orders=False, dry_run=True)

    assert runtime.managed_trade("BTC") is None
    assert _next_poll_time_after_full_poll(runtime, _NoPositionClient(), ["BTC"], config) == _next_1h_wake_time(_NoPositionClient().now(), 10)


def test_idle_scheduler_disabled_keeps_full_poll_behavior(tmp_path):
    config = _live_config(tmp_path)
    config.execution.idle_1h_aligned_poll = False
    runtime = LiveRuntime(config, _Exchange(), LiveStateStore(config.storage.sqlite_path))

    assert _should_full_poll(runtime, _NoPositionClient(), ["BTC"], config, pd.Timestamp("2030-01-01 10:00:10Z")) is True


def test_recoverable_guard_error_after_full_poll_keeps_30s_poll(tmp_path):
    config = _live_config(tmp_path)
    runtime = LiveRuntime(config, _Exchange(), LiveStateStore(config.storage.sqlite_path))

    assert _next_poll_time_after_full_poll(runtime, _NetworkErrorClient(), ["BTC"], config) == pd.Timestamp("2026-01-01 09:15:30Z")


def test_poll_once_updates_existing_managed_trade_and_prints_observability(tmp_path, monkeypatch, capsys):
    config = _live_config(tmp_path)
    exchange = _Exchange()
    runtime = LiveRuntime(config, exchange, LiveStateStore(config.storage.sqlite_path))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.system_stop_order_id = "system-stop"
    runtime.store.update_trade(trade)
    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: _features())

    _poll_once(runtime, _Client(), ["BTC"], cli_allow_testnet_orders=False, dry_run=True)

    updated = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    output = capsys.readouterr().out
    assert updated.current_stop_loss == 120
    assert "stop moved 95.0 -> 120.0" in output
    assert "BTC managed position; waiting for trailing-stop update" not in output
    assert "latest_1h=" not in output
    assert "1h_close=" not in output
    assert "15m_rsi=" not in output
    assert "5m_close=" not in output
    assert "exchange_position=" not in output
    assert "2026-01-01 17:15:00+08:00" in output


def test_poll_once_updates_stop_from_completed_1h_not_forming_1h(tmp_path, monkeypatch):
    config = _live_config(tmp_path)
    exchange = _Exchange()
    runtime = LiveRuntime(config, exchange, LiveStateStore(config.storage.sqlite_path))
    runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: _features_with_forming_1h())

    _poll_once(runtime, _Client(), ["BTC"], cli_allow_testnet_orders=False, dry_run=True)

    updated = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    assert updated.current_stop_loss == 120


def test_poll_once_waits_when_completed_1h_is_missing(tmp_path, monkeypatch, capsys):
    config = _live_config(tmp_path)
    exchange = _Exchange()
    runtime = LiveRuntime(config, exchange, LiveStateStore(config.storage.sqlite_path))
    runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: _forming_1h_features())

    _poll_once(runtime, _Client(), ["BTC"], cli_allow_testnet_orders=False, dry_run=True)

    updated = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    output = capsys.readouterr().out
    assert updated.current_stop_loss == 95
    assert "BTC managed position; waiting for trailing-stop update" in output
    assert "stop moved" not in output


def test_poll_once_marks_special_adverse_slope_status(tmp_path, monkeypatch, capsys):
    config = _live_config(tmp_path)
    exchange = _Exchange()
    runtime = LiveRuntime(config, exchange, LiveStateStore(config.storage.sqlite_path))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.adverse_slope_tp_active = True
    trade.adverse_slope_tp_price = 999
    runtime.store.update_trade(trade)
    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: _forming_1h_features())

    _poll_once(runtime, _Client(), ["BTC"], cli_allow_testnet_orders=False, dry_run=True)

    output = capsys.readouterr().out
    assert "[SPECIAL] BTC managed position; waiting for trailing-stop update" in output


def test_poll_once_continues_when_stale_system_stop_cancel_is_missing(tmp_path, monkeypatch, capsys):
    config = _live_config(tmp_path)
    exchange = _MissingStopExchange()
    runtime = LiveRuntime(config, exchange, LiveStateStore(config.storage.sqlite_path))
    trade = runtime.store.create_trade(runtime.position_key("SOL", "short"), "SOL", "short", 1, 73.926, "strategy", 73.926)
    trade.system_stop_order_id = "55762129063"
    runtime.store.update_trade(trade)
    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: _flat_features())

    _poll_once(runtime, _NoPositionClient(), ["BTC", "ETH", "SOL"], cli_allow_testnet_orders=False, dry_run=False)

    output = capsys.readouterr().out
    assert "BTC waiting for 1h setup" in output
    assert "ETH waiting for 1h setup" in output
    assert "SOL exchange position disappeared; system stop cancelled and trade archived" in output
    assert runtime.store.open_trade(runtime.position_key("SOL", "short")) is None


def test_poll_once_does_not_update_stop_from_forming_5m(tmp_path, monkeypatch, capsys):
    config = _live_config(tmp_path)
    exchange = _Exchange()
    runtime = LiveRuntime(config, exchange, LiveStateStore(config.storage.sqlite_path))
    runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: _forming_stop_features())

    _poll_once(runtime, _FormingClient(), ["BTC"], cli_allow_testnet_orders=False, dry_run=True)

    updated = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    output = capsys.readouterr().out
    assert updated.current_stop_loss == 95
    assert "managed position; waiting for trailing-stop update" in output
    assert "stop moved" not in output


def test_poll_once_handles_naive_clock_with_aware_candles(tmp_path, monkeypatch, capsys):
    config = _live_config(tmp_path)
    runtime = LiveRuntime(config, _Exchange(), LiveStateStore(config.storage.sqlite_path))
    runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: _features())

    _poll_once(runtime, _NaiveClient(), ["BTC"], cli_allow_testnet_orders=False, dry_run=True)

    assert "2026-01-01 17:15:00+08:00" in capsys.readouterr().out


def test_poll_once_reuses_fetched_positions_for_strategy_guard(tmp_path, monkeypatch):
    config = _live_config(tmp_path)
    runtime = LiveRuntime(config, _Exchange(), LiveStateStore(config.storage.sqlite_path))
    client = _CountingNoPositionClient()
    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: _flat_features())

    _poll_once(runtime, client, ["BTC", "ETH"], cli_allow_testnet_orders=False, dry_run=True)

    assert client.position_calls == 1


def test_poll_once_passes_full_balance_to_strategy_entry(monkeypatch):
    captured = {}

    class Runtime:
        strategy_config = object()

        def can_place_orders(self, cli_allow_testnet_orders):
            return False

        def reconcile_symbol(self, symbol, positions, allow_orders, dry_run):
            return []

        def managed_trade(self, symbol):
            return None

        def maybe_open_strategy_trade(self, symbol, features_1h, features_15m, features_5m, balance, allow_orders, dry_run, exchange_positions=None):
            captured["balance"] = balance
            return []

    class BalanceClient(_NoPositionClient):
        def fetch_balance(self):
            return SimpleNamespace(equity=10000, available=1234)

    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: _flat_features())

    _poll_once(Runtime(), BalanceClient(), ["BTC"], cli_allow_testnet_orders=False, dry_run=True)

    assert captured["balance"].available == 1234


def _live_config(tmp_path):
    return main.__globals__["load_live_config"](_live_config_path(tmp_path))


def _live_config_path(tmp_path):
    data = yaml.safe_load(open("configs/live_hyperliquid_testnet.yaml", encoding="utf-8"))
    data["storage"]["sqlite_path"] = str(tmp_path / "live.sqlite3")
    path = tmp_path / "live.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _features():
    one_h = pd.DataFrame(
        [{"open": 100, "high": 121, "low": 90, "close": 95, "rsi14": 20, "lb": 80, "mb": 120, "ub": 160}],
        index=[pd.Timestamp("2026-01-01 08:00", tz="UTC")],
    )
    fifteen_m = pd.DataFrame(
        [{"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 25}],
        index=[pd.Timestamp("2026-01-01 09:00", tz="UTC")],
    )
    five_m = pd.DataFrame(
        [{"open": 100, "high": 140, "low": 125, "close": 130, "mb": 100}],
        index=[pd.Timestamp("2026-01-01 09:10", tz="UTC")],
    )
    return one_h, fifteen_m, five_m


def _features_with_forming_1h():
    one_h = pd.DataFrame(
        [
            {"open": 100, "high": 121, "low": 90, "close": 95, "rsi14": 20, "lb": 80, "mb": 120, "ub": 160},
            {"open": 100, "high": 151, "low": 90, "close": 145, "rsi14": 50, "lb": 80, "mb": 150, "ub": 180},
        ],
        index=[pd.Timestamp("2026-01-01 08:00", tz="UTC"), pd.Timestamp("2026-01-01 09:00", tz="UTC")],
    )
    _, fifteen_m, five_m = _features()
    return one_h, fifteen_m, five_m


def _forming_1h_features():
    one_h = pd.DataFrame(
        [{"open": 100, "high": 151, "low": 90, "close": 145, "rsi14": 50, "lb": 80, "mb": 150, "ub": 180}],
        index=[pd.Timestamp("2026-01-01 09:00", tz="UTC")],
    )
    _, fifteen_m, five_m = _features()
    return one_h, fifteen_m, five_m


def _flat_features():
    one_h = pd.DataFrame(
        [{"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 50, "lb": 80, "mb": 100, "ub": 120}],
        index=[pd.Timestamp("2026-01-01 08:00", tz="UTC")],
    )
    fifteen_m = pd.DataFrame(
        [{"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 50}],
        index=[pd.Timestamp("2026-01-01 09:00", tz="UTC")],
    )
    five_m = pd.DataFrame(
        [{"open": 100, "high": 101, "low": 99, "close": 100, "mb": 100}],
        index=[pd.Timestamp("2026-01-01 09:10", tz="UTC")],
    )
    return one_h, fifteen_m, five_m


def _forming_stop_features():
    one_h = pd.DataFrame(
        [{"open": 100, "high": 121, "low": 90, "close": 95, "rsi14": 20, "lb": 80, "mb": 120, "ub": 160}],
        index=[pd.Timestamp("2026-01-01 08:00", tz="UTC")],
    )
    fifteen_m = pd.DataFrame(
        [{"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 25}],
        index=[pd.Timestamp("2026-01-01 09:00", tz="UTC")],
    )
    five_m = pd.DataFrame(
        [
            {"open": 99, "high": 100, "low": 98, "close": 99, "mb": 100},
            {"open": 100, "high": 140, "low": 125, "close": 130, "mb": 100},
        ],
        index=[pd.Timestamp("2026-01-01 09:25", tz="UTC"), pd.Timestamp("2026-01-01 09:30", tz="UTC")],
    )
    return one_h, fifteen_m, five_m


class _Client:
    def __init__(self, *args, **kwargs):
        self._now = pd.Timestamp("2026-01-01 09:15", tz="UTC")
        self.open_order_calls = []
        self.ohlcv_calls = 0

    def now(self):
        return getattr(self, "_now", pd.Timestamp("2026-01-01 09:15", tz="UTC"))

    def fetch_balance(self):
        return SimpleNamespace(equity=10000)

    def fetch_positions(self):
        return [ExchangePosition("BTC", "long", 1, 100, 130)]

    def fetch_open_orders(self, symbol):
        self.open_order_calls.append(symbol)
        return []

    def get_market_price(self, symbol):
        return 130

    def fetch_ohlcv(self, symbol, timeframe, limit):
        self.ohlcv_calls += 1
        raise AssertionError("idle guard must not fetch OHLCV")


class _NoPositionClient(_Client):
    def fetch_positions(self):
        return []


class _PositionClient(_Client):
    def fetch_positions(self):
        return [ExchangePosition("BTC", "long", 1, 100, 101)]


class _OpenOrderClient(_NoPositionClient):
    def fetch_open_orders(self, symbol):
        self.open_order_calls.append(symbol)
        return [{"id": "open-order"}]


class _NetworkErrorClient(_NoPositionClient):
    def fetch_positions(self):
        raise TimeoutError("read timed out")


class _FormingClient(_Client):
    def now(self):
        return pd.Timestamp("2026-01-01 09:32", tz="UTC")


class _NaiveClient(_Client):
    def now(self):
        return pd.Timestamp("2026-01-01 09:15")


class _CountingNoPositionClient(_NoPositionClient):
    def __init__(self):
        super().__init__()
        self.position_calls = 0

    def fetch_positions(self):
        self.position_calls += 1
        return []


class _Exchange:
    def cancel_order(self, symbol, exchange_order_id):
        return None

    def create_reduce_only_stop(self, symbol, side, qty, stop_price):
        return {"id": "new-stop"}


class _MissingStopExchange(_Exchange):
    def cancel_order(self, symbol, exchange_order_id):
        raise OrderNotFound("Order was never placed, already canceled, or filled")


class OrderNotFound(Exception):
    pass
