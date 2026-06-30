from dataclasses import dataclass
from typing import Literal

import pandas as pd


Side = Literal["long", "short"]


@dataclass(frozen=True)
class EntryReference:
    signal_time: object
    entry_reference_LB: float
    entry_reference_MB: float
    entry_reference_UB: float
    frozen_ATR: float
    signal_side: Side


def compute_signals(data: pd.DataFrame, config) -> pd.DataFrame:
    long_signal = (
        (data["close"] < data["lb"])
        & (data["rsi14"] < config.rsi.oversold)
        & (not config.volume.entry_filter_enabled or data["volume_ratio"] <= config.volume.weak)
        & (not config.range_filter.entry_filter_enabled or data["range_allowed"])
        & ~data["lower_band_walking"]
        & ~data["rsi_flat_entry_block"]
    )
    short_signal = (
        (data["close"] > data["ub"])
        & (data["rsi14"] > config.rsi.overbought)
        & (not config.volume.entry_filter_enabled or data["volume_ratio"] <= config.volume.weak)
        & (not config.range_filter.entry_filter_enabled or data["range_allowed"])
        & ~data["upper_band_walking"]
        & ~data["rsi_flat_entry_block"]
    )
    invalid_signal = long_signal & short_signal
    return pd.DataFrame(
        {
            "long_signal_1h": long_signal & ~invalid_signal,
            "short_signal_1h": short_signal & ~invalid_signal,
            "invalid_signal": invalid_signal,
        },
        index=data.index,
    )


def freeze_entry_reference(row: pd.Series, side: Side) -> EntryReference:
    return EntryReference(
        signal_time=row.name,
        entry_reference_LB=float(row["lb"]),
        entry_reference_MB=float(row["mb"]),
        entry_reference_UB=float(row["ub"]),
        frozen_ATR=float(row["atr"]),
        signal_side=side,
    )
