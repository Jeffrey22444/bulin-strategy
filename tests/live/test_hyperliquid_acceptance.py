import sys

from bbmr.live.hyperliquid_client import ExchangePosition
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


def test_acceptance_refuses_existing_position_before_orders(monkeypatch, capsys):
    monkeypatch.setenv("HYPERLIQUID_WALLET_ADDRESS", "wallet")
    monkeypatch.setenv("HYPERLIQUID_PRIVATE_KEY", "private")
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
