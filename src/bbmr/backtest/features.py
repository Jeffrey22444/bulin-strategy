import pandas as pd

from bbmr.exit_rules import early_fail_long, early_fail_short, soft_fail_long, soft_fail_short
from bbmr.indicators import (
    compute_atr,
    compute_bollinger,
    compute_bw_percentile,
    compute_mb_slope,
    compute_rsi,
    compute_volume_ratio,
)
from bbmr.market_state import compute_market_state
from bbmr.signals import compute_signals


def build_1h_features(ohlcv_1h: pd.DataFrame, config) -> pd.DataFrame:
    features = ohlcv_1h.copy()
    bollinger = compute_bollinger(features["close"], config.bollinger.bb_period, config.bollinger.bb_std_mult)
    features = features.join(bollinger)
    features["bw_percentile"] = compute_bw_percentile(features["bw"], config.bollinger.bandwidth_lookback)
    features["rsi14"] = compute_rsi(features["close"], config.rsi.period)
    features["atr"] = compute_atr(features["high"], features["low"], features["close"], config.atr.period)
    features["volume_ratio"] = compute_volume_ratio(features["volume"], config.volume.ma_period)
    features["mb_slope_pct"] = compute_mb_slope(features["mb"], config.middle_band_slope.slope_n)

    state = compute_market_state(features, config)
    features = features.join(state.drop(columns=["mb_slope_pct"]))
    signals = compute_signals(features, config)
    features = features.join(signals)

    features["soft_fail_long"] = soft_fail_long(features["close"], features["lb"], config.soft_fail.bars)
    features["soft_fail_short"] = soft_fail_short(features["close"], features["ub"], config.soft_fail.bars)
    features["early_fail_long"] = early_fail_long(
        features["soft_fail_long"],
        features["bw_percentile"],
        features["volume_ratio"],
        features["lower_band_walking"],
        config,
    )
    features["early_fail_short"] = early_fail_short(
        features["soft_fail_short"],
        features["bw_percentile"],
        features["volume_ratio"],
        features["upper_band_walking"],
        config,
    )
    features["soft_fail"] = features["soft_fail_long"] | features["soft_fail_short"]
    features["early_fail"] = features["early_fail_long"] | features["early_fail_short"]
    return features
