import argparse
import copy
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile
import time
from urllib3.exceptions import ReadTimeoutError

import pandas as pd
from requests.exceptions import ConnectionError, ReadTimeout

from bbmr.live.config import load_live_config
from bbmr.live.dashboard import write_lifecycle, write_snapshot
from bbmr.live.env import load_project_env
from bbmr.live.hyperliquid_client import HyperliquidClient, missing_credential_names
from bbmr.live.state_store import LiveStateStore
from bbmr.live.symbols import canonical_symbols
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
    parser.add_argument("--bind-legacy-identity", action="store_true")
    args = parser.parse_args(argv)

    load_project_env()
    config = load_live_config(args.live_config)
    if config.exchange.env == "mainnet" and not args.allow_mainnet:
        raise ValueError("mainnet requires explicit --allow-mainnet")

    symbols = canonical_symbols([args.symbol] if args.symbol is not None else config.symbols.default)

    missing = missing_credential_names(config)
    if args.dry_run and missing:
        print("dry-run: credentials missing; no exchange calls or orders will be sent")
        return 0
    if missing:
        raise ValueError(f"missing credential environment variables: {', '.join(missing)}")

    active_config = _simulation_config(config) if args.dry_run else config
    fingerprint = _wallet_fingerprint(config)
    active_fingerprint = _simulation_fingerprint(fingerprint) if args.dry_run else fingerprint
    with _wallet_identity_lock(active_fingerprint), _live_runner_lock(active_config.storage.sqlite_path):
        store = LiveStateStore(
            active_config.storage.sqlite_path,
            identity_fingerprint=active_fingerprint,
            environment=active_config.exchange.env,
            bind_legacy_identity=args.bind_legacy_identity,
        )
        _safe_dashboard(lambda: write_lifecycle(active_config.storage.sqlite_path, "starting"))
        try:
            client = None
            runtime = None
            next_full_poll_at = None
            while True:
                if client is None:
                    client = _build_client(active_config, store, symbols)
                    if client is None:
                        if args.once:
                            return 0
                        time.sleep(float(active_config.execution.poll_seconds))
                        continue
                    runtime = LiveRuntime(active_config, client, store, account=active_fingerprint)
                if _should_full_poll(runtime, client, symbols, active_config, next_full_poll_at):
                    features = _poll_once(runtime, client, symbols, args.allow_testnet_orders, args.dry_run)
                    if features is not None:
                        _safe_dashboard(lambda: write_lifecycle(active_config.storage.sqlite_path, "running"))
                        _safe_dashboard(lambda: write_snapshot(runtime, symbols, features, client.now()))
                    next_full_poll_at = _next_poll_time_after_full_poll(runtime, client, symbols, active_config)
                if args.once:
                    return 0
                time.sleep(_next_sleep_seconds(client.now(), next_full_poll_at, active_config))
        except Exception as exc:
            _record_runner_fatal(store, exc)
            _safe_dashboard(lambda: write_lifecycle(active_config.storage.sqlite_path, "error"))
            raise


def _build_client(config, store: LiveStateStore, symbols: list[str]) -> HyperliquidClient | None:
    try:
        return HyperliquidClient(config)
    except Exception as exc:
        if not _is_recoverable_poll_network_error(exc):
            raise
        _record_recoverable_network_error(store, symbols, exc, event_time=pd.Timestamp.now(tz="UTC"))
        print(f"{_display_time(pd.Timestamp.now(tz='UTC'))} [WARN] live startup network error; waiting for next cycle")
        return None


