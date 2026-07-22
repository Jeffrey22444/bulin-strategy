import json

import pandas as pd
import pytest

from bbmr.live.config import load_live_config
from bbmr.live.dashboard import ENTRY, archived_states, bandwidth_with_rules, current_path, observe, write_archive_svg, write_snapshot
from bbmr.live.state_store import LiveStateStore
from bbmr.live.trailing_runtime import LiveRuntime
from bbmr.trailing import Setup


class Exchange:
    def now(self):
        return pd.Timestamp("2030-01-01 12:00Z")


def _runtime(tmp_path):
    config = load_live_config("configs/live_hyperliquid_testnet.yaml")
    config.storage.sqlite_path = str(tmp_path / "live.sqlite3")
    return LiveRuntime(config, Exchange(), LiveStateStore(config.storage.sqlite_path))


def _features():
    index = pd.date_range("2030-01-01 01:00Z", periods=11, freq="h")
    one_h = pd.DataFrame({"close": [100.0] * 11, "lb": [90.0] * 11, "mb": [100.0] * 11, "ub": [110.0] * 11, "rsi14": [50.0] * 11}, index=index)
    five_m = pd.DataFrame({"close": [100.0], "high": [101.0], "low": [99.0]}, index=[pd.Timestamp("2030-01-01 11:50Z")])
    return one_h, one_h, five_m


def _trace(runtime, *, states=None, reason=None, entry_risk=None, entry_risks=None, bandwidth=None):
    risks = entry_risks or {
        "long": {"slow_slope_state": "normal", "slow_slope_pct": None, "effective_state": "normal", "rsi_threshold": 40, "leverage": 3, "allow": True, "reason": None, "linkage_state": "none", "shock_direction": None, "source_shock_bucket": None, "shock_age": None},
        "short": {"slow_slope_state": "normal", "slow_slope_pct": None, "effective_state": "normal", "rsi_threshold": 60, "leverage": 3, "allow": True, "reason": None, "linkage_state": "none", "shock_direction": None, "source_shock_bucket": None, "shock_age": None},
    }
    runtime.dashboard_traces["BTC"] = {
        "entry_states": states or ["current"] + ["muted"] * (len(ENTRY) - 1),
        "entry_block_reason": reason,
        "entry_allowed": False,
        "entry_risk": entry_risk or risks["long"],
        "entry_risks": risks,
        "bandwidth": bandwidth or {"label": "NORMAL", "allow": True, "reason": None, "raw": 0.02, "percentile": 50.0, "change_1h": 0.01, "change_3h": 0.02},
    }


def test_entry_unprotected_is_explicit_and_has_no_active_branch(tmp_path):
    runtime = _runtime(tmp_path)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95, status="entry_unprotected")

    view = observe(runtime, "BTC", _features())

    assert view["display_status"] == "多头持仓未建立保护止损"
    assert view["entry_block_reason"] == "entry_unprotected"
    assert "entry_unprotected" in view["position_tags"]
    assert isinstance(view["bandwidth"]["status"], str)
    assert {"raw", "percentile", "change_1h", "change_3h"} <= view["bandwidth"].keys()
    assert view["bandwidth"]["units"] == {"raw": "ratio", "percentile": "rank_0_100", "change_1h": "relative_ratio", "change_3h": "relative_ratio"}
    assert view["entry_risk"]["linkage_state"] == "none"
    assert view["entry_steps"][-1] == {"id": ENTRY[-1], "state": "muted"}
    assert {item["state"] for item in view["branch_connectors"]} == {"muted"}
    assert trade.internal_trade_id


def test_dashboard_uses_verified_protection_truth_not_stop_id(tmp_path):
    runtime = _runtime(tmp_path)
    trade = runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "strategy", 95)
    trade.system_stop_order_id = "stale-local-id"
    trade.protection_status = "unknown"
    runtime.store.update_trade(trade)

    view = observe(runtime, "BTC", _features())

    assert view["entry_allowed"] is False
    assert view["entry_block_reason"] == "entry_unprotected"
    assert "protection_unknown" in view["position_tags"]


