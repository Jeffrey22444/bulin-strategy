from types import SimpleNamespace
import json
import inspect
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import pytest
import yaml

from bbmr.live.hyperliquid_client import AccountDataError, ExchangePosition, LiveBalance, MarketQuote
from bbmr.live.env import load_project_env
from bbmr.live.run import (
    _light_guard_detects_active_state,
    _live_runner_lock,
    _next_1h_wake_time,
    _next_poll_time_after_full_poll,
    _next_sleep_seconds,
    _poll_once,
    _should_full_poll,
    _wallet_fingerprint,
    _wallet_identity_lock,
    _simulation_config,
    main,
)
from bbmr.live.state_store import LiveStateStore, TrendPendingOrder
from bbmr.live.trailing_runtime import LiveRuntime


def test_mainnet_requires_cli_flag_even_when_config_allows(tmp_path, monkeypatch):
    data = yaml.safe_load(open("configs/live_hyperliquid_testnet.yaml", encoding="utf-8"))
    data["exchange"]["env"] = "mainnet"
    data["exchange"]["allow_mainnet"] = True
    path = tmp_path / "live_mainnet.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setattr("bbmr.live.run.load_project_env", lambda: None)

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


def test_dry_run_uses_isolated_store_lock_and_dashboard_namespace(tmp_path, monkeypatch):
    config_path = _live_config_path(tmp_path)
    config = _live_config(tmp_path)
    simulated = _simulation_config(config)

    monkeypatch.setenv("HYPERLIQUID_WALLET_ADDRESS", "wallet-a")
    monkeypatch.setattr("bbmr.live.run.load_project_env", lambda: None)
    monkeypatch.setattr("bbmr.live.run.missing_credential_names", lambda config: [])
    monkeypatch.setattr("bbmr.live.run.HyperliquidClient", _NoPositionClient)
    monkeypatch.setattr("bbmr.live.run._poll_once", lambda *args, **kwargs: None)

    assert main(["--live-config", str(config_path), "--once", "--dry-run"]) == 0

    assert not (tmp_path / "live.sqlite3").exists()
    assert not (tmp_path / "live_runner.lock").exists()
    assert not (tmp_path / "dashboard").exists()
    assert Path(simulated.storage.sqlite_path).is_file()
    assert (Path(simulated.storage.sqlite_path).parent / "live_runner.lock").is_file()
    assert (Path(simulated.storage.sqlite_path).parent / "dashboard" / "lifecycle.json").is_file()


def test_unhandled_runner_error_is_sanitized_and_persisted_then_reraised(tmp_path, monkeypatch):
    config_path = _live_config_path(tmp_path)
    captured = {}

    def fatal_runtime(config, client, store, account):
        captured["path"] = config.storage.sqlite_path
        raise RuntimeError("https://secret-endpoint.example/private")

    monkeypatch.setenv("HYPERLIQUID_WALLET_ADDRESS", "wallet-a")
    monkeypatch.setattr("bbmr.live.run.load_project_env", lambda: None)
    monkeypatch.setattr("bbmr.live.run.missing_credential_names", lambda config: [])
    monkeypatch.setattr("bbmr.live.run.HyperliquidClient", _NoPositionClient)
    monkeypatch.setattr("bbmr.live.run.LiveRuntime", fatal_runtime)

    with pytest.raises(RuntimeError, match="secret-endpoint"):
        main(["--live-config", str(config_path), "--once"])

    store = LiveStateStore(captured["path"])
    payload = json.loads(store.events()[-1]["payload_json"])
    assert store.events()[-1]["event_type"] == "runner_fatal"
    assert payload == {"reason": "unhandled RuntimeError", "severity": "CRITICAL"}
    assert "secret" not in json.dumps(payload)
    assert json.loads((Path(captured["path"]).parent / "dashboard" / "lifecycle.json").read_text())["status"] == "error"


