"""Read-only local dashboard snapshot and API."""
from __future__ import annotations

import argparse, fcntl, html, json, math, os, re, sqlite3, tempfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

from bbmr.config import load_config
from bbmr.live.config import load_live_config

ENTRY = ("completed_1h", "price_outer_break_1h", "rsi_threshold_1h", "completed_5m", "price_prev_extreme_break_5m", "bandwidth_guard", "entry_account_orderbook_guard", "opened_protected")
LANES = {"normal": ("normal_midpoint_condition", "normal_risk_half_stop", "normal_middle_cross_condition", "normal_breakeven_stop", "normal_halfband_condition", "normal_midband_follow_stop", "normal_outer_break_condition", "normal_outer_close_stop"), "special": ("special_regime_active", "special_protective_stop_active", "special_target_tracking", "special_target_reached", "special_close_confirmed"), "exspecial": ("exspecial_regime_active", "exspecial_stop_frozen", "exspecial_target_tracking", "exspecial_target_reached", "exspecial_close_confirmed")}
TREND_ENTRY = ("first_directional_exspecial", "freeze_limit_price", "trend_takeover_safety", "trend_gtc_pending", "trend_opened_protected")
TREND_MANAGEMENT = ("protective_stop", "water_mark", "break_even", "weakening", "middle_cross", "normal_fallback", "exit_cleanup")
ID = re.compile(r"^[0-9a-f-]{36}$")

def root(path): return Path(path).parent / "dashboard"
def current_path(path): return root(path) / "current.json"
def lifecycle_path(path): return root(path) / "lifecycle.json"
def archive_path(path, trade_id): return root(path) / "archives" / f"{trade_id}.svg"
def _now(): return datetime.now(timezone.utc).isoformat()
def _state(items): return [{"id": ident, "state": value} for ident, value in items]
def _connectors(ids, states): return [{"from": left, "to": right, "state": states[index]} for index, (left, right) in enumerate(zip(ids, ids[1:]))]
def _iso(value): return None if value is None else pd.Timestamp(value).isoformat()
def _empty_entry_risks(): return {side: {"slow_slope_state": None, "slow_slope_pct": None, "effective_state": None, "rsi_threshold": None, "leverage": None, "allow": False, "reason": "unavailable", "linkage_state": "none", "shock_direction": None, "source_shock_bucket": None, "shock_age": None} for side in ("long", "short")}

def _atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
        temporary = handle.name
    os.replace(temporary, path)

def write_lifecycle(sqlite_path, status): _atomic(lifecycle_path(sqlite_path), {"status": status, "updated_at": _now()})

def write_snapshot(runtime, symbols, features_by_symbol, observed_at):
    updates = [re.sub(r"https?://\S+", "[endpoint]", str(line))[:500] for line in getattr(runtime, "dashboard_updates", [])][-40:]
    _atomic(current_path(runtime.live_config.storage.sqlite_path), {"observed_at": observed_at.isoformat(), "last_successful_poll_at": observed_at.isoformat(), "configured_symbols": symbols, "updates": updates, "symbols": {symbol: observe(runtime, symbol, features_by_symbol[symbol]) for symbol in symbols}})

