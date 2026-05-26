import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import curiosity


def _audit(tmp_path, rows):
    p = tmp_path / "audit.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return str(p)


def test_pick_most_stale_above_threshold(tmp_path):
    chans = [
        {"id": 9, "path": "/v/9.mp4", "name": "Cam9", "event_type": "abnormal_crowd"},
        {"id": 10, "path": "/v/10.mp4", "name": "Cam10", "event_type": "abnormal_crowd"},
        {"id": 11, "path": "/v/11.mp4", "name": "Cam11", "event_type": "abnormal_crowd"},
    ]
    now = 1_000_000.0
    path = _audit(tmp_path, [
        {"channel": "9", "ts": now - 300},          # 5 分前
        {"channel": "10", "ts": now - 2 * 3600},    # 2 小時前(最久)
        {"channel": "11", "ts": now - 30 * 60},     # 30 分前
    ])
    pick = curiosity.stale_pick(chans, audit_path=path, min_idle_minutes=15, now=now)
    assert pick is not None
    ch, idle_min = pick
    assert ch["id"] == 10 and idle_min == 120  # 最久那一台


def test_skip_stream_channels(tmp_path):
    chans = [
        {"id": 101, "path": "https://x/live", "event_type": "traffic"},
        {"id": 102, "path": "rtsp://x/live", "event_type": "traffic"},
    ]
    pick = curiosity.stale_pick(chans, audit_path=None, min_idle_minutes=15, now=1_000_000)
    assert pick is None       # live stream 略過


def test_none_when_all_recent(tmp_path):
    chans = [{"id": 9, "path": "/v/9.mp4", "event_type": "abnormal_crowd"}]
    now = 1_000_000
    path = _audit(tmp_path, [{"channel": "9", "ts": now - 60}])
    assert curiosity.stale_pick(chans, audit_path=path, min_idle_minutes=15, now=now) is None


def test_candidate_shape():
    ch = {"id": 12, "name": "Cam12", "path": "/v/12.mp4", "event_type": "abnormal_crowd"}
    c = curiosity.curiosity_candidate(ch, now=1234.0)
    assert c["channel"] == 12 and c["event_type"] == "abnormal_crowd"
    assert c["source"] == "curiosity" and c["cheap_evidence"]["source"] == "curiosity"
