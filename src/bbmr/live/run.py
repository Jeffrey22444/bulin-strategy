import argparse
import time

from bbmr.live.config import load_live_config
from bbmr.live.env import load_project_env
from bbmr.live.hyperliquid_client import HyperliquidClient, missing_credential_names
from bbmr.live.state_store import LiveStateStore
from bbmr.live.trailing_runtime import LiveRuntime, latest_completed_features
from bbmr.trailing import latest_completed_row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-config", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--symbol")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-testnet-orders", action="store_true")
    parser.add_argument("--allow-mainnet", action="store_true")
    args = parser.parse_args(argv)

    load_project_env()
    config = load_live_config(args.live_config)
    if config.exchange.env == "mainnet" and not args.allow_mainnet:
        raise ValueError("mainnet requires explicit --allow-mainnet")

    symbols = [args.symbol] if args.symbol else config.symbols.default
    store = LiveStateStore(config.storage.sqlite_path)

    missing = missing_credential_names(config)
    if args.dry_run and missing:
        print("dry-run: credentials missing; no exchange calls or orders will be sent")
        return 0
    if missing:
        raise ValueError(f"missing credential environment variables: {', '.join(missing)}")

    client = HyperliquidClient(config)

    runtime = LiveRuntime(config, client, store)
    while True:
        _poll_once(runtime, client, symbols, args.allow_testnet_orders, args.dry_run)
        if args.once:
            return 0
        time.sleep(config.execution.poll_seconds)


def _poll_once(runtime: LiveRuntime, client: HyperliquidClient, symbols: list[str], cli_allow_testnet_orders: bool, dry_run: bool) -> None:
    allow_orders = runtime.can_place_orders(cli_allow_testnet_orders)
    balance = client.fetch_balance()
    positions = client.fetch_positions()
    for symbol in symbols:
        poll_time = client.now()
        for event in runtime.reconcile_symbol(symbol, positions, allow_orders, dry_run):
            print(f"{poll_time} {event}")
        features = latest_completed_features(client, symbol, runtime.strategy_config)
        trade = runtime.managed_trade(symbol)
        if trade:
            row_5m = latest_completed_row(features[2], poll_time, "5m")
            event = runtime.update_stop(trade, features[0].iloc[-1], row_5m, allow_orders, dry_run) if row_5m is not None else None
            print(f"{poll_time} {event or f'{symbol} managed position; waiting for trailing-stop update'}")
            continue
        events = runtime.maybe_open_strategy_trade(symbol, *features, balance.equity, allow_orders, dry_run)
        for event in events:
            print(f"{poll_time} {event}")
        if not events:
            print(f"{poll_time} {symbol} waiting for 1h setup")


if __name__ == "__main__":
    raise SystemExit(main())
