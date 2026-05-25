import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import watchdog


def test_service_health_maps_up_down():
    svcs = [("nemotron", "http://x/1"), ("falcon", "http://x/2"), ("nemoclaw", "http://x/3")]
    health = watchdog.service_health(svcs, probe=lambda u: u.endswith("1"))
    assert health == {"nemotron": "up", "falcon": "down", "nemoclaw": "down"}


def test_healthy_all_up():
    assert watchdog.healthy({"a": "up", "b": "up"}) is True
    assert watchdog.healthy({"a": "up", "b": "down"}) is False
    assert watchdog.healthy({}) is False


def test_record_transition_only_on_change(tmp_path):
    path = tmp_path / "health.jsonl"
    up = {"nemotron": "up", "falcon": "up", "nemoclaw": "up"}
    down = {"nemotron": "up", "falcon": "down", "nemoclaw": "up"}
    assert watchdog._record_transition(None, up, str(path)) is True       # 首次記
    assert watchdog._record_transition(up, up, str(path)) is False        # 不變不記
    assert watchdog._record_transition(up, down, str(path)) is True       # 降級
    assert watchdog._record_transition(down, up, str(path)) is True       # 復原
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    import json
    evts = [json.loads(l)["event"] for l in lines]
    assert evts == ["recover", "degrade", "recover"]