def test_live_run_rejects_second_instance(tmp_path, monkeypatch):
    config_path = _live_config_path(tmp_path)

    monkeypatch.setattr("bbmr.live.run.load_project_env", lambda: None)
    monkeypatch.setattr("bbmr.live.run.missing_credential_names", lambda config: [])

    with _live_runner_lock(str(tmp_path / "live.sqlite3")):
        with pytest.raises(RuntimeError, match="live runner already running"):
            main(["--live-config", str(config_path), "--once"])


def test_wallet_fingerprint_is_environment_scoped_and_does_not_expose_wallet(tmp_path, monkeypatch):
    config = _live_config(tmp_path)
    monkeypatch.setenv("HYPERLIQUID_WALLET_ADDRESS", "wallet-a")
    first = _wallet_fingerprint(config)
    config.exchange.env = "mainnet"
    second = _wallet_fingerprint(config)

    assert len(first) == 64
    assert first != second
    assert "wallet" not in first


def test_wallet_identity_lock_is_independent_of_sqlite_path():
    with _wallet_identity_lock("a" * 64):
        with pytest.raises(RuntimeError, match="wallet identity"):
            with _wallet_identity_lock("a" * 64):
                pass
        with _wallet_identity_lock("b" * 64):
            pass


def test_identity_mismatch_blocks_before_client_construction(tmp_path, monkeypatch):
    config_path = _live_config_path(tmp_path)
    config = _live_config(tmp_path)
    monkeypatch.setenv("HYPERLIQUID_WALLET_ADDRESS", "wallet-a")
    LiveStateStore(
        config.storage.sqlite_path,
        identity_fingerprint=_wallet_fingerprint(config),
        environment=config.exchange.env,
    )
    monkeypatch.setenv("HYPERLIQUID_WALLET_ADDRESS", "wallet-b")
    monkeypatch.setattr("bbmr.live.run.load_project_env", lambda: None)
    monkeypatch.setattr("bbmr.live.run.missing_credential_names", lambda config: [])

    def client_must_not_construct(config):
        raise AssertionError("client must not construct after identity mismatch")

    monkeypatch.setattr("bbmr.live.run.HyperliquidClient", client_must_not_construct)
    with pytest.raises(RuntimeError, match="identity mismatch"):
        main(["--live-config", str(config_path), "--once"])


def test_main_locks_identity_then_database_before_opening_store(tmp_path, monkeypatch):
    config_path = _live_config_path(tmp_path)
    calls = []

    @contextmanager
    def identity_lock(fingerprint):
        calls.append("identity_lock")
        yield

    @contextmanager
    def database_lock(path):
        calls.append("database_lock")
        yield

    def store(path, **kwargs):
        calls.append("store")
        return SimpleNamespace()

    monkeypatch.setenv("HYPERLIQUID_WALLET_ADDRESS", "wallet-a")
    monkeypatch.setattr("bbmr.live.run.load_project_env", lambda: None)
    monkeypatch.setattr("bbmr.live.run.missing_credential_names", lambda config: [])
    monkeypatch.setattr("bbmr.live.run._wallet_identity_lock", identity_lock)
    monkeypatch.setattr("bbmr.live.run._live_runner_lock", database_lock)
    monkeypatch.setattr("bbmr.live.run.LiveStateStore", store)
    monkeypatch.setattr("bbmr.live.run._safe_dashboard", lambda callback: None)
    monkeypatch.setattr("bbmr.live.run._build_client", lambda *args: calls.append("client") or None)

    assert main(["--live-config", str(config_path), "--once"]) == 0
    assert calls == ["identity_lock", "database_lock", "store", "client"]


