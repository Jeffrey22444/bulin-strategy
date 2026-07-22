import sys

from bbmr.live.hyperliquid_client import ExchangePosition, LiveBalance
from bbmr.live.env import load_project_env
from scripts import hyperliquid_acceptance


class FakeAcceptanceClient:
    def __init__(self, config):
        self.config = config
        self.touched_orders = False

    def fetch_positions(self):
        return [ExchangePosition("BTC", "long", 1, 100, 100)]

    def fetch_open_orders(self, symbol):
        self.touched_orders = True
        return []


class CleanupClient(FakeAcceptanceClient):
    def __init__(self, config, *, fail_stop=False, fail_close=False):
        super().__init__(config)
        self.positions = []
        self.fail_stop = fail_stop
        self.fail_close = fail_close
        self.actions = []

    def fetch_positions(self):
        return list(self.positions)

    def fetch_balance(self):
        return LiveBalance(100, 100)

    def get_market_price(self, symbol):
        return 100

    def format_qty(self, symbol, qty):
        return qty

    def set_leverage(self, symbol, leverage, margin_mode):
        self.actions.append("leverage")

    def create_market_entry(self, symbol, side, qty):
        self.actions.append("entry")
        self.positions = [ExchangePosition(symbol, side, qty, 100, 100)]
        return {"id": "entry"}

    def create_reduce_only_stop(self, symbol, side, qty, stop_price):
        self.actions.append("stop")
        if self.fail_stop:
            raise RuntimeError("stop failed")
        return {"id": "owned-stop"}

    def close_position_market(self, symbol, side, qty):
        self.actions.append("close")
        if self.fail_close:
            raise RuntimeError("close failed")
        self.positions = []
        return {"id": "close"}

    def cancel_order(self, symbol, order_id):
        self.actions.append(("cancel", order_id))


def test_acceptance_refuses_existing_position_before_orders(monkeypatch, capsys):
    monkeypatch.setenv("HYPERLIQUID_WALLET_ADDRESS", "wallet")
    monkeypatch.setenv("HYPERLIQUID_PRIVATE_KEY", "private")
    monkeypatch.setattr(hyperliquid_acceptance, "load_project_env", lambda: None)
    monkeypatch.setattr(hyperliquid_acceptance, "HyperliquidClient", FakeAcceptanceClient)
    monkeypatch.setattr(sys, "argv", ["hyperliquid_acceptance.py", "--symbol", "BTC", "--notional-usd", "20"])

    assert hyperliquid_acceptance.main() == 1
    assert "already has a position" in capsys.readouterr().err


def test_acceptance_loads_credentials_from_env_file(tmp_path, monkeypatch, capsys):
    env_path = tmp_path / ".env"
    env_path.write_text("HYPERLIQUID_WALLET_ADDRESS=env-wallet\nHYPERLIQUID_PRIVATE_KEY=env-private\n", encoding="utf-8")
    captured = {}

    class CapturingClient(FakeAcceptanceClient):
        def __init__(self, config):
            captured["wallet"] = __import__("os").environ.get("HYPERLIQUID_WALLET_ADDRESS")
            captured["private"] = __import__("os").environ.get("HYPERLIQUID_PRIVATE_KEY")

    monkeypatch.delenv("HYPERLIQUID_WALLET_ADDRESS", raising=False)
    monkeypatch.delenv("HYPERLIQUID_PRIVATE_KEY", raising=False)
    monkeypatch.setattr(hyperliquid_acceptance, "load_project_env", lambda: load_project_env(env_path))
    monkeypatch.setattr(hyperliquid_acceptance, "HyperliquidClient", CapturingClient)
    monkeypatch.setattr(sys, "argv", ["hyperliquid_acceptance.py", "--symbol", "BTC", "--notional-usd", "20"])

    assert hyperliquid_acceptance.main() == 1
    output = capsys.readouterr()
    assert captured == {"wallet": "env-wallet", "private": "env-private"}
    assert "env-wallet" not in output.out + output.err
    assert "env-private" not in output.out + output.err


def test_acceptance_confirms_zero_before_cancelling_its_owned_stop(monkeypatch, capsys):
    client = CleanupClient(None)
    monkeypatch.setattr(hyperliquid_acceptance, "load_project_env", lambda: None)
    monkeypatch.setattr(hyperliquid_acceptance, "missing_credential_names", lambda config: [])
    monkeypatch.setattr(hyperliquid_acceptance, "HyperliquidClient", lambda config: client)

    assert hyperliquid_acceptance.main(["--symbol", "BTC", "--notional-usd", "20"]) == 0

    assert client.positions == []
    assert client.actions == ["leverage", "entry", "stop", "close", ("cancel", "owned-stop")]
    assert "passed" in capsys.readouterr().out


def test_acceptance_close_failure_retains_owned_stop_and_returns_manual_action(monkeypatch, capsys):
    client = CleanupClient(None, fail_close=True)
    monkeypatch.setattr(hyperliquid_acceptance, "load_project_env", lambda: None)
    monkeypatch.setattr(hyperliquid_acceptance, "missing_credential_names", lambda config: [])
    monkeypatch.setattr(hyperliquid_acceptance, "HyperliquidClient", lambda config: client)

    assert hyperliquid_acceptance.main(["--symbol", "BTC", "--notional-usd", "20"]) == 1

    assert client.positions
    assert ("cancel", "owned-stop") not in client.actions
    assert "manual cleanup required" in capsys.readouterr().err


def test_acceptance_stop_creation_failure_attempts_safe_close_but_never_reports_pass(monkeypatch, capsys):
    client = CleanupClient(None, fail_stop=True)
    monkeypatch.setattr(hyperliquid_acceptance, "load_project_env", lambda: None)
    monkeypatch.setattr(hyperliquid_acceptance, "missing_credential_names", lambda config: [])
    monkeypatch.setattr(hyperliquid_acceptance, "HyperliquidClient", lambda config: client)

    assert hyperliquid_acceptance.main(["--symbol", "BTC", "--notional-usd", "20"]) == 1

    assert client.positions == []
    assert client.actions == ["leverage", "entry", "stop", "close"]
    assert "stop failed" in capsys.readouterr().err
