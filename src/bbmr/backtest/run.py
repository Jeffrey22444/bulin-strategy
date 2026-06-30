import argparse
from pathlib import Path

import pandas as pd

from bbmr.backtest.data import load_symbol_ohlcv
from bbmr.backtest.event_loop import BacktestResult, run_event_loop
from bbmr.backtest.features import build_1h_features
from bbmr.backtest.trailing_portfolio_event_loop import run_trailing_portfolio_event_loop
from bbmr.backtest.reporting import TRAILING_PORTFOLIO_ENGINE, write_reports
from bbmr.backtest.trailing_event_loop import run_trailing_event_loop
from bbmr.backtest.trailing_features import build_trailing_features
from bbmr.config import load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--init-cash", type=float, required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--portfolio-mode", choices=["independent", "shared"], default="independent")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.portfolio_mode == "shared" and config.strategy.name != "bbmr_trailing_stop_v1":
        raise ValueError("--portfolio-mode shared is only supported for bbmr_trailing_stop_v1")

    if args.portfolio_mode == "shared":
        symbol_features = {}
        for symbol in args.symbols:
            symbol_features[symbol] = build_trailing_features(*load_symbol_ohlcv(args.data_dir, symbol), config)
        write_reports(
            run_trailing_portfolio_event_loop(symbol_features, config, args.init_cash),
            config,
            Path(args.out_dir),
            overwrite=args.overwrite,
            engine=TRAILING_PORTFOLIO_ENGINE,
        )
        return 0

    results = []
    for symbol in args.symbols:
        ohlcv_1h, ohlcv_15m, ohlcv_5m = load_symbol_ohlcv(args.data_dir, symbol)
        if config.strategy.name == "bbmr_trailing_stop_v1":
            result = run_trailing_event_loop(symbol, *build_trailing_features(ohlcv_1h, ohlcv_15m, ohlcv_5m, config), config, args.init_cash)
        else:
            result = run_event_loop(symbol, build_1h_features(ohlcv_1h, config), ohlcv_15m, ohlcv_5m, config, args.init_cash)
        results.append(result)

    merged = _merge_results(results)
    write_reports(merged, config, Path(args.out_dir), overwrite=args.overwrite)
    return 0


def _merge_results(results: list[BacktestResult]) -> BacktestResult:
    return BacktestResult(
        symbol=",".join(result.symbol for result in results),
        orders=pd.concat([result.orders for result in results], ignore_index=True) if results else pd.DataFrame(),
        trades=pd.concat([result.trades for result in results], ignore_index=True) if results else pd.DataFrame(),
        equity_curve=pd.concat([result.equity_curve for result in results], ignore_index=True) if results else pd.DataFrame(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
