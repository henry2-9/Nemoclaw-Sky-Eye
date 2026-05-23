import os, sys, tempfile, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import act

def _policy_path(): return os.path.join(os.path.dirname(__file__), "..", "policy.yaml")

def test_allow_notifies_and_audits(monkeypatch):
    sent = {}
    monkeypatch.setattr(act.notify, "notify_from_env",
                        lambda text, photo_path=None: sent.update(text=text, photo=photo_path))
    monkeypatch.setattr(act.redact, "redact_pii", lambda p, out_path=None: p + "_red.jpg")
    audit_path = os.path.join(tempfile.mkdtemp(), "a.jsonl")
    inc = {"channel":"7","event_type":"fire_smoke","confidence":0.9,"severity":"high",
           "summary":"濃煙竄出","media_refs":["/tmp/x.jpg"],
           "evidence_citations":[{"tool":"fpg-analyze-video","finding":"濃煙"}]}
    d = act.run(inc, policy_path=_policy_path(), recent=[], audit_path=audit_path, now=datetime.datetime(2026,5,24,12,0))
    assert d["decision"] == "ALLOW"
    assert "text" in sent                       # 有通知
    assert os.path.exists(audit_path)           # 有稽核
    assert d.get("redacted") is True            # 走過馬賽克

def test_block_does_not_notify(monkeypatch):
    sent = {}
    monkeypatch.setattr(act.notify, "notify_from_env", lambda **k: sent.update(k))
    audit_path = os.path.join(tempfile.mkdtemp(), "a.jsonl")
    inc = {"channel":"7","event_type":"fire_smoke","confidence":0.4,"severity":"high",
           "evidence_citations":[{"tool":"x","finding":"y"}]}
    d = act.run(inc, policy_path=_policy_path(), recent=[], audit_path=audit_path, now=datetime.datetime(2026,5,24,12,0))
    assert d["decision"] == "BLOCK"
    assert sent == {}                           # 未通知
    assert os.path.exists(audit_path)           # 仍留稽核