def test_cli_symbol_is_canonical_before_client_loop(tmp_path, monkeypatch):
    config_path = _live_config_path(tmp_path)
    captured = {}

    monkeypatch.setenv("HYPERLIQUID_WALLET_ADDRESS", "wallet-a")
    monkeypatch.setattr("bbmr.live.run.load_project_env", lambda: None)
    monkeypatch.setattr("bbmr.live.run.missing_credential_names", lambda config: [])
    monkeypatch.setattr("bbmr.live.run.LiveStateStore", lambda *args, **kwargs: SimpleNamespace())
    monkeypatch.setattr("bbmr.live.run._safe_dashboard", lambda callback: None)
    def capture_client_symbols(config, store, symbols):
        captured["symbols"] = symbols
        return None

    monkeypatch.setattr("bbmr.live.run._build_client", capture_client_symbols)

    assert main(["--live-config", str(config_path), "--symbol", "btcusdc", "--once"]) == 0
    assert captured["symbols"] == ["BTC"]


def test_cli_empty_symbol_is_rejected_before_store_or_client(tmp_path, monkeypatch):
    config_path = _live_config_path(tmp_path)
    constructed = []

    monkeypatch.setattr("bbmr.live.run.load_project_env", lambda: None)
    monkeypatch.setattr("bbmr.live.run.LiveStateStore", lambda *args, **kwargs: constructed.append("store"))
    monkeypatch.setattr("bbmr.live.run.HyperliquidClient", lambda *args, **kwargs: constructed.append("client"))

    with pytest.raises(ValueError, match="symbol cannot be empty"):
        main(["--live-config", str(config_path), "--symbol", "", "--once"])

    assert constructed == []


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


def test_live_run_continues_next_cycle_on_startup_request_timeout(tmp_path, monkeypatch, capsys):
    from ccxt.base.errors import RequestTimeout

    config_path = _live_config_path(tmp_path)

    class StartupTimeoutClient:
        def __init__(self, config):
            raise RequestTimeout("hyperliquid POST https://api.hyperliquid-testnet.xyz/info")

    monkeypatch.setattr("bbmr.live.run.load_project_env", lambda: None)
    monkeypatch.setattr("bbmr.live.run.missing_credential_names", lambda config: [])
    monkeypatch.setattr("bbmr.live.run.HyperliquidClient", StartupTimeoutClient)

    assert main(["--live-config", str(config_path), "--once"]) == 0

    output = capsys.readouterr().out
    assert "[WARN] live startup network error; waiting for next cycle" in output
    row = LiveStateStore(str(tmp_path / "live.sqlite3")).events()[-1]
    assert row["event_type"] == "recoverable_network_error"
    assert json.loads(row["payload_json"])["severity"] == "WARN"


def test_live_run_unknown_startup_error_still_raises(tmp_path, monkeypatch):
    config_path = _live_config_path(tmp_path)

    class BrokenStartupClient:
        def __init__(self, config):
            raise RuntimeError("bad startup state")

    monkeypatch.setattr("bbmr.live.run.load_project_env", lambda: None)
    monkeypatch.setattr("bbmr.live.run.missing_credential_names", lambda config: [])
    monkeypatch.setattr("bbmr.live.run.HyperliquidClient", BrokenStartupClient)

    with pytest.raises(RuntimeError, match="bad startup state"):
        main(["--live-config", str(config_path), "--once"])


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


