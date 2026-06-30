from bbmr.live.env import load_project_env


def test_env_loader_parses_basic_values_and_preserves_exported(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(
        "# local credentials\nHYPERLIQUID_WALLET_ADDRESS='env-wallet'\nHYPERLIQUID_PRIVATE_KEY=env-private\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HYPERLIQUID_PRIVATE_KEY", "export-private")
    monkeypatch.delenv("HYPERLIQUID_WALLET_ADDRESS", raising=False)

    load_project_env(path)

    assert __import__("os").environ["HYPERLIQUID_WALLET_ADDRESS"] == "env-wallet"
    assert __import__("os").environ["HYPERLIQUID_PRIVATE_KEY"] == "export-private"
