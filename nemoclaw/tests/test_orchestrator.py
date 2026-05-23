import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import orchestrator as orch

def test_select_caps_and_prioritizes():
    cands = [
        {"channel": 9, "event_type": "abnormal_crowd"},
        {"channel": 1, "event_type": "fire_smoke"},
        {"channel": 5, "event_type": "intrusion"},
        {"channel": 13, "event_type": "abnormal_weather"},
        {"channel": 2, "event_type": "fire_smoke"},
    ]
    sel = orch.select_candidates(cands, max_n=3)
    assert len(sel) == 3
    # fire_smoke 兩個優先,其次 intrusion
    assert [c["event_type"] for c in sel] == ["fire_smoke", "fire_smoke", "intrusion"]

def test_parse_grading_extracts_json_amid_prose():
    ans = '好的,分析如下 {"confirmed": true, "confidence": 0.85, "severity": "high", "summary": "濃煙"} 以上'
    g = orch.parse_grading(ans)
    assert g["confirmed"] is True
    assert g["confidence"] == 0.85
    assert g["severity"] == "high"

def test_parse_grading_bad_json_is_unconfirmed():
    g = orch.parse_grading("沒有偵測到任何 JSON 的純文字")
    assert g["confirmed"] is False
    assert g["confidence"] == 0.0

def test_parse_grading_clamps_and_validates():
    g = orch.parse_grading('{"confirmed": true, "confidence": 5, "severity": "bogus", "summary": "x"}')
    assert g["confidence"] == 1.0       # clamp 到 1
    assert g["severity"] == "low"        # 非法 severity 回退 low

def test_investigate_returns_none_when_unconfirmed():
    cand = {"channel": 5, "event_type": "intrusion", "frame_path": "/tmp/f.jpg"}
    analyze = lambda ch, q: '{"confirmed": false, "confidence": 0.1, "severity": "low", "summary": "無人"}'
    assert orch.investigate(cand, analyze) is None

def test_investigate_builds_incident_when_confirmed():
    cand = {"channel": 18, "event_type": "fire_smoke", "frame_path": "/tmp/f.jpg",
            "cheap_evidence": {"counts": {"smoke": 1}}}
    analyze = lambda ch, q: '{"confirmed": true, "confidence": 0.9, "severity": "high", "summary": "濃煙竄出"}'
    inc = orch.investigate(cand, analyze)
    assert inc["channel"] == "18"
    assert inc["confidence"] == 0.9
    assert inc["media_refs"] == ["/tmp/f.jpg"]
    assert any(e["tool"] == "fpg-analyze-video" for e in inc["evidence_citations"])

def test_run_cycle_silent_when_no_candidates():
    out = orch.run_cycle([], sweep_fn=lambda ch: [], analyze_fn=None, act_fn=None)
    assert out["candidates"] == 0 and out["incidents"] == 0

def test_run_cycle_full_path():
    cands = [{"channel": 18, "event_type": "fire_smoke", "frame_path": "/tmp/f.jpg",
              "cheap_evidence": {"counts": {"smoke": 1}}}]
    acted = []
    out = orch.run_cycle(
        channels=["dummy"],
        sweep_fn=lambda ch: cands,
        analyze_fn=lambda ch, q: '{"confirmed": true, "confidence": 0.9, "severity": "high", "summary": "濃煙"}',
        act_fn=lambda inc: acted.append(inc) or {"decision": "ALLOW"},
        max_n=4)
    assert out["candidates"] == 1 and out["incidents"] == 1
    assert acted[0]["event_type"] == "fire_smoke"
