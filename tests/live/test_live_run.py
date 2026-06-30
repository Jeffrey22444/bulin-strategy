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
    assert "latest_1h=2026-01-01 09:00:00+00:00" in output
    assert "latest_15m=2026-01-01 09:15:00+00:00" in output
    assert "latest_5m=2026-01-01 09:15:00+00:00" in output
    assert "1h_close=95.0" in output
    assert "1h_rsi=20.0" in output
    assert "1h_lb=80.0" in output
    assert "1h_mb=120.0" in output
    assert "1h_ub=160.0" in output
    assert "15m_rsi=25.0" in output
    assert "5m_close=130.0" in output
    assert "5m_high=140.0" in output
    assert "5m_low=125.0" in output
    assert "exchange_position=" in output
    assert "local_trade=open" in output


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
    assert "BTC poll" in output
    assert "ETH poll" in output
    assert "SOL exchange position disappeared; system stop cancelled and trade archived" in output
    assert runtime.store.open_trade(runtime.position_key("SOL", "short")) is None


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
