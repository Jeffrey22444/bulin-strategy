import pandas as pd
import pytest

from bbmr.config import load_config
from bbmr.trailing_features import build_trailing_features
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
    assert "candle_open_at_utc=" in output
    assert "candle_open_at_beijing=" in output
    assert "completed_at_utc=" in output
    assert "completed_at_beijing=" in output
    assert "close=" in output
    assert "rsi=" in output


class FiveMinuteClient:
    def __init__(self, frame):
        self.frame = frame

    def fetch_ohlcv(self, symbol, timeframe, limit):
        assert (symbol, timeframe, limit) == ("BTC", "5m", 500)
        return self.frame

    def now(self):
        return self.frame.index[-1] + pd.Timedelta("5m")


def test_calibration_rows_match_live_builder_5m_rsi_for_same_ohlcv():
    config = load_config("configs/strategy_bbmr_trailing_stop_v1.yaml")
    index = pd.date_range("2030-01-01", periods=500, freq="5min", tz="UTC")
    close = [100 + (position % 2) for position in range(497)] + [100, 101, 103]
    frame = pd.DataFrame(
        {"open": close, "high": [value + 1 for value in close], "low": [value - 1 for value in close], "close": close, "volume": 1},
        index=index,
    )

    calibration_rows = hyperliquid_rsi_calibration.completed_rsi_rows(FiveMinuteClient(frame), config, "BTC", "5m", 5)
    live_rows = build_trailing_features(frame, frame, frame, config)[2].dropna(subset=["rsi14"]).tail(5)

    assert len(calibration_rows) == len(live_rows) == 5
    for (candle_open_at, completed_at, close_value, rsi_value), (live_open_at, live_row) in zip(
        calibration_rows, live_rows.iterrows(), strict=True
    ):
        assert candle_open_at == live_open_at
        assert completed_at == live_open_at + pd.Timedelta("5m")
        assert close_value == live_row.close
        assert rsi_value == pytest.approx(live_row.rsi14)