def observe(runtime, symbol, _features=None):
    """Format runner-owned trace data; never re-evaluate entry strategy conditions."""
    trace = getattr(runtime, "dashboard_traces", {}).get(symbol, {})
    trade = runtime.managed_trade(symbol)
    setup = runtime.setups.get(symbol)
    entry_states = trace.get("entry_states", ["current"] + ["muted"] * (len(ENTRY) - 1))
    if len(entry_states) != len(ENTRY):
        entry_states = ["current"] + ["muted"] * (len(ENTRY) - 1)
    bandwidth = {"label": "UNAVAILABLE", "allow": False, "reason": "unavailable", "raw": None, "percentile": None, "change_1h": None, "change_3h": None, **(trace.get("bandwidth") or {})}
    entry_risks = trace.get("entry_risks") or _empty_entry_risks()
    slow_slope_pct = entry_risks.get("long", {}).get("slow_slope_pct")
    slope_valid = isinstance(slow_slope_pct, (int, float)) and not isinstance(slow_slope_pct, bool) and math.isfinite(slow_slope_pct)
    protected = bool(trade and trade.status == "open" and trade.protection_status == "protected")
    unprotected = bool(trade and not protected)
    is_trend = bool(trade and trade.source == "trend_riding")
    regime = "exspecial" if trade and trade.adverse_slope_tp_active else "special" if trade and trade.special_tp_active else trade.last_valid_slope_state if trade else "normal"
    regime = regime or "normal"
    management = management_steps(runtime.store, trade, regime) if not unprotected else {name: ["muted"] * len(ids) for name, ids in LANES.items()}
    tags = (["manual_adopted"] if trade and trade.source == "manual_adopted" else []) + (["manual_size_changed"] if trade and has_event(runtime.store, trade.internal_trade_id, "manual_size_changed") else [])
    tags += ["entry_unprotected"] if unprotected else []
    if trade and trade.protection_status:
        tags.append(f"protection_{trade.protection_status}")
    trend_flow = trend_flow_snapshot(runtime, symbol, trade)
    if is_trend:
        trend_ids = TREND_MANAGEMENT
        active = "exit_cleanup" if trade.status == "exit_cleanup" else "weakening" if trade.special_tp_active else "protective_stop"
        trend_states = ["current" if name == active else "passed" if name == "protective_stop" and trade.status == "open" else "muted" for name in trend_ids]
        branch_connectors = []
        management_connectors = {"trend_riding": _connectors(trend_ids, ["current" if state == "current" else "muted" for state in trend_states[:-1]])}
        management_steps_view = {"trend_riding": _state(zip(trend_ids, trend_states))}
        management_summary = "趋势管理：退出清理" if trade.status == "exit_cleanup" else "趋势管理：弱化监测" if trade.special_tp_active else "趋势管理：保护止损与水位跟踪"
    else:
        branch_connectors = [{"from": "opened_protected", "to": name, "state": "current" if trade and not unprotected and name == regime else "muted"} for name in LANES]
        management_connectors = {name: _connectors(LANES[name], ["passed" if states[index] == states[index + 1] == "passed" else "current" if states[index] != "muted" and states[index + 1] == "current" else "muted" for index in range(len(states) - 1)]) for name, states in management.items()}
        management_steps_view = {name: _state(zip(LANES[name], states)) for name, states in management.items()}
        management_summary = "等待保护止损恢复" if unprotected else {"normal": "分段止损链运行中", "special": "保护止损与中轨止盈并行", "exspecial": "保护止损冻结 · 防御退出监测"}[regime] if trade else "等待开仓条件"
    return {
        "symbol": symbol,
        "display_status": "多头持仓未建立保护止损" if unprotected and trade.side == "long" else "空头持仓未建立保护止损" if unprotected else "多头持仓中" if trade and trade.side == "long" else "空头持仓中" if trade else "等待进场确认" if setup else "等待开仓条件",
        "regime": "trend_riding" if is_trend else regime,
        "completed_1h_available": bool(trace.get("completed_1h_available")) or slope_valid,
        "completed_1h_slope_pct": slow_slope_pct if slope_valid else None,
        "slope_quality": "valid" if slope_valid else "unavailable",
        "bandwidth": {"status": bandwidth["label"], "allowed": bandwidth["allow"], "reason": bandwidth["reason"], "raw": bandwidth["raw"], "percentile": bandwidth["percentile"], "change_1h": bandwidth["change_1h"], "change_3h": bandwidth["change_3h"], "units": {"raw": "ratio", "percentile": "rank_0_100", "change_1h": "relative_ratio", "change_3h": "relative_ratio"}, "rapid_expanding": bandwidth.get("rapid_expanding", False), "shock_direction": bandwidth.get("shock_direction"), "linkage_state": bandwidth.get("linkage_state", "none"), "source_shock_bucket": _iso(bandwidth.get("source_shock_bucket")), "shock_age": bandwidth.get("shock_age")},
        "trend_riding": {"mode": getattr(runtime, "trend_mode", "off")},
        "trend_flow": trend_flow,
        "entry_risk": trace.get("entry_risk") or _empty_entry_risks()["long"],
        "entry_risks": entry_risks,
        "entry_allowed": bool(trace.get("entry_allowed")) and not unprotected and not trade,
        "entry_block_reason": "entry_unprotected" if unprotected else trace.get("entry_block_reason"),
        "position_source": trade.source if trade else None,
        "position_tags": tags,
        "entry_steps": _state(zip(ENTRY, entry_states)),
        "entry_connectors": _connectors(ENTRY, ["passed" if entry_states[index] == entry_states[index + 1] == "passed" else "current" if entry_states[index] != "muted" and entry_states[index + 1] == "current" else "muted" for index in range(len(ENTRY) - 1)]),
        "branch_connectors": branch_connectors,
        "management_steps": management_steps_view,
        "management_connectors": management_connectors,
        "management_summary": management_summary,
        "regime_transition": None,
    }