def _poll_once(runtime: LiveRuntime, client: HyperliquidClient, symbols: list[str], cli_allow_testnet_orders: bool, dry_run: bool) -> dict | None:
    allow_orders = runtime.can_place_orders(cli_allow_testnet_orders)
    updates: list[str] = []
    def emit(message: str) -> None:
        updates.append(message)
        print(message)

    def account_open_orders() -> list:
        try:
            return client.fetch_open_orders()
        except TypeError:
            return [order for symbol in symbols for order in client.fetch_open_orders(symbol)]

    def refresh_account_truth() -> tuple[object, list, list | None]:
        refreshed_balance = client.fetch_balance()
        refreshed_positions = client.fetch_positions()
        return refreshed_balance, refreshed_positions, account_open_orders()
    try:
        balance = client.fetch_balance()
        positions = client.fetch_positions()
        features_by_symbol = {symbol: latest_completed_features(client, symbol, runtime.strategy_config) for symbol in symbols}
    except Exception as exc:
        if not _is_recoverable_poll_network_error(exc):
            raise
        _record_recoverable_network_error(runtime.store, symbols, exc, event_time=client.now())
        print(f"{_display_time(client.now())} [WARN] live poll network error; waiting for next cycle")
        return None
    try:
        account_orders = account_open_orders()
    except Exception as exc:
        if not _is_recoverable_poll_network_error(exc):
            raise
        _record_recoverable_network_error(runtime.store, symbols, exc, event_time=client.now())
        print(f"{_display_time(client.now())} [WARN] account open-order truth unavailable; new strategy entries blocked this cycle")
        account_orders = None
    for symbol in symbols:
        poll_time = client.now()
        display_time = _display_time(poll_time)
        features = features_by_symbol[symbol]
        runtime.observe_bandwidth_state(symbol, features[0])
        runtime.update_shadow_outcomes(symbol, features[2])
        runtime.trend_poll(symbol, features[0], features[2], balance, positions)
        for trend_transition in getattr(runtime, "consume_trend_transitions", lambda _symbol: [])(symbol):
            emit(f"{display_time} {trend_transition}")
        for event in runtime.reconcile_symbol(symbol, positions, allow_orders, dry_run):
            emit(f"{display_time} {event}")
        trade = runtime.managed_trade(symbol)
        if trade:
            runtime.record_management_trace(symbol)
            if trade.status != "open" or trade.protection_status != "protected":
                emit(f"{display_time} [CRITICAL] {symbol} managed position protection recovery pending")
                continue
            row_1h = latest_completed_row(features[0], poll_time, "1h")
            row_5m = latest_completed_row(features[2], poll_time, "5m")
            if trade.source == "trend_riding":
                event = runtime.update_trend_trade(trade, features[0], allow_orders, dry_run)
                emit(f"{display_time} {event or f'{symbol} trend position; waiting for completed-1h update'}")
                continue
            state_event = runtime.update_adverse_slope_take_profit(trade, features[0])
            if state_event:
                emit(f"{display_time} {state_event}")
            if trade.adverse_slope_tp_active or trade.special_tp_active:
                try:
                    market_price = client.get_market_price(symbol)
                except Exception as exc:
                    if not _is_recoverable_poll_network_error(exc):
                        raise
                    _record_recoverable_network_error(runtime.store, [symbol], exc, event_time=client.now())
                    emit(f"{display_time} [WARN] {symbol} market-price network error; regime target check skipped; waiting for next cycle")
                else:
                    tp_event = runtime.maybe_close_adverse_slope_take_profit(trade, market_price, allow_orders, dry_run)
                    if tp_event:
                        emit(f"{display_time} {tp_event}")
                        if runtime.managed_trade(symbol) is None:
                            continue
            event = runtime.update_stop(trade, row_1h, row_5m, allow_orders, dry_run) if row_1h is not None and row_5m is not None else None
            if trade.adverse_slope_tp_active:
                waiting = f"[EXSPECIAL] {symbol} managed position; trailing updates frozen; waiting for defensive half-band exit or protective stop"
            elif trade.special_tp_active:
                waiting = f"[SPECIAL] {symbol} managed position; waiting for rolling 1h middle TP or protective stop"
            else:
                waiting = f"{symbol} managed position; waiting for trailing-stop update"
            emit(f"{display_time} {event or waiting}")
            if trade.source == "strategy":
                takeover_event = runtime.maybe_open_trend_trade(
                    symbol, features[0], features[2], balance, allow_orders, dry_run, positions, account_orders,
                )
                for trend_transition in getattr(runtime, "consume_trend_transitions", lambda _symbol: [])(symbol):
                    emit(f"{display_time} {trend_transition}")
                if takeover_event:
                    emit(f"{display_time} {takeover_event}")
                    if runtime.consume_account_mutation():
                        try:
                            balance, positions, account_orders = refresh_account_truth()
                        except Exception as exc:
                            if not _is_recoverable_poll_network_error(exc):
                                raise
                            _record_recoverable_network_error(runtime.store, symbols, exc, event_time=client.now())
                            account_orders = None
                            emit(f"{display_time} [WARN] account refresh unavailable after order-state mutation; later strategy entries blocked this cycle")
            continue
        try:
            trend_event = runtime.maybe_open_trend_trade(symbol, features[0], features[2], balance, allow_orders, dry_run, positions, account_orders)
            for trend_transition in getattr(runtime, "consume_trend_transitions", lambda _symbol: [])(symbol):
                emit(f"{display_time} {trend_transition}")
            if trend_event:
                emit(f"{display_time} {trend_event}")
                if runtime.consume_account_mutation():
                    try:
                        balance, positions, account_orders = refresh_account_truth()
                    except Exception as exc:
                        if not _is_recoverable_poll_network_error(exc):
                            raise
                        _record_recoverable_network_error(runtime.store, symbols, exc, event_time=client.now())
                        account_orders = None
                        emit(f"{display_time} [WARN] account refresh unavailable after order-state mutation; later strategy entries blocked this cycle")
                continue
            events = runtime.maybe_open_strategy_trade(
                symbol,
                *features,
                balance,
                allow_orders,
                dry_run,
                exchange_positions=positions,
                account_orders=account_orders,
                account_orders_verified=True,
            )
        except Exception as exc:
            if not _is_recoverable_poll_network_error(exc):
                raise
            _record_recoverable_network_error(runtime.store, [symbol], exc, event_time=client.now())
            emit(f"{display_time} [WARN] {symbol} entry check network error; waiting for next cycle")
            continue
        for event in events:
            emit(f"{display_time} {event}")
        runtime.record_trend_mr_outcome(symbol, events)
        if not events:
            pending_status = getattr(runtime, "trend_local_pending_status", lambda _symbol, _features: None)(symbol, features[0])
            emit(f"{display_time} {pending_status or f'{symbol} waiting for 1h setup'}")
        if runtime.consume_account_mutation():
            try:
                balance, positions, account_orders = refresh_account_truth()
            except Exception as exc:
                if not _is_recoverable_poll_network_error(exc):
                    raise
                _record_recoverable_network_error(runtime.store, symbols, exc, event_time=client.now())
                account_orders = None
                emit(f"{display_time} [WARN] account refresh unavailable after order-state mutation; later strategy entries blocked this cycle")
    runtime.dashboard_updates = updates
    return features_by_symbol


