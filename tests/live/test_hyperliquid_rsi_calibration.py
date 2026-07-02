import pandas as pd

from scripts import hyperliquid_rsi_calibration


class FakeClient:
    def __init__(self, config):
        self.config = config

    def fetch_ohlcv(self, symbol, timeframe, limit):
        assert (symbol, timeframe, limit) == ("BTC", "15m", 500)
        return pd.DataFrame(
            {
                "open": range(20),
                "high": range(20),
                "low": range(20),
                "close": [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64],
                "volume": range(20),
            },
            index=pd.date_range("2026-01-01", periods=20, freq="15min", tz="UTC"),
        )

    def now(self):
        return pd.Timestamp("2026-01-01 05:00Z")


def test_rsi_calibration_script_prints_fake_client_output(monkeypatch, capsys):
    monkeypatch.setattr(hyperliquid_rsi_calibration, "load_project_env", lambda: None)
    monkeypatch.setattr(hyperliquid_rsi_calibration, "missing_credential_names", lambda config: [])
    monkeypatch.setattr(hyperliquid_rsi_calibration, "HyperliquidClient", FakeClient)

    assert hyperliquid_rsi_calibration.main(["--symbol", "BTC", "--timeframe", "15m", "--count", "1"]) == 0

    output = capsys.readouterr().out
    assert "source=hyperliquid-testnet symbol=BTC timeframe=15m method=wilder period=14 warmup_bars=500" in output
    assert "rsi=" in output