def trend_flow_snapshot(runtime, symbol, trade):
    """Expose runner-owned trend state only; never reconstruct a trend signal for the UI."""
    state = getattr(runtime, "trend_states", {}).get(symbol)
    state = state if isinstance(state, dict) else {}
    episode = state.get("episode") if isinstance(state.get("episode"), dict) else None
    pending_status = state.get("pending_status") if isinstance(state.get("pending_status"), str) else None
    takeover_phase = state.get("takeover_phase") if isinstance(state.get("takeover_phase"), str) else None
    is_trend = bool(trade and trade.source == "trend_riding")
    active = bool(is_trend or episode or pending_status)
    entry = ["muted"] * len(TREND_ENTRY)
    if episode:
        entry[0] = "current"
    if pending_status:
        entry[:2] = ["passed", "passed"]
        if takeover_phase in {"waiting_opposite_mr", "takeover_triggered", "closing_mr", "flat_cleanup"}:
            entry[2] = "current"
        elif pending_status in {"intent", "open", "ambiguous", "cancel_requested"}:
            entry[2:4] = ["passed", "current"]
    if is_trend:
        entry = ["passed"] * len(TREND_ENTRY)
        entry[-1] = "passed" if trade.status == "open" and trade.protection_status == "protected" else "current"
    management = ["muted"] * len(TREND_MANAGEMENT)
    if is_trend:
        active_id = "exit_cleanup" if trade.status == "exit_cleanup" else "weakening" if trade.special_tp_active else "protective_stop"
        management = ["current" if name == active_id else "passed" if name == "protective_stop" and trade.status == "open" else "muted" for name in TREND_MANAGEMENT]
    mode = getattr(runtime, "trend_mode", "unknown")
    mode = mode if mode in {"off", "shadow", "live"} else "unknown"
    frozen_close = episode.get("frozen_close") if episode else None
    limit_price = episode.get("limit_price") if episode else None
    frozen_close = frozen_close if isinstance(frozen_close, (int, float)) and not isinstance(frozen_close, bool) and math.isfinite(frozen_close) else None
    limit_price = limit_price if isinstance(limit_price, (int, float)) and not isinstance(limit_price, bool) and math.isfinite(limit_price) else None
    return {
        "active": active,
        "mode": mode,
        "frozen_1h_close": frozen_close,
        "limit_price": limit_price,
        "entry_steps": _state(zip(TREND_ENTRY, entry)),
        "entry_connectors": _connectors(TREND_ENTRY, ["passed" if entry[index] == entry[index + 1] == "passed" else "current" if entry[index] != "muted" and entry[index + 1] == "current" else "muted" for index in range(len(entry) - 1)]),
        "management_steps": _state(zip(TREND_MANAGEMENT, management)),
        "management_connectors": _connectors(TREND_MANAGEMENT, ["passed" if management[index] == management[index + 1] == "passed" else "current" if management[index] != "muted" and management[index + 1] == "current" else "muted" for index in range(len(management) - 1)]),
    }


