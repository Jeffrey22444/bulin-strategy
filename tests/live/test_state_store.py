import sqlite3

import pandas as pd
import pytest

from bbmr.live.state_store import LiveShadowTrigger, LiveStateStore, LiveTrade, MREntryIntent, StopReplacementIntent, TrendPendingOrder


def test_new_store_binds_only_identity_fingerprint_and_environment(tmp_path):
    path = tmp_path / "live.sqlite3"
    fingerprint = "a" * 64

    store = LiveStateStore(str(path), identity_fingerprint=fingerprint, environment="testnet")
    row = store.connection.execute("SELECT fingerprint, environment FROM live_store_identity").fetchone()

    assert dict(row) == {"fingerprint": fingerprint, "environment": "testnet"}


def test_bound_store_rejects_rebind(tmp_path):
    path = tmp_path / "live.sqlite3"
    LiveStateStore(str(path), identity_fingerprint="a" * 64, environment="testnet")

    with pytest.raises(RuntimeError, match="identity mismatch"):
        LiveStateStore(str(path), identity_fingerprint="b" * 64, environment="testnet")
    with pytest.raises(RuntimeError, match="identity mismatch"):
        LiveStateStore(str(path), identity_fingerprint="a" * 64, environment="mainnet")


def test_closed_legacy_store_requires_explicit_one_time_identity_binding(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    legacy = LiveStateStore(str(path))
    trade = legacy.create_trade("legacy:testnet:BTC:long", "BTC", "long", 1, 100, "strategy", 95)
    legacy.archive_trade(trade, "closed")

    with pytest.raises(RuntimeError, match="bind-legacy-identity"):
        LiveStateStore(str(path), identity_fingerprint="a" * 64, environment="testnet")

    bound = LiveStateStore(
        str(path),
        identity_fingerprint="a" * 64,
        environment="testnet",
        bind_legacy_identity=True,
    )
    assert bound.connection.execute("SELECT status FROM live_trades").fetchone()["status"] == "closed"


def test_active_legacy_store_cannot_be_bound(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    LiveStateStore(str(path)).create_trade("legacy:testnet:BTC:long", "BTC", "long", 1, 100, "strategy", 95)

    with pytest.raises(RuntimeError, match="active trades"):
        LiveStateStore(str(path), identity_fingerprint="a" * 64, environment="testnet", bind_legacy_identity=True)


def test_legacy_store_with_non_terminal_trend_pending_cannot_be_bound(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    legacy = LiveStateStore(str(path))
    legacy.create_trend_pending(
        TrendPendingOrder(
            pending_id="pending-1",
            symbol="BTC",
            side="long",
            mode="shadow",
            status="intent",
            episode_bucket=pd.Timestamp("2030-01-01 08:00Z"),
            frozen_close=100,
            limit_price=99,
            requested_qty=1,
            notional=99,
            stop_distance_pct=0.05,
        )
    )

    with pytest.raises(RuntimeError, match="non-terminal pending orders"):
        LiveStateStore(str(path), identity_fingerprint="a" * 64, environment="testnet", bind_legacy_identity=True)


def test_active_position_key_is_unique_across_active_statuses(tmp_path):
    store = LiveStateStore(str(tmp_path / "live.sqlite3"))
    store.create_trade("acct:testnet:BTC:long", "BTC", "long", 1, 100, "strategy", 95)

    with pytest.raises(sqlite3.IntegrityError):
        store.create_trade("acct:testnet:BTC:long", "BTC", "long", 1, 100, "strategy", 95, status="entry_unprotected")


def test_legacy_duplicate_active_position_key_blocks_store_open(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE live_trades (
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
        );
        INSERT INTO live_trades VALUES ('one', 'acct:testnet:BTC:long', 'BTC', 'long', 1, 100, 'strategy', 'open', 95, 95, NULL, NULL);
        INSERT INTO live_trades VALUES ('two', 'acct:testnet:BTC:long', 'BTC', 'long', 1, 100, 'strategy', 'entry_unprotected', 95, 95, NULL, NULL);
        """
    )
    connection.close()

    with pytest.raises(RuntimeError, match="duplicate active exchange positions"):
        LiveStateStore(str(path))


@pytest.mark.parametrize("method", ["create", "update", "archive"])
def test_trade_state_and_lifecycle_event_roll_back_together_when_event_write_fails(tmp_path, monkeypatch, method):
    store = LiveStateStore(str(tmp_path / "live.sqlite3"))
    def fail_event(*args, **kwargs):
        raise RuntimeError("journal write failed")

    monkeypatch.setattr(store, "append_event", fail_event)
    if method == "create":
        with pytest.raises(RuntimeError, match="journal write failed"):
            store.create_trade_with_event("acct:testnet:BTC:long", "BTC", "long", 1, 100, "strategy", 95, event_type="entry_opened", event_symbol="BTC")
        assert store.open_trade("acct:testnet:BTC:long") is None
        return

    trade = store.create_trade("acct:testnet:BTC:long", "BTC", "long", 1, 100, "strategy", 95)
    if method == "update":
        trade.qty = 2
        with pytest.raises(RuntimeError, match="journal write failed"):
            store.update_trade_with_event(trade, "stop_updated", "BTC")
        assert store.open_trade(trade.exchange_position_key).qty == 1
    else:
        with pytest.raises(RuntimeError, match="journal write failed"):
            store.archive_trade_with_event(trade, "closed", "exit_archived", "BTC")
        assert store.open_trade(trade.exchange_position_key) is not None


def test_state_write_failure_does_not_append_lifecycle_event(tmp_path, monkeypatch):
    store = LiveStateStore(str(tmp_path / "live.sqlite3"))
    trade = store.create_trade("acct:testnet:BTC:long", "BTC", "long", 1, 100, "strategy", 95)
    trade.qty = 2

    def fail_update(*args, **kwargs):
        raise RuntimeError("state write failed")

    monkeypatch.setattr(store, "_update_trade", fail_update)
    with pytest.raises(RuntimeError, match="state write failed"):
        store.update_trade_with_event(trade, "stop_updated", "BTC")

    assert store.open_trade(trade.exchange_position_key).qty == 1
    assert store.events() == []


def test_stop_replacement_intent_and_event_are_atomic_and_restart_durable(tmp_path, monkeypatch):
    path = tmp_path / "live.sqlite3"
    store = LiveStateStore(str(path))
    trade = store.create_trade("acct:testnet:BTC:long", "BTC", "long", 1, 100, "strategy", 95, status="entry_unprotected")
    intent = StopReplacementIntent(trade.internal_trade_id, "old-stop", "0x" + "1" * 32, "BTC", "long", 1, 95)

    monkeypatch.setattr(store, "append_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("journal write failed")))
    with pytest.raises(RuntimeError, match="journal write failed"):
        store.create_stop_replacement_with_event(intent, trade, "protective_stop_replacement_started")
    assert store.stop_replacement(trade.internal_trade_id) is None

    monkeypatch.undo()
    store.create_stop_replacement_with_event(intent, trade, "protective_stop_replacement_started")
    reopened = LiveStateStore(str(path))
    restored = reopened.stop_replacement(trade.internal_trade_id)
    assert restored is not None
    assert (restored.old_stop_order_id, restored.replacement_client_id, restored.phase) == ("old-stop", intent.replacement_client_id, "create_pending")

    initial_event_count = len(store.events())
    intent.new_stop_order_id = "new-stop"
    intent.phase = "cancel_pending"
    monkeypatch.setattr(store, "append_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("journal write failed")))
    with pytest.raises(RuntimeError, match="journal write failed"):
        store.update_stop_replacement_with_event(intent, trade, "protective_stop_replacement_confirmed")
    unchanged = store.stop_replacement(trade.internal_trade_id)
    assert unchanged is not None and unchanged.new_stop_order_id is None and unchanged.phase == "create_pending"
    assert len(store.events()) == initial_event_count

    monkeypatch.undo()
    store.update_stop_replacement_with_event(intent, trade, "protective_stop_replacement_confirmed")
    trade.system_stop_order_id = "new-stop"
    trade.status = "open"
    trade.protection_status = "protected"
    trade.protection_verified_at = pd.Timestamp("2030-01-01 09:00Z")
    initial_event_count = len(store.events())
    monkeypatch.setattr(store, "append_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("journal write failed")))
    with pytest.raises(RuntimeError, match="journal write failed"):
        store.promote_stop_replacement_with_event(trade, intent, "protective_stop_replacement_promoted")
    retained = store.stop_replacement(trade.internal_trade_id)
    stored_trade = store.open_trade(trade.exchange_position_key)
    assert retained is not None and retained.new_stop_order_id == "new-stop" and retained.phase == "cancel_pending"
    assert stored_trade.system_stop_order_id is None and stored_trade.status == "entry_unprotected"
    assert len(store.events()) == initial_event_count


def test_mr_entry_intent_lifecycle_state_and_events_are_atomic(tmp_path, monkeypatch):
    store = LiveStateStore(str(tmp_path / "live.sqlite3"))
    intent = MREntryIntent(
        "intent-1", "account-1", "BTC", "long", pd.Timestamp("2030-01-01 09:00Z"),
        pd.Timestamp("2030-01-01 09:30Z"), 2, 200, 3, 200 / 3, 100, 101,
        "0x" + "1" * 32,
    )
    monkeypatch.setattr(store, "append_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("journal write failed")))
    with pytest.raises(RuntimeError, match="journal write failed"):
        store.create_mr_entry_intent_with_event(intent)
    assert store.active_mr_entry_intent("BTC") is None

    monkeypatch.undo()
    store.create_mr_entry_intent_with_event(intent)
    trade = LiveTrade(
        "trade-1", "account-1:testnet:BTC:long", "BTC", "long", 1.5, 101,
        "strategy", "entry_unprotected", 95, 95,
    )
    before_events = len(store.events())
    monkeypatch.setattr(store, "append_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("journal write failed")))
    with pytest.raises(RuntimeError, match="journal write failed"):
        store.create_trade_and_fill_mr_intent_with_event(trade, intent)
    restored = store.active_mr_entry_intent("BTC")
    assert restored is not None and restored.status == "prepared"
    assert store.open_trade(trade.exchange_position_key) is None
    assert len(store.events()) == before_events

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


def test_store_persists_managed_position_regime_state(tmp_path):
    store = LiveStateStore(str(tmp_path / "live.sqlite3"))
    trade = store.create_trade("acct:testnet:BTC:long", "BTC", "long", 1, 100, "manual_adopted", 95)
    trade.last_valid_slope_state = "special"
    trade.special_tp_active = True
    trade.special_tp_bucket_start = pd.Timestamp("2030-01-01 08:00Z")
    trade.special_tp_price = 120
    trade.adverse_slope_tp_active = True
    trade.adverse_slope_tp_bucket_start = pd.Timestamp("2030-01-01 09:00Z")
    trade.adverse_slope_tp_price = 110
    trade.trailing_frozen = True
    trade.trend_break_even = True
    store.update_trade(trade)

    loaded = LiveStateStore(str(tmp_path / "live.sqlite3")).open_trade("acct:testnet:BTC:long")

    assert loaded.last_valid_slope_state == "special"
    assert loaded.special_tp_active is True
    assert loaded.special_tp_bucket_start == pd.Timestamp("2030-01-01 08:00Z")
    assert loaded.special_tp_price == 120
    assert loaded.adverse_slope_tp_active is True
    assert loaded.adverse_slope_tp_price == 110
    assert loaded.trailing_frozen is True
    assert loaded.trend_break_even is True



def test_store_persists_entry_unprotected_status(tmp_path):
    store = LiveStateStore(str(tmp_path / "live.sqlite3"))
    trade = store.create_trade("acct:testnet:BTC:long", "BTC", "long", 1, 100, "strategy", 95, status="entry_unprotected")

    loaded = LiveStateStore(str(tmp_path / "live.sqlite3")).open_trade("acct:testnet:BTC:long")
    assert loaded.status == "entry_unprotected"

    loaded.status = "open"
    store.update_trade(loaded)

    reopened = LiveStateStore(str(tmp_path / "live.sqlite3")).open_trade("acct:testnet:BTC:long")
    assert reopened.status == "open"


@pytest.mark.parametrize("protection_status", ["unknown", "recovery"])
def test_closed_trade_protection_history_does_not_trigger_recovery_guard(tmp_path, protection_status):
    store = LiveStateStore(str(tmp_path / "live.sqlite3"))
    trade = store.create_trade("acct:testnet:BTC:long", "BTC", "long", 1, 100, "strategy", 95)
    trade.protection_status = protection_status
    store.update_trade(trade)
    store.archive_trade(trade, "closed")

    assert store.has_protection_recovery() is False


@pytest.mark.parametrize(
    ("status", "protection_status"),
    [
        ("entry_unprotected", "unprotected"),
        ("open", "unknown"),
        ("open", "recovery"),
    ],
)
def test_non_closed_protection_recovery_state_still_blocks(tmp_path, status, protection_status):
    store = LiveStateStore(str(tmp_path / "live.sqlite3"))
    trade = store.create_trade("acct:testnet:BTC:long", "BTC", "long", 1, 100, "strategy", 95, status=status)
    trade.protection_status = protection_status
    store.update_trade(trade)

    assert store.has_protection_recovery() is True


def test_stop_replacement_still_triggers_recovery_guard(tmp_path):
    store = LiveStateStore(str(tmp_path / "live.sqlite3"))
    trade = store.create_trade("acct:testnet:BTC:long", "BTC", "long", 1, 100, "strategy", 95, status="entry_unprotected")
    intent = StopReplacementIntent(trade.internal_trade_id, "old-stop", "0x" + "1" * 32, "BTC", "long", 1, 95)
    store.create_stop_replacement_with_event(intent, trade, "protective_stop_replacement_started")

    assert store.has_protection_recovery() is True


def test_store_persists_shadow_trigger_across_restart(tmp_path):
    store = LiveStateStore(str(tmp_path / "live.sqlite3"))
    trigger = LiveShadowTrigger(
        "shadow-1",
        "BTC",
        "long",
        "middle_band",
        pd.Timestamp("2030-01-01 09:25Z"),
        pd.Timestamp("2030-01-01 10:00Z"),
        pd.Timestamp("2030-01-01 09:00Z"),
        100,
        95,
        110,
    )

    assert store.record_shadow_trigger(trigger) is True
    loaded = LiveStateStore(str(tmp_path / "live.sqlite3")).open_shadow_triggers("BTC")

    assert loaded == [trigger]


def test_store_persists_and_updates_active_trend_pending(tmp_path):
    path = tmp_path / "live.sqlite3"
    store = LiveStateStore(str(path))
    pending = TrendPendingOrder(
        pending_id="pending-1",
        symbol="BTC",
        side="long",
        mode="shadow",
        status="intent",
        episode_bucket=pd.Timestamp("2030-01-01 08:00Z"),
        frozen_close=100,
        limit_price=99,
        requested_qty=1,
        notional=99,
        stop_distance_pct=0.05,
        client_order_id="client-1",
        entry_snapshot_json='{"slope_state": "ex_special"}',
    )

    assert store.create_trend_pending(pending) is True
    pending.status = "open"
    pending.exchange_order_id = "order-1"
    pending.last_1h_bucket = pd.Timestamp("2030-01-01 09:00Z")
    pending.last_5m_bucket = pd.Timestamp("2030-01-01 09:05Z")
    store.update_trend_pending(pending, "trend_pending_opened", {"source": "exchange"})

    reopened = LiveStateStore(str(path))
    loaded = reopened.trend_pending("BTC")

    assert loaded.status == "open"
    assert loaded.exchange_order_id == "order-1"
    assert loaded.last_1h_bucket == pd.Timestamp("2030-01-01 09:00Z")
    assert reopened.active_trend_pendings() == [loaded]
    event = reopened.events()[-1]
    assert event["event_type"] == "trend_pending_opened"
    assert '"pending_id": "pending-1"' in event["payload_json"]


def test_store_persists_trend_takeover_phase_and_expiry(tmp_path):
    store = LiveStateStore(str(tmp_path / "live.sqlite3"))
    pending = TrendPendingOrder(
        "pending-takeover",
        "BTC",
        "long",
        "live",
        "intent",
        pd.Timestamp("2030-01-01 09:00Z"),
        120,
        118.8,
        1,
        120,
        0.05,
        expires_at=pd.Timestamp("2030-01-01 16:00Z"),
        takeover_phase="waiting_opposite_mr",
        takeover_trade_id="mr-1",
        takeover_side="short",
    )

    assert store.create_trend_pending(pending) is True
    pending.takeover_phase = "closing_mr"
    pending.takeover_close_attempted = True
    pending.takeover_close_order_id = "close-1"
    store.update_trend_pending(pending, "trend_takeover_mr_close_requested")

    loaded = LiveStateStore(store.path).trend_pending("BTC")
    assert loaded.expires_at == pd.Timestamp("2030-01-01 16:00Z")
    assert (loaded.takeover_phase, loaded.takeover_trade_id, loaded.takeover_side) == ("closing_mr", "mr-1", "short")
    assert loaded.takeover_close_attempted is True
    assert loaded.takeover_close_order_id == "close-1"


def test_store_keeps_terminal_trend_pending_and_does_not_recreate_episode(tmp_path):
    store = LiveStateStore(str(tmp_path / "live.sqlite3"))
    episode = pd.Timestamp("2030-01-01 08:00Z")
    pending = TrendPendingOrder(
        pending_id="pending-1",
        symbol="BTC",
        side="long",
        mode="shadow",
        status="intent",
        episode_bucket=episode,
        frozen_close=100,
        limit_price=99,
        requested_qty=1,
        notional=99,
        stop_distance_pct=0.05,
    )

    assert store.create_trend_pending(pending) is True
    pending.status = "canceled"
    pending.cancel_reason = "midband_reached_entry"
    store.update_trend_pending(pending)

    duplicate = TrendPendingOrder(
        pending_id="pending-2",
        symbol="BTC",
        side="long",
        mode="shadow",
        status="intent",
        episode_bucket=episode,
        frozen_close=101,
        limit_price=99.99,
        requested_qty=1,
        notional=99.99,
        stop_distance_pct=0.05,
    )
    assert store.create_trend_pending(duplicate) is False
    assert store.trend_pending("BTC") is None
    terminal = store.trend_pending_for_episode("BTC", "long", episode)
    assert terminal.pending_id == "pending-1"
    assert terminal.status == "canceled"
    assert terminal.cancel_reason == "midband_reached_entry"
