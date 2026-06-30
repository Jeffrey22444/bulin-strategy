from pathlib import Path

import pytest

from bbmr.backtest.data import load_ohlcv_csv


def _write(path: Path, rows: list[str]) -> Path:
    path.write_text("timestamp,open,high,low,close,volume\n" + "\n".join(rows), encoding="utf-8")
    return path


def test_csv_loader_validates_required_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("timestamp,open,high,low,close\n2026-01-01T00:00:00Z,1,2,1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing"):
        load_ohlcv_csv(path)


def test_csv_loader_rejects_duplicate_timestamp(tmp_path):
    path = _write(
        tmp_path / "dup.csv",
        [
            "2026-01-01T00:00:00Z,1,2,1,2,10",
            "2026-01-01T00:00:00Z,1,2,1,2,10",
        ],
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_ohlcv_csv(path)


def test_csv_loader_rejects_invalid_ohlc(tmp_path):
    path = _write(tmp_path / "bad_ohlc.csv", ["2026-01-01T00:00:00Z,1,1,1,2,10"])
    with pytest.raises(ValueError, match="high"):
        load_ohlcv_csv(path)


def test_csv_loader_returns_utc_datetime_index():
    frame = load_ohlcv_csv("tests/fixtures/ohlcv/BTC_5m.csv")
    assert str(frame.index.tz) == "UTC"
    assert frame.index.is_monotonic_increasing


def test_csv_loader_keeps_iso_timestamp_support(tmp_path):
    path = _write(tmp_path / "iso.csv", ["2024-01-01T00:00:00Z,1,2,1,2,10"])
    frame = load_ohlcv_csv(path)
    assert frame.index[0].isoformat() == "2024-01-01T00:00:00+00:00"


def test_csv_loader_accepts_unix_seconds_timestamp(tmp_path):
    path = _write(tmp_path / "unix.csv", ["1704067200,1,2,1,2,10"])
    frame = load_ohlcv_csv(path)
    assert frame.index[0].isoformat() == "2024-01-01T00:00:00+00:00"


def test_csv_loader_rejects_duplicate_unix_seconds_timestamp(tmp_path):
    path = _write(
        tmp_path / "unix_dup.csv",
        [
            "1704067200,1,2,1,2,10",
            "1704067200,1,2,1,2,10",
        ],
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_ohlcv_csv(path)
