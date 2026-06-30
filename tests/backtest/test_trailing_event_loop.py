import json

import pandas as pd

from bbmr.backtest.run import main
from bbmr.backtest.trailing_event_loop import Position, Setup, _updated_stop, run_trailing_event_loop
from bbmr.config import load_config


def _ts(value: str) -> pd.Timestamp:
    return pd.Timestamp(value, tz="UTC")


def _config():
    config = load_config("configs/strategy_bbmr_trailing_stop_v1.yaml")
    config.costs.taker_fee_bps = 0
    config.costs.slippage_bps = 0
    config.trailing_stop.initial_stop_pct = 0.02
    return config


def _frame(index, rows):
    return pd.DataFrame(rows, index=[_ts(value) for value in index])


def _long_1h():
    return _frame(
        ["2026-01-01 08:00", "2026-01-01 09:00"],
        [
            {"open": 120, "high": 121, "low": 90, "close": 95, "lb": 100, "mb": 120, "ub": 140, "rsi14": 20},
            {"open": 120, "high": 121, "low": 90, "close": 120, "lb": 100, "mb": 120, "ub": 140, "rsi14": 50},
        ],
    )


def _short_1h():
    return _frame(
        ["2026-01-01 08:00", "2026-01-01 09:00"],
        [
            {"open": 120, "high": 150, "low": 119, "close": 145, "lb": 100, "mb": 120, "ub": 140, "rsi14": 80},
            {"open": 120, "high": 150, "low": 119, "close": 120, "lb": 100, "mb": 120, "ub": 140, "rsi14": 50},
        ],
    )


def _long_15m(baseline=20, confirm=25, confirm_close=100):
    return _frame(
        ["2026-01-01 08:45", "2026-01-01 09:00", "2026-01-01 09:15"],
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": baseline},
            {"open": confirm_close, "high": 101, "low": 99, "close": confirm_close, "rsi14": confirm},
            {"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": confirm},
        ],
    )


def _short_15m(baseline=70, confirm=65):
    return _frame(
        ["2026-01-01 08:45", "2026-01-01 09:00"],
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": baseline},
            {"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": confirm},
        ],
    )


def _long_5m(signal_close=105, fill_open=106, after_close=106):
    return _frame(
        ["2026-01-01 08:55", "2026-01-01 09:10", "2026-01-01 09:15"],
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "mb": 99},
            {"open": 104, "high": 106, "low": 103, "close": signal_close, "mb": 100},
            {"open": fill_open, "high": 107, "low": 105, "close": after_close, "mb": 100},
        ],
    )


def _long_5m_sequence(closes):
    rows = []
    for close in closes:
        rows.append({"open": 100, "high": max(101, close), "low": min(99, close), "close": close, "mb": 100})
    index = [_ts("2026-01-01 08:55"), _ts("2026-01-01 09:10")]
    index += [_ts("2026-01-01 09:15") + pd.Timedelta(minutes=5 * offset) for offset in range(len(closes) - 2)]
    return pd.DataFrame(rows, index=index)


def _short_5m(signal_close=135, fill_open=134, after_close=134):
    return _frame(
        ["2026-01-01 08:55", "2026-01-01 09:10", "2026-01-01 09:15"],
        [
            {"open": 130, "high": 131, "low": 129, "close": 130, "mb": 131},
            {"open": 136, "high": 137, "low": 134, "close": signal_close, "mb": 136},
            {"open": fill_open, "high": 135, "low": 133, "close": after_close, "mb": 136},
        ],
    )


def test_trailing_config_loads():
    config = load_config("configs/strategy_bbmr_trailing_stop_v1.yaml")
    assert config.strategy.name == "bbmr_trailing_stop_v1"
    assert 0 < config.trailing_stop.initial_stop_pct < 1


def test_long_setup_records_latest_completed_15m_baseline_rsi():
    result = run_trailing_event_loop("BTC", _long_1h(), _long_15m(baseline=20, confirm=25), _long_5m(), _config(), 10000)
    trade = result.trades.iloc[0]
    assert trade["setup_trigger_time"] == _ts("2026-01-01 09:00")
    assert trade["setup_rsi_15m"] == 20
    assert trade["confirm_15m_time"] == _ts("2026-01-01 09:15")


