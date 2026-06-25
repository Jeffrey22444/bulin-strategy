import json

from bbmr.event_logger import log_event
from bbmr.storage import open_storage
from bbmr.trade_models import RunSession, TradeEvent, TradeRecord


def _run(run_id: str) -> RunSession:
    return RunSession(
        run_id=run_id,
        strategy_name="bbmr_v3_2",
        config_hash="hash",
        started_at="2026-01-01T00:00:00",
        mode="test",
    )


def _trade(trade_id: str, run_id: str, early_fail: int = 0) -> TradeRecord:
    return TradeRecord(
        trade_id=trade_id,
        run_id=run_id,
        symbol="BTC",
        side="long",
        state="EXITED",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:01:00",
        early_fail_triggered=early_fail,
    )


def test_creates_sqlite_db_and_run_session(tmp_path):
    db_path = tmp_path / "bbmr.sqlite3"
    storage = open_storage(db_path)
    storage.create_run_session(_run("run-1"))
    row = storage.fetch_one("SELECT run_id FROM run_sessions WHERE run_id = ?", ("run-1",))
    storage.close()
    assert db_path.exists()
    assert row["run_id"] == "run-1"


def test_writes_trade_and_event(tmp_path):
    storage = open_storage(tmp_path / "bbmr.sqlite3")
    storage.create_run_session(_run("run-1"))
    storage.upsert_trade(_trade("trade-1", "run-1"))
    storage.insert_trade_event(
        TradeEvent(
            event_id="event-1",
            run_id="run-1",
            trade_id="trade-1",
            timestamp="2026-01-01T00:02:00",
            symbol="BTC",
            state_before="OPEN_NORMAL",
            event_type="STOP_LOSS_5M",
            state_after="EXITED",
        )
    )
    assert storage.fetch_one("SELECT trade_id FROM trades WHERE trade_id = ?", ("trade-1",))["trade_id"] == "trade-1"
    assert storage.fetch_one("SELECT event_id FROM trade_events WHERE event_id = ?", ("event-1",))["event_id"] == "event-1"
    storage.close()


def test_counts_early_fail_by_run_and_isolates_runs(tmp_path):
    storage = open_storage(tmp_path / "bbmr.sqlite3")
    storage.create_run_session(_run("run-1"))
    storage.create_run_session(_run("run-2"))
    storage.upsert_trade(_trade("trade-1", "run-1", early_fail=1))
    storage.upsert_trade(_trade("trade-2", "run-1", early_fail=0))
    storage.upsert_trade(_trade("trade-3", "run-2", early_fail=1))
    assert storage.count_early_fail_by_run("run-1") == 1
    assert storage.count_early_fail_by_run("run-2") == 1
    storage.close()


def test_duplicate_ids_do_not_double_count_early_fail(tmp_path):
    storage = open_storage(tmp_path / "bbmr.sqlite3")
    storage.create_run_session(_run("run-1"))
    storage.create_run_session(_run("run-1"))
    storage.upsert_trade(_trade("trade-1", "run-1", early_fail=1))
    storage.upsert_trade(_trade("trade-1", "run-1", early_fail=1))
    storage.insert_trade_event(TradeEvent("event-1", "run-1", "2026-01-01T00:00:00", "EARLY_FAIL_1H"))
    storage.insert_trade_event(TradeEvent("event-1", "run-1", "2026-01-01T00:00:00", "EARLY_FAIL_1H"))
    assert storage.count_early_fail_by_run("run-1") == 1
    assert storage.fetch_one("SELECT COUNT(*) AS count FROM trade_events")["count"] == 1
    storage.close()


def test_event_logger_writes_metadata_json(tmp_path):
    storage = open_storage(tmp_path / "bbmr.sqlite3")
    storage.create_run_session(_run("run-1"))
    event = log_event(
        storage,
        "run-1",
        "SIGNAL_BLOCKED_BY_RSI_FLAT",
        event_id="event-1",
        symbol="BTC",
        metadata={"side": "long"},
    )
    row = storage.fetch_one("SELECT metadata_json FROM trade_events WHERE event_id = ?", (event.event_id,))
    storage.close()
    assert json.loads(row["metadata_json"]) == {"side": "long"}
