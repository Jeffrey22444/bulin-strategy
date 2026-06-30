import pandas as pd


_TIMEFRAMES = {"1h": pd.Timedelta(hours=1), "15m": pd.Timedelta(minutes=15)}


def latest_completed_row(frame: pd.DataFrame, current_5m_time, timeframe: str):
    completed_at = frame.index + _TIMEFRAMES[timeframe]
    usable = completed_at <= pd.Timestamp(current_5m_time)
    if not usable.any():
        return None
    return frame.iloc[usable.nonzero()[0][-1]]


def count_completed_since(frame: pd.DataFrame, start_time, current_5m_time, timeframe: str = "15m") -> int:
    completed_at = frame.index + _TIMEFRAMES[timeframe]
    return int(((completed_at > pd.Timestamp(start_time)) & (completed_at <= pd.Timestamp(current_5m_time))).sum())