def test_poll_once_continues_when_entry_open_order_check_times_out(tmp_path, monkeypatch, capsys):
    from ccxt.base.errors import RequestTimeout

    config = _live_config(tmp_path)

    class TimeoutOpenOrderClient(_NoPositionClient):
        def fetch_open_orders(self, symbol=None):
            raise RequestTimeout("hyperliquid POST https://api.hyperliquid-testnet.xyz/info")

    runtime = LiveRuntime(config, _Exchange(), LiveStateStore(config.storage.sqlite_path))
    runtime.exchange.now = lambda: pd.Timestamp("2026-01-01 09:15Z")
    runtime.strategy_config.bandwidth_entry_guard.percentile_lookback = 4
    one_h = pd.DataFrame(
        [{"open": 120, "high": 121, "low": 99, "close": 120, "rsi14": 50, "lb": 100, "mb": 120, "ub": 140}] * 3 + [{"open": 120, "high": 121, "low": 90, "close": 95, "rsi14": 20, "lb": 100, "mb": 120, "ub": 140}],
        index=pd.date_range(end="2026-01-01 08:00Z", periods=4, freq="h"),
    )
    five_m = pd.DataFrame(
        [{"open": 99, "high": 100, "low": 98, "close": 99, "mb": 100}, {"open": 104, "high": 106, "low": 103, "close": 105, "mb": 100}],
        index=[pd.Timestamp("2026-01-01 09:05Z"), pd.Timestamp("2026-01-01 09:10Z")],
    )
    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: (one_h, one_h, five_m))

    _poll_once(runtime, TimeoutOpenOrderClient(), ["BTC"], cli_allow_testnet_orders=False, dry_run=True)

    output = capsys.readouterr().out
    assert "[WARN] account open-order truth unavailable; new strategy entries blocked this cycle" in output
    row = next(row for row in runtime.store.events() if row["event_type"] == "recoverable_network_error")
    assert row["event_type"] == "recoverable_network_error"
    assert json.loads(row["payload_json"])["severity"] == "WARN"


def test_poll_once_feature_timeout_happens_before_state_changes(tmp_path, monkeypatch):
    config = _live_config(tmp_path)
    runtime = LiveRuntime(config, _Exchange(), LiveStateStore(config.storage.sqlite_path))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: (_ for _ in ()).throw(TimeoutError("read timed out")))

    _poll_once(runtime, _NoPositionClient(), ["BTC"], cli_allow_testnet_orders=False, dry_run=True)

    assert runtime.store.open_trade(runtime.position_key("BTC", "long")).internal_trade_id == trade.internal_trade_id


def test_poll_once_account_schema_error_stops_before_reconcile_or_entry_side_effects(tmp_path, monkeypatch):
    config = _live_config(tmp_path)
    cancelled = []

    class RecordingExchange(_Exchange):
        def cancel_order(self, symbol, exchange_order_id):
            cancelled.append((symbol, exchange_order_id))

    class InvalidPositionClient(_NoPositionClient):
        def fetch_positions(self):
            raise AccountDataError("invalid Hyperliquid position contracts")

    runtime = LiveRuntime(config, RecordingExchange(), LiveStateStore(config.storage.sqlite_path))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.system_stop_order_id = "system-stop"
    runtime.store.update_trade(trade)
    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda *args: pytest.fail("features must not be read after invalid account facts"))

    with pytest.raises(AccountDataError, match="invalid Hyperliquid position contracts"):
        _poll_once(runtime, InvalidPositionClient(), ["BTC"], cli_allow_testnet_orders=True, dry_run=False)

    assert runtime.store.open_trade(runtime.position_key("BTC", "long")).internal_trade_id == trade.internal_trade_id
    assert cancelled == []


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
    assert updated.current_stop_loss == 95
    assert updated.status == "entry_unprotected"
    assert "protective stop truth unknown" in output
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
    assert updated.current_stop_loss == 95
    assert updated.status == "entry_unprotected"


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
    assert "BTC managed position protection recovery pending" in output
    assert "stop moved" not in output


def test_poll_once_journals_bandwidth_without_terminal_output(tmp_path, monkeypatch, capsys):
    config = _live_config(tmp_path)
    runtime = LiveRuntime(config, _Exchange(), LiveStateStore(config.storage.sqlite_path))
    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: _features())

    _poll_once(runtime, _Client(), ["BTC"], cli_allow_testnet_orders=False, dry_run=True)
    _poll_once(runtime, _Client(), ["BTC"], cli_allow_testnet_orders=False, dry_run=True)

    output = capsys.readouterr().out
    observations = [row for row in runtime.store.events() if row["event_type"] == "bandwidth_state_observed"]
    assert "BandWidth bucket=" not in output
    assert len(observations) == 1
    assert json.loads(observations[0]["payload_json"])["label"] == "UNAVAILABLE"


