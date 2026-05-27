import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import correlation


def _append_audit(path, rows):
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_scan_emits_when_two_channels_share_event_type(tmp_path, monkeypatch):
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setenv("NEMOCLAW_AUDIT_PATH", str(audit))
    now = time.time()
    _append_audit(audit, [
        {"decision": "ALLOW", "ts": now - 60, "channel": "201",
         "event_type": "fire_smoke", "severity": "high",
         "summary": "Times Square 大量濃煙", "trace_id": "t1"},
        {"decision": "ALLOW", "ts": now - 30, "channel": "202",
         "event_type": "fire_smoke", "severity": "high",
         "summary": "Rialto Bridge 火光", "trace_id": "t2"},
    ])
    alerts = correlation.scan(window_sec=300, min_channels=2, now_ts=now)
    assert len(alerts) == 1
    a = alerts[0]
    assert a["event_type"] == "fire_smoke"
    assert a["channels"] == ["201", "202"]
    assert a["severity_inferred"] == "high"
    assert len(a["evidence"]) == 2


def test_scan_critical_when_three_or_more_channels(tmp_path, monkeypatch):
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setenv("NEMOCLAW_AUDIT_PATH", str(audit))
    now = time.time()
    _append_audit(audit, [
        {"decision": "ALLOW", "ts": now - i * 30, "channel": str(200 + i),
         "event_type": "intrusion", "severity": "high",
         "summary": f"event {i}", "trace_id": f"t{i}"}
        for i in range(1, 4)
    ])
    alerts = correlation.scan(window_sec=300, min_channels=2, now_ts=now)
    assert len(alerts) == 1
    assert alerts[0]["severity_inferred"] == "critical"
    assert alerts[0]["channel_count"] == 3


def test_scan_ignores_rows_outside_window(tmp_path, monkeypatch):
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setenv("NEMOCLAW_AUDIT_PATH", str(audit))
    now = time.time()
    _append_audit(audit, [
        {"decision": "ALLOW", "ts": now - 1000, "channel": "201",
         "event_type": "fire_smoke", "severity": "high", "summary": "old"},
        {"decision": "ALLOW", "ts": now - 60, "channel": "202",
         "event_type": "fire_smoke", "severity": "high", "summary": "fresh"},
    ])
    alerts = correlation.scan(window_sec=300, min_channels=2, now_ts=now)
    assert alerts == []


def test_scan_dedup_within_ttl(tmp_path, monkeypatch):
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setenv("NEMOCLAW_AUDIT_PATH", str(audit))
    now = time.time()
    _append_audit(audit, [
        {"decision": "ALLOW", "ts": now - 60, "channel": "201",
         "event_type": "fire_smoke", "severity": "high", "summary": "a"},
        {"decision": "ALLOW", "ts": now - 30, "channel": "202",
         "event_type": "fire_smoke", "severity": "high", "summary": "b"},
    ])
    first = correlation.scan(window_sec=300, min_channels=2, now_ts=now)
    assert len(first) == 1
    second = correlation.scan(window_sec=300, min_channels=2, dedup_ttl=600, now_ts=now + 60)
    assert second == []


def test_scan_skips_blocked_or_abstain(tmp_path, monkeypatch):
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setenv("NEMOCLAW_AUDIT_PATH", str(audit))
    now = time.time()
    _append_audit(audit, [
        {"decision": "BLOCK", "ts": now - 60, "channel": "201",
         "event_type": "fire_smoke", "severity": "high", "summary": "x"},
        {"decision": "ABSTAIN", "ts": now - 30, "channel": "202",
         "event_type": "fire_smoke", "severity": "high", "summary": "y"},
    ])
    assert correlation.scan(window_sec=300, min_channels=2, now_ts=now) == []


def test_latest_returns_in_reverse_chronological(tmp_path, monkeypatch):
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setenv("NEMOCLAW_AUDIT_PATH", str(audit))
    now = time.time()
    _append_audit(audit, [
        {"decision": "ALLOW", "ts": now - 60, "channel": "201",
         "event_type": "fire_smoke", "severity": "high", "summary": "a"},
        {"decision": "ALLOW", "ts": now - 30, "channel": "202",
         "event_type": "fire_smoke", "severity": "high", "summary": "b"},
    ])
    correlation.scan(window_sec=300, min_channels=2, now_ts=now)
    items = correlation.latest(5)
    assert len(items) == 1
    assert items[0]["event_type"] == "fire_smoke"
