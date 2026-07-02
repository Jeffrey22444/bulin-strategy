from types import SimpleNamespace

import pandas as pd
import pytest
import yaml

from bbmr.live.hyperliquid_client import ExchangePosition
from bbmr.live.env import load_project_env
from bbmr.live.run import _poll_once, main
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
    assert "2026-01-01 17:15:00+08:00 live poll network error; waiting for next cycle" in output


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
    assert "2026-01-01 17:15:00+08:00 live poll network error; waiting for next cycle" in output


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
        pass

    def now(self):
        return pd.Timestamp("2026-01-01 09:15", tz="UTC")

    def fetch_balance(self):
        return SimpleNamespace(equity=10000)

    def fetch_positions(self):
        return [ExchangePosition("BTC", "long", 1, 100, 130)]


class _NoPositionClient(_Client):
    def fetch_positions(self):
        return []


class _FormingClient(_Client):
    def now(self):
        return pd.Timestamp("2026-01-01 09:32", tz="UTC")


class _NaiveClient(_Client):
    def now(self):
        return pd.Timestamp("2026-01-01 09:15")


class _CountingNoPositionClient(_NoPositionClient):
    def __init__(self):
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