def test_poll_once_marks_special_adverse_slope_status_for_manual_adopted(tmp_path, monkeypatch, capsys):
    config = _live_config(tmp_path)
    exchange = _Exchange()
    runtime = LiveRuntime(config, exchange, LiveStateStore(config.storage.sqlite_path))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "manual_adopted", 95)
    trade.adverse_slope_tp_active = True
    trade.adverse_slope_tp_price = 999
    runtime.store.update_trade(trade)
    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: _forming_1h_features())

    _poll_once(runtime, _Client(), ["BTC"], cli_allow_testnet_orders=False, dry_run=True)

    output = capsys.readouterr().out
    assert "BTC managed position protection recovery pending" in output


def test_poll_once_keeps_managed_trade_when_special_tp_market_price_times_out(tmp_path, monkeypatch, capsys):
    from ccxt.base.errors import RequestTimeout

    class MarketPriceTimeoutClient(_Client):
        def get_market_price(self, symbol):
            raise RequestTimeout("hyperliquid POST https://api.hyperliquid-testnet.xyz/info")

    config = _live_config(tmp_path)
    runtime = LiveRuntime(config, _Exchange(), LiveStateStore(config.storage.sqlite_path))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.system_stop_order_id = "system-stop"
    trade.adverse_slope_tp_active = True
    trade.adverse_slope_tp_price = 120
    runtime.store.update_trade(trade)
    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: _features() if symbol == "BTC" else _flat_features())
    monkeypatch.setattr(runtime, "maybe_close_adverse_slope_take_profit", lambda *args: pytest.fail("special TP close must not run after a price-read timeout"))

    _poll_once(runtime, MarketPriceTimeoutClient(), ["BTC", "ETH"], cli_allow_testnet_orders=False, dry_run=True)

    updated = runtime.store.open_trade(runtime.position_key("BTC", "long"))
    output = capsys.readouterr().out
    assert updated.adverse_slope_tp_active is True
    assert updated.adverse_slope_tp_price == 120
    assert updated.system_stop_order_id == "system-stop"
    assert updated.current_stop_loss == 95
    assert "BTC market-price network error; regime target check skipped; waiting for next cycle" not in output
    assert "ETH strategy entry blocked: protective-stop recovery active" in output
    assert "exit_archived" not in [row["event_type"] for row in runtime.store.events()]
    assert "BTC managed position protection recovery pending" in output


