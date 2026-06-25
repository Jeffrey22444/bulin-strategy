import sqlite3
from dataclasses import asdict
from pathlib import Path

from bbmr.trade_models import RunSession, TradeEvent, TradeRecord


SCHEMA = """
CREATE TABLE IF NOT EXISTS run_sessions (
    run_id TEXT PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    mode TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    state TEXT NOT NULL,
    entry_time TEXT,
    exit_time TEXT,
    entry_price REAL,
    exit_price REAL,
    initial_size REAL,
    add_size REAL DEFAULT 0,
    weighted_avg_entry REAL,
    fixed_sl REAL,
    one_r REAL,
    add_count INTEGER DEFAULT 0,
    soft_fail_triggered INTEGER DEFAULT 0,
    soft_fail_time TEXT,
    early_fail_triggered INTEGER DEFAULT 0,
    early_fail_time TEXT,
    early_fail_confirmation_count INTEGER DEFAULT 0,
    early_fail_bw_expansion INTEGER DEFAULT 0,
    early_fail_shock_volume INTEGER DEFAULT 0,
    early_fail_band_walking INTEGER DEFAULT 0,
    exit_reason TEXT,
    realized_pnl REAL,
    realized_pnl_r REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES run_sessions(run_id)
);

CREATE TABLE IF NOT EXISTS trade_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    trade_id TEXT,
    timestamp TEXT NOT NULL,
    symbol TEXT,
    state_before TEXT,
    event_type TEXT NOT NULL,
    state_after TEXT,
    price REAL,
    reason TEXT,
    metadata_json TEXT,
    FOREIGN KEY(run_id) REFERENCES run_sessions(run_id),
    FOREIGN KEY(trade_id) REFERENCES trades(trade_id)
);
"""


class ResearchStorage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def create_run_session(self, run: RunSession) -> None:
        self.connection.execute(
            """
            INSERT OR IGNORE INTO run_sessions
            (run_id, strategy_name, config_hash, started_at, ended_at, mode, notes)
            VALUES (:run_id, :strategy_name, :config_hash, :started_at, :ended_at, :mode, :notes)
            """,
            asdict(run),
        )
        self.connection.commit()

    def upsert_trade(self, trade: TradeRecord) -> None:
        data = asdict(trade)
        columns = ", ".join(data)
        placeholders = ", ".join(f":{key}" for key in data)
        updates = ", ".join(f"{key}=excluded.{key}" for key in data if key != "trade_id")
        self.connection.execute(
            f"INSERT INTO trades ({columns}) VALUES ({placeholders}) ON CONFLICT(trade_id) DO UPDATE SET {updates}",
            data,
        )
        self.connection.commit()

    def insert_trade_event(self, event: TradeEvent) -> None:
        data = asdict(event)
        columns = ", ".join(data)
        placeholders = ", ".join(f":{key}" for key in data)
        self.connection.execute(
            f"INSERT OR IGNORE INTO trade_events ({columns}) VALUES ({placeholders})",
            data,
        )
        self.connection.commit()

    def count_early_fail_by_run(self, run_id: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM trades WHERE run_id = ? AND early_fail_triggered = 1",
            (run_id,),
        ).fetchone()
        return int(row["count"])

    def fetch_one(self, query: str, params: tuple = ()) -> sqlite3.Row | None:
        return self.connection.execute(query, params).fetchone()


def open_storage(path: str | Path) -> ResearchStorage:
    return ResearchStorage(path)
