from pathlib import Path

import pandas as pd


OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    missing = [column for column in OHLCV_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"missing OHLCV columns: {missing}")

    frame = frame[OHLCV_COLUMNS].copy()
    frame["timestamp"] = _parse_timestamp(frame["timestamp"])
    if frame["timestamp"].duplicated().any():
        raise ValueError("duplicate timestamps")
    frame = frame.set_index("timestamp")
    if not frame.index.is_monotonic_increasing:
        raise ValueError("timestamps must be monotonic increasing")

    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame.isna().any().any():
        raise ValueError("OHLCV values must be numeric and non-NaN")
    if (frame["high"] < frame[["open", "close"]].max(axis=1)).any():
        raise ValueError("high must be >= max(open, close)")
    if (frame["low"] > frame[["open", "close"]].min(axis=1)).any():
        raise ValueError("low must be <= min(open, close)")
    if (frame["volume"] < 0).any():
        raise ValueError("volume must be >= 0")
    return frame


def _parse_timestamp(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().all():
        return pd.to_datetime(numeric, unit="s", utc=True)
    return pd.to_datetime(values, utc=True)


def load_symbol_ohlcv(data_dir: str | Path, symbol: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    root = Path(data_dir)
    paths = [root / f"{symbol}_{timeframe}.csv" for timeframe in ("1h", "15m", "5m")]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing timeframe files: {missing}")
    return tuple(load_ohlcv_csv(path) for path in paths)
