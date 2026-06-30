import pandas as pd

from bbmr.config import StrategyConfig


def compute_squeeze(bw_percentile: pd.Series, squeeze_pct: float) -> pd.Series:
    return (bw_percentile < squeeze_pct).fillna(False)


def compute_expansion(bw_percentile: pd.Series, high_pct: float) -> pd.Series:
    return (bw_percentile > high_pct).fillna(False)


def compute_range_allowed(
    bw_percentile: pd.Series,
    squeeze_pct: float,
    high_pct: float,
    mb_slope_pct: pd.Series,
    mb_slope_max: float,
) -> pd.Series:
    return (
        bw_percentile.notna()
        & mb_slope_pct.notna()
        & (bw_percentile >= squeeze_pct)
        & (bw_percentile <= high_pct)
        & (mb_slope_pct <= mb_slope_max)
    )


def compute_lower_band_walking(close: pd.Series, mb: pd.Series, lb: pd.Series, atr: pd.Series, config) -> pd.Series:
    if not config.enabled:
        return pd.Series(False, index=close.index)
    close, mb, lb, atr = (pd.to_numeric(series, errors="coerce") for series in (close, mb, lb, atr))
    below_mb_count = (close < mb).rolling(config.walk_bars).sum()
    near_lb_count = (close <= lb + atr * config.walk_atr_dist).rolling(config.walk_bars).sum()
    outside_lb_count = (close < lb).rolling(config.walk_bars).sum()
    return (
        ((below_mb_count >= config.walk_min_side_bars) & (near_lb_count >= config.walk_min_near_bars))
        | (outside_lb_count >= config.walk_min_outside_bars)
    ).fillna(False)


def compute_upper_band_walking(close: pd.Series, mb: pd.Series, ub: pd.Series, atr: pd.Series, config) -> pd.Series:
    if not config.enabled:
        return pd.Series(False, index=close.index)
    close, mb, ub, atr = (pd.to_numeric(series, errors="coerce") for series in (close, mb, ub, atr))
    above_mb_count = (close > mb).rolling(config.walk_bars).sum()
    near_ub_count = (close >= ub - atr * config.walk_atr_dist).rolling(config.walk_bars).sum()
    outside_ub_count = (close > ub).rolling(config.walk_bars).sum()
    return (
        ((above_mb_count >= config.walk_min_side_bars) & (near_ub_count >= config.walk_min_near_bars))
        | (outside_ub_count >= config.walk_min_outside_bars)
    ).fillna(False)


def compute_rsi_flat_entry_block(rsi14: pd.Series, low: float, high: float, bars: int) -> pd.Series:
    in_band = (rsi14 >= low) & (rsi14 <= high)
    return (in_band.rolling(bars).sum() >= bars).fillna(False)


def compute_rsi_flat_entry_released(rsi14: pd.Series, low: float, high: float) -> pd.Series:
    return ((rsi14 < low) | (rsi14 > high)).fillna(False)


def compute_market_state(indicators: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    mb_slope_pct = indicators["mb_slope_pct"]
    range_allowed = compute_range_allowed(
        indicators["bw_percentile"],
        config.bandwidth_state.squeeze_pct,
        config.bandwidth_state.high_pct,
        mb_slope_pct,
        config.middle_band_slope.slope_max,
    )
    lower_band_walking = compute_lower_band_walking(
        indicators["close"], indicators["mb"], indicators["lb"], indicators["atr"], config.band_walking
    )
    upper_band_walking = compute_upper_band_walking(
        indicators["close"], indicators["mb"], indicators["ub"], indicators["atr"], config.band_walking
    )
    rsi_flat_entry_block = compute_rsi_flat_entry_block(
        indicators["rsi14"],
        config.rsi_flat_entry_filter.low,
        config.rsi_flat_entry_filter.high,
        config.rsi_flat_entry_filter.bars,
    )
    return pd.DataFrame(
        {
            "squeeze": compute_squeeze(indicators["bw_percentile"], config.bandwidth_state.squeeze_pct),
            "expansion": compute_expansion(indicators["bw_percentile"], config.bandwidth_state.high_pct),
            "mb_slope_pct": mb_slope_pct,
            "mb_slope_ok": mb_slope_pct.notna() & (mb_slope_pct <= config.middle_band_slope.slope_max),
            "range_allowed": range_allowed,
            "lower_band_walking": lower_band_walking,
            "upper_band_walking": upper_band_walking,
            "rsi_flat_entry_block": rsi_flat_entry_block,
            "rsi_flat_entry_released": compute_rsi_flat_entry_released(
                indicators["rsi14"], config.rsi_flat_entry_filter.low, config.rsi_flat_entry_filter.high
            ),
            "long_market_allowed": range_allowed
            & ~lower_band_walking
            & (indicators["volume_ratio"] <= config.volume.weak)
            & ~rsi_flat_entry_block,
            "short_market_allowed": range_allowed
            & ~upper_band_walking
            & (indicators["volume_ratio"] <= config.volume.weak)
            & ~rsi_flat_entry_block,
        },
        index=indicators.index,
    )
