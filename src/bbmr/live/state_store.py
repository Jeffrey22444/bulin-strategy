import sqlite3
import uuid
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


@dataclass
class LiveTrade:
    internal_trade_id: str
    exchange_position_key: str
    symbol: str
    side: str
    qty: float
    entry_price: float
    source: str
    status: str
    initial_stop_loss: float
    current_stop_loss: float
    system_stop_order_id: str | None = None
    protection_status: str = "unprotected"
    protection_verified_at: pd.Timestamp | None = None
    protection_reason: str | None = None
    entry_time: pd.Timestamp | None = None
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    realized_pnl: float | None = None
    fees: float | None = None
    pnl_source: str = "unknown"
    setup_trigger_time: pd.Timestamp | None = None
    setup_rsi_15m: float | None = None
    confirm_15m_time: pd.Timestamp | None = None
    trailing_stage: int = 0
    midband_follow_bucket_start: pd.Timestamp | None = None
    adverse_slope_tp_active: bool = False
    adverse_slope_tp_bucket_start: pd.Timestamp | None = None
    adverse_slope_tp_price: float | None = None
    entry_slope_state: str | None = None
    last_valid_slope_state: str | None = None
    special_tp_active: bool = False
    special_tp_bucket_start: pd.Timestamp | None = None
    special_tp_price: float | None = None
    trailing_frozen: bool = False
    trend_break_even: bool = False


@dataclass
class LivePendingSetup:
    symbol: str
    side: str
    status: str
    trigger_time: pd.Timestamp
    expiry_time: pd.Timestamp
    setup_rsi_15m: float | None
    confirmation_after: pd.Timestamp | None
    confirmed_15m: bool
    confirm_15m_time: pd.Timestamp | None
    close_1h: float
    lb_1h: float
    mb_1h: float
    ub_1h: float
    rsi_1h: float
    created_at: str
    updated_at: str


@dataclass
class LiveShadowTrigger:
    trigger_id: str
    symbol: str
    side: str
    trigger_type: str
    trigger_time: pd.Timestamp
    expiry_time: pd.Timestamp
    setup_trigger_time: pd.Timestamp
    entry_price: float
    setup_close: float
    no_chase_boundary: float
    mfe: float = 0.0
    mae: float = 0.0
    status: str = "open"


@dataclass
class TrendShadowTrade:
    shadow_trade_id: str
    symbol: str
    side: str
    status: str
    entry_time: pd.Timestamp
    entry_price: float
    qty: float
    notional: float
    initial_stop_loss: float
    current_stop_loss: float
    candidate_bucket: pd.Timestamp
    last_1h_bucket: pd.Timestamp | None = None
    last_5m_bucket: pd.Timestamp | None = None
    favorable_price: float | None = None
    break_even: bool = False
    weakening: bool = False
    mfe_pct: float = 0.0
    mae_pct: float = 0.0
    entry_snapshot_json: str = "{}"


@dataclass
class TrendPendingOrder:
    pending_id: str
    symbol: str
    side: str
    mode: str
    status: str
    episode_bucket: pd.Timestamp
    frozen_close: float
    limit_price: float
    requested_qty: float
    notional: float
    stop_distance_pct: float
    exchange_order_id: str | None = None
    client_order_id: str | None = None
    last_1h_bucket: pd.Timestamp | None = None
    last_5m_bucket: pd.Timestamp | None = None
    cancel_reason: str | None = None
    entry_snapshot_json: str = "{}"
    created_at: str = ""
    updated_at: str = ""
    expires_at: pd.Timestamp | None = None
    takeover_phase: str | None = None
    takeover_trade_id: str | None = None
    takeover_side: str | None = None
    takeover_close_order_id: str | None = None
    takeover_close_attempted: bool = False


@dataclass
class StopReplacementIntent:
    internal_trade_id: str
    old_stop_order_id: str | None
    replacement_client_id: str
    symbol: str
    side: str
    qty: float
    trigger_price: float
    new_stop_order_id: str | None = None
    create_attempted: bool = False
    phase: str = "create_pending"
    reason: str | None = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class MREntryIntent:
    intent_id: str
    account_id: str
    symbol: str
    side: str
    setup_trigger_time: pd.Timestamp
    trigger_bucket: pd.Timestamp
    requested_qty: float
    notional: float
    leverage: int
    margin_reservation: float
    reference_price: float
    ioc_boundary_price: float
    client_order_id: str
    exchange_order_id: str | None = None
    submit_attempted: bool = False
    status: str = "prepared"
    reason: str | None = None
    created_at: str = ""
    updated_at: str = ""


