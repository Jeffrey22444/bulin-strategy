import json

import pandas as pd
import pytest

from bbmr.backtest.reporting import TRAILING_PORTFOLIO_ENGINE, write_reports
from bbmr.backtest.run import main
from bbmr.backtest.trailing_portfolio_event_loop import run_trailing_portfolio_event_loop
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


def _one_h():
    return _frame(
        ["2026-01-01 08:00", "2026-01-01 09:00"],
        [
            {"open": 120, "high": 121, "low": 90, "close": 95, "lb": 100, "mb": 120, "ub": 140, "rsi14": 20},
            {"open": 120, "high": 121, "low": 90, "close": 120, "lb": 100, "mb": 120, "ub": 140, "rsi14": 50},
        ],
    )


def _fifteen_m(close_0915=100):
    return _frame(
        ["2026-01-01 08:45", "2026-01-01 09:00", "2026-01-01 09:15"],
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 20},
            {"open": 100, "high": 101, "low": 99, "close": 100, "rsi14": 25},
            {"open": close_0915, "high": 101, "low": 99, "close": close_0915, "rsi14": 25},
        ],
    )


def _five_m(closes):
    rows = []
    for close in closes:
        rows.append({"open": 100, "high": max(101, close), "low": min(99, close), "close": close, "mb": 100})
    index = [_ts("2026-01-01 08:55"), _ts("2026-01-01 09:10")]
    index += [_ts("2026-01-01 09:15") + pd.Timedelta(minutes=5 * offset) for offset in range(len(closes) - 2)]
    return pd.DataFrame(rows, index=index)


def _features(*, closes=(100, 105, 106, 106, 106, 106), close_0915=100):
    return _one_h(), _fifteen_m(close_0915), _five_m(closes)


def test_shared_mode_records_one_portfolio_equity_curve_not_symbol_concat():
    result = run_trailing_portfolio_event_loop({"BTC": _features(), "ETH": _features()}, _config(), 10000)
    assert set(result.equity_curve["symbol"]) == {"BTC,ETH"}
    assert len(result.equity_curve) == len(_five_m((100, 105, 106, 106, 106, 106))) + 1


def test_shared_entry_notional_uses_current_portfolio_equity():
    result = run_trailing_portfolio_event_loop({"BTC": _features(), "ETH": _features()}, _config(), 10000)
    entries = result.orders[result.orders["order_type"] == "entry"]
    for _, entry in entries.iterrows():
        assert entry["price"] * entry["qty"] == pytest.approx(2000)
    assert (result.trades["equity_before"] == 10000).all()


def test_shared_initial_stop_uses_configured_percent():
    config = _config()
    config.trailing_stop.initial_stop_pct = 0.03
    result = run_trailing_portfolio_event_loop({"BTC": _features()}, config, 10000)
    assert result.trades.iloc[0]["initial_stop_loss"] == 97


def test_different_symbols_can_be_open_at_the_same_time():
    result = run_trailing_portfolio_event_loop({"BTC": _features(), "ETH": _features(), "SOL": _features()}, _config(), 10000)
    entries = result.orders[result.orders["order_type"] == "entry"]
    assert len(entries) == 3
    assert entries["time"].nunique() == 1
    assert set(entries["symbol"]) == {"BTC", "ETH", "SOL"}


def test_same_symbol_cannot_open_duplicate_position_at_same_time():
    result = run_trailing_portfolio_event_loop({"BTC": _features(closes=(100, 105, 106, 105, 105, 105))}, _config(), 10000)
    entries = result.orders[result.orders["order_type"] == "entry"]
    assert len(entries) == 1


def test_same_setup_normal_exit_cannot_reenter():
    result = run_trailing_portfolio_event_loop(
        {"BTC": _features(closes=(100, 105, 115, 101, 105, 106), close_0915=99)},
        _config(),
        10000,
    )
    assert result.trades.iloc[0]["exit_reason"] == "trailing_stop_15m_close"
    assert len(result.orders[result.orders["order_type"] == "entry"]) == 1


def test_same_setup_initial_stop_allows_second_entry_after_full_chain():
    result = run_trailing_portfolio_event_loop(
        {"BTC": _features(closes=(100, 105, 97, 105, 106, 106))},
        _config(),
        10000,
    )
    entries = result.orders[result.orders["order_type"] == "entry"]
    assert result.trades.iloc[0]["exit_reason"] == "initial_stop_5m_close"
    assert len(entries) == 2
    assert result.trades.iloc[1]["confirm_15m_time"] == _ts("2026-01-01 09:30")
    assert result.trades.iloc[1]["setup_rsi_15m"] == result.trades.iloc[0]["setup_rsi_15m"]
    assert result.trades.iloc[1]["entry_signal_5m_close_time"] >= result.trades.iloc[1]["confirm_15m_time"]


def test_same_setup_does_not_allow_third_entry_after_second_initial_stop():
    result = run_trailing_portfolio_event_loop(
        {"BTC": _features(closes=(100, 105, 97, 105, 105, 97, 105))},
        _config(),
        10000,
    )
    assert (result.trades["exit_reason"] == "initial_stop_5m_close").sum() == 2
    assert len(result.orders[result.orders["order_type"] == "entry"]) == 2


def test_cli_shared_mode_writes_single_portfolio_report(tmp_path):
    out_dir = tmp_path / "shared_report"
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
                "--portfolio-mode",
                "shared",
            ]
        )
        == 0
    )
    assert pd.read_csv(out_dir / "summary.csv").loc[0, "engine"] == "trailing_portfolio_event_loop"
    with (out_dir / "run_metadata.json").open("r", encoding="utf-8") as handle:
        assert json.load(handle)["engine"] == "trailing_portfolio_event_loop"
    assert set(pd.read_csv(out_dir / "equity_curve.csv")["symbol"]) == {"BTC"}


def test_shared_summary_uses_one_portfolio_metrics(tmp_path):
    result = run_trailing_portfolio_event_loop({"BTC": _features(), "ETH": _features()}, _config(), 10000)
    out_dir = tmp_path / "shared_summary"
    write_reports(result, _config(), out_dir, engine=TRAILING_PORTFOLIO_ENGINE)

    summary = pd.read_csv(out_dir / "summary.csv").iloc[0]
    equity = pd.read_csv(out_dir / "equity_curve.csv")
    trades = pd.read_csv(out_dir / "trades.csv")
    assert summary["init_cash"] == 10000
    assert summary["final_equity"] == equity["equity"].iloc[-1]
    assert summary["total_return_pct"] == pytest.approx((summary["final_equity"] / 10000 - 1) * 100)
    assert summary["total_trades"] == len(trades)
    assert set(equity["symbol"]) == {"BTC,ETH"}


def test_old_strategy_rejects_shared_portfolio_mode(tmp_path):
    with pytest.raises(ValueError, match="only supported for bbmr_trailing_stop_v1"):
        main(
            [
                "--config",
                "configs/strategy_bbmr_v3_2.yaml",
                "--data-dir",
                "tests/fixtures/ohlcv",
                "--out-dir",
                str(tmp_path / "report"),
                "--init-cash",
                "10000",
                "--symbols",
                "BTC",
                "--portfolio-mode",
                "shared",
            ]
        )
