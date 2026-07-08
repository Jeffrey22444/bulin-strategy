import json

from bbmr.live.state_store import LiveStateStore
from scripts.live_safety_journal import main


def test_live_safety_journal_prints_only_safety_severities(tmp_path, capsys):
    path = tmp_path / "live.sqlite3"
    store = LiveStateStore(str(path))
    store.append_event("setup_created", "BTC")
    store.append_event("recoverable_network_error", "BTC", payload_json=json.dumps({"severity": "WARN", "reason": "timeout"}))
    store.append_event("debug_event", "ETH", payload_json=json.dumps({"severity": "INFO", "reason": "ignore"}))
    store.append_event("entry_unprotected", "SOL", payload_json=json.dumps({"severity": "CRITICAL", "reason": "stop failed"}))

    assert main([str(path), "--limit", "10"]) == 0

    output = capsys.readouterr().out
    assert "[WARN] recoverable_network_error BTC" in output
    assert "[CRITICAL] entry_unprotected SOL" in output
    assert "setup_created" not in output
    assert "debug_event" not in output
