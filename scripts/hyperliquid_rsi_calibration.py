#!/usr/bin/env python3
import argparse
import sys

import pandas as pd

from bbmr.config import load_config
from bbmr.indicators import compute_rsi
from bbmr.live.config import load_live_config
from bbmr.live.env import load_project_env
from bbmr.live.hyperliquid_client import HyperliquidClient, missing_credential_names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-config", default="configs/live_hyperliquid_testnet.yaml")
    parser.add_argument("--symbol", default="BTC")
    parser.add_argument("--timeframe", default="15m", choices=("1h", "15m", "5m"))
    parser.add_argument("--count", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        load_project_env()
        live_config = load_live_config(args.live_config)
        missing = missing_credential_names(live_config)
        if missing:
            raise ValueError(f"missing credential environment variables: {', '.join(missing)}")
        strategy_config = load_config(live_config.strategy_config)
        client = HyperliquidClient(live_config)
        rows = completed_rsi_rows(client, strategy_config, args.symbol, args.timeframe, args.count)
        print(
            f"source=hyperliquid-{live_config.exchange.env} symbol={args.symbol} timeframe={args.timeframe} "
            f"method={strategy_config.rsi.method} period={strategy_config.rsi.period} warmup_bars={strategy_config.rsi.warmup_bars}"
        )
        for candle_time, close, rsi in rows:
            print(f"{candle_time.isoformat()} close={close:.8f} rsi={rsi:.6f}")
        return 0
    except Exception as exc:
        print(f"RSI calibration failed: {exc}", file=sys.stderr)
        return 1


def completed_rsi_rows(client, strategy_config, symbol: str, timeframe: str, count: int) -> list[tuple[pd.Timestamp, float, float]]:
    frame = client.fetch_ohlcv(symbol, timeframe, strategy_config.rsi.warmup_bars)
    rsi = compute_rsi(frame["close"], strategy_config.rsi.period, strategy_config.rsi.method)
    completed_at = _utc_index(frame.index) + pd.Timedelta(timeframe)
    usable = completed_at <= _utc_timestamp(client.now())
    result = []
    for candle_time, row, value in zip(completed_at[usable], frame.loc[usable].itertuples(), rsi.loc[usable], strict=True):
        if pd.notna(value):
            result.append((candle_time, float(row.close), float(value)))
    return result[-count:]


def _utc_timestamp(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _utc_index(index) -> pd.DatetimeIndex:
    timestamps = pd.DatetimeIndex(index)
    if timestamps.tz is None:
        return timestamps.tz_localize("UTC")
    return timestamps.tz_convert("UTC")


if __name__ == "__main__":
    raise SystemExit(main())
