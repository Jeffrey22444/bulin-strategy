#!/usr/bin/env python3
import argparse
import sys

from bbmr.live.config import load_live_config
from bbmr.config import load_config
from bbmr.live.env import load_project_env
from bbmr.live.hyperliquid_client import HyperliquidClient, missing_credential_names
from bbmr.live.symbols import same_symbol


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-config", default="configs/live_hyperliquid_testnet.yaml")
    parser.add_argument("--symbol", default="BTC")
    parser.add_argument("--notional-usd", type=float, default=20.0)
    args = parser.parse_args()
    try:
        load_project_env()
        config = load_live_config(args.live_config)
        if config.exchange.env != "testnet":
            raise ValueError("acceptance only supports testnet")
        if not config.execution.allow_testnet_orders:
            raise ValueError("config must allow testnet orders for acceptance")
        missing = missing_credential_names(config)
        if missing:
            raise ValueError(f"missing credential environment variables: {', '.join(missing)}")
        client = HyperliquidClient(config)
        if any(same_symbol(position.symbol, args.symbol) for position in client.fetch_positions()):
            raise ValueError(f"{args.symbol} already has a position; refusing acceptance")
        if client.fetch_open_orders(args.symbol):
            raise ValueError(f"{args.symbol} has open orders; refusing acceptance")
        balance = client.fetch_balance()
        if balance.available < args.notional_usd:
            raise ValueError("insufficient testnet USDC")
        price = client.get_market_price(args.symbol)
        qty = client.format_qty(args.symbol, args.notional_usd / price)
        if qty <= 0:
            raise ValueError("formatted quantity is zero")
        strategy = load_config(config.strategy_config)
        stop_price = price * (1 - strategy.trailing_stop.initial_stop_pct)
        stop_order_id = None
        try:
            client.set_leverage(args.symbol, config.execution.leverage, config.exchange.margin_mode)
            client.create_market_entry(args.symbol, "long", qty)
            stop = client.create_reduce_only_stop(args.symbol, "long", qty, stop_price)
            stop_order_id = str(stop.get("id"))
            client.close_position_market(args.symbol, "long", qty)
        finally:
            if stop_order_id:
                client.cancel_order(args.symbol, stop_order_id)
        print("Hyperliquid testnet acceptance passed")
        return 0
    except Exception as exc:
        print(f"Hyperliquid acceptance refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
