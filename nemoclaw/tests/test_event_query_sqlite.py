import argparse
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import event_query_sqlite as q  # noqa: E402
import sqlite_store as s  # noqa: E402


@pytest.fixture(autouse=True)
def fresh(tmp_path):
    """每個測試獨立 db + workspace;store/query 皆在呼叫時讀 env/模組變數。"""
    os.environ["NEMOCLAW_SQLITE_PATH"] = str(tmp_path / "q.db")
    os.environ["SENTINEL_WORKSPACE"] = str(tmp_path)
    q.WORKSPACE_ROOT = str(tmp_path)
    q.EVENT_DATA_ROOT = str(tmp_path / "event_data")
    q._CAMS_CACHE = None
    yield


def _ns(**kw):
    base = dict(hours=None, days=None, today=False, start=None, end=None,
               camera=None, type=None, event_class=None, status="all",
               limit=10, id=None, kind="all")
    base.update(kw)
    return argparse.Namespace(**base)


def _seed():
    cs = s.ChannelStore()
    cs.add_stream_channel("camX", "https://x/cam?camera=1", 5, "Plant-A")
    es = s.EventStore()
    # 用 FPG mongo 風格大寫鍵寫入,驗證 sqlite_store 的鍵名相容
    es.insert_event({"event_id": "ev1", "Channel_id": 5, "Event_type_id": 4,
                     "Event_class_id": 0, "Description": "fire detected",
                     "Event_time": "2026-05-25T10:00:00",
                     "metadata": {"source": "video_ingest"}})
    return es


def test_insert_accepts_capitalized_keys():
    es = s.EventStore()
    es.insert_event({"event_id": "e9", "Channel_id": 3, "Event_type_id": 4,
                     "Event_class_id": 1, "Description": "smoke"})
    ev = es.get_event_by_id("e9")
    assert ev["camera_id"] == 3 and ev["type_id"] == 4
    assert ev["class_id"] == 1 and ev["description"] == "smoke"


def test_cameras():
    _seed()
    out = q.cmd_cameras()
    assert any(c["channel_id"] == 5 and c["channel_name"] == "camX"
               for c in out["cameras"])


def test_latest_enriches_event():
    _seed()
    out = q.cmd_latest(_ns())
    assert out["events"] and out["events"][0]["event_id"] == "ev1"
    ev0 = out["events"][0]
    assert ev0["event_type_id"] == 4 and ev0["event_type_name"] == "火煙偵測"
    assert ev0["description"] == "fire detected"
    assert ev0["camera"]["channel_name"] == "camX"
    assert ev0["location"] == "Plant-A"


def test_summary_counts():
    _seed()
    out = q.cmd_summary(_ns(limit=5))
    assert out["total_events"] == 1
    assert out["backend"] == "sqlite"
    assert out["by_type"][0]["event_type_id"] == 4
    assert out["by_camera"][0]["channel_id"] == 5


def test_event_by_id():
    _seed()
    out = q.cmd_event(_ns(id="ev1"))
    assert out["event"]["event_id"] == "ev1"
    assert "full_image" in out["event"] and "video" in out["event"]


def test_filter_by_camera():
    es = _seed()
    es.insert_event({"event_id": "ev2", "Channel_id": 9, "Event_type_id": 7,
                     "Description": "intrusion", "Event_time": "2026-05-25T11:00:00"})
    out = q.cmd_latest(_ns(camera=9))
    assert len(out["events"]) == 1 and out["events"][0]["event_id"] == "ev2"


def test_filter_by_type_alias():
    es = _seed()
    es.insert_event({"event_id": "ev2", "Channel_id": 9, "Event_type_id": 7,
                     "Description": "intrusion", "Event_time": "2026-05-25T11:00:00"})
    out = q.cmd_latest(_ns(type="fire_smoke"))  # 別名 → type 4
    assert len(out["events"]) == 1 and out["events"][0]["event_id"] == "ev1"


def test_media_scans_event_data(tmp_path):
    _seed()
    ed = tmp_path / "event_data"
    ed.mkdir()
    (ed / "ev1_cam5_f.jpg").write_bytes(b"\xff\xd8\xff")
    (ed / "ev1_cam5_v.mp4").write_bytes(b"\x00\x00")
    out = q.cmd_media(_ns(id="ev1"))
    fulls = out["full_image"]["candidates"]
    vids = out["video"]["candidates"]
    assert any(c["exists"] and c["absolute_path"].endswith("_f.jpg") for c in fulls)
    assert any(c["exists"] and c["absolute_path"].endswith("_v.mp4") for c in vids)
    assert out.get("media_directive", "").startswith("MEDIA:")


def test_unknown_type_fails():
    _seed()
    with pytest.raises(SystemExit) as exc:
        q.cmd_latest(_ns(type="no_such_type"))
    assert exc.value.code == 2


# ── sentinel-violation-report 的 drop-in 介面 ──

def test_enrich_event_attaches_media_blocks(tmp_path):
    _seed()
    q._CAMS_CACHE = None  # 清快取(fixture 換了 db)
    ed = tmp_path / "event_data"
    ed.mkdir()
    (ed / "ev1_cam5_f.jpg").write_bytes(b"\xff\xd8\xff")
    row = s.EventStore().get_event_by_id("ev1")
    out = q.enrich_event(row)
    assert out["full_image"]["candidates"] and out["full_image"]["candidates"][0]["kind"] == "file"
    assert "crop_image" in out and out["crop_image"]["candidates"] == []
    assert out["event_class_title"] == "火煙偵測"
    out = q.attach_media_delivery(out)
    assert out.get("media_directive", "").startswith("MEDIA:")


def test_filter_violations_only():
    es = _seed()  # ev1 = type 4(非 safety)→ 違規
    es.insert_event({"event_id": "safe1", "Channel_id": 5, "Event_type_id": 3,
                     "Description": "safety ok", "Event_time": "2026-05-25T09:00:00"})
    es.insert_event({"event_id": "safe_viol", "Channel_id": 5, "Event_type_id": 3,
                     "Description": "safety violation", "Event_time": "2026-05-25T09:30:00",
                     "metadata": {"has_violation": True}})
    rows = s.EventStore().get_latest_events(100)
    viol = q.filter_violations_only(rows)
    ids = {r["event_id"] for r in viol}
    assert "ev1" in ids and "safe_viol" in ids and "safe1" not in ids
