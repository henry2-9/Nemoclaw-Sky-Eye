import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import flight_recorder


def test_record_stage_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NEMOCLAW_FLIGHT_RECORDER", raising=False)
    path = os.path.join(tempfile.mkdtemp(), "flight.jsonl")
    assert flight_recorder.record_stage("t1", "stage", {"x": 1}, path=path) is None
    assert not os.path.exists(path)


def test_record_stage_and_render(monkeypatch):
    monkeypatch.setenv("NEMOCLAW_FLIGHT_RECORDER", "1")
    path = os.path.join(tempfile.mkdtemp(), "flight.jsonl")
    flight_recorder.record_stage("t1", "sweep_selected", {"channel": 19}, path=path)
    flight_recorder.record_stage("t1", "policy_decision", {"decision": "ALLOW"}, path=path)
    rows = flight_recorder.load(path)
    traces = flight_recorder.group_by_trace(rows)
    assert list(traces) == ["t1"]
    text = flight_recorder.render_text("t1", traces["t1"])
    assert "sweep_selected" in text
    assert "policy_decision" in text
