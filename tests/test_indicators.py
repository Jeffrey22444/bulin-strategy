import numpy as np
import pandas as pd
import pytest

from bbmr.indicators import (
    compute_atr,
    compute_bollinger,
    compute_bw_percentile,
    compute_mb_slope,
    compute_rsi,
    compute_volume_ratio,
)


def test_bollinger_preserves_index_and_warmup_is_nan():
    close = pd.Series(range(1, 6), index=pd.date_range("2026-01-01", periods=5))
    result = compute_bollinger(close, period=3, mult=2)
    assert result.index.equals(close.index)
    assert result["mb"].iloc[:2].isna().all()
    assert result["mb"].iloc[2] == 2


def test_bollinger_does_not_use_future_data():
    close = pd.Series([1.0, 2.0, 3.0, 1000.0])
    original = compute_bollinger(close, period=3, mult=2)
    changed_future = compute_bollinger(pd.Series([1.0, 2.0, 3.0, -1000.0]), period=3, mult=2)
    assert original.loc[2, "mb"] == changed_future.loc[2, "mb"]


def test_bw_percentile_uses_only_rolling_window():
    bw = pd.Series([1.0, 100.0, 2.0, 3.0])
    result = compute_bw_percentile(bw, lookback=3)
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == pytest.approx(200 / 3)
    assert result.iloc[3] == pytest.approx(200 / 3)


def test_rsi_atr_volume_ratio_and_mb_slope_preserve_index():
    index = pd.date_range("2026-01-01", periods=20)
    close = pd.Series(range(20), index=index, dtype=float)
    high = close + 1
    low = close - 1
    volume = pd.Series(range(1, 21), index=index, dtype=float)
    mb = close.rolling(3).mean()

    assert compute_rsi(close, 14).index.equals(index)
    assert compute_atr(high, low, close, 14).index.equals(index)
    assert compute_volume_ratio(volume, 3).index.equals(index)
    slope = compute_mb_slope(mb, 3)
    assert slope.index.equals(index)
    assert slope.iloc[:5].isna().all()
