from typing import Literal


Side = Literal["long", "short"]


def initial_position_size(account_equity: float, risk_per_trade: float, one_R: float) -> float:
    if account_equity <= 0 or risk_per_trade <= 0 or one_R <= 0:
        raise ValueError("account equity, risk per trade, and one_R must be positive")
    return account_equity * risk_per_trade / one_R


def total_risk_after_add(
    side: Side,
    initial_position_size: float,
    initial_entry_price: float,
    add_size: float,
    add_entry_price: float,
    fixed_sl: float,
) -> float:
    if side == "long":
        return initial_position_size * (initial_entry_price - fixed_sl) + add_size * (add_entry_price - fixed_sl)
    return initial_position_size * (fixed_sl - initial_entry_price) + add_size * (fixed_sl - add_entry_price)


def calculate_add_size(
    side: Side,
    initial_position_size: float,
    initial_entry_price: float,
    add_entry_price: float,
    fixed_sl: float,
    initial_risk_amount: float,
    add_size_frac: float,
    add_max_total_r: float,
    exchange_min_order_size: float | None = None,
) -> float:
    proposed = initial_position_size * add_size_frac
    risk_room = initial_risk_amount * add_max_total_r - total_risk_after_add(
        side, initial_position_size, initial_entry_price, 0, add_entry_price, fixed_sl
    )
    per_unit_add_risk = add_entry_price - fixed_sl if side == "long" else fixed_sl - add_entry_price
    final_size = min(proposed, max(0.0, risk_room / per_unit_add_risk))
    if exchange_min_order_size is not None and final_size < exchange_min_order_size:
        return 0.0
    return final_size
