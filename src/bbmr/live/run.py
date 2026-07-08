import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import socket
import time
from urllib3.exceptions import ReadTimeoutError

import pandas as pd
from requests.exceptions import ConnectionError, ReadTimeout

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

    with _live_runner_lock(config.storage.sqlite_path):
        client = HyperliquidClient(config)

        runtime = LiveRuntime(config, client, store)
        next_full_poll_at = None
        while True:
            if _should_full_poll(runtime, client, symbols, config, next_full_poll_at):
                _poll_once(runtime, client, symbols, args.allow_testnet_orders, args.dry_run)
                next_full_poll_at = _next_poll_time_after_full_poll(runtime, client, symbols, config)
            if args.once:
                return 0
            time.sleep(_next_sleep_seconds(client.now(), next_full_poll_at, config))


def _poll_once(runtime: LiveRuntime, client: HyperliquidClient, symbols: list[str], cli_allow_testnet_orders: bool, dry_run: bool) -> None:
    allow_orders = runtime.can_place_orders(cli_allow_testnet_orders)
    try:
        balance = client.fetch_balance()
        positions = client.fetch_positions()
        features_by_symbol = {symbol: latest_completed_features(client, symbol, runtime.strategy_config) for symbol in symbols}
    except Exception as exc:
        if not _is_recoverable_poll_network_error(exc):
            raise
        _record_recoverable_network_error(runtime, client, symbols, exc)
        print(f"{_display_time(client.now())} [WARN] live poll network error; waiting for next cycle")
        return
    for symbol in symbols:
        poll_time = client.now()
        display_time = _display_time(poll_time)
        for event in runtime.reconcile_symbol(symbol, positions, allow_orders, dry_run):
            print(f"{display_time} {event}")
        features = features_by_symbol[symbol]
        trade = runtime.managed_trade(symbol)
        if trade:
            row_1h = latest_completed_row(features[0], poll_time, "1h")
            row_5m = latest_completed_row(features[2], poll_time, "5m")
            state_event = runtime.update_adverse_slope_take_profit(trade, features[0])
            if state_event:
                print(f"{display_time} {state_event}")
            if trade.adverse_slope_tp_active:
                tp_event = runtime.maybe_close_adverse_slope_take_profit(trade, client.get_market_price(symbol), allow_orders, dry_run)
                if tp_event:
                    print(f"{display_time} {tp_event}")
                    if runtime.managed_trade(symbol) is None:
                        continue
            event = runtime.update_stop(trade, row_1h, row_5m, allow_orders, dry_run) if row_1h is not None and row_5m is not None else None
            special = "[SPECIAL] " if trade.adverse_slope_tp_active else ""
            print(f"{display_time} {special}{event or f'{symbol} managed position; waiting for trailing-stop update'}")
            continue
        events = runtime.maybe_open_strategy_trade(symbol, *features, balance, allow_orders, dry_run, exchange_positions=positions)
        for event in events:
            print(f"{display_time} {event}")
        if not events:
            print(f"{display_time} {symbol} waiting for 1h setup")


def _display_time(value) -> pd.Timestamp:
    return _utc_time(value).tz_convert("Asia/Shanghai")


def _utc_time(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _next_1h_wake_time(now, grace_seconds: int) -> pd.Timestamp:
    current_hour = _utc_time(now).floor("h") + pd.Timedelta(seconds=grace_seconds)
    if _utc_time(now) <= current_hour:
        return current_hour
    return current_hour + pd.Timedelta(hours=1)


def _runtime_has_local_state(runtime: LiveRuntime, symbols: list[str]) -> bool:
    return any(runtime.managed_trade(symbol) for symbol in symbols) or any(symbol in runtime.setups for symbol in symbols)


def _light_guard_detects_active_state(runtime: LiveRuntime, client: HyperliquidClient, symbols: list[str], active_on_network_error: bool = False) -> bool:
    if _runtime_has_local_state(runtime, symbols):
        return True
    try:
        positions = client.fetch_positions()
        if any(position.symbol in symbols for position in positions):
            return True
        return any(client.fetch_open_orders(symbol) for symbol in symbols)
    except Exception as exc:
        if not _is_recoverable_poll_network_error(exc):
            raise
        _record_recoverable_network_error(runtime, client, symbols, exc)
        print(f"{_display_time(client.now())} [WARN] live poll network error; waiting for next cycle")
        return active_on_network_error


def _should_full_poll(runtime: LiveRuntime, client: HyperliquidClient, symbols: list[str], config, next_full_poll_at: pd.Timestamp | None) -> bool:
    return (
        not config.execution.idle_1h_aligned_poll
        or next_full_poll_at is None
        or _utc_time(client.now()) >= _utc_time(next_full_poll_at)
        or _light_guard_detects_active_state(runtime, client, symbols)
    )


def _next_poll_time_after_full_poll(runtime: LiveRuntime, client: HyperliquidClient, symbols: list[str], config) -> pd.Timestamp:
    now = _utc_time(client.now())
    if not config.execution.idle_1h_aligned_poll or _light_guard_detects_active_state(runtime, client, symbols, active_on_network_error=True):
        return now + pd.Timedelta(seconds=config.execution.poll_seconds)
    return _next_1h_wake_time(now, config.execution.idle_candle_grace_seconds)


def _next_sleep_seconds(now, next_full_poll_at: pd.Timestamp | None, config) -> float:
    if not config.execution.idle_1h_aligned_poll or next_full_poll_at is None:
        return float(config.execution.poll_seconds)
    seconds_to_full = max(0.0, (_utc_time(next_full_poll_at) - _utc_time(now)).total_seconds())
    return max(0.0, min(seconds_to_full, float(config.execution.idle_position_guard_seconds), float(config.execution.poll_seconds)))


@contextmanager
def _live_runner_lock(sqlite_path: str):
    lock_path = Path(sqlite_path).parent / "live_runner.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"live runner already running; lock={lock_path}") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _is_recoverable_poll_network_error(exc: Exception) -> bool:
    try:
        from ccxt.base.errors import NetworkError, RequestTimeout
    except Exception:
        NetworkError = ()
        RequestTimeout = ()
    return isinstance(exc, (NetworkError, RequestTimeout, ConnectionError, ReadTimeout, ReadTimeoutError, TimeoutError, socket.timeout))


def _record_recoverable_network_error(runtime: LiveRuntime, client: HyperliquidClient, symbols: list[str], exc: Exception) -> None:
    payload = json.dumps({"severity": "WARN", "reason": f"{exc.__class__.__name__}: {exc}"}, sort_keys=True)
    event_time = client.now()
    for symbol in symbols:
        runtime.store.append_event("recoverable_network_error", symbol, event_time=event_time, payload_json=payload)


if __name__ == "__main__":
    raise SystemExit(main())