def test_poll_once_advances_waiting_takeover_to_reduce_only_close_before_trend_order(tmp_path, monkeypatch):
    class TakeoverExchange:
        def __init__(self):
            self.positions = [ExchangePosition("BTC", "short", 1, 120, 120)]
            self.orders = {"mr-stop": {"id": "mr-stop", "symbol": "BTC", "side": "buy", "amount": 1, "triggerPrice": 126, "reduceOnly": True, "status": "open"}}
            self.closes = []
            self.cancelled = []
            self.leverage_calls = []
            self.limit_entries = []

        def fetch_positions(self):
            return list(self.positions)

        def now(self):
            return pd.Timestamp("2030-01-01 10:15Z")

        def fetch_market_quote(self, symbol):
            return MarketQuote(118.5, 118.8, 118.65)

        def fetch_open_orders(self, symbol):
            return []

        def close_position_market(self, symbol, side, qty):
            self.closes.append((symbol, side, qty))
            self.positions = []
            return {"id": "takeover-close"}

        def cancel_order(self, symbol, order_id):
            self.cancelled.append((symbol, order_id))
            self.orders[order_id] = {"id": order_id, "status": "canceled"}

        def fetch_order(self, symbol, order_id, client_order_id=None):
            return self.orders[order_id]

        def format_qty(self, symbol, qty):
            return qty

        def format_price(self, symbol, price):
            return price

        def set_leverage(self, *args):
            self.leverage_calls.append(args)

        def create_limit_entry(self, *args):
            self.limit_entries.append(args)
            return {"id": "unexpected-trend-order"}

    class TakeoverClient(_Client):
        def __init__(self, exchange):
            super().__init__()
            self.exchange = exchange
            self._now = pd.Timestamp("2030-01-01 10:15Z")

        def fetch_balance(self):
            return LiveBalance(10000, 10000)

        def fetch_positions(self):
            return self.exchange.fetch_positions()

        def fetch_open_orders(self, symbol=None):
            return []

        def get_market_price(self, symbol):
            return 120

    exchange = TakeoverExchange()
    config = _live_config(tmp_path)
    runtime = LiveRuntime(config, exchange, LiveStateStore(config.storage.sqlite_path))
    runtime.trend_mode = runtime.takeover_mode = "live"
    mr = runtime.store.create_trade(runtime.position_key("BTC", "short"), "BTC", "short", 1, 120, "strategy", 126)
    mr.system_stop_order_id = "mr-stop"
    mr.protection_status = "protected"
    runtime.store.update_trade(mr)
    pending = TrendPendingOrder(
        "waiting", "BTC", "long", "live", "intent", pd.Timestamp("2030-01-01 09:00Z"),
        120, 119.28, 1, 120, 0.05, client_order_id="0x" + "1" * 32,
        expires_at=pd.Timestamp("2030-01-01 16:00Z"), takeover_phase="waiting_opposite_mr",
        takeover_trade_id=mr.internal_trade_id, takeover_side="short",
    )
    runtime.store.create_trend_pending(pending)
    features = _takeover_features()
    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: features)

    _poll_once(runtime, TakeoverClient(exchange), ["BTC"], cli_allow_testnet_orders=True, dry_run=False)

    terminal = runtime.store.trend_pending_for_episode("BTC", "long", pending.episode_bucket)
    assert exchange.closes == [("BTC", "short", 1)]
    assert exchange.cancelled == [("BTC", "mr-stop")]
    assert exchange.leverage_calls == exchange.limit_entries == []
    assert terminal.takeover_phase == "trend_entry_intent"


