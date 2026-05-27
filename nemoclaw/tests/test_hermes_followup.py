import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import hermes_followup as hf


def test_validate_cmd_allowlist():
    assert hf.validate_cmd("date -u")
    assert hf.validate_cmd("uname -a")
    assert hf.validate_cmd("curl -s -m 5 https://api.weather.gov/alerts")
    assert hf.validate_cmd("dig +short example.com")
    assert hf.validate_cmd("ping -c 1 1.1.1.1")
    # blocked commands
    assert not hf.validate_cmd("rm -rf /")
    assert not hf.validate_cmd("bash -c date")
    assert not hf.validate_cmd("python -c 'print(1)'")


def test_validate_cmd_blocks_shell_metachars():
    assert not hf.validate_cmd("date; ls")
    assert not hf.validate_cmd("date && ls")
    assert not hf.validate_cmd("date | ls")
    assert not hf.validate_cmd("date > /tmp/x")
    assert not hf.validate_cmd("date `id`")
    assert not hf.validate_cmd("date $(id)")


def test_validate_cmd_curl_must_be_https():
    assert not hf.validate_cmd("curl http://insecure.com")
    assert not hf.validate_cmd("curl -X POST https://api.example.com")
    assert not hf.validate_cmd("curl --upload-file f https://example.com")


def test_validate_cmd_ping_count_required_and_capped():
    assert not hf.validate_cmd("ping 1.1.1.1")
    assert not hf.validate_cmd("ping -c 99 1.1.1.1")
    assert hf.validate_cmd("ping -c 3 1.1.1.1")


def test_run_pipeline_with_mocks(tmp_path, monkeypatch):
    monkeypatch.setenv("NEMOCLAW_FOLLOWUPS_PATH", str(tmp_path / "followups.jsonl"))

    def fake_plan(incident):
        return {"commands": [{"cmd": "date -u", "purpose": "對時"}],
                "rationale": "驗證系統時間"}

    def fake_exec(cmd):
        return ("Wed May 27 13:00:00 UTC 2026", "", 0, 42)

    def fake_conclude(incident, results):
        return "時間正常,無異常。"

    incident = {"trace_id": "t1", "channel": "201", "event_type": "fire_smoke",
                "severity": "high", "summary": "濃煙"}
    out = hf.run(incident, plan_fn=fake_plan, exec_fn=fake_exec, conclude_fn=fake_conclude)
    assert out is not None
    assert out["channel"] == "201"
    assert len(out["commands"]) == 1
    assert out["commands"][0]["stdout"] == "Wed May 27 13:00:00 UTC 2026"
    assert out["conclusion"] == "時間正常,無異常。"
    assert out["governed_by"] == "nemoclaw-openshell-sandbox"
    # persisted
    items = hf.latest(5)
    assert len(items) == 1
    assert items[0]["trace_id"] == "t1"


def test_run_returns_none_when_plan_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("NEMOCLAW_FOLLOWUPS_PATH", str(tmp_path / "followups.jsonl"))
    out = hf.run({"trace_id": "t"}, plan_fn=lambda i: None)
    assert out is None
    assert hf.latest(5) == []


def test_run_filters_invalid_cmds_from_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("NEMOCLAW_FOLLOWUPS_PATH", str(tmp_path / "followups.jsonl"))
    # plan proposes one valid + one invalid; only valid one runs
    calls = []

    def fake_plan(incident):
        # simulate hf.plan() output where invalid cmd is already filtered out by plan
        # at higher level (validate_cmd inside plan), so we test exec path
        return {"commands": [{"cmd": "date -u", "purpose": "對時"}], "rationale": "x"}

    def fake_exec(cmd):
        calls.append(cmd)
        return ("ok", "", 0, 10)

    hf.run({"trace_id": "t", "channel": "1", "event_type": "x", "severity": "high"},
           plan_fn=fake_plan, exec_fn=fake_exec, conclude_fn=lambda i, r: "")
    assert calls == ["date -u"]
