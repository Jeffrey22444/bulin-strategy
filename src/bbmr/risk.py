from typing import Literal


Side = Literal["long", "short"]


def fixed_stop_loss(side: Side, entry_price: float, frozen_atr: float, sl_atr_mult: float, min_stop_pct: float) -> float:
    stop_distance = max(frozen_atr * sl_atr_mult, entry_price * min_stop_pct)
    return entry_price - stop_distance if side == "long" else entry_price + stop_distance


def one_r(side: Side, entry_price: float, fixed_sl: float) -> float:
    value = entry_price - fixed_sl if side == "long" else fixed_sl - entry_price
    if value <= 0:
        raise ValueError("one_R must be positive")
    return value