def management_steps(store, trade, regime):
    result = {name: ["muted"] * len(ids) for name, ids in LANES.items()}
    if not trade: return result
    if regime == "normal":
        reasons = stop_reasons(store, trade.internal_trade_id)
        completed = 6 if trade.trailing_stage >= 3 else 0
        if any("first-step risk reduced" in reason for reason in reasons): completed = max(completed, 2)
        if any("5m close > 1h middle" in reason or "5m close < 1h middle" in reason for reason in reasons): completed = max(completed, 4)
        if any("5m high > 1h upper" in reason or "5m low < 1h lower" in reason for reason in reasons): completed = 8
        result["normal"] = ["passed" if index < completed else "current" if index == completed else "muted" for index in range(8)]
    elif regime == "special": result["special"] = ["current", "current", "current", "muted", "muted"]
    else: result["exspecial"] = ["current", "current", "current", "muted", "muted"]
    return result

def archived_states(store, trade, reason):
    regime = "exspecial" if trade.adverse_slope_tp_active else "special" if trade.special_tp_active else trade.last_valid_slope_state or "normal"
    protected = trade.status == "open" and trade.protection_status == "protected"
    entry = ["muted"] * 7 + ["current"] if trade.source == "manual_adopted" else ["passed"] * 7 + ["passed" if protected else "current"]
    management = management_steps(store, trade, regime)
    if regime in {"special", "exspecial"} and "target" in reason:
        management[regime] = ["passed"] * len(LANES[regime])
    return {"regime": regime, "position_tags": (["manual_adopted"] if trade.source == "manual_adopted" else []) + (["entry_unprotected"] if not protected else []), "entry_steps": _state(zip(ENTRY, entry)), "entry_connectors": _connectors(ENTRY, ["passed" if entry[index] == entry[index + 1] == "passed" else "muted" for index in range(len(ENTRY) - 1)]), "branch_connectors": [{"from": "opened_protected", "to": name, "state": "passed" if name == regime and protected else "muted"} for name in LANES], "management_steps": {name: _state(zip(LANES[name], states)) for name, states in management.items()}, "management_connectors": {name: _connectors(LANES[name], ["passed" if states[index] == states[index + 1] == "passed" else "muted" for index in range(len(states) - 1)]) for name, states in management.items()}}

def stop_reasons(store, trade_id):
    rows = store.connection.execute("SELECT payload_json FROM live_trade_events WHERE internal_trade_id = ? AND event_type = 'stop_updated' ORDER BY event_id DESC LIMIT 16", (trade_id,)).fetchall()
    reasons = []
    for row in rows:
        try: reasons.append(str(json.loads(row[0] or "{}").get("reason", "")))
        except json.JSONDecodeError: continue
    return reasons

def has_event(store, trade_id, event_type): return store.connection.execute("SELECT 1 FROM live_trade_events WHERE internal_trade_id = ? AND event_type = ? LIMIT 1", (trade_id, event_type)).fetchone() is not None

def write_archive_svg(sqlite_path, trade, states):
    try:
        frozen = json.dumps({key: states.get(key) for key in ("entry_steps", "entry_connectors", "branch_connectors", "management_steps", "management_connectors", "position_tags", "regime")}, ensure_ascii=False, separators=(",", ":"))
        labels = [f"{item['id']} · {item['state']}" for item in states.get("entry_steps", [])]
        for lane, items in states.get("management_steps", {}).items(): labels.extend(f"{lane}/{item['id']} · {item['state']}" for item in items)
        rows = "".join(f'<text x="32" y="{44 + index * 22}" font-size="14">{html.escape(label)}</text>' for index, label in enumerate(labels))
        height = max(120, 60 + len(labels) * 22)
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="{height}"><metadata>{html.escape(frozen)}</metadata><rect width="100%" height="100%" fill="#f5f5f7"/><g font-family="-apple-system, PingFang SC" fill="#1d1d1f">{rows}</g></svg>'
        target = archive_path(sqlite_path, trade.internal_trade_id); target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle: handle.write(svg.encode()); temporary = handle.name
        os.replace(temporary, target); return True
    except Exception: return False

