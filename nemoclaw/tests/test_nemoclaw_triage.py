import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import nemoclaw_triage as t

def test_parse_valid_json():
    r = t.parse('好 {"severity":"high","recommended_action":"escalate","rationale":"濃煙擴大"} 完')
    assert r["severity"] == "high"
    assert r["recommended_action"] == "escalate"
    assert r["governed_by"] == "nemoclaw-openshell"

def test_parse_invalid_values_become_none():
    r = t.parse('{"severity":"bogus","recommended_action":"nuke","rationale":"x"}')
    assert r["severity"] is None and r["recommended_action"] is None

def test_parse_no_json_returns_none():
    assert t.parse("沒有 json") is None

def test_triage_uses_injected_post():
    def fake_post(endpoint, payload, timeout):
        # 確認送的是 hermes-agent + 含描述
        assert payload["model"] == "hermes-agent"
        assert "濃煙" in payload["messages"][-1]["content"]
        return {"choices":[{"message":{"content":'{"severity":"critical","recommended_action":"report","rationale":"火勢擴大"}'}}]}
    r = t.triage("fire_smoke", "畫面有濃煙竄出", {"counts":{"smoke":1}}, post=fake_post)
    assert r["severity"] == "critical"
    assert r["recommended_action"] == "report"

def test_triage_graceful_degrade_on_error():
    def boom(*a, **k): raise OSError("8642 down")
    assert t.triage("fire_smoke", "desc", {}, post=boom) is None
