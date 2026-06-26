from bbmr.signals import EntryReference


def long_entry_confirmed(close_15m: float, entry_reference: EntryReference) -> bool:
    return close_15m > entry_reference.entry_reference_LB


def short_entry_confirmed(close_15m: float, entry_reference: EntryReference) -> bool:
    return close_15m < entry_reference.entry_reference_UB


def pending_expired(waited_bars: int, reentry_bars: int) -> bool:
    return waited_bars > reentry_bars


def pending_invalidated(
    side: str,
    squeeze: bool,
    expansion: bool,
    lower_band_walking: bool,
    upper_band_walking: bool,
    volume_ratio: float,
    volume_reject: float,
) -> bool:
    return (
        squeeze
        or expansion
        or (side == "long" and lower_band_walking)
        or (side == "short" and upper_band_walking)
        or volume_ratio >= volume_reject
    )


def long_second_reentry_confirmed(low_15m: float, close_15m: float, current_lb: float) -> bool:
    return low_15m <= current_lb and close_15m > current_lb


def short_second_reentry_confirmed(high_15m: float, close_15m: float, current_ub: float) -> bool:
    return high_15m >= current_ub and close_15m < current_ub
