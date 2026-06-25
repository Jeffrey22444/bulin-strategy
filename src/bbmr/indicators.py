import numpy as np
import pandas as pd


def compute_bollinger(close: pd.Series, period: int, mult: float) -> pd.DataFrame:
    mb = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    ub = mb + std * mult
    lb = mb - std * mult
    bw = (ub - lb) / mb
    return pd.DataFrame({"mb": mb, "ub": ub, "lb": lb, "bw": bw}, index=close.index)


def compute_bw_percentile(bw: pd.Series, lookback: int) -> pd.Series:
    def percentile(window: pd.Series) -> float:
        current = window.iloc[-1]
        return float((window <= current).sum() / len(window) * 100)

    return bw.rolling(lookback).apply(percentile, raw=False)


def compute_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    true_range.iloc[0] = np.nan
    return true_range.rolling(period).mean()


def compute_volume_ratio(volume: pd.Series, ma_period: int) -> pd.Series:
    return volume / volume.rolling(ma_period).mean()


def compute_mb_slope(mb: pd.Series, slope_n: int) -> pd.Series:
    return (mb / mb.shift(slope_n) - 1).abs()
