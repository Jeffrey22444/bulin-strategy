import pandas as pd

from bbmr.backtest.alignment import count_completed_since, latest_completed_row


def _frame(freq: str, periods: int = 4):
    index = pd.date_range("2026-01-01T00:00:00Z", periods=periods, freq=freq)
    return pd.DataFrame({"close": range(periods)}, index=index)


def test_alignment_does_not_use_incomplete_1h_row():
    frame = _frame("1h")
    assert latest_completed_row(frame, pd.Timestamp("2026-01-01T00:59:00Z"), "1h") is None
    assert latest_completed_row(frame, pd.Timestamp("2026-01-01T01:00:00Z"), "1h")["close"] == 0


def test_alignment_does_not_use_incomplete_15m_row():
    frame = _frame("15min")
    assert latest_completed_row(frame, pd.Timestamp("2026-01-01T00:14:00Z"), "15m") is None
    assert latest_completed_row(frame, pd.Timestamp("2026-01-01T00:30:00Z"), "15m")["close"] == 1


def test_waited_bars_count_completed_15m_not_5m():
    frame = _frame("15min")
    assert count_completed_since(frame, pd.Timestamp("2026-01-01T00:00:00Z"), pd.Timestamp("2026-01-01T00:20:00Z")) == 1
    assert count_completed_since(frame, pd.Timestamp("2026-01-01T00:00:00Z"), pd.Timestamp("2026-01-01T00:44:00Z")) == 2