def test_poll_once_cancels_waiting_takeover_on_completed_middle_without_touch_mutation(tmp_path, monkeypatch):
    class TakeoverExchange:
        def __init__(self):
            self.positions = [ExchangePosition("BTC", "short", 1, 120, 120)]
            self.orders = {"mr-stop": {"id": "mr-stop", "symbol": "BTC", "side": "buy", "amount": 1, "triggerPrice": 126, "reduceOnly": True, "status": "open"}}
            self.closes = []
            self.cancelled = []
            self.leverage_calls = []
            self.limit_entries = []

        def fetch_positions(self):
            return list(self.positions)

        def now(self):
            return pd.Timestamp("2030-01-01 10:15Z")

        def fetch_market_quote(self, symbol):
            raise AssertionError("middle invalidation must precede fresh L2")

        def fetch_open_orders(self, symbol):
            return []

        def fetch_order(self, symbol, order_id, client_order_id=None):
            return self.orders[order_id]

        def format_qty(self, symbol, qty):
            return qty

        def format_price(self, symbol, price):
            return price

        def close_position_market(self, *args):
            self.closes.append(args)

        def cancel_order(self, *args):
            self.cancelled.append(args)

        def set_leverage(self, *args):
            self.leverage_calls.append(args)

        def create_limit_entry(self, *args):
            self.limit_entries.append(args)

    class TakeoverClient(_Client):
        def __init__(self, exchange):
            super().__init__()
            self.exchange = exchange
            self._now = pd.Timestamp("2030-01-01 10:15Z")

        def fetch_balance(self):
            return LiveBalance(10000, 10000)

        def fetch_positions(self):
            return self.exchange.fetch_positions()

        def fetch_open_orders(self, symbol=None):
            return []

        def get_market_price(self, symbol):
            return 120

    exchange = TakeoverExchange()
    config = _live_config(tmp_path)
    runtime = LiveRuntime(config, exchange, LiveStateStore(config.storage.sqlite_path))
    runtime.trend_mode = runtime.takeover_mode = "live"
    mr = runtime.store.create_trade(runtime.position_key("BTC", "short"), "BTC", "short", 1, 120, "strategy", 126)
    mr.system_stop_order_id = "mr-stop"
    mr.protection_status = "protected"
    runtime.store.update_trade(mr)
    pending = TrendPendingOrder(
        "waiting", "BTC", "long", "live", "intent", pd.Timestamp("2030-01-01 09:00Z"),
        120, 119.28, 1, 120, 0.05, expires_at=pd.Timestamp("2030-01-01 16:00Z"),
        takeover_phase="waiting_opposite_mr", takeover_trade_id=mr.internal_trade_id, takeover_side="short",
    )
    runtime.store.create_trend_pending(pending)
    features = _takeover_features(close=101)
    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: features)

    _poll_once(runtime, TakeoverClient(exchange), ["BTC"], cli_allow_testnet_orders=True, dry_run=False)

    terminal = runtime.store.trend_pending_for_episode("BTC", "long", pending.episode_bucket)
    restored_mr = runtime.store.open_trade(mr.exchange_position_key)
    assert terminal.status == "canceled" and terminal.cancel_reason == "completed_1h_middle_invalidated"
    assert restored_mr is not None and restored_mr.system_stop_order_id == "mr-stop"
    assert exchange.closes == exchange.cancelled == exchange.leverage_calls == exchange.limit_entries == []


def test_poll_once_reraises_unknown_special_tp_market_price_error(tmp_path, monkeypatch):
    class BrokenMarketPriceClient(_Client):
        def get_market_price(self, symbol):
            raise RuntimeError("bad price state")

    config = _live_config(tmp_path)
    runtime = LiveRuntime(config, _Exchange(), LiveStateStore(config.storage.sqlite_path))
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.adverse_slope_tp_active = True
    trade.adverse_slope_tp_price = 120
    runtime.store.update_trade(trade)
    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: _features())

    _poll_once(runtime, BrokenMarketPriceClient(), ["BTC"], cli_allow_testnet_orders=False, dry_run=True)


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
    assert "BTC managed position protection recovery pending" in output
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

        def observe_bandwidth_state(self, symbol, features_1h):
            return None

        def update_shadow_outcomes(self, symbol, features_5m):
            return None

        def trend_poll(self, symbol, features_1h, features_5m, balance, positions):
            return None

        def maybe_open_trend_trade(self, symbol, features_1h, features_5m, balance, allow_orders, dry_run, positions, account_orders):
            return None

        def record_trend_mr_outcome(self, symbol, events):
            return None

        def record_management_trace(self, symbol):
            return None

        def consume_account_mutation(self):
            return False

        def trend_active(self, symbol):
            return False

        def maybe_open_strategy_trade(self, symbol, features_1h, features_15m, features_5m, balance, allow_orders, dry_run, exchange_positions=None, account_orders=None, account_orders_verified=False):
            captured["balance"] = balance
            return []

    class BalanceClient(_NoPositionClient):
        def fetch_balance(self):
            return SimpleNamespace(equity=10000, available=1234)

    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: _flat_features())

    _poll_once(Runtime(), BalanceClient(), ["BTC"], cli_allow_testnet_orders=False, dry_run=True)

    assert captured["balance"].available == 1234


def test_poll_once_requires_runtime_observation_interface(monkeypatch):
    class IncompleteRuntime:
        strategy_config = object()

        def can_place_orders(self, cli_allow_testnet_orders):
            return False

    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: _flat_features())

    with pytest.raises(AttributeError, match="observe_bandwidth_state"):
        _poll_once(IncompleteRuntime(), _NoPositionClient(), ["BTC"], cli_allow_testnet_orders=False, dry_run=True)


