import json

import pandas as pd
import pytest

from bbmr.backtest.run import main


def test_cli_writes_all_output_files(tmp_path):
    out_dir = tmp_path / "report"
    assert (
        main(
            [
                "--config",
                "configs/strategy_bbmr_v3_2.yaml",
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
    assert pd.read_csv(out_dir / "summary.csv").loc[0, "engine"] == "manual_event_loop"
    with (out_dir / "run_metadata.json").open("r", encoding="utf-8") as handle:
        assert json.load(handle)["engine"] == "manual_event_loop"


def test_cli_refuses_existing_out_dir_without_overwrite(tmp_path):
    out_dir = tmp_path / "report"
    out_dir.mkdir()
    with pytest.raises(FileExistsError):
        main(
            [
                "--config",
                "configs/strategy_bbmr_v3_2.yaml",
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


def test_cli_allows_existing_out_dir_with_overwrite(tmp_path):
    out_dir = tmp_path / "report"
    out_dir.mkdir()
    assert (
        main(
            [
                "--config",
                "configs/strategy_bbmr_v3_2.yaml",
                "--data-dir",
                "tests/fixtures/ohlcv",
                "--out-dir",
                str(out_dir),
                "--init-cash",
                "10000",
                "--symbols",
                "BTC",
                "--overwrite",
            ]
        )
        == 0
    )