def read_json(path):
    try: return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError): return None
def runner_status(sqlite_path):
    lock = Path(sqlite_path).parent / "live_runner.lock"
    if not lock.exists(): return "stopped"
    try:
        with lock.open() as handle:
            try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return (read_json(lifecycle_path(sqlite_path)) or {}).get("status", "unknown")
            finally: fcntl.flock(handle, fcntl.LOCK_UN)
    except OSError: return "unknown"
    return "stopped"

def ro(path): return sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
def latest_bandwidth(path, symbol):
    try:
        with ro(path) as conn:
            row = conn.execute("SELECT payload_json FROM live_trade_events WHERE symbol = ? AND event_type = 'bandwidth_state_observed' ORDER BY event_id DESC LIMIT 1", (symbol,)).fetchone()
        payload = json.loads(row[0]) if row and row[0] else {}
        return {"status": payload.get("label", "UNAVAILABLE"), "allowed": payload.get("guard") == "ALLOW", "reason": payload.get("reason"), "raw": payload.get("raw"), "percentile": payload.get("percentile"), "change_1h": payload.get("change_1h"), "change_3h": payload.get("change_3h"), "units": payload.get("units", {"raw": "ratio", "percentile": "rank_0_100", "change_1h": "relative_ratio", "change_3h": "relative_ratio"}), "rapid_expanding": payload.get("rapid_expanding", False), "shock_direction": payload.get("shock_direction"), "linkage_state": payload.get("linkage_state", "none"), "source_shock_bucket": payload.get("source_shock_bucket"), "shock_age": payload.get("shock_age"), "entry_risks": payload.get("entry_risks", _empty_entry_risks())}
    except (sqlite3.Error, json.JSONDecodeError):
        return {"status": "UNAVAILABLE", "allowed": False, "reason": "unavailable", "raw": None, "percentile": None, "change_1h": None, "change_3h": None, "units": {"raw": "ratio", "percentile": "rank_0_100", "change_1h": "relative_ratio", "change_3h": "relative_ratio"}, "rapid_expanding": False, "shock_direction": None, "linkage_state": "none", "source_shock_bucket": None, "shock_age": None, "entry_risks": _empty_entry_risks()}
def bandwidth_with_rules(state, rules):
    state = {"status": "UNAVAILABLE", "allowed": False, "reason": "unavailable", "raw": None, "percentile": None, "change_1h": None, "change_3h": None, "units": {"raw": "ratio", "percentile": "rank_0_100", "change_1h": "relative_ratio", "change_3h": "relative_ratio"}, "rapid_expanding": False, "shock_direction": None, "linkage_state": "none", "source_shock_bucket": None, "shock_age": None, **state}
    percentile = state.get("percentile")
    change = state.get("change_1h")
    high = rules.high_percentile
    expansion = rules.min_1h_expansion_pct
    return {**state, "high_percentile": high, "percentile_distance": None if percentile is None else percentile - high, "expansion_threshold": expansion, "expansion_distance": None if change is None else change - expansion}
def archives(path, limit):
    try:
        with ro(path) as conn: rows = conn.execute("SELECT t.internal_trade_id,t.symbol,t.side,COALESCE(t.exit_time,(SELECT e.event_time FROM live_trade_events e WHERE e.internal_trade_id=t.internal_trade_id AND e.event_type='exit_archived' ORDER BY e.event_id DESC LIMIT 1)),t.realized_pnl,t.entry_price,t.qty FROM live_trades t WHERE t.status='closed' ORDER BY 4 DESC LIMIT ?", (limit,)).fetchall()
    except sqlite3.Error: return []
    return [archive_row(path, row) for row in rows]
