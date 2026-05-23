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
