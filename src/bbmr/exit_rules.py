import pandas as pd


def fixed_sl_triggered(side: str, low_5m: float, high_5m: float, fixed_sl: float) -> bool:
    return low_5m <= fixed_sl if side == "long" else high_5m >= fixed_sl


def take_profit_price(side: str, current_mb: float, current_lb: float, current_ub: float, tp_mid_frac: float) -> float:
    if side == "long":
        return current_mb + (current_ub - current_mb) * tp_mid_frac
    return current_mb - (current_mb - current_lb) * tp_mid_frac


def take_profit_triggered(side: str, high_5m: float, low_5m: float, tp_price: float) -> bool:
    return high_5m >= tp_price if side == "long" else low_5m <= tp_price


def added_take_profit_price(side: str, current_mb: float, weighted_avg_entry: float, one_r: float, min_profit_r_after_add: float) -> float:
    buffer = one_r * min_profit_r_after_add
    if side == "long":
        return max(current_mb, weighted_avg_entry + buffer)
    return min(current_mb, weighted_avg_entry - buffer)


def soft_fail_long(close_1h: pd.Series, current_lb: pd.Series, bars: int) -> pd.Series:
    return ((close_1h < current_lb).rolling(bars).sum() >= bars).fillna(False)


def soft_fail_short(close_1h: pd.Series, current_ub: pd.Series, bars: int) -> pd.Series:
    return ((close_1h > current_ub).rolling(bars).sum() >= bars).fillna(False)


def _early_fail(soft_fail, bw_percentile, volume_ratio, band_walking, config) -> pd.Series:
    enabled = [
        config.early_fail.use_bw_expansion,
        config.early_fail.use_shock_volume,
        config.early_fail.use_band_walking,
    ]
    if config.early_fail.min_confirmations > sum(enabled):
        raise ValueError("early_fail.min_confirmations exceeds enabled confirmation sources")

    confirmations = pd.Series(0, index=soft_fail.index)
    if config.early_fail.use_bw_expansion:
        confirmations += (bw_percentile > config.bandwidth_state.early_fail_bw_pct).fillna(False).astype(int)
    if config.early_fail.use_shock_volume:
        confirmations += (volume_ratio >= config.volume.reject).fillna(False).astype(int)
    if config.early_fail.use_band_walking:
        confirmations += band_walking.fillna(False).astype(int)
    return soft_fail.fillna(False) & (confirmations >= config.early_fail.min_confirmations)


def early_fail_long(soft_fail, bw_percentile, volume_ratio, lower_band_walking, config) -> pd.Series:
    return _early_fail(soft_fail, bw_percentile, volume_ratio, lower_band_walking, config)


def early_fail_short(soft_fail, bw_percentile, volume_ratio, upper_band_walking, config) -> pd.Series:
    return _early_fail(soft_fail, bw_percentile, volume_ratio, upper_band_walking, config)
