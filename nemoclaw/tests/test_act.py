import os, sys, tempfile, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import act

def _policy_path(): return os.path.join(os.path.dirname(__file__), "..", "policy.yaml")

def test_allow_notifies_and_audits(monkeypatch):
    monkeypatch.setenv("NEMOCLAW_MEDIA_ENABLED", "0")
    sent = {}
    monkeypatch.setattr(act.notify, "notify_from_env",
                        lambda text, photo_path=None: sent.update(text=text, photo=photo_path))
    monkeypatch.setattr(act.redact, "redact_pii", lambda p, out_path=None: p + "_red.jpg")
    audit_path = os.path.join(tempfile.mkdtemp(), "a.jsonl")
    inc = {"channel":"7","event_type":"fire_smoke","confidence":0.9,"severity":"high",
           "summary":"濃煙竄出","media_refs":["/tmp/x.jpg"],
           "evidence_citations":[{"tool":"sentinel-analyze-video","finding":"濃煙"}]}
    d = act.run(inc, policy_path=_policy_path(), recent=[], audit_path=audit_path, now=datetime.datetime(2026,5,24,12,0))
    assert d["decision"] == "ALLOW"
    assert "text" in sent                       # 有通知
    assert os.path.exists(audit_path)           # 有稽核
    assert d.get("redacted") is True            # 走過馬賽克
    assert d["notification_sent"] is True

def test_block_does_not_notify(monkeypatch):
    monkeypatch.setenv("NEMOCLAW_MEDIA_ENABLED", "0")
    sent = {}
    monkeypatch.setattr(act.notify, "notify_from_env", lambda **k: sent.update(k))
    audit_path = os.path.join(tempfile.mkdtemp(), "a.jsonl")
    inc = {"channel":"7","event_type":"fire_smoke","confidence":0.4,"severity":"high",
           "evidence_citations":[{"tool":"x","finding":"y"}]}
    d = act.run(inc, policy_path=_policy_path(), recent=[], audit_path=audit_path, now=datetime.datetime(2026,5,24,12,0))
    assert d["decision"] == "BLOCK"
    assert sent == {}                           # 未通知
    assert os.path.exists(audit_path)           # 仍留稽核

def test_notify_disabled_skips_external_send(monkeypatch):
    monkeypatch.setenv("NEMOCLAW_MEDIA_ENABLED", "0")
    monkeypatch.setenv("NEMOCLAW_NOTIFY_DISABLED", "1")
    sent = {}
    monkeypatch.setattr(act.notify, "notify_from_env",
                        lambda text, photo_path=None: sent.update(text=text, photo=photo_path))
    audit_path = os.path.join(tempfile.mkdtemp(), "a.jsonl")
    inc = {"trace_id":"t1","channel":"7","event_type":"fire_smoke","confidence":0.9,"severity":"high",
           "summary":"濃煙竄出","media_refs":["/tmp/x.jpg"],
           "evidence_citations":[{"tool":"sentinel-analyze-video","finding":"濃煙"}]}
    d = act.run(inc, policy_path=_policy_path(), recent=[], audit_path=audit_path,
                now=datetime.datetime(2026,5,24,12,0))
    assert d["decision"] == "ALLOW"
    assert sent == {}
    assert d["trace_id"] == "t1"
    assert d["notification_sent"] is False
    assert any("notify disabled" in r for r in d["reasons"])

def test_critical_escalates_and_autogenerates_report(monkeypatch, tmp_path):
    monkeypatch.setenv("NEMOCLAW_MEDIA_ENABLED", "0")
    monkeypatch.setenv("NEMOCLAW_MEDIA_DIR", str(tmp_path))
    sent = {}
    monkeypatch.setattr(act.notify, "notify_from_env",
                        lambda text, photo_path=None: sent.update(text=text, photo=photo_path))
    monkeypatch.setattr(act.redact, "redact_pii", lambda p, out_path=None: p + "_red.jpg")
    audit_path = os.path.join(tempfile.mkdtemp(), "a.jsonl")
    inc = {"trace_id": "t-crit", "channel": "5", "event_type": "fire_smoke",
           "confidence": 0.95, "severity": "critical", "summary": "大量濃煙",
           "media_refs": ["/tmp/x.jpg"], "governed_by": "nemoclaw-openshell",
           "evidence_citations": [{"tool": "sentinel-analyze-video", "finding": "fire"}]}
    d = act.run(inc, policy_path=_policy_path(), recent=[], audit_path=audit_path,
                now=datetime.datetime(2026, 5, 26, 12, 0))
    assert d["decision"] == "ALLOW"
    assert d["escalated"] is True                       # critical → 自主二級升級
    assert d["report_path"] and os.path.exists(d["report_path"])  # 自主產報告
    assert "二級升級" in sent["text"]                    # 通知含升級標記


def test_high_escalates_without_report(monkeypatch):
    monkeypatch.setenv("NEMOCLAW_MEDIA_ENABLED", "0")
    monkeypatch.setattr(act.notify, "notify_from_env", lambda text, photo_path=None: None)
    monkeypatch.setattr(act.redact, "redact_pii", lambda p, out_path=None: p)
    audit_path = os.path.join(tempfile.mkdtemp(), "a.jsonl")
    inc = {"trace_id": "t-high", "channel": "7", "event_type": "fire_smoke",
           "confidence": 0.9, "severity": "high", "summary": "濃煙",
           "media_refs": ["/tmp/x.jpg"],
           "evidence_citations": [{"tool": "x", "finding": "y"}]}
    d = act.run(inc, policy_path=_policy_path(), recent=[], audit_path=audit_path,
                now=datetime.datetime(2026, 5, 26, 12, 0))
    assert d["escalated"] is True       # high 路由含 escalate
    assert d["report_path"] is None     # high 不含 report


def test_notification_text_includes_media_links():
    text = act._notification_text(
        {"channel":"19","event_type":"fire_smoke","severity":"critical","summary":"濃煙"},
        {"injection_detected":True, "media_artifacts":{"urls":{
            "trace":"http://dash/trace?trace_id=t1",
            "clip":"http://dash/media/t1/clip.mp4",
            "falcon_annotated":"http://dash/media/t1/falcon_annotated.jpg",
        }}},
    )
    assert "事件頁: http://dash/trace?trace_id=t1" in text
    assert "錄影切片: http://dash/media/t1/clip.mp4" in text
    assert "感知標記圖: http://dash/media/t1/falcon_annotated.jpg" in text


def test_allow_persists_confirmed_incident_to_sqlite(monkeypatch):
    monkeypatch.setenv("NEMOCLAW_MEDIA_ENABLED", "0")
    monkeypatch.setenv("NEMOCLAW_NOTIFY_DISABLED", "1")
    monkeypatch.setenv("NEMOCLAW_EVENT_STORE_ENABLED", "1")
    monkeypatch.setenv("NEMOCLAW_DB_BACKEND", "sqlite")
    inc = {"trace_id": "persist-1", "channel": "19", "event_type": "security_anomaly",
           "confidence": 0.93, "severity": "medium", "summary": "遺留行李",
           "trigger_origin": "scheduled",
           "evidence_citations": [{"tool": "falcon", "finding": "bag"}]}

    d = act.run(inc, policy_path=_policy_path(), recent=[],
                now=datetime.datetime(2026, 5, 26, 12, 0))
    import sqlite_store
    row = sqlite_store.EventStore().get_event_by_id("persist-1")

    assert d["decision"] == "ALLOW"
    assert d["event_id"] == "persist-1"
    assert row["type_id"] == 9
    assert row["metadata"]["trigger_origin"] == "scheduled"
