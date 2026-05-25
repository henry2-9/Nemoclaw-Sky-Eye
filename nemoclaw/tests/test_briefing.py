import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import briefing


def _audit(tmp_path, rows):
    p = tmp_path / "audit.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return str(p)


def test_recent_events_filters_window_and_allow(tmp_path):
    now = 1000000.0
    path = _audit(tmp_path, [
        {"decision": "ALLOW", "ts": now - 100, "severity": "high", "channel": "5", "event_type": "fire_smoke", "summary": "煙"},
        {"decision": "ALLOW", "ts": now - 99999, "severity": "low", "channel": "2", "event_type": "x"},   # 太舊
        {"decision": "BLOCK", "ts": now - 50, "severity": "high"},                                         # 非 ALLOW
    ])
    evs = briefing.recent_events(hours=1, audit_path=path, now=now)
    assert len(evs) == 1 and evs[0]["channel"] == "5"


def test_fallback_brief_no_events():
    assert "無確認事件" in briefing.generate_briefing(hours=1, audit_path="/no/such", now=0)


def test_fallback_brief_summarizes(tmp_path):
    now = 1000000.0
    path = _audit(tmp_path, [
        {"decision": "ALLOW", "ts": now - 10, "severity": "high", "channel": "5", "event_type": "fire_smoke", "summary": "濃煙"},
        {"decision": "ALLOW", "ts": now - 20, "severity": "critical", "channel": "7", "event_type": "fire_smoke", "summary": "明火"},
    ])
    text = briefing.generate_briefing(hours=1, audit_path=path, now=now)   # 無 vlm_fn → fallback
    assert "2 起" in text and "critical" in text and ("7" in text)


def test_vlm_fn_used_when_available(tmp_path):
    now = 1000000.0
    path = _audit(tmp_path, [
        {"decision": "ALLOW", "ts": now - 10, "severity": "high", "channel": "5", "event_type": "fire_smoke", "summary": "煙"},
    ])
    text = briefing.generate_briefing(hours=1, audit_path=path, now=now,
                                      vlm_fn=lambda p: "【簡報】1 起高風險事件,建議派員查看。")
    assert text == "【簡報】1 起高風險事件,建議派員查看。"


def test_write_read_latest(tmp_path):
    p = tmp_path / "latest.txt"
    briefing.write_latest("情勢穩定", path=str(p))
    assert briefing.read_latest(str(p)) == "情勢穩定"