def test_long_confirmation_compares_against_baseline_not_previous_15m():
    result = run_trailing_event_loop("BTC", _long_1h(), _long_15m(baseline=30, confirm=25), _long_5m(), _config(), 10000)
    assert result.orders.empty


def test_short_confirmation_compares_later_15m_against_baseline():
    result = run_trailing_event_loop("BTC", _short_1h(), _short_15m(baseline=70, confirm=65), _short_5m(), _config(), 10000)
    trade = result.trades.iloc[0]
    assert trade["side"] == "short"
    assert trade["setup_rsi_15m"] == 70
    assert trade["confirm_15m_time"] == _ts("2026-01-01 09:15")


def test_setup_expires_at_next_1h_close_without_entry():
    five_m = _frame(
        ["2026-01-01 08:55", "2026-01-01 09:55", "2026-01-01 10:00"],
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "mb": 99},
            {"open": 100, "high": 101, "low": 99, "close": 100, "mb": 99},
            {"open": 100, "high": 101, "low": 99, "close": 100, "mb": 99},
        ],
    )
    result = run_trailing_event_loop("BTC", _long_1h(), _long_15m(baseline=30, confirm=25), five_m, _config(), 10000)
    assert result.orders.empty
    assert result.equity_curve.iloc[-1]["state"] == "flat"


def test_5m_entry_signal_fills_on_next_5m_open_not_trigger_close():
    result = run_trailing_event_loop(
        "BTC", _long_1h(), _long_15m(), _long_5m(signal_close=105, fill_open=106), _config(), 10000
    )
    trade = result.trades.iloc[0]
    assert trade["entry_signal_5m_close_time"] == _ts("2026-01-01 09:15")
    assert trade["entry_time"] == _ts("2026-01-01 09:15")
    assert trade["entry_price"] == 106


def test_long_position_size_uses_20_percent_equity_notional():
    result = run_trailing_event_loop("BTC", _long_1h(), _long_15m(), _long_5m(fill_open=100), _config(), 10000)
    assert result.trades.iloc[0]["qty"] == 20


def test_short_position_size_uses_20_percent_equity_notional():
    result = run_trailing_event_loop("BTC", _short_1h(), _short_15m(), _short_5m(fill_open=100), _config(), 10000)
    assert result.trades.iloc[0]["qty"] == 20


def test_long_initial_stop_is_entry_price_minus_2_percent():
    result = run_trailing_event_loop("BTC", _long_1h(), _long_15m(), _long_5m(fill_open=100), _config(), 10000)
    assert result.trades.iloc[0]["initial_stop_loss"] == 98


def test_long_initial_stop_uses_configured_percent():
    config = _config()
    config.trailing_stop.initial_stop_pct = 0.03
    result = run_trailing_event_loop("BTC", _long_1h(), _long_15m(), _long_5m(fill_open=100), config, 10000)
    assert result.trades.iloc[0]["initial_stop_loss"] == 97


def test_short_initial_stop_is_entry_price_plus_2_percent():
    result = run_trailing_event_loop("BTC", _short_1h(), _short_15m(), _short_5m(fill_open=100), _config(), 10000)
    assert result.trades.iloc[0]["initial_stop_loss"] == 102


def test_short_initial_stop_uses_configured_percent():
    config = _config()
    config.trailing_stop.initial_stop_pct = 0.03
    result = run_trailing_event_loop("BTC", _short_1h(), _short_15m(), _short_5m(fill_open=100), config, 10000)
    assert result.trades.iloc[0]["initial_stop_loss"] == 103