def test_trend_trade_snapshot_uses_only_trend_management_lane(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.store.create_trade(runtime.position_key("BTC", "long"), "BTC", "long", 1, 100, "trend_riding", 95)

    view = observe(runtime, "BTC", _features())

    assert view["regime"] == "trend_riding"
    assert view["branch_connectors"] == []
    assert set(view["management_steps"]) == {"trend_riding"}
    assert set(view["management_connectors"]) == {"trend_riding"}
    assert "趋势管理" in view["management_summary"]


def test_trend_flow_exposes_runner_frozen_close_and_limit_price(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.trend_states["BTC"] = {
        "episode": {"frozen_close": 120.0, "limit_price": 118.8},
        "pending_status": "open",
    }

    view = observe(runtime, "BTC", _features())

    assert view["trend_flow"]["frozen_1h_close"] == 120.0
    assert view["trend_flow"]["limit_price"] == 118.8


def test_archive_svg_uses_final_runtime_state_not_old_current_snapshot(tmp_path):
    runtime = _runtime(tmp_path)
    trade = runtime.store.create_trade("test:BTC:long", "BTC", "long", 1, 100, "strategy", 95)
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "dashboard" / "current.json").write_text('{"symbols":{"BTC":{"entry_steps":[{"id":"stale","state":"passed"}]}}}')

    states = archived_states(runtime.store, trade, "protective_stop_filled")
    assert write_archive_svg(runtime.live_config.storage.sqlite_path, trade, states) is True
    svg = (tmp_path / "dashboard" / "archives" / f"{trade.internal_trade_id}.svg").read_text()

    assert "stale" not in svg
    assert "opened_protected" in svg


def test_dashboard_entry_risk_keeps_linkage_separate_from_position_regime(tmp_path):
    runtime = _runtime(tmp_path)
    risk = {"slow_slope_state": "normal", "slow_slope_pct": None, "effective_state": "normal", "rsi_threshold": 60, "leverage": 3, "allow": False, "reason": "high_expanding", "linkage_state": "bw_shock_block", "shock_direction": "up", "source_shock_bucket": "2030-01-01T11:00:00+00:00", "shock_age": 0}
    _trace(runtime, entry_risk=risk, entry_risks={"long": {**risk, "linkage_state": "none", "shock_direction": None, "allow": True, "reason": None}, "short": risk})

    view = observe(runtime, "BTC")

    assert view["regime"] == "normal"
    assert view["entry_risk"]["linkage_state"] == "bw_shock_block"
    assert view["entry_risk"]["shock_direction"] == "up"
    assert view["entry_block_reason"] is None


def test_dashboard_places_bandwidth_final_filter_after_5m_trigger(tmp_path):
    runtime = _runtime(tmp_path)
    _trace(runtime, states=["passed", "passed", "passed", "passed", "passed", "current", "muted", "muted"], reason="high_expanding")

    view = observe(runtime, "BTC")

    assert [step["id"] for step in view["entry_steps"]] == list(ENTRY)
    assert [step["state"] for step in view["entry_steps"]] == ["passed", "passed", "passed", "passed", "passed", "current", "muted", "muted"]
    assert view["entry_block_reason"] == "high_expanding"
    assert view["entry_allowed"] is False


def test_dashboard_exposes_completed_slow_slope_for_both_entry_sides(tmp_path):
    runtime = _runtime(tmp_path)
    risks = {
        "long": {"slow_slope_state": "normal", "slow_slope_pct": 0.01, "effective_state": "normal", "rsi_threshold": 40, "leverage": 3, "allow": True, "reason": None, "linkage_state": "none", "shock_direction": None, "source_shock_bucket": None, "shock_age": None},
        "short": {"slow_slope_state": "normal", "slow_slope_pct": 0.01, "effective_state": "normal", "rsi_threshold": 60, "leverage": 3, "allow": True, "reason": None, "linkage_state": "none", "shock_direction": None, "source_shock_bucket": None, "shock_age": None},
    }
    _trace(runtime, entry_risks=risks)

    view = observe(runtime, "BTC")

    assert view["completed_1h_available"] is True
    assert view["completed_1h_slope_pct"] == pytest.approx(0.01)
    assert view["slope_quality"] == "valid"
    assert view["entry_risks"]["long"]["slow_slope_pct"] == pytest.approx(0.01)
    assert view["entry_risks"]["short"]["slow_slope_pct"] == pytest.approx(0.01)


@pytest.mark.parametrize(("start", "age", "source"), [("2030-01-01 05:00Z", 1, "2030-01-01T10:00:00+00:00"), ("2030-01-01 04:00Z", 2, "2030-01-01T09:00:00+00:00")])
def test_dashboard_exposes_h1_h2_side_specific_entry_risks(tmp_path, start, age, source):
    runtime = _runtime(tmp_path)
    risks = {
        "long": {"slow_slope_state": "normal", "slow_slope_pct": None, "effective_state": "normal", "rsi_threshold": 40, "leverage": 3, "allow": True, "reason": None, "linkage_state": "none", "shock_direction": None, "source_shock_bucket": None, "shock_age": None},
        "short": {"slow_slope_state": "normal", "slow_slope_pct": None, "effective_state": "special", "rsi_threshold": 68, "leverage": 2, "allow": True, "reason": None, "linkage_state": "bw_continuation_special", "shock_direction": "up", "source_shock_bucket": source, "shock_age": age},
    }
    _trace(runtime, entry_risks=risks, entry_risk=risks["short"])

    view = observe(runtime, "BTC")

    assert view["entry_risks"]["short"]["linkage_state"] == "bw_continuation_special"
    assert view["entry_risks"]["short"]["source_shock_bucket"] == source
    assert view["entry_risks"]["short"]["shock_age"] == age
    assert view["entry_risks"]["short"]["rsi_threshold"] == 68
    assert view["entry_risks"]["short"]["leverage"] == 2
    assert view["entry_risks"]["long"]["effective_state"] == "normal"


def test_dashboard_defaults_new_bandwidth_fields_for_older_snapshot_payloads(tmp_path):
    runtime = _runtime(tmp_path)

    state = bandwidth_with_rules({"status": "NORMAL", "allowed": True, "raw": 0.02, "percentile": 50.0, "change_1h": 0.01, "change_3h": 0.02}, runtime.strategy_config.bandwidth_entry_guard)

    assert state["units"]["percentile"] == "rank_0_100"
    assert state["linkage_state"] == "none"
    assert state["shock_direction"] is None


def test_snapshot_serializes_runner_trace_without_strategy_reconstruction(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    _trace(runtime, states=["passed", "passed", "passed", "passed", "passed", "current", "muted", "muted"], reason="high_expanding")
    runtime.dashboard_traces["DOGE"] = runtime.dashboard_traces.pop("BTC")
    monkeypatch.setattr(runtime, "entry_risk_observation", lambda *args: pytest.fail("dashboard must not re-evaluate strategy"))

    write_snapshot(runtime, ["DOGE"], {"DOGE": _features()}, pd.Timestamp("2030-01-01 12:00Z"))

    snapshot = json.loads(current_path(runtime.live_config.storage.sqlite_path).read_text())
    assert snapshot["configured_symbols"] == ["DOGE"]
    assert [step["state"] for step in snapshot["symbols"]["DOGE"]["entry_steps"]] == ["passed", "passed", "passed", "passed", "passed", "current", "muted", "muted"]