def _safe_dashboard(action) -> None:
    try:
        action()
    except Exception:
        print("[WARN] dashboard observation unavailable; live runner continues")


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
    return (
        any(runtime.managed_trade(symbol) for symbol in symbols)
        or any(symbol in runtime.setups for symbol in symbols)
        or any(runtime.store.trend_pending(symbol) is not None for symbol in symbols)
        or any(runtime.store.open_trend_shadow_trade(symbol) is not None for symbol in symbols)
    )


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
        _record_recoverable_network_error(runtime.store, symbols, exc, event_time=client.now())
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
    if any(runtime.trend_active(symbol) for symbol in symbols):
        return now.floor("5min") + pd.Timedelta(minutes=5, seconds=config.execution.idle_candle_grace_seconds)
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


def _wallet_fingerprint(config) -> str:
    wallet = os.environ.get(config.exchange.wallet_address_env)
    if not wallet or not wallet.strip():
        raise ValueError("wallet address is required for runner identity")
    material = f"bbmr-live-v1:{config.exchange.env}:{wallet.strip().lower()}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _simulation_config(config):
    simulated = copy.deepcopy(config)
    production = Path(config.storage.sqlite_path).expanduser().resolve()
    simulated_path = production.parent / f"{production.name}.dry-run" / production.name
    if simulated_path == production:
        raise RuntimeError("dry-run storage path must differ from production storage path")
    simulated.storage.sqlite_path = str(simulated_path)
    return simulated


def _simulation_fingerprint(fingerprint: str) -> str:
    return hashlib.sha256(f"bbmr-dry-run:{fingerprint}".encode("utf-8")).hexdigest()


def _record_runner_fatal(store: LiveStateStore, exc: Exception) -> None:
    try:
        store.append_event(
            "runner_fatal",
            "runner",
            event_time=pd.Timestamp.now(tz="UTC"),
            payload_json=json.dumps({"severity": "CRITICAL", "reason": f"unhandled {exc.__class__.__name__}"}, sort_keys=True),
        )
    except Exception:
        pass


@contextmanager
def _wallet_identity_lock(fingerprint: str):
    lock_path = Path(tempfile.gettempdir()) / "bbmr-live-runner-locks" / f"{fingerprint}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("live runner already running for wallet identity") from exc
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


def _record_recoverable_network_error(store: LiveStateStore, symbols: list[str], exc: Exception, event_time) -> None:
    payload = json.dumps({"severity": "WARN", "reason": f"{exc.__class__.__name__}: {exc}"}, sort_keys=True)
    for symbol in symbols:
        store.append_event("recoverable_network_error", symbol, event_time=event_time, payload_json=payload)


if __name__ == "__main__":
    raise SystemExit(main())
