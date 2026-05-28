import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import register_channels as rc

def test_load_channels_parses_yaml():
    chans = rc.load_channels(os.path.join(os.path.dirname(__file__), "..", "channels.yaml"))
    assert len(chans) == 16
    # id 唯一且為整數(實際號段避開既有 RTSP 攝影機,不綁定特定起始值)
    ids = [c["id"] for c in chans]
    assert len(set(ids)) == 16 and all(isinstance(i, int) for i in ids)
    assert chans[0]["event_type"] == "fire_smoke"
    assert chans[0]["path"].endswith("火煙偵測1.mp4")
    assert os.path.isabs(chans[0]["path"])

def test_register_calls_add_file_channel_for_each(monkeypatch):
    calls = []
    class FakeDB:
        def get_channel_by_channel_id(self, cid): return None
        def add_file_channel(self, channel_name, file_path, channel_id=None, location=""):
            calls.append((channel_name, file_path, channel_id)); return "id"
    chans = rc.load_channels(os.path.join(os.path.dirname(__file__), "..", "channels.yaml"))
    rc.register(chans, FakeDB())
    assert len(calls) == 16
    # 傳入的 channel_id 應與 yaml 一致
    assert [c[2] for c in calls] == [ch["id"] for ch in chans]


def test_register_updates_existing_stream_source_when_supported():
    calls = []

    class FakeDB:
        def get_channel_by_channel_id(self, cid):
            return {"channel_id": cid}

        def update_stream_channel(self, cid, name, url, location):
            calls.append((cid, name, url, location))

    rc.register([{"id": 201, "name": "Times Square", "url": "https://x", "path": "https://x"}], FakeDB())
    assert calls == [(201, "Times Square", "https://x", "NemoClaw Sentinel")]


def test_discovered_channels_merge_by_profile(tmp_path):
    discovered_landmarks = """channels:
  - id: 220
    name: discovered landmark
    url: https://example/landmark
    event_type: abnormal_crowd
"""
    discovered_traffic = """channels:
  - id: 120
    name: discovered intersection
    url: https://example/traffic
    event_type: security_anomaly
"""
    (tmp_path / "discovered.yaml").write_text(discovered_landmarks, encoding="utf-8")
    (tmp_path / "discovered_traffic.yaml").write_text(discovered_traffic, encoding="utf-8")
    main = """channels:
  - id: 1
    name: primary
    url: https://example/primary
    event_type: traffic
"""
    (tmp_path / "world_channels.yaml").write_text(main, encoding="utf-8")
    (tmp_path / "landmarks.yaml").write_text(main, encoding="utf-8")

    world = rc.load_channels(str(tmp_path / "world_channels.yaml"), merge_discovered=True)
    landmarks = rc.load_channels(str(tmp_path / "landmarks.yaml"), merge_discovered=True)

    assert [c["id"] for c in world] == [1, 120]
    assert world[1]["event_type"] == "traffic"
    assert [c["id"] for c in landmarks] == [1, 220]
    assert landmarks[1]["event_type"] == "security_anomaly"


def test_discovery_is_opt_in(monkeypatch):
    monkeypatch.delenv("NEMOCLAW_DISCOVERY_ENABLED", raising=False)
    assert rc.discovery_enabled() is False
    monkeypatch.setenv("NEMOCLAW_DISCOVERY_ENABLED", "1")
    assert rc.discovery_enabled() is True
