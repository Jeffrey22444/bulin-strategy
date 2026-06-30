import pandas as pd

from bbmr.indicators import compute_bollinger, compute_rsi


def build_trailing_features(
    ohlcv_1h: pd.DataFrame, ohlcv_15m: pd.DataFrame, ohlcv_5m: pd.DataFrame, config
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    features_1h = ohlcv_1h.copy()
    features_1h = features_1h.join(
        compute_bollinger(features_1h["close"], config.bollinger.bb_period, config.bollinger.bb_std_mult)
    )
    features_1h["rsi14"] = compute_rsi(features_1h["close"], config.rsi.period)

    features_15m = ohlcv_15m.copy()
    features_15m["rsi14"] = compute_rsi(features_15m["close"], config.rsi.period)

    features_5m = ohlcv_5m.copy()
    features_5m = features_5m.join(
        compute_bollinger(features_5m["close"], config.bollinger.bb_period, config.bollinger.bb_std_mult)
    )
    return features_1h, features_15m, features_5m