class LiveStateStore:
    def __init__(self, path: str, *, identity_fingerprint: str | None = None, environment: str | None = None, bind_legacy_identity: bool = False):
        self.path = path
        self.identity_fingerprint: str | None = None
        self.environment: str | None = None
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self._bind_identity(identity_fingerprint, environment, bind_legacy_identity)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS live_trades (
                internal_trade_id TEXT PRIMARY KEY,
                exchange_position_key TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL NOT NULL,
                entry_price REAL NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                initial_stop_loss REAL NOT NULL,
                current_stop_loss REAL NOT NULL,
                system_stop_order_id TEXT,
                close_reason TEXT
            )
            """
        )
        self._ensure_trade_columns()
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS live_pending_setups (
                symbol TEXT PRIMARY KEY,
                side TEXT NOT NULL,
                status TEXT NOT NULL,
                trigger_time TEXT NOT NULL,
                expiry_time TEXT NOT NULL,
                setup_rsi_15m REAL NOT NULL,
                confirmation_after TEXT,
                confirmed_15m INTEGER NOT NULL,
                confirm_15m_time TEXT,
                close_1h REAL NOT NULL,
                lb_1h REAL NOT NULL,
                mb_1h REAL NOT NULL,
                ub_1h REAL NOT NULL,
                rsi_1h REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS live_trade_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT,
                internal_trade_id TEXT,
                setup_trigger_time TEXT,
                event_time TEXT NOT NULL,
                payload_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS live_stop_replacements (
                internal_trade_id TEXT PRIMARY KEY,
                old_stop_order_id TEXT,
                replacement_client_id TEXT NOT NULL UNIQUE,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL NOT NULL,
                trigger_price REAL NOT NULL,
                new_stop_order_id TEXT,
                create_attempted INTEGER NOT NULL DEFAULT 0,
                phase TEXT NOT NULL CHECK(phase IN ('create_pending', 'cancel_pending')),
                reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS live_mr_entry_intents (
                intent_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                setup_trigger_time TEXT NOT NULL,
                trigger_bucket TEXT NOT NULL,
                requested_qty REAL NOT NULL,
                notional REAL NOT NULL,
                leverage INTEGER NOT NULL,
                margin_reservation REAL NOT NULL,
                reference_price REAL NOT NULL,
                ioc_boundary_price REAL NOT NULL,
                client_order_id TEXT NOT NULL UNIQUE,
                exchange_order_id TEXT,
                submit_attempted INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL CHECK(status IN ('prepared', 'submitted', 'ambiguous', 'filled', 'terminal_no_fill')),
                reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(account_id, symbol, side, setup_trigger_time, trigger_bucket)
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS live_shadow_triggers (
                trigger_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_time TEXT NOT NULL,
                expiry_time TEXT NOT NULL,
                setup_trigger_time TEXT NOT NULL,
                entry_price REAL NOT NULL,
                setup_close REAL NOT NULL,
                no_chase_boundary REAL NOT NULL,
                mfe REAL NOT NULL DEFAULT 0,
                mae REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'open',
                UNIQUE(symbol, side, trigger_type, trigger_time, setup_trigger_time)
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS live_trend_shadow_trades (
                shadow_trade_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, side TEXT NOT NULL,
                status TEXT NOT NULL, entry_time TEXT NOT NULL, entry_price REAL NOT NULL,
                qty REAL NOT NULL, notional REAL NOT NULL, initial_stop_loss REAL NOT NULL,
                current_stop_loss REAL NOT NULL, candidate_bucket TEXT NOT NULL,
                last_1h_bucket TEXT, last_5m_bucket TEXT, favorable_price REAL,
                break_even INTEGER NOT NULL DEFAULT 0, weakening INTEGER NOT NULL DEFAULT 0,
                mfe_pct REAL NOT NULL DEFAULT 0, mae_pct REAL NOT NULL DEFAULT 0,
                exit_time TEXT, exit_price REAL, exit_reason TEXT, gross_pnl REAL,
                cost_estimate REAL, net_pnl_estimate REAL, simulated_completed_candle TEXT,
                baseline_start_event_id INTEGER, baseline_end_event_id INTEGER,
                baseline_valid_until TEXT, entry_snapshot_json TEXT NOT NULL,
                baseline_end_snapshot_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS live_trend_pending_orders (
                pending_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN (
                    'intent', 'open', 'cancel_requested', 'filled',
                    'canceled', 'rejected', 'ambiguous'
                )),
                episode_bucket TEXT NOT NULL,
                frozen_close REAL NOT NULL,
                limit_price REAL NOT NULL,
                requested_qty REAL NOT NULL,
                notional REAL NOT NULL,
                stop_distance_pct REAL NOT NULL,
                exchange_order_id TEXT,
                client_order_id TEXT,
                last_1h_bucket TEXT,
                last_5m_bucket TEXT,
                cancel_reason TEXT,
                entry_snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT,
                takeover_phase TEXT,
                takeover_trade_id TEXT,
                takeover_side TEXT,
                takeover_close_order_id TEXT,
                takeover_close_attempted INTEGER NOT NULL DEFAULT 0,
                UNIQUE(symbol, side, episode_bucket)
            )
            """
        )
        self._ensure_event_columns()
        self._ensure_stop_replacement_columns()
        self._ensure_trend_shadow_columns()
        self._ensure_trend_pending_columns()
        self._ensure_active_trade_unique()
        self.connection.commit()

    def _bind_identity(self, fingerprint: str | None, environment: str | None, bind_legacy_identity: bool) -> None:
        if fingerprint is None:
            return
        if not environment:
            raise ValueError("environment is required for runner identity")
        tables = {
            row["name"]
            for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
        }
        if "live_store_identity" in tables:
            row = self.connection.execute("SELECT fingerprint, environment FROM live_store_identity WHERE singleton = 1").fetchone()
            if row is None or row["fingerprint"] != fingerprint or row["environment"] != environment:
                raise RuntimeError("SQLite identity mismatch")
            self.identity_fingerprint = fingerprint
            self.environment = environment
            return
        if self._legacy_has_content(tables):
            if not bind_legacy_identity:
                raise RuntimeError("legacy SQLite identity binding requires --bind-legacy-identity")
            self._assert_legacy_bindable(tables)
        self.connection.execute(
            "CREATE TABLE live_store_identity (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), fingerprint TEXT NOT NULL, environment TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        self.connection.execute(
            "INSERT INTO live_store_identity (singleton, fingerprint, environment, created_at) VALUES (1, ?, ?, ?)",
            (fingerprint, environment, _now()),
        )
        self.connection.commit()
        self.identity_fingerprint = fingerprint
        self.environment = environment

    def _legacy_has_content(self, tables: set[str]) -> bool:
        for table in tables:
            if self.connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None:
                return True
        return False

    def _assert_legacy_bindable(self, tables: set[str]) -> None:
        if "live_trades" in tables and self.connection.execute("SELECT 1 FROM live_trades WHERE status IN ('open', 'entry_unprotected', 'exit_cleanup') LIMIT 1").fetchone():
            raise RuntimeError("legacy SQLite has active trades")
        if "live_trend_pending_orders" in tables and self.connection.execute("SELECT 1 FROM live_trend_pending_orders WHERE status IN ('intent', 'open', 'cancel_requested', 'ambiguous') LIMIT 1").fetchone():
            raise RuntimeError("legacy SQLite has non-terminal pending orders")

    def _ensure_active_trade_unique(self) -> None:
        duplicate = self.connection.execute(
            "SELECT exchange_position_key FROM live_trades WHERE status IN ('open', 'entry_unprotected', 'exit_cleanup') GROUP BY exchange_position_key HAVING COUNT(*) > 1 LIMIT 1"
        ).fetchone()
        if duplicate is not None:
            raise RuntimeError("SQLite has duplicate active exchange positions")
        self.connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS live_trades_active_position_unique ON live_trades(exchange_position_key) WHERE status IN ('open', 'entry_unprotected', 'exit_cleanup')"
        )

    def create_trade(
        self,
        exchange_position_key: str,
        symbol: str,
        side: str,
        qty: float,
        entry_price: float,
        source: str,
        initial_stop_loss: float,
        *,
        entry_time=None,
        setup_trigger_time=None,
        setup_rsi_15m: float | None = None,
        confirm_15m_time=None,
        entry_slope_state: str | None = None,
        status: str = "open",
    ) -> LiveTrade:
        trade = self._create_trade(
            exchange_position_key,
            symbol,
            side,
            qty,
            entry_price,
            source,
            initial_stop_loss,
            entry_time=entry_time,
            setup_trigger_time=setup_trigger_time,
            setup_rsi_15m=setup_rsi_15m,
            confirm_15m_time=confirm_15m_time,
            entry_slope_state=entry_slope_state,
            status=status,
        )
        self.connection.commit()
        return trade

    def _create_trade(
        self,
        exchange_position_key: str,
        symbol: str,
        side: str,
        qty: float,
        entry_price: float,
        source: str,
        initial_stop_loss: float,
        *,
        entry_time=None,
        setup_trigger_time=None,
        setup_rsi_15m: float | None = None,
        confirm_15m_time=None,
        entry_slope_state: str | None = None,
        status: str = "open",
    ) -> LiveTrade:
        trade = LiveTrade(
            str(uuid.uuid4()),
            exchange_position_key,
            symbol,
            side,
            qty,
            entry_price,
            source,
            status,
            initial_stop_loss,
            initial_stop_loss,
            entry_time=_timestamp(entry_time),
            setup_trigger_time=_timestamp(setup_trigger_time),
            setup_rsi_15m=setup_rsi_15m,
            confirm_15m_time=_timestamp(confirm_15m_time),
            entry_slope_state=entry_slope_state,
        )
        self._insert_trade(trade)
        return trade

    def _insert_trade(self, trade: LiveTrade) -> None:
        self.connection.execute(
            """
            INSERT INTO live_trades
            (internal_trade_id, exchange_position_key, symbol, side, qty, entry_price, source, status, initial_stop_loss, current_stop_loss, system_stop_order_id,
             entry_time, pnl_source, setup_trigger_time, setup_rsi_15m, confirm_15m_time, trailing_stage, midband_follow_bucket_start,
             adverse_slope_tp_active, adverse_slope_tp_bucket_start, adverse_slope_tp_price, entry_slope_state,
             last_valid_slope_state, special_tp_active, special_tp_bucket_start, special_tp_price, trailing_frozen, trend_break_even,
             protection_status, protection_verified_at, protection_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.internal_trade_id, trade.exchange_position_key, trade.symbol, trade.side, trade.qty, trade.entry_price,
                trade.source, trade.status, trade.initial_stop_loss, trade.current_stop_loss, trade.system_stop_order_id,
                _iso(trade.entry_time), trade.pnl_source, _iso(trade.setup_trigger_time), trade.setup_rsi_15m,
                _iso(trade.confirm_15m_time), trade.trailing_stage, _iso(trade.midband_follow_bucket_start),
                int(trade.adverse_slope_tp_active), _iso(trade.adverse_slope_tp_bucket_start), trade.adverse_slope_tp_price,
                trade.entry_slope_state, trade.last_valid_slope_state, int(trade.special_tp_active),
                _iso(trade.special_tp_bucket_start), trade.special_tp_price, int(trade.trailing_frozen), int(trade.trend_break_even),
                trade.protection_status, _iso(trade.protection_verified_at), trade.protection_reason,
            ),
        )

    def create_trade_with_event(self, *args, event_type: str, event_symbol: str, event_kwargs: dict | None = None, **kwargs) -> LiveTrade:
        with self.connection:
            trade = self._create_trade(*args, **kwargs)
            self.append_event(event_type, event_symbol, trade=trade, commit=False, **(event_kwargs or {}))
        return trade

    def open_trade(self, exchange_position_key: str) -> LiveTrade | None:
        row = self.connection.execute(
            "SELECT * FROM live_trades WHERE exchange_position_key = ? AND status IN ('open', 'entry_unprotected', 'exit_cleanup')",
            (exchange_position_key,),
        ).fetchone()
        return _trade(row) if row else None

    def update_trade(self, trade: LiveTrade) -> None:
        self._update_trade(trade)
        self.connection.commit()

    def _update_trade(self, trade: LiveTrade) -> None:
        self.connection.execute(
            """
            UPDATE live_trades
            SET qty = ?, entry_price = ?, status = ?, initial_stop_loss = ?, current_stop_loss = ?, system_stop_order_id = ?, pnl_source = ?,
                trailing_stage = ?, midband_follow_bucket_start = ?, adverse_slope_tp_active = ?, adverse_slope_tp_bucket_start = ?, adverse_slope_tp_price = ?, entry_slope_state = ?,
                last_valid_slope_state = ?, special_tp_active = ?, special_tp_bucket_start = ?, special_tp_price = ?, trailing_frozen = ?, trend_break_even = ?,
                protection_status = ?, protection_verified_at = ?, protection_reason = ?
            WHERE internal_trade_id = ?
            """,
            (
                trade.qty,
                trade.entry_price,
                trade.status,
                trade.initial_stop_loss,
                trade.current_stop_loss,
                trade.system_stop_order_id,
                trade.pnl_source,
                trade.trailing_stage,
                _iso(trade.midband_follow_bucket_start),
                int(trade.adverse_slope_tp_active),
                _iso(trade.adverse_slope_tp_bucket_start),
                trade.adverse_slope_tp_price,
                trade.entry_slope_state,
                trade.last_valid_slope_state,
                int(trade.special_tp_active),
                _iso(trade.special_tp_bucket_start),
                trade.special_tp_price,
                int(trade.trailing_frozen),
                int(trade.trend_break_even),
                trade.protection_status,
                _iso(trade.protection_verified_at),
                trade.protection_reason,
                trade.internal_trade_id,
            ),
        )

    def update_trade_with_event(self, trade: LiveTrade, event_type: str, event_symbol: str, *, event_kwargs: dict | None = None) -> None:
        with self.connection:
            self._update_trade(trade)
            self.append_event(event_type, event_symbol, trade=trade, commit=False, **(event_kwargs or {}))

    def stop_replacement(self, internal_trade_id: str) -> StopReplacementIntent | None:
        row = self.connection.execute(
            "SELECT * FROM live_stop_replacements WHERE internal_trade_id = ?",
            (internal_trade_id,),
        ).fetchone()
        return _stop_replacement(row) if row else None

    def create_stop_replacement_with_event(self, intent: StopReplacementIntent, trade: LiveTrade, event_type: str, *, payload: dict | None = None) -> None:
        now = _now()
        intent.created_at = intent.created_at or now
        intent.updated_at = now
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO live_stop_replacements
                (internal_trade_id, old_stop_order_id, replacement_client_id, symbol, side, qty, trigger_price, new_stop_order_id, create_attempted, phase, reason, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.internal_trade_id, intent.old_stop_order_id, intent.replacement_client_id,
                    intent.symbol, intent.side, intent.qty, intent.trigger_price, intent.new_stop_order_id,
                    int(intent.create_attempted), intent.phase, intent.reason, intent.created_at, intent.updated_at,
                ),
            )
            self.append_event(event_type, trade.symbol, trade=trade, event_time=_timestamp(now), payload_json=json.dumps(payload or {}, sort_keys=True), commit=False)

    def update_stop_replacement_with_event(self, intent: StopReplacementIntent, trade: LiveTrade, event_type: str, *, payload: dict | None = None) -> None:
        intent.updated_at = _now()
        with self.connection:
            self.connection.execute(
                """
                UPDATE live_stop_replacements
                SET old_stop_order_id = ?, replacement_client_id = ?, symbol = ?, side = ?, qty = ?, trigger_price = ?,
                    new_stop_order_id = ?, create_attempted = ?, phase = ?, reason = ?, updated_at = ?
                WHERE internal_trade_id = ?
                """,
                (
                    intent.old_stop_order_id, intent.replacement_client_id, intent.symbol, intent.side,
                    intent.qty, intent.trigger_price, intent.new_stop_order_id, int(intent.create_attempted), intent.phase, intent.reason,
                    intent.updated_at, intent.internal_trade_id,
                ),
            )
            self.append_event(event_type, trade.symbol, trade=trade, event_time=_timestamp(intent.updated_at), payload_json=json.dumps(payload or {}, sort_keys=True), commit=False)

    def promote_stop_replacement_with_event(self, trade: LiveTrade, intent: StopReplacementIntent, event_type: str, *, payload: dict | None = None) -> None:
        with self.connection:
            self._update_trade(trade)
            self.connection.execute("DELETE FROM live_stop_replacements WHERE internal_trade_id = ?", (intent.internal_trade_id,))
            self.append_event(event_type, trade.symbol, trade=trade, event_time=trade.protection_verified_at, payload_json=json.dumps(payload or {}, sort_keys=True), commit=False)

    def create_mr_entry_intent_with_event(self, intent: MREntryIntent, event_type: str = "mr_entry_intent_prepared") -> None:
        now = _now()
        intent.created_at = intent.created_at or now
        intent.updated_at = now
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO live_mr_entry_intents
                (intent_id, account_id, symbol, side, setup_trigger_time, trigger_bucket, requested_qty, notional, leverage,
                 margin_reservation, reference_price, ioc_boundary_price, client_order_id, exchange_order_id, submit_attempted,
                 status, reason, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.intent_id, intent.account_id, intent.symbol, intent.side, _iso(intent.setup_trigger_time), _iso(intent.trigger_bucket),
                    intent.requested_qty, intent.notional, intent.leverage, intent.margin_reservation, intent.reference_price,
                    intent.ioc_boundary_price, intent.client_order_id, intent.exchange_order_id, int(intent.submit_attempted),
                    intent.status, intent.reason, intent.created_at, intent.updated_at,
                ),
            )
            self.append_event(event_type, intent.symbol, side=intent.side, setup_trigger_time=intent.setup_trigger_time, event_time=intent.trigger_bucket, payload_json=json.dumps(_mr_intent_payload(intent), sort_keys=True), commit=False)

    def mr_intent_for_trigger(self, account_id: str, symbol: str, side: str, setup_trigger_time, trigger_bucket) -> MREntryIntent | None:
        row = self.connection.execute(
            """SELECT * FROM live_mr_entry_intents
               WHERE account_id = ? AND symbol = ? AND side = ? AND setup_trigger_time = ? AND trigger_bucket = ?""",
            (account_id, symbol, side, _iso(_timestamp(setup_trigger_time)), _iso(_timestamp(trigger_bucket))),
        ).fetchone()
        return _mr_entry_intent(row) if row else None

    def active_mr_entry_intent(self, symbol: str) -> MREntryIntent | None:
        row = self.connection.execute(
            """SELECT * FROM live_mr_entry_intents
               WHERE symbol = ? AND status IN ('prepared', 'submitted', 'ambiguous')
               ORDER BY created_at DESC LIMIT 1""",
            (symbol,),
        ).fetchone()
        return _mr_entry_intent(row) if row else None

    def active_mr_entry_intents(self) -> list[MREntryIntent]:
        rows = self.connection.execute(
            """SELECT * FROM live_mr_entry_intents
               WHERE status IN ('prepared', 'submitted', 'ambiguous') ORDER BY created_at"""
        ).fetchall()
        return [_mr_entry_intent(row) for row in rows]

    def active_system_stop_order_ids(self) -> set[str]:
        rows = self.connection.execute(
            """SELECT system_stop_order_id FROM live_trades
               WHERE status IN ('open', 'entry_unprotected', 'exit_cleanup') AND system_stop_order_id IS NOT NULL"""
        ).fetchall()
        return {str(row["system_stop_order_id"]) for row in rows if row["system_stop_order_id"] not in (None, "")}

    def update_mr_entry_intent_with_event(self, intent: MREntryIntent, event_type: str) -> None:
        intent.updated_at = _now()
        with self.connection:
            self.connection.execute(
                """
                UPDATE live_mr_entry_intents
                SET exchange_order_id = ?, submit_attempted = ?, status = ?, reason = ?, updated_at = ?
                WHERE intent_id = ?
                """,
                (intent.exchange_order_id, int(intent.submit_attempted), intent.status, intent.reason, intent.updated_at, intent.intent_id),
            )
            self.append_event(event_type, intent.symbol, side=intent.side, setup_trigger_time=intent.setup_trigger_time, event_time=intent.trigger_bucket, payload_json=json.dumps(_mr_intent_payload(intent), sort_keys=True), commit=False)

    def create_trade_and_fill_mr_intent_with_event(self, trade: LiveTrade, intent: MREntryIntent) -> None:
        intent.status = "filled"
        intent.reason = None
        intent.updated_at = _now()
        with self.connection:
            self._insert_trade(trade)
            self.connection.execute(
                "UPDATE live_mr_entry_intents SET status = ?, reason = ?, updated_at = ? WHERE intent_id = ?",
                (intent.status, intent.reason, intent.updated_at, intent.intent_id),
            )
            self.append_event("entry_unprotected", trade.symbol, trade=trade, setup_trigger_time=trade.setup_trigger_time, event_time=intent.trigger_bucket, payload_json=json.dumps(_severity_payload_for_store("CRITICAL", reason="entry fill awaiting protective stop"), sort_keys=True), commit=False)
            self.append_event("mr_entry_intent_filled", intent.symbol, side=intent.side, setup_trigger_time=intent.setup_trigger_time, event_time=intent.trigger_bucket, payload_json=json.dumps(_mr_intent_payload(intent), sort_keys=True), commit=False)

    def has_protection_recovery(self) -> bool:
        return self.connection.execute(
        "SELECT 1 FROM live_stop_replacements LIMIT 1"
    ).fetchone() is not None or self.connection.execute(
        "SELECT 1 FROM live_trades WHERE status != 'closed' AND "
        "(status = 'entry_unprotected' OR protection_status IN ('recovery', 'unknown')) LIMIT 1"
    ).fetchone() is not None

    def archive_trade(self, trade: LiveTrade, reason: str, *, exit_time=None, exit_price: float | None = None, realized_pnl: float | None = None, fees: float | None = None, pnl_source: str = "unknown") -> None:
        self._archive_trade(
            trade,
            reason,
            exit_time=exit_time,
            exit_price=exit_price,
            realized_pnl=realized_pnl,
            fees=fees,
            pnl_source=pnl_source,
        )
        self.connection.commit()

    def _archive_trade(self, trade: LiveTrade, reason: str, *, exit_time=None, exit_price: float | None = None, realized_pnl: float | None = None, fees: float | None = None, pnl_source: str = "unknown") -> None:
        self.connection.execute(
            """
            UPDATE live_trades
            SET status = 'closed', close_reason = ?, exit_time = ?, exit_price = ?, realized_pnl = ?, fees = ?, pnl_source = ?
            WHERE internal_trade_id = ?
            """,
            (reason, _iso(_timestamp(exit_time)), exit_price, realized_pnl, fees, pnl_source, trade.internal_trade_id),
        )

    def archive_trade_with_event(self, trade: LiveTrade, reason: str, event_type: str, event_symbol: str, *, exit_time=None, exit_price: float | None = None, realized_pnl: float | None = None, fees: float | None = None, pnl_source: str = "unknown", event_kwargs: dict | None = None) -> None:
        with self.connection:
            self._archive_trade(
                trade,
                reason,
                exit_time=exit_time,
                exit_price=exit_price,
                realized_pnl=realized_pnl,
                fees=fees,
                pnl_source=pnl_source,
            )
            self.append_event(event_type, event_symbol, trade=trade, commit=False, **(event_kwargs or {}))

    def save_pending_setup(self, setup) -> None:
        now = _now()
        existing = self.connection.execute("SELECT created_at FROM live_pending_setups WHERE symbol = ?", (setup.symbol,)).fetchone()
        created_at = existing["created_at"] if existing else now
        self.connection.execute(
            """
            INSERT INTO live_pending_setups
            (symbol, side, status, trigger_time, expiry_time, setup_rsi_15m, confirmation_after, confirmed_15m, confirm_15m_time,
             close_1h, lb_1h, mb_1h, ub_1h, rsi_1h, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                side = excluded.side,
                status = excluded.status,
                trigger_time = excluded.trigger_time,
                expiry_time = excluded.expiry_time,
                setup_rsi_15m = excluded.setup_rsi_15m,
                confirmation_after = excluded.confirmation_after,
                confirmed_15m = excluded.confirmed_15m,
                confirm_15m_time = excluded.confirm_15m_time,
                close_1h = excluded.close_1h,
                lb_1h = excluded.lb_1h,
                mb_1h = excluded.mb_1h,
                ub_1h = excluded.ub_1h,
                rsi_1h = excluded.rsi_1h,
                updated_at = excluded.updated_at
            """,
            (
                setup.symbol,
                setup.side,
                setup.status,
                _iso(setup.trigger_time),
                _iso(setup.expiry_time),
                _stored_setup_rsi(setup.setup_rsi_15m),
                _iso(setup.confirmation_after),
                int(setup.confirmed_15m),
                _iso(setup.confirm_15m_time),
                setup.close_1h,
                setup.lb_1h,
                setup.mb_1h,
                setup.ub_1h,
                setup.rsi_1h,
                created_at,
                now,
            ),
        )
        self.connection.commit()

    def load_pending_setups(self, now) -> list[LivePendingSetup]:
        now_ts = _timestamp(now)
        rows = self.connection.execute("SELECT * FROM live_pending_setups WHERE status = 'pending'").fetchall()
        return [setup for setup in (_pending_setup(row) for row in rows) if setup.expiry_time > now_ts]

    def expire_pending_setups(self, now) -> None:
        now_ts = _timestamp(now)
        rows = self.connection.execute("SELECT symbol, expiry_time FROM live_pending_setups WHERE status = 'pending'").fetchall()
        for row in rows:
            if _timestamp(row["expiry_time"]) <= now_ts:
                self.connection.execute(
                    "UPDATE live_pending_setups SET status = 'expired', updated_at = ? WHERE symbol = ?",
                    (_now(), row["symbol"]),
                )
        self.connection.commit()

    def delete_pending_setup(self, symbol: str) -> None:
        self.connection.execute("DELETE FROM live_pending_setups WHERE symbol = ?", (symbol,))
        self.connection.commit()

    def append_event(self, event_type: str, symbol: str, *, side: str | None = None, trade: LiveTrade | None = None, shadow_trade_id: str | None = None, setup_trigger_time=None, event_time=None, payload_json: str | None = None, commit: bool = True) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO live_trade_events
            (event_type, symbol, side, internal_trade_id, shadow_trade_id, setup_trigger_time, event_time, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                symbol,
                side or (trade.side if trade else None),
                trade.internal_trade_id if trade else None,
                shadow_trade_id,
                _iso(_timestamp(setup_trigger_time)),
                _iso(_timestamp(event_time)) or _now(),
                payload_json,
                _now(),
            ),
        )
        if commit:
            self.connection.commit()
        return int(cursor.lastrowid)

    def open_trend_shadow_trade(self, symbol: str) -> TrendShadowTrade | None:
        row = self.connection.execute("SELECT * FROM live_trend_shadow_trades WHERE symbol = ? AND status = 'open'", (symbol,)).fetchone()
        return _trend_shadow_trade(row) if row else None

    def trend_shadow_status(self, symbol: str) -> dict | None:
        row = self.connection.execute("SELECT baseline_valid_until,current_stop_loss,break_even,weakening,status,net_pnl_estimate,actual_mr_result_json FROM live_trend_shadow_trades WHERE symbol = ? AND status = 'open'", (symbol,)).fetchone()
        return None if row is None else dict(row)

    def record_trend_shadow_mr_result(self, symbol: str, payload: dict) -> None:
        with self.connection:
            self.connection.execute("UPDATE live_trend_shadow_trades SET actual_mr_result_json = ?, updated_at = ? WHERE symbol = ? AND status = 'open'", (json.dumps(payload, sort_keys=True), _now(), symbol))

    def trend_shadow_baseline(self, symbol: str, *, close: bool = False) -> dict | None:
        column = "baseline_end_snapshot_json" if close else "entry_snapshot_json"
        row = self.connection.execute(f"SELECT {column},actual_mr_result_json FROM live_trend_shadow_trades WHERE symbol = ? AND status = 'open'", (symbol,)).fetchone()
        if not row:
            return None
        return {"snapshot": json.loads(row[column] or "{}"), "actual_mr_result": json.loads(row["actual_mr_result_json"] or "{\"status\": \"pending\"}")}

    def create_trend_shadow_trade(self, trade: TrendShadowTrade, payload: dict) -> None:
        now = _now()
        with self.connection:
            baseline_id = self.connection.execute("SELECT COALESCE(MAX(event_id), 0) FROM live_trade_events").fetchone()[0]
            self.connection.execute(
                """INSERT INTO live_trend_shadow_trades
                (shadow_trade_id,symbol,side,status,entry_time,entry_price,qty,notional,initial_stop_loss,current_stop_loss,candidate_bucket,last_1h_bucket,last_5m_bucket,favorable_price,break_even,weakening,mfe_pct,mae_pct,baseline_start_event_id,entry_snapshot_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (trade.shadow_trade_id,trade.symbol,trade.side,trade.status,_iso(trade.entry_time),trade.entry_price,trade.qty,trade.notional,trade.initial_stop_loss,trade.current_stop_loss,_iso(trade.candidate_bucket),_iso(trade.last_1h_bucket),_iso(trade.last_5m_bucket),trade.favorable_price,int(trade.break_even),int(trade.weakening),trade.mfe_pct,trade.mae_pct,baseline_id,trade.entry_snapshot_json,now,now),
            )
            self.append_event("trend_shadow_opened", trade.symbol, side=trade.side, shadow_trade_id=trade.shadow_trade_id, event_time=trade.entry_time, payload_json=json.dumps(payload, sort_keys=True, default=str), commit=False)

    def update_trend_shadow_trade(self, trade: TrendShadowTrade, event_type: str | None = None, payload: dict | None = None, event_time=None) -> None:
        with self.connection:
            self.connection.execute(
                """UPDATE live_trend_shadow_trades SET status=?,current_stop_loss=?,last_1h_bucket=?,last_5m_bucket=?,favorable_price=?,break_even=?,weakening=?,mfe_pct=?,mae_pct=?,updated_at=? WHERE shadow_trade_id=?""",
                (trade.status,trade.current_stop_loss,_iso(trade.last_1h_bucket),_iso(trade.last_5m_bucket),trade.favorable_price,int(trade.break_even),int(trade.weakening),trade.mfe_pct,trade.mae_pct,_now(),trade.shadow_trade_id),
            )
            if event_type:
                self.append_event(event_type, trade.symbol, side=trade.side, shadow_trade_id=trade.shadow_trade_id, event_time=event_time, payload_json=json.dumps(payload or {}, sort_keys=True), commit=False)

    def close_trend_shadow_trade(self, trade: TrendShadowTrade, reason: str, exit_price: float, event_time, payload: dict) -> None:
        gross = (exit_price - trade.entry_price) * trade.qty * (1 if trade.side == "long" else -1)
        try:
            assumptions = json.loads(trade.entry_snapshot_json).get("cost_assumptions", {})
            entry_bps = float(assumptions.get("entry_fee_bps", assumptions.get("maker_fee_bps", 0)))
            exit_bps = float(assumptions.get("exit_fee_bps", assumptions.get("taker_fee_bps", 0))) + float(assumptions.get("slippage_bps", 0))
        except (TypeError, ValueError, json.JSONDecodeError):
            entry_bps = exit_bps = 0.0
        cost = (trade.notional * entry_bps + abs(exit_price * trade.qty) * exit_bps) / 10000
        with self.connection:
            end_id = self.connection.execute("SELECT COALESCE(MAX(event_id), 0) FROM live_trade_events").fetchone()[0]
            self.connection.execute("UPDATE live_trend_shadow_trades SET status='closed',exit_time=?,exit_price=?,exit_reason=?,gross_pnl=?,cost_estimate=?,net_pnl_estimate=?,baseline_end_event_id=?,baseline_end_snapshot_json=?,updated_at=? WHERE shadow_trade_id=?", (_iso(event_time),exit_price,reason,gross,cost,gross-cost,end_id,json.dumps(payload.get("baseline_end", {}),sort_keys=True),_now(),trade.shadow_trade_id))
            self.append_event("trend_shadow_closed",trade.symbol,side=trade.side,shadow_trade_id=trade.shadow_trade_id,event_time=event_time,payload_json=json.dumps({**payload,"reason":reason,"gross_pnl":gross,"cost_estimate":cost,"net_pnl_estimate":gross-cost,"cost_assumptions":assumptions if 'assumptions' in locals() else {},"simulated_completed_candle":True},sort_keys=True),commit=False)

    def create_trend_pending(self, pending: TrendPendingOrder) -> bool:
        now = _now()
        pending.created_at = pending.created_at or now
        pending.updated_at = pending.updated_at or pending.created_at
        cursor = self.connection.execute(
            """
            INSERT INTO live_trend_pending_orders
            (pending_id, symbol, side, mode, status, episode_bucket, frozen_close,
             limit_price, requested_qty, notional, stop_distance_pct,
             exchange_order_id, client_order_id, last_1h_bucket, last_5m_bucket,
             cancel_reason, entry_snapshot_json, created_at, updated_at, expires_at,
             takeover_phase, takeover_trade_id, takeover_side, takeover_close_order_id, takeover_close_attempted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT DO NOTHING
            """,
            (
                pending.pending_id,
                pending.symbol,
                pending.side,
                pending.mode,
                pending.status,
                _iso(pending.episode_bucket),
                pending.frozen_close,
                pending.limit_price,
                pending.requested_qty,
                pending.notional,
                pending.stop_distance_pct,
                pending.exchange_order_id,
                pending.client_order_id,
                _iso(pending.last_1h_bucket),
                _iso(pending.last_5m_bucket),
                pending.cancel_reason,
                pending.entry_snapshot_json,
                pending.created_at,
                pending.updated_at,
                _iso(pending.expires_at),
                pending.takeover_phase,
                pending.takeover_trade_id,
                pending.takeover_side,
                pending.takeover_close_order_id,
                int(pending.takeover_close_attempted),
            ),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def trend_pending(self, symbol: str) -> TrendPendingOrder | None:
        row = self.connection.execute(
            """
            SELECT * FROM live_trend_pending_orders
            WHERE symbol = ?
              AND status IN ('intent', 'open', 'cancel_requested', 'ambiguous')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
        return _trend_pending_order(row) if row else None

    def trend_pending_for_episode(self, symbol: str, side: str, episode_bucket) -> TrendPendingOrder | None:
        row = self.connection.execute(
            """
            SELECT * FROM live_trend_pending_orders
            WHERE symbol = ? AND side = ? AND episode_bucket = ?
            """,
            (symbol, side, _iso(_timestamp(episode_bucket))),
        ).fetchone()
        return _trend_pending_order(row) if row else None

    def update_trend_pending(
        self,
        pending: TrendPendingOrder,
        event_type: str | None = None,
        payload: dict | None = None,
    ) -> None:
        pending.updated_at = _now()
        with self.connection:
            self.connection.execute(
                """
                UPDATE live_trend_pending_orders
                SET status = ?, frozen_close = ?, limit_price = ?, requested_qty = ?,
                    notional = ?, stop_distance_pct = ?, exchange_order_id = ?,
                    client_order_id = ?, last_1h_bucket = ?, last_5m_bucket = ?,
                    cancel_reason = ?, entry_snapshot_json = ?, updated_at = ?, expires_at = ?,
                    takeover_phase = ?, takeover_trade_id = ?, takeover_side = ?,
                    takeover_close_order_id = ?, takeover_close_attempted = ?
                WHERE pending_id = ?
                """,
                (
                    pending.status,
                    pending.frozen_close,
                    pending.limit_price,
                    pending.requested_qty,
                    pending.notional,
                    pending.stop_distance_pct,
                    pending.exchange_order_id,
                    pending.client_order_id,
                    _iso(pending.last_1h_bucket),
                    _iso(pending.last_5m_bucket),
                    pending.cancel_reason,
                    pending.entry_snapshot_json,
                    pending.updated_at,
                    _iso(pending.expires_at),
                    pending.takeover_phase,
                    pending.takeover_trade_id,
                    pending.takeover_side,
                    pending.takeover_close_order_id,
                    int(pending.takeover_close_attempted),
                    pending.pending_id,
                ),
            )
            if event_type:
                event_payload = {**(payload or {}), "pending_id": pending.pending_id}
                self.append_event(
                    event_type,
                    pending.symbol,
                    side=pending.side,
                    event_time=pending.updated_at,
                    payload_json=json.dumps(event_payload, sort_keys=True, default=str),
                    commit=False,
                )

    def active_trend_pendings(self) -> list[TrendPendingOrder]:
        rows = self.connection.execute(
            """
            SELECT * FROM live_trend_pending_orders
            WHERE status IN ('intent', 'open', 'cancel_requested', 'ambiguous')
            ORDER BY created_at
            """
        ).fetchall()
        return [_trend_pending_order(row) for row in rows]

    def trend_shadow_baseline_trades(self, symbol: str, start, end) -> list[dict]:
        rows = self.connection.execute(
            """SELECT internal_trade_id,status,source,close_reason,realized_pnl,fees,pnl_source,entry_time,exit_time
               FROM live_trades WHERE symbol = ?
               AND entry_time IS NOT NULL AND entry_time <= ?
               AND (exit_time IS NULL OR exit_time >= ?)""",
            (symbol, _iso(end), _iso(start)),
        ).fetchall()
        return [{"internal_trade_id": row["internal_trade_id"], "status": row["status"], "source": row["source"], "close_reason": row["close_reason"], "realized_pnl": row["realized_pnl"], "fees": row["fees"], "pnl_source": row["pnl_source"], "baseline_status": "unresolved" if row["status"] != "closed" else "resolved"} for row in rows]

    def truncate_trend_shadow_baseline(self, when) -> None:
        rows = self.connection.execute("SELECT shadow_trade_id,symbol,side FROM live_trend_shadow_trades WHERE status='open' AND baseline_valid_until IS NULL").fetchall()
        with self.connection:
            for row in rows:
                self.connection.execute("UPDATE live_trend_shadow_trades SET baseline_valid_until=?,updated_at=? WHERE shadow_trade_id=?", (_iso(when),_now(),row["shadow_trade_id"]))
                self.append_event("trend_shadow_baseline_truncated",row["symbol"],side=row["side"],shadow_trade_id=row["shadow_trade_id"],event_time=when,payload_json=json.dumps({"baseline_valid_until":_iso(when)},sort_keys=True),commit=False)

    def has_event(self, event_type: str, symbol: str, event_time, *, setup_trigger_time=None) -> bool:
        row = self.connection.execute(
            """
            SELECT 1 FROM live_trade_events
            WHERE event_type = ? AND symbol = ? AND event_time = ?
              AND (setup_trigger_time IS ? OR setup_trigger_time = ?)
            LIMIT 1
            """,
            (event_type, symbol, _iso(_timestamp(event_time)), _iso(_timestamp(setup_trigger_time)), _iso(_timestamp(setup_trigger_time))),
        ).fetchone()
        return row is not None

    def has_trade_event(self, internal_trade_id: str, event_type: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM live_trade_events WHERE internal_trade_id = ? AND event_type = ? LIMIT 1",
            (internal_trade_id, event_type),
        ).fetchone() is not None

    def record_shadow_trigger(self, trigger: LiveShadowTrigger) -> bool:
        cursor = self.connection.execute(
            """
            INSERT INTO live_shadow_triggers
            (trigger_id, symbol, side, trigger_type, trigger_time, expiry_time, setup_trigger_time, entry_price, setup_close, no_chase_boundary, mfe, mae, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, side, trigger_type, trigger_time, setup_trigger_time) DO NOTHING
            """,
            (
                trigger.trigger_id,
                trigger.symbol,
                trigger.side,
                trigger.trigger_type,
                _iso(trigger.trigger_time),
                _iso(trigger.expiry_time),
                _iso(trigger.setup_trigger_time),
                trigger.entry_price,
                trigger.setup_close,
                trigger.no_chase_boundary,
                trigger.mfe,
                trigger.mae,
                trigger.status,
            ),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def open_shadow_triggers(self, symbol: str) -> list[LiveShadowTrigger]:
        rows = self.connection.execute(
            "SELECT * FROM live_shadow_triggers WHERE symbol = ? AND status = 'open' ORDER BY trigger_time",
            (symbol,),
        ).fetchall()
        return [_shadow_trigger(row) for row in rows]

    def update_shadow_trigger(self, trigger: LiveShadowTrigger) -> None:
        self.connection.execute(
            "UPDATE live_shadow_triggers SET mfe = ?, mae = ?, status = ? WHERE trigger_id = ?",
            (trigger.mfe, trigger.mae, trigger.status, trigger.trigger_id),
        )
        self.connection.commit()

    def events(self) -> list[sqlite3.Row]:
        return self.connection.execute("SELECT * FROM live_trade_events ORDER BY event_id").fetchall()

    def _ensure_trade_columns(self) -> None:
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(live_trades)").fetchall()}
        for name, definition in {
            "entry_time": "TEXT",
            "exit_time": "TEXT",
            "exit_price": "REAL",
            "realized_pnl": "REAL",
            "fees": "REAL",
            "pnl_source": "TEXT NOT NULL DEFAULT 'unknown'",
            "setup_trigger_time": "TEXT",
            "setup_rsi_15m": "REAL",
            "confirm_15m_time": "TEXT",
            "trailing_stage": "INTEGER NOT NULL DEFAULT 0",
            "midband_follow_bucket_start": "TEXT",
            "adverse_slope_tp_active": "INTEGER NOT NULL DEFAULT 0",
            "adverse_slope_tp_bucket_start": "TEXT",
            "adverse_slope_tp_price": "REAL",
            "entry_slope_state": "TEXT",
            "last_valid_slope_state": "TEXT",
            "special_tp_active": "INTEGER NOT NULL DEFAULT 0",
            "special_tp_bucket_start": "TEXT",
            "special_tp_price": "REAL",
            "trailing_frozen": "INTEGER NOT NULL DEFAULT 0",
            "trend_break_even": "INTEGER NOT NULL DEFAULT 0",
            "protection_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "protection_verified_at": "TEXT",
            "protection_reason": "TEXT",
        }.items():
            if name not in columns:
                self.connection.execute(f"ALTER TABLE live_trades ADD COLUMN {name} {definition}")

    def _ensure_event_columns(self) -> None:
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(live_trade_events)").fetchall()}
        if "shadow_trade_id" not in columns:
            self.connection.execute("ALTER TABLE live_trade_events ADD COLUMN shadow_trade_id TEXT")

    def _ensure_stop_replacement_columns(self) -> None:
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(live_stop_replacements)").fetchall()}
        if "create_attempted" not in columns:
            self.connection.execute("ALTER TABLE live_stop_replacements ADD COLUMN create_attempted INTEGER NOT NULL DEFAULT 0")

    def _ensure_trend_shadow_columns(self) -> None:
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(live_trend_shadow_trades)").fetchall()}
        if "actual_mr_result_json" not in columns:
            self.connection.execute("ALTER TABLE live_trend_shadow_trades ADD COLUMN actual_mr_result_json TEXT")

    def _ensure_trend_pending_columns(self) -> None:
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(live_trend_pending_orders)").fetchall()}
        for name, definition in {
            "expires_at": "TEXT",
            "takeover_phase": "TEXT",
            "takeover_trade_id": "TEXT",
            "takeover_side": "TEXT",
            "takeover_close_order_id": "TEXT",
            "takeover_close_attempted": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            if name not in columns:
                self.connection.execute(f"ALTER TABLE live_trend_pending_orders ADD COLUMN {name} {definition}")


def _trade(row: sqlite3.Row) -> LiveTrade:
    return LiveTrade(
        row["internal_trade_id"],
        row["exchange_position_key"],
        row["symbol"],
        row["side"],
        float(row["qty"]),
        float(row["entry_price"]),
        row["source"],
        row["status"],
        float(row["initial_stop_loss"]),
        float(row["current_stop_loss"]),
        row["system_stop_order_id"],
        row["protection_status"],
        _timestamp(row["protection_verified_at"]),
        row["protection_reason"],
        _timestamp(row["entry_time"]),
        _timestamp(row["exit_time"]),
        None if row["exit_price"] is None else float(row["exit_price"]),
        None if row["realized_pnl"] is None else float(row["realized_pnl"]),
        None if row["fees"] is None else float(row["fees"]),
        row["pnl_source"],
        _timestamp(row["setup_trigger_time"]),
        None if row["setup_rsi_15m"] is None else float(row["setup_rsi_15m"]),
        _timestamp(row["confirm_15m_time"]),
        int(row["trailing_stage"]),
        _timestamp(row["midband_follow_bucket_start"]),
        bool(row["adverse_slope_tp_active"]),
        _timestamp(row["adverse_slope_tp_bucket_start"]),
        None if row["adverse_slope_tp_price"] is None else float(row["adverse_slope_tp_price"]),
        row["entry_slope_state"],
        row["last_valid_slope_state"],
        bool(row["special_tp_active"]),
        _timestamp(row["special_tp_bucket_start"]),
        None if row["special_tp_price"] is None else float(row["special_tp_price"]),
        bool(row["trailing_frozen"]),
        bool(row["trend_break_even"]),
    )


def _pending_setup(row: sqlite3.Row) -> LivePendingSetup:
    return LivePendingSetup(
        row["symbol"],
        row["side"],
        row["status"],
        _timestamp(row["trigger_time"]),
        _timestamp(row["expiry_time"]),
        _loaded_setup_rsi(row["setup_rsi_15m"]),
        _timestamp(row["confirmation_after"]),
        bool(row["confirmed_15m"]),
        _timestamp(row["confirm_15m_time"]),
        float(row["close_1h"]),
        float(row["lb_1h"]),
        float(row["mb_1h"]),
        float(row["ub_1h"]),
        float(row["rsi_1h"]),
        row["created_at"],
        row["updated_at"],
    )


def _stop_replacement(row: sqlite3.Row) -> StopReplacementIntent:
    return StopReplacementIntent(
        internal_trade_id=row["internal_trade_id"],
        old_stop_order_id=row["old_stop_order_id"],
        replacement_client_id=row["replacement_client_id"],
        symbol=row["symbol"],
        side=row["side"],
        qty=float(row["qty"]),
        trigger_price=float(row["trigger_price"]),
        new_stop_order_id=row["new_stop_order_id"],
        create_attempted=bool(row["create_attempted"]),
        phase=row["phase"],
        reason=row["reason"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _mr_entry_intent(row: sqlite3.Row) -> MREntryIntent:
    return MREntryIntent(
        intent_id=row["intent_id"],
        account_id=row["account_id"],
        symbol=row["symbol"],
        side=row["side"],
        setup_trigger_time=_timestamp(row["setup_trigger_time"]),
        trigger_bucket=_timestamp(row["trigger_bucket"]),
        requested_qty=float(row["requested_qty"]),
        notional=float(row["notional"]),
        leverage=int(row["leverage"]),
        margin_reservation=float(row["margin_reservation"]),
        reference_price=float(row["reference_price"]),
        ioc_boundary_price=float(row["ioc_boundary_price"]),
        client_order_id=row["client_order_id"],
        exchange_order_id=row["exchange_order_id"],
        submit_attempted=bool(row["submit_attempted"]),
        status=row["status"],
        reason=row["reason"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _mr_intent_payload(intent: MREntryIntent) -> dict:
    payload = {
        "intent_id": intent.intent_id,
        "client_order_id": intent.client_order_id,
        "exchange_order_id": intent.exchange_order_id,
        "trigger_bucket": _iso(intent.trigger_bucket),
        "notional": intent.notional,
        "margin_reservation": intent.margin_reservation,
        "submit_attempted": intent.submit_attempted,
        "status": intent.status,
        "reason": intent.reason,
    }
    if intent.status in {"submitted", "ambiguous"}:
        payload["severity"] = "ERROR"
    return payload


def _severity_payload_for_store(severity: str, **payload) -> dict:
    return {"severity": severity, **payload}


def _shadow_trigger(row: sqlite3.Row) -> LiveShadowTrigger:
    return LiveShadowTrigger(
        row["trigger_id"],
        row["symbol"],
        row["side"],
        row["trigger_type"],
        _timestamp(row["trigger_time"]),
        _timestamp(row["expiry_time"]),
        _timestamp(row["setup_trigger_time"]),
        float(row["entry_price"]),
        float(row["setup_close"]),
        float(row["no_chase_boundary"]),
        float(row["mfe"]),
        float(row["mae"]),
        row["status"],
    )


def _trend_shadow_trade(row: sqlite3.Row) -> TrendShadowTrade:
    return TrendShadowTrade(
        row["shadow_trade_id"], row["symbol"], row["side"], row["status"], _timestamp(row["entry_time"]),
        float(row["entry_price"]), float(row["qty"]), float(row["notional"]), float(row["initial_stop_loss"]),
        float(row["current_stop_loss"]), _timestamp(row["candidate_bucket"]), _timestamp(row["last_1h_bucket"]),
        _timestamp(row["last_5m_bucket"]), None if row["favorable_price"] is None else float(row["favorable_price"]),
        bool(row["break_even"]), bool(row["weakening"]), float(row["mfe_pct"]), float(row["mae_pct"]), row["entry_snapshot_json"],
    )


def _trend_pending_order(row: sqlite3.Row) -> TrendPendingOrder:
    return TrendPendingOrder(
        pending_id=row["pending_id"],
        symbol=row["symbol"],
        side=row["side"],
        mode=row["mode"],
        status=row["status"],
        episode_bucket=_timestamp(row["episode_bucket"]),
        frozen_close=float(row["frozen_close"]),
        limit_price=float(row["limit_price"]),
        requested_qty=float(row["requested_qty"]),
        notional=float(row["notional"]),
        stop_distance_pct=float(row["stop_distance_pct"]),
        exchange_order_id=row["exchange_order_id"],
        client_order_id=row["client_order_id"],
        last_1h_bucket=_timestamp(row["last_1h_bucket"]),
        last_5m_bucket=_timestamp(row["last_5m_bucket"]),
        cancel_reason=row["cancel_reason"],
        entry_snapshot_json=row["entry_snapshot_json"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        expires_at=_timestamp(row["expires_at"]),
        takeover_phase=row["takeover_phase"],
        takeover_trade_id=row["takeover_trade_id"],
        takeover_side=row["takeover_side"],
        takeover_close_order_id=row["takeover_close_order_id"],
        takeover_close_attempted=bool(row["takeover_close_attempted"]),
    )


def _timestamp(value):
    if value is None:
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _iso(value) -> str | None:
    if value is None:
        return None
    return pd.Timestamp(value).isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stored_setup_rsi(value: float | None) -> float:
    return -1.0 if value is None else value


def _loaded_setup_rsi(value) -> float | None:
    parsed = float(value)
    return None if parsed < 0 else parsed
