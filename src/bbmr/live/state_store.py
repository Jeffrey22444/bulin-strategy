import sqlite3
import uuid
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


class LiveStateStore:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
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
        self.connection.commit()

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
    ) -> LiveTrade:
        trade = LiveTrade(
            str(uuid.uuid4()),
            exchange_position_key,
            symbol,
            side,
            qty,
            entry_price,
            source,
            "open",
            initial_stop_loss,
            initial_stop_loss,
            entry_time=_timestamp(entry_time),
            setup_trigger_time=_timestamp(setup_trigger_time),
            setup_rsi_15m=setup_rsi_15m,
            confirm_15m_time=_timestamp(confirm_15m_time),
        )
        self.connection.execute(
            """
            INSERT INTO live_trades
            (internal_trade_id, exchange_position_key, symbol, side, qty, entry_price, source, status, initial_stop_loss, current_stop_loss, system_stop_order_id,
             entry_time, pnl_source, setup_trigger_time, setup_rsi_15m, confirm_15m_time, trailing_stage)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.internal_trade_id,
                trade.exchange_position_key,
                trade.symbol,
                trade.side,
                trade.qty,
                trade.entry_price,
                trade.source,
                trade.status,
                trade.initial_stop_loss,
                trade.current_stop_loss,
                trade.system_stop_order_id,
                _iso(trade.entry_time),
                trade.pnl_source,
                _iso(trade.setup_trigger_time),
                trade.setup_rsi_15m,
                _iso(trade.confirm_15m_time),
                trade.trailing_stage,
            ),
        )
        self.connection.commit()
        return trade

    def open_trade(self, exchange_position_key: str) -> LiveTrade | None:
        row = self.connection.execute(
            "SELECT * FROM live_trades WHERE exchange_position_key = ? AND status = 'open'",
            (exchange_position_key,),
        ).fetchone()
        return _trade(row) if row else None

    def update_trade(self, trade: LiveTrade) -> None:
        self.connection.execute(
            """
            UPDATE live_trades
            SET qty = ?, entry_price = ?, initial_stop_loss = ?, current_stop_loss = ?, system_stop_order_id = ?, pnl_source = ?, trailing_stage = ?
            WHERE internal_trade_id = ?
            """,
            (trade.qty, trade.entry_price, trade.initial_stop_loss, trade.current_stop_loss, trade.system_stop_order_id, trade.pnl_source, trade.trailing_stage, trade.internal_trade_id),
        )
        self.connection.commit()

    def archive_trade(self, trade: LiveTrade, reason: str, *, exit_time=None, exit_price: float | None = None, realized_pnl: float | None = None, fees: float | None = None, pnl_source: str = "unknown") -> None:
        self.connection.execute(
            """
            UPDATE live_trades
            SET status = 'closed', close_reason = ?, exit_time = ?, exit_price = ?, realized_pnl = ?, fees = ?, pnl_source = ?
            WHERE internal_trade_id = ?
            """,
            (reason, _iso(_timestamp(exit_time)), exit_price, realized_pnl, fees, pnl_source, trade.internal_trade_id),
        )
        self.connection.commit()

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

    def append_event(self, event_type: str, symbol: str, *, side: str | None = None, trade: LiveTrade | None = None, setup_trigger_time=None, event_time=None, payload_json: str | None = None) -> None:
        self.connection.execute(
            """
            INSERT INTO live_trade_events
            (event_type, symbol, side, internal_trade_id, setup_trigger_time, event_time, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                symbol,
                side or (trade.side if trade else None),
                trade.internal_trade_id if trade else None,
                _iso(_timestamp(setup_trigger_time)),
                _iso(_timestamp(event_time)) or _now(),
                payload_json,
                _now(),
            ),
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
        }.items():
            if name not in columns:
                self.connection.execute(f"ALTER TABLE live_trades ADD COLUMN {name} {definition}")


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
