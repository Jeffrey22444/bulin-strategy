import pandas as pd

from bbmr.live.state_store import LiveStateStore


def test_store_creates_updates_and_archives_trade(tmp_path):
    store = LiveStateStore(str(tmp_path / "live.sqlite3"))
    trade = store.create_trade("acct:testnet:BTC:long", "BTC", "long", 1, 100, "manual_adopted", 95)
    trade.qty = 2
    trade.system_stop_order_id = "stop-1"
    store.update_trade(trade)

    loaded = store.open_trade("acct:testnet:BTC:long")
    assert loaded.qty == 2
    assert loaded.system_stop_order_id == "stop-1"

    store.archive_trade(loaded, "manual_or_exchange_closed")
    assert store.open_trade("acct:testnet:BTC:long") is None


def test_store_supports_pnl_source_markers(tmp_path):
    store = LiveStateStore(str(tmp_path / "live.sqlite3"))

    for source in ("exchange", "estimated_local", "unknown"):
        trade = store.create_trade(f"acct:testnet:BTC:{source}", "BTC", "long", 1, 100, "strategy", 95)
        store.archive_trade(trade, "closed", pnl_source=source)

    sources = {
        row["pnl_source"]
        for row in store.connection.execute("SELECT pnl_source FROM live_trades WHERE status = 'closed'").fetchall()
    }
    assert sources == {"exchange", "estimated_local", "unknown"}


def test_store_persists_trailing_stage(tmp_path):
    store = LiveStateStore(str(tmp_path / "live.sqlite3"))
    trade = store.create_trade("acct:testnet:BTC:long", "BTC", "long", 1, 100, "strategy", 95)
    trade.trailing_stage = 3
    store.update_trade(trade)

    reopened = LiveStateStore(str(tmp_path / "live.sqlite3"))
    loaded = reopened.open_trade("acct:testnet:BTC:long")

    assert loaded.trailing_stage == 3


def test_store_persists_midband_follow_bucket_start(tmp_path):
    store = LiveStateStore(str(tmp_path / "live.sqlite3"))
    trade = store.create_trade("acct:testnet:BTC:long", "BTC", "long", 1, 100, "strategy", 95)
    trade.trailing_stage = 3
    trade.midband_follow_bucket_start = pd.Timestamp("2030-01-01 08:00Z")
    store.update_trade(trade)

    loaded = LiveStateStore(str(tmp_path / "live.sqlite3")).open_trade("acct:testnet:BTC:long")

    assert loaded.trailing_stage == 3
    assert loaded.midband_follow_bucket_start == pd.Timestamp("2030-01-01 08:00Z")


def test_store_persists_adverse_slope_take_profit_state(tmp_path):
    store = LiveStateStore(str(tmp_path / "live.sqlite3"))
    trade = store.create_trade("acct:testnet:BTC:long", "BTC", "long", 1, 100, "strategy", 95)
    trade.adverse_slope_tp_active = True
    trade.adverse_slope_tp_bucket_start = pd.Timestamp("2030-01-01 08:00Z")
    trade.adverse_slope_tp_price = 120
    store.update_trade(trade)

    loaded = LiveStateStore(str(tmp_path / "live.sqlite3")).open_trade("acct:testnet:BTC:long")

    assert loaded.adverse_slope_tp_active is True
    assert loaded.adverse_slope_tp_bucket_start == pd.Timestamp("2030-01-01 08:00Z")
    assert loaded.adverse_slope_tp_price == 120


def test_store_persists_entry_unprotected_status(tmp_path):
    store = LiveStateStore(str(tmp_path / "live.sqlite3"))
    trade = store.create_trade("acct:testnet:BTC:long", "BTC", "long", 1, 100, "strategy", 95, status="entry_unprotected")

    loaded = LiveStateStore(str(tmp_path / "live.sqlite3")).open_trade("acct:testnet:BTC:long")
    assert loaded.status == "entry_unprotected"

    loaded.status = "open"
    store.update_trade(loaded)

    reopened = LiveStateStore(str(tmp_path / "live.sqlite3")).open_trade("acct:testnet:BTC:long")
    assert reopened.status == "open"