def test_long_trailing_stop_only_moves_upward():
    position = Position("long", 1, _ts("2026-01-01 09:15"), 100, 0, 10000, Setup("long", pd.Series(), _ts("2026-01-01 09:00"), _ts("2026-01-01 10:00"), 20), _ts("2026-01-01 09:15"), 98, 98, _ts("2026-01-01 09:15"))
    row_1h = pd.Series({"lb": 90, "mb": 110, "ub": 130})
    moved = _updated_stop(position, 111, row_1h)
    position.current_stop_loss = moved
    assert moved > 98
    assert _updated_stop(position, 95, row_1h) == moved


def test_short_trailing_stop_only_moves_downward():
    position = Position("short", 1, _ts("2026-01-01 09:15"), 100, 0, 10000, Setup("short", pd.Series(), _ts("2026-01-01 09:00"), _ts("2026-01-01 10:00"), 70), _ts("2026-01-01 09:15"), 102, 102, _ts("2026-01-01 09:15"))
    row_1h = pd.Series({"lb": 70, "mb": 90, "ub": 110})
    moved = _updated_stop(position, 89, row_1h)
    position.current_stop_loss = moved
    assert moved < 102
    assert _updated_stop(position, 105, row_1h) == moved


def test_long_initial_stop_forced_exit_uses_later_5m_close():
    result = run_trailing_event_loop("BTC", _long_1h(), _long_15m(), _long_5m(fill_open=100, after_close=97), _config(), 10000)
    assert result.trades.iloc[0]["exit_reason"] == "initial_stop_5m_close"


def test_short_initial_stop_forced_exit_uses_later_5m_close():
    result = run_trailing_event_loop("BTC", _short_1h(), _short_15m(), _short_5m(fill_open=100, after_close=103), _config(), 10000)
    assert result.trades.iloc[0]["exit_reason"] == "initial_stop_5m_close"


def test_long_normal_trailing_exit_uses_15m_close_after_stop_update_time():
    five_m = _frame(
        ["2026-01-01 08:55", "2026-01-01 09:10", "2026-01-01 09:15", "2026-01-01 09:25"],
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "mb": 99},
            {"open": 104, "high": 106, "low": 103, "close": 105, "mb": 100},
            {"open": 100, "high": 116, "low": 100, "close": 115, "mb": 100},
            {"open": 101, "high": 102, "low": 100, "close": 101, "mb": 100},
        ],
    )
    fifteen_m = _long_15m(confirm_close=99)
    fifteen_m.loc[_ts("2026-01-01 09:15"), "close"] = 99
    result = run_trailing_event_loop("BTC", _long_1h(), fifteen_m, five_m, _config(), 10000)
    assert result.trades.iloc[0]["exit_reason"] == "trailing_stop_15m_close"
    assert result.trades.iloc[0]["exit_time"] == _ts("2026-01-01 09:30")


def test_short_normal_trailing_exit_uses_15m_close_after_stop_update_time():
    fifteen_m = _frame(
        ["2026-01-01 08:45", "2026-01-01 09:00", "2026-01-01 09:15"],
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 70},
            {"open": 101, "high": 102, "low": 100, "close": 101, "rsi14": 65},
            {"open": 101, "high": 102, "low": 100, "close": 101, "rsi14": 65},
        ],
    )
    five_m = _frame(
        ["2026-01-01 08:55", "2026-01-01 09:10", "2026-01-01 09:15", "2026-01-01 09:25"],
        [
            {"open": 130, "high": 131, "low": 129, "close": 130, "mb": 131},
            {"open": 136, "high": 137, "low": 134, "close": 135, "mb": 136},
            {"open": 100, "high": 100, "low": 84, "close": 85, "mb": 136},
            {"open": 99, "high": 100, "low": 98, "close": 99, "mb": 136},
        ],
    )
    result = run_trailing_event_loop("BTC", _short_1h(), fifteen_m, five_m, _config(), 10000)
    assert result.trades.iloc[0]["exit_reason"] == "trailing_stop_15m_close"
    assert result.trades.iloc[0]["exit_time"] == _ts("2026-01-01 09:30")


def test_initial_stop_forced_exit_has_priority_over_trailing_stop_exit():
    fifteen_m = _long_15m(confirm_close=90)
    result = run_trailing_event_loop("BTC", _long_1h(), fifteen_m, _long_5m(fill_open=100, after_close=97), _config(), 10000)
    assert result.trades.iloc[0]["exit_reason"] == "initial_stop_5m_close"