def test_runner_uses_the_complete_required_runtime_interface():
    import bbmr.live.run as run

    source = inspect.getsource(run._poll_once) + inspect.getsource(run._next_poll_time_after_full_poll)
    for method in (
        "observe_bandwidth_state",
        "update_shadow_outcomes",
        "trend_poll",
        "record_management_trace",
        "maybe_open_trend_trade",
        "consume_account_mutation",
        "record_trend_mr_outcome",
        "trend_active",
    ):
        assert f"runtime.{method}(" in source
        assert f'getattr(runtime, "{method}"' not in source


def test_poll_once_blocks_later_symbol_when_post_mutation_refresh_fails(tmp_path, monkeypatch, capsys):
    captured = []

    class Runtime:
        strategy_config = object()

        def __init__(self):
            self.store = LiveStateStore(str(tmp_path / "live.sqlite3"))
            self.calls = 0

        def can_place_orders(self, _flag):
            return True

        def reconcile_symbol(self, symbol, positions, allow_orders, dry_run):
            return []

        def managed_trade(self, symbol):
            return None

        def observe_bandwidth_state(self, symbol, features_1h):
            return None

        def update_shadow_outcomes(self, symbol, features_5m):
            return None

        def trend_poll(self, symbol, features_1h, features_5m, balance, positions):
            return None

        def maybe_open_trend_trade(self, symbol, features_1h, features_5m, balance, allow_orders, dry_run, positions, account_orders):
            return None

        def record_trend_mr_outcome(self, symbol, events):
            return None

        def record_management_trace(self, symbol):
            return None

        def maybe_open_strategy_trade(self, symbol, *args, account_orders=None, account_orders_verified=False, **kwargs):
            self.calls += 1
            captured.append((symbol, account_orders, account_orders_verified))
            return [f"{symbol} intent changed"]

        def consume_account_mutation(self):
            return self.calls == 1

        def trend_active(self, symbol):
            return False

    class Client:
        def __init__(self):
            self.position_reads = 0

        def now(self):
            return pd.Timestamp("2026-01-01 09:15Z")

        def fetch_balance(self):
            return SimpleNamespace(equity=10000, available=1000)

        def fetch_positions(self):
            self.position_reads += 1
            if self.position_reads > 1:
                raise TimeoutError("refresh timeout")
            return []

        def fetch_open_orders(self, symbol=None):
            return []

    monkeypatch.setattr("bbmr.live.run.latest_completed_features", lambda client, symbol, strategy_config: _flat_features())

    _poll_once(Runtime(), Client(), ["BTC", "ETH"], cli_allow_testnet_orders=True, dry_run=False)

    assert captured == [("BTC", [], True), ("ETH", None, True)]
    assert "account refresh unavailable after order-state mutation; later strategy entries blocked this cycle" in capsys.readouterr().out


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


def _takeover_features(close=120):
    index = pd.date_range(end=pd.Timestamp("2030-01-01 09:00Z"), periods=4, freq="h")
    one_h = pd.DataFrame(
        [{"open": 100, "high": 121, "low": 99, "close": 120, "lb": 90, "mb": 100, "ub": 130, "rsi14": 50} for _ in index],
        index=index,
    )
    one_h.iloc[-1, one_h.columns.get_loc("mb")] = 101
    one_h.iloc[-1, one_h.columns.get_loc("close")] = close
    fifteen_m = pd.DataFrame(
        [{"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 50}],
        index=[pd.Timestamp("2030-01-01 10:00Z")],
    )
    five_m = pd.DataFrame(
        [{"open": 120, "high": 120, "low": 118, "close": 119, "mb": 101}],
        index=[pd.Timestamp("2030-01-01 10:10Z")],
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