def archive_row(path, row):
    notional = float(row[5] or 0) * float(row[6] or 0)
    pnl_pct = None if row[4] is None or notional <= 0 else float(row[4]) / notional * 100
    return {"id":row[0],"symbol":row[1],"side":row[2],"closed_at":row[3],"realized_pnl":row[4],"currency":"USDC","pnl_pct":pnl_pct,"snapshot_available":archive_path(path,row[0]).is_file()}

class Handler(BaseHTTPRequestHandler):
    config = None
    def log_message(self, *_): pass
    def do_GET(self):
        parsed=urlparse(self.path); path=parsed.path
        if path == "/api/dashboard/overview":
            symbol=parse_qs(parsed.query).get("symbol",[None])[0]
            snapshot=read_json(current_path(self.config.storage.sqlite_path))
            configured = snapshot.get("configured_symbols") if isinstance(snapshot, dict) else None
            if not isinstance(configured, list) or not configured: return self.send_json(503,{"error":"unavailable"})
            if symbol is None: symbol = configured[0]
            if symbol not in configured: return self.send_json(400,{"error":"invalid_symbol"})
            if not snapshot or symbol not in snapshot["symbols"]: return self.send_json(503,{"error":"unavailable"})
            body={key:snapshot.get(key) for key in ("observed_at","last_successful_poll_at","configured_symbols","updates")}; body.update(snapshot["symbols"][symbol]); body["updates"]=body.get("updates") or []; body["bandwidth"]=bandwidth_with_rules(body.get("bandwidth") or latest_bandwidth(self.config.storage.sqlite_path,symbol),self.strategy_config.bandwidth_entry_guard); body["entry_risks"]=body.get("entry_risks") or body["bandwidth"].get("entry_risks",_empty_entry_risks()); body["runner"]={"status":runner_status(self.config.storage.sqlite_path)}; body["data_status"]="fresh"; return self.send_json(200,body)
        if path == "/api/dashboard/archives":
            try: limit=max(1,min(int(parse_qs(parsed.query).get("limit",[50])[0]),50))
            except ValueError: return self.send_json(400,{"error":"invalid_limit"})
            return self.send_json(200,{"archives":archives(self.config.storage.sqlite_path,limit)})
        match=re.fullmatch(r"/api/dashboard/archives/([0-9a-f-]{36})(/snapshot)?",path)
        if not match or not ID.fullmatch(match.group(1)): return self.send_json(404,{"error":"not_found"})
        if match.group(2):
            file=archive_path(self.config.storage.sqlite_path,match.group(1))
            if not file.is_file(): return self.send_json(404,{"error":"snapshot_unavailable"})
            data=file.read_bytes(); self.send_response(200); self.send_header("content-type","image/svg+xml"); self.end_headers(); return self.wfile.write(data)
        rows=[row for row in archives(self.config.storage.sqlite_path,50) if row["id"]==match.group(1)]
        return self.send_json(200,rows[0]) if rows else self.send_json(404,{"error":"not_found"})
    def send_json(self,status,payload):
        data=json.dumps(payload).encode(); self.send_response(status); self.send_header("content-type","application/json"); self.end_headers(); self.wfile.write(data)

def main(argv=None):
    parser=argparse.ArgumentParser(); parser.add_argument("--live-config",required=True); parser.add_argument("--port",type=int,default=8765); args=parser.parse_args(argv)
    Handler.config=load_live_config(args.live_config); Handler.strategy_config=load_config(Handler.config.strategy_config); ThreadingHTTPServer(("127.0.0.1",args.port),Handler).serve_forever()
if __name__ == "__main__": main()