def test_independent_same_setup_reentry_requires_new_confirmation_after_initial_stop():
    result = run_trailing_event_loop("BTC", _long_1h(), _long_15m(), _long_5m_sequence((100, 105, 97, 105, 106, 106)), _config(), 10000)
    entries = result.orders[result.orders["order_type"] == "entry"]
    first_exit_time = result.trades.iloc[0]["exit_time"]
    assert result.trades.iloc[0]["exit_reason"] == "initial_stop_5m_close"
    assert len(entries) == 2
    assert result.trades.iloc[1]["confirm_15m_time"] > first_exit_time
    assert result.trades.iloc[1]["confirm_15m_time"] == _ts("2026-01-01 09:30")
    assert result.trades.iloc[1]["setup_rsi_15m"] == result.trades.iloc[0]["setup_rsi_15m"]
    assert result.trades.iloc[1]["entry_signal_5m_close_time"] >= result.trades.iloc[1]["confirm_15m_time"]


def test_independent_same_setup_normal_exit_cannot_reenter():
    five_m = _frame(
        ["2026-01-01 08:55", "2026-01-01 09:10", "2026-01-01 09:15", "2026-01-01 09:25", "2026-01-01 09:30"],
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "mb": 99},
            {"open": 104, "high": 106, "low": 103, "close": 105, "mb": 100},
            {"open": 100, "high": 116, "low": 100, "close": 115, "mb": 100},
            {"open": 101, "high": 102, "low": 100, "close": 101, "mb": 100},
            {"open": 100, "high": 106, "low": 99, "close": 105, "mb": 100},
        ],
    )
    fifteen_m = _long_15m(confirm_close=99)
    fifteen_m.loc[_ts("2026-01-01 09:15"), "close"] = 99
    result = run_trailing_event_loop("BTC", _long_1h(), fifteen_m, five_m, _config(), 10000)
    assert result.trades.iloc[0]["exit_reason"] == "trailing_stop_15m_close"
    assert len(result.orders[result.orders["order_type"] == "entry"]) == 1


def test_independent_same_setup_forbids_third_entry():
    result = run_trailing_event_loop("BTC", _long_1h(), _long_15m(), _long_5m_sequence((100, 105, 97, 105, 105, 97, 105)), _config(), 10000)
    assert (result.trades["exit_reason"] == "initial_stop_5m_close").sum() == 2
    assert len(result.orders[result.orders["order_type"] == "entry"]) == 2


def test_old_filter_like_columns_do_not_block_new_strategy():
    one_h = _long_1h().assign(range_allowed=False, lower_band_walking=True, rsi_flat_entry_block=True, volume_ratio=999)
    five_m = _long_5m().assign(range_allowed=False, lower_band_walking=True, rsi_flat_entry_block=True, volume_ratio=999)
    result = run_trailing_event_loop("BTC", one_h, _long_15m(), five_m, _config(), 10000)
    assert not result.orders.empty


def test_cli_routes_trailing_strategy_and_writes_reports(tmp_path):
    out_dir = tmp_path / "trailing_report"
    assert (
        main(
            [
                "--config",
                "configs/strategy_bbmr_trailing_stop_v1.yaml",
                "--data-dir",
                "tests/fixtures/ohlcv",
                "--out-dir",
                str(out_dir),
                "--init-cash",
                "10000",
                "--symbols",
                "BTC",
            ]
        )
        == 0
    )
    for name in ["summary.csv", "trades.csv", "orders.csv", "equity_curve.csv", "config_snapshot.yaml", "run_metadata.json"]:
        assert (out_dir / name).exists()
    assert pd.read_csv(out_dir / "summary.csv").loc[0, "engine"] == "trailing_event_loop"
    with (out_dir / "run_metadata.json").open("r", encoding="utf-8") as handle:
        assert json.load(handle)["engine"] == "trailing_event_loop"
