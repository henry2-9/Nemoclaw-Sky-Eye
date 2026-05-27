import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import sweep

# event_type → (query, 觸發門檻):counts 中相關類別 >= 門檻則為候選
def test_candidate_when_threshold_met(monkeypatch, tmp_path):
    # 隔離 baseline/feed_health 狀態,避免被先前累積污染(crowd 用 baseline 冷啟動 floor=2)
    monkeypatch.setenv("NEMOCLAW_BASELINE_PATH", str(tmp_path / "b.json"))
    monkeypatch.setenv("NEMOCLAW_FEED_HEALTH_PATH", str(tmp_path / "h.json"))
    monkeypatch.setattr(sweep.falcon_client, "detect",
        lambda img, q, **k: {"counts": {"person": 3}})
    monkeypatch.setattr(sweep.feed, "grab_frame", lambda *a, **k: "/tmp/f.jpg")
    chan = {"id": 9, "name": "Cam09", "path": "/v/a.mp4", "event_type": "abnormal_crowd"}
    cands = sweep.sweep_channels([chan])
    assert len(cands) == 1
    assert cands[0]["channel"] == 9
    assert cands[0]["event_type"] == "abnormal_crowd"

def test_silent_when_below_threshold(monkeypatch):
    monkeypatch.setattr(sweep.falcon_client, "detect",
        lambda img, q, **k: {"counts": {"person": 0}})
    monkeypatch.setattr(sweep.feed, "grab_frame", lambda *a, **k: "/tmp/f.jpg")
    chan = {"id": 5, "name": "Cam05", "path": "/v/b.mp4", "event_type": "intrusion"}
    assert sweep.sweep_channels([chan]) == []

def test_format_output_silent_when_empty():
    assert sweep.format_output([]).strip() == "[SILENT]"

def test_format_output_json_when_candidates():
    out = sweep.format_output([{"channel": 9, "event_type": "abnormal_crowd"}])
    assert '"channel": 9' in out
    assert "[SILENT]" not in out


def test_traffic_normal_vehicle_does_not_wake_nemotron(monkeypatch, tmp_path):
    monkeypatch.setenv("NEMOCLAW_BASELINE_PATH", str(tmp_path / "b.json"))
    monkeypatch.setenv("NEMOCLAW_FEED_HEALTH_PATH", str(tmp_path / "h.json"))
    monkeypatch.setattr(sweep.falcon_client, "detect",
        lambda img, q, **k: {"counts": {"car": 1, "person": 1}})
    monkeypatch.setattr(sweep.feed, "grab_frame", lambda *a, **k: "/tmp/f.jpg")
    chan = {"id": 101, "name": "road", "path": "http://cam", "event_type": "traffic"}
    assert sweep.sweep_channels([chan]) == []


def test_security_anomaly_promotes_fire_on_landmark(monkeypatch, tmp_path):
    monkeypatch.setenv("NEMOCLAW_BASELINE_PATH", str(tmp_path / "b.json"))
    monkeypatch.setenv("NEMOCLAW_FEED_HEALTH_PATH", str(tmp_path / "h.json"))
    monkeypatch.setenv("NEMOCLAW_LIVE_EVIDENCE_CLIP", "0")
    monkeypatch.setattr(sweep.falcon_client, "detect",
        lambda img, q, **k: {"counts": {"smoke": 1}})
    monkeypatch.setattr(sweep.feed, "grab_frame", lambda *a, **k: "/tmp/f.jpg")
    chan = {"id": 201, "name": "city", "path": "http://cam", "event_type": "security_anomaly"}
    cands = sweep.sweep_channels([chan])
    assert len(cands) == 1
    assert cands[0]["event_type"] == "security_anomaly"


def test_successful_patrol_publishes_wall_snapshot_even_without_incident(monkeypatch):
    published = []
    monkeypatch.setattr(sweep.falcon_client, "detect",
        lambda img, q, **k: {"counts": {"person": 0}})
    monkeypatch.setattr(sweep.feed, "grab_frame", lambda *a, **k: "/tmp/f.jpg")
    monkeypatch.setattr(sweep._wall_snapshots, "publish",
        lambda channel, name, frame: published.append((channel, name, frame)))
    chan = {"id": 201, "name": "Landmark", "path": "http://cam", "event_type": "security_anomaly"}

    assert sweep.sweep_channels([chan]) == []
    assert published == [(201, "Landmark", "/tmp/f.jpg")]
