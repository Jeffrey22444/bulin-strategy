def long_add_allowed(
    *,
    has_long_position: bool,
    add_count: int,
    floating_pnl_R: float,
    add_trigger_loss_r: float,
    fixed_sl_triggered: bool,
    soft_fail_long: bool,
    squeeze: bool,
    expansion: bool,
    lower_band_walking: bool,
    volume_ratio: float,
    volume_reject: float,
    long_second_reentry_confirmed: bool,
) -> bool:
    return (
        has_long_position
        and add_count == 0
        and floating_pnl_R <= -add_trigger_loss_r
        and not fixed_sl_triggered
        and not soft_fail_long
        and not squeeze
        and not expansion
        and not lower_band_walking
        and volume_ratio < volume_reject
        and long_second_reentry_confirmed
    )


def short_add_allowed(
    *,
    has_short_position: bool,
    add_count: int,
    floating_pnl_R: float,
    add_trigger_loss_r: float,
    fixed_sl_triggered: bool,
    soft_fail_short: bool,
    squeeze: bool,
    expansion: bool,
    upper_band_walking: bool,
    volume_ratio: float,
    volume_reject: float,
    short_second_reentry_confirmed: bool,
) -> bool:
    return (
        has_short_position
        and add_count == 0
        and floating_pnl_R <= -add_trigger_loss_r
        and not fixed_sl_triggered
        and not soft_fail_short
        and not squeeze
        and not expansion
        and not upper_band_walking
        and volume_ratio < volume_reject
        and short_second_reentry_confirmed
    )
