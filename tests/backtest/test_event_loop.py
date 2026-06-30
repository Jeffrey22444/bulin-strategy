import pandas as pd

from bbmr.backtest.event_loop import run_event_loop
from bbmr.config import load_config


def _config():
    return load_config("configs/strategy_bbmr_v3_2.yaml")


def _features(rows):
    return pd.DataFrame(rows, index=pd.to_datetime([row.pop("time") for row in rows], utc=True))


def _bars(rows):
    return pd.DataFrame(rows, index=pd.to_datetime([row.pop("time") for row in rows], utc=True))


def _row(**overrides):
    row = {
        "open": 100,
        "high": 101,
        "low": 99,
        "close": 100,
        "volume": 10,
        "mb": 100,
        "ub": 110,
        "lb": 90,
        "bw": 0.2,
        "bw_percentile": 50,
        "rsi14": 25,
        "atr": 1,
        "volume_ratio": 1,
        "mb_slope_pct": 0,
        "range_allowed": True,
        "squeeze": False,
        "expansion": False,
        "lower_band_walking": False,
        "upper_band_walking": False,
        "rsi_flat_entry_block": False,
        "soft_fail_long": False,
        "soft_fail_short": False,
        "early_fail_long": False,
        "early_fail_short": False,
        "soft_fail": False,
        "early_fail": False,
        "long_signal_1h": False,
        "short_signal_1h": False,
        "invalid_signal": False,
    }
    row.update(overrides)
    return row


def test_entry_opens_from_15m_close_and_same_bar_does_not_stop():
    features = _features([dict(time="2026-01-01T00:00:00Z", **_row(long_signal_1h=True, lb=90, mb=100, ub=110))])
    bars_15m = _bars(
        [
            {"time": "2026-01-01T01:00:00Z", "open": 90, "high": 91, "low": 89, "close": 90, "volume": 1},
            {"time": "2026-01-01T01:15:00Z", "open": 90, "high": 100, "low": 80, "close": 91, "volume": 1},
        ]
    )
    bars_5m = _bars(
        [
            {"time": "2026-01-01T01:15:00Z", "open": 90, "high": 200, "low": 1, "close": 91, "volume": 1},
            {"time": "2026-01-01T01:30:00Z", "open": 90, "high": 200, "low": 1, "close": 91, "volume": 1},
        ]
    )
    result = run_event_loop("BTC", features, bars_15m, bars_5m, _config(), 10_000)
    assert result.orders.iloc[0]["order_type"] == "entry"
    assert result.orders.iloc[0]["price"] == 91
    assert result.trades.iloc[0]["exit_reason"] == "end_of_data"


def test_same_5m_sl_tp_conflict_exits_stop_loss_next_bar():
    features = _features([dict(time="2026-01-01T00:00:00Z", **_row(long_signal_1h=True, lb=90, mb=100, ub=110))])
    bars_15m = _bars(
        [
            {"time": "2026-01-01T01:00:00Z", "open": 90, "high": 91, "low": 89, "close": 90, "volume": 1},
            {"time": "2026-01-01T01:15:00Z", "open": 90, "high": 100, "low": 89, "close": 91, "volume": 1},
        ]
    )
    bars_5m = _bars(
        [
            {"time": "2026-01-01T01:15:00Z", "open": 91, "high": 91, "low": 90, "close": 91, "volume": 1},
            {"time": "2026-01-01T01:30:00Z", "open": 91, "high": 91, "low": 90, "close": 91, "volume": 1},
            {"time": "2026-01-01T01:35:00Z", "open": 91, "high": 200, "low": 1, "close": 91, "volume": 1},
        ]
    )
    result = run_event_loop("BTC", features, bars_15m, bars_5m, _config(), 10_000)
    assert result.trades.iloc[0]["exit_reason"] == "stop_loss"


def test_add_uses_15m_close_and_updates_weighted_average():
    features = _features([dict(time="2026-01-01T00:00:00Z", **_row(long_signal_1h=True, lb=98, mb=200, ub=300))])
    bars_15m = _bars(
        [
            {"time": "2026-01-01T01:00:00Z", "open": 99, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"time": "2026-01-01T01:15:00Z", "open": 99, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"time": "2026-01-01T01:30:00Z", "open": 100, "high": 100, "low": 98, "close": 98.5, "volume": 1},
        ]
    )
    bars_5m = _bars(
        [
            {"time": "2026-01-01T01:15:00Z", "open": 100, "high": 100, "low": 99, "close": 100, "volume": 1},
            {"time": "2026-01-01T01:30:00Z", "open": 100, "high": 100, "low": 99, "close": 100, "volume": 1},
            {"time": "2026-01-01T01:45:00Z", "open": 99, "high": 100, "low": 98, "close": 98.5, "volume": 1},
        ]
    )
    result = run_event_loop("BTC", features, bars_15m, bars_5m, _config(), 10_000)
    add = result.orders[result.orders["order_type"] == "add"].iloc[0]
    assert add["price"] == 98.5
    assert result.trades.iloc[0]["add_qty"] > 0
    assert result.trades.iloc[0]["weighted_avg_entry"] < 100


def test_soft_fail_does_not_close_but_early_fail_closes():
    features = _features(
        [
            dict(time="2026-01-01T00:00:00Z", **_row(long_signal_1h=True, lb=90, mb=200, ub=300)),
            dict(time="2026-01-01T01:00:00Z", **_row(soft_fail_long=True, lb=90, mb=200, ub=300)),
            dict(time="2026-01-01T02:00:00Z", **_row(early_fail_long=True, lb=90, mb=200, ub=300)),
        ]
    )
    bars_15m = _bars(
        [
            {"time": "2026-01-01T01:00:00Z", "open": 90, "high": 91, "low": 89, "close": 90, "volume": 1},
            {"time": "2026-01-01T01:15:00Z", "open": 90, "high": 100, "low": 89, "close": 91, "volume": 1},
        ]
    )
    bars_5m = _bars(
        [
            {"time": "2026-01-01T01:15:00Z", "open": 91, "high": 91, "low": 90, "close": 91, "volume": 1},
            {"time": "2026-01-01T01:30:00Z", "open": 91, "high": 91, "low": 90, "close": 91, "volume": 1},
            {"time": "2026-01-01T02:00:00Z", "open": 91, "high": 91, "low": 90, "close": 91, "volume": 1},
            {"time": "2026-01-01T03:00:00Z", "open": 91, "high": 91, "low": 90, "close": 91, "volume": 1},
        ]
    )
    result = run_event_loop("BTC", features, bars_15m, bars_5m, _config(), 10_000)
    assert "SOFT_FAIL_1H" not in result.orders["event"].tolist()
    assert result.trades.iloc[0]["exit_reason"] == "early_fail"
