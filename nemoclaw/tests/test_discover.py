import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import discover


def _scored_results():
    # 模擬 yt_search 的結果(每個 query 都回兩筆)
    def search_fn(query, n=8):
        return [
            {"id": f"vid_{query[:5]}_1", "title": f"Famous {query} ABC", "url": f"https://yt/?v={hash(query)%9999}_1"},
            {"id": f"vid_{query[:5]}_2", "title": f"Boring video {query}", "url": f"https://yt/?v={hash(query)%9999}_2"},
        ]

    def validate_fn(url):
        return ("/tmp/fake.jpg", "https://hls/fake")   # 都通過

    def score_fn(frame, title, vlm_fn=None):
        # title 含 "Famous" 視為地標,其他不是
        if "Famous" in title:
            return True, 0.85, title[:30]
        return False, 0.1, title

    return search_fn, validate_fn, score_fn


def test_discover_filters_and_registers(tmp_path, monkeypatch):
    # 隔離寫入路徑與 sqlite(指到空的 tmp 後端)
    monkeypatch.setattr(discover, "DISCOVERED_PATH", str(tmp_path / "discovered.yaml"))
    monkeypatch.setattr(discover, "DISCOVERED_TRAFFIC_PATH", str(tmp_path / "discovered_traffic.yaml"))
    monkeypatch.setattr(discover, "LANDMARKS_PATH", str(tmp_path / "landmarks.yaml"))
    monkeypatch.setattr(discover, "WORLD_CHANNELS_PATH", str(tmp_path / "world_channels.yaml"))
    monkeypatch.setenv("NEMOCLAW_SQLITE_PATH", str(tmp_path / "ch.db"))
    monkeypatch.setenv("NEMOCLAW_DB_BACKEND", "sqlite")
    monkeypatch.setenv("NEMOCLAW_THOUGHTS_PATH", str(tmp_path / "th.jsonl"))
    s, v, sc = _scored_results()
    added = discover.discover(max_new=3, vlm_fn=lambda *a, **k: "", search_fn=s, validate_fn=v, score_fn=sc)
    # 4 queries × 1 "Famous" each = 4 候選但 URL 互不同;max_new=3 → 加 3 個
    assert len(added) == 3
    assert all(a["id"] >= discover.START_ID for a in added)
    # 寫入 discovered.yaml
    import yaml
    doc = yaml.safe_load(open(tmp_path / "discovered.yaml"))
    assert len(doc["channels"]) == 3
    # sqlite 也有
    import db_factory
    assert len(db_factory.channel_db().get_all_channels()) >= 3


def test_discover_dedups_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(discover, "DISCOVERED_PATH", str(tmp_path / "discovered.yaml"))
    monkeypatch.setattr(discover, "DISCOVERED_TRAFFIC_PATH", str(tmp_path / "discovered_traffic.yaml"))
    monkeypatch.setattr(discover, "LANDMARKS_PATH", str(tmp_path / "landmarks.yaml"))
    monkeypatch.setattr(discover, "WORLD_CHANNELS_PATH", str(tmp_path / "world_channels.yaml"))
    monkeypatch.setenv("NEMOCLAW_SQLITE_PATH", str(tmp_path / "ch.db"))
    monkeypatch.setenv("NEMOCLAW_DB_BACKEND", "sqlite")
    monkeypatch.setenv("NEMOCLAW_THOUGHTS_PATH", str(tmp_path / "th.jsonl"))
    # 預植 landmarks.yaml 已知一個 URL
    import yaml
    yaml.safe_dump({"channels": [{"id": 201, "name": "X", "url": "https://yt/known", "event_type": "abnormal_crowd"}]},
                   open(tmp_path / "landmarks.yaml", "w"), allow_unicode=True)
    def search_fn(q, n=8):
        return [{"id": "k", "title": "Famous KNOWN", "url": "https://yt/known"}]   # 全已知
    def validate_fn(u): return ("/tmp/fake.jpg", "https://hls/x")
    def score_fn(f, t, vlm_fn=None): return True, 0.9, t
    added = discover.discover(max_new=3, vlm_fn=lambda *a, **k: "",
                              search_fn=search_fn, validate_fn=validate_fn, score_fn=score_fn)
    assert added == []


def test_discover_traffic_profile_registers_traffic_channels(tmp_path, monkeypatch):
    monkeypatch.setattr(discover, "DISCOVERED_PATH", str(tmp_path / "discovered.yaml"))
    monkeypatch.setattr(discover, "DISCOVERED_TRAFFIC_PATH", str(tmp_path / "discovered_traffic.yaml"))
    monkeypatch.setattr(discover, "LANDMARKS_PATH", str(tmp_path / "landmarks.yaml"))
    monkeypatch.setattr(discover, "WORLD_CHANNELS_PATH", str(tmp_path / "world_channels.yaml"))
    monkeypatch.setenv("NEMOCLAW_SQLITE_PATH", str(tmp_path / "ch.db"))
    monkeypatch.setenv("NEMOCLAW_DB_BACKEND", "sqlite")
    monkeypatch.setenv("NEMOCLAW_THOUGHTS_PATH", str(tmp_path / "th.jsonl"))

    def search_fn(query, n=8):
        return [{"id": f"road-{query[:4]}", "title": f"Intersection {query}",
                 "url": f"https://yt/road-{abs(hash(query)) % 9999}"}]

    def validate_fn(url):
        return ("/tmp/traffic.jpg", "https://hls/traffic")

    def score_fn(frame, title, vlm_fn=None):
        return True, 0.88, f"{title[:18]} 路口"

    added = discover.discover(max_new=2, search_fn=search_fn, validate_fn=validate_fn,
                              score_fn=score_fn, profile="traffic")

    assert len(added) == 2
    assert all(a["id"] >= discover.TRAFFIC_START_ID for a in added)
    assert all(a["event_type"] == "traffic" for a in added)
    assert all("交通探索" in a["name"] for a in added)
    import yaml
    doc = yaml.safe_load(open(tmp_path / "discovered_traffic.yaml", encoding="utf-8"))
    assert [c["event_type"] for c in doc["channels"]] == ["traffic", "traffic"]


def test_score_landmark_parses_json():
    fake_vlm = lambda img, prompt: '{"is_landmark": true, "name": "巴黎鐵塔", "confidence": 0.92}'
    is_lm, conf, name = discover.score_landmark("/tmp/x.jpg", "Eiffel Tower live", vlm_fn=fake_vlm)
    assert is_lm is True and conf == 0.92 and name == "巴黎鐵塔"


def test_score_landmark_rejects_bad_json():
    fake_vlm = lambda img, prompt: "this is not json"
    is_lm, conf, name = discover.score_landmark("/tmp/x.jpg", "random video", vlm_fn=fake_vlm)
    assert is_lm is False and conf == 0.0


def test_score_traffic_camera_parses_json_and_prompt_mentions_intersections():
    prompts = []

    def fake_vlm(img, prompt):
        prompts.append(prompt)
        return '{"is_traffic_camera": true, "name": "Shibuya Crossing", "confidence": 0.91}'

    ok, conf, name = discover.score_traffic_camera("/tmp/x.jpg", "Shibuya live", vlm_fn=fake_vlm)

    assert ok is True and conf == 0.91 and name == "Shibuya Crossing"
    assert "路口" in prompts[0]
    assert "traffic light" in prompts[0]
