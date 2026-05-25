import os, sys, tempfile
os.environ["NEMOCLAW_SQLITE_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import sqlite_store as s

def test_channel_add_stream_and_resolve():
    cs = s.ChannelStore()
    assert cs.add_stream_channel("camA", "https://x/cam?camera=1", 101, "demo")
    ch = cs.get_channel_by_channel_id(101)
    assert ch and ch["source_url"].endswith("camera=1") and ch["source_type"] == "stream"
    assert ("https://x/cam?camera=1", 101) in cs.get_stream_sources_with_channel_ids()

def test_channel_unique_name_and_id():
    cs = s.ChannelStore()
    cs.add_stream_channel("dup", "https://a", 301)
    assert cs.add_stream_channel("dup", "https://b", 302) is None     # 名稱重複
    assert cs.add_stream_channel("other", "https://c", 301) is None   # id 重複

def test_file_channel_requires_existing_file():
    cs = s.ChannelStore()
    assert cs.add_file_channel("missing", "/no/such/file.mp4", 401) is None

def test_event_insert_get_latest():
    es = s.EventStore()
    eid = es.insert_event({"event_id": "e1", "camera_id": 9, "description": "smoke",
                           "metadata": {"k": 1}, "image_path": "/x.jpg"})
    assert eid == "e1"
    ev = es.get_event_by_id("e1")
    assert ev["description"] == "smoke" and ev["metadata"]["k"] == 1
    assert any(e["event_id"] == "e1" for e in es.get_latest_events(10))
    assert any(e["event_id"] == "e1" for e in es.get_latest_events_by_camera(9, 10))
