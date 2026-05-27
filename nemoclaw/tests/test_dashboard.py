import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dashboard import app as dashboard


def test_attack_demo_incident_can_be_featured_on_home_page():
    row = {"channel": "19", "severity": "critical", "trigger_origin": "demo_manual",
           "injection_detected": True, "escalated": True,
           "media_artifacts": {"urls": {"clip": "/media/demo/redacted_clip.mp4"}}}
    assert dashboard._latest_media_row([row]) is row
    rendered = dashboard._render_attack_scene([row])
    assert "攻擊演練" in rendered
    assert "已阻擋" in rendered
    assert "查看證據鏈" in rendered


def test_source_grid_uses_supervisor_active_configuration(monkeypatch, tmp_path):
    marker = tmp_path / "active_channels_file"
    config = tmp_path / "world_channels.yaml"
    config.write_text("channels: []\n", encoding="utf-8")
    marker.write_text(str(config), encoding="utf-8")
    monkeypatch.setattr(dashboard, "_NEMODIR", str(tmp_path))
    monkeypatch.setattr(
        dashboard._register_channels,
        "load_channels",
        lambda path, merge_discovered=True: [{"id": 101, "name": "Road source"}],
    )
    monkeypatch.setattr(
        dashboard._feed_health,
        "state",
        lambda: {"101": {"ok": True, "name": "Road source", "last": "2026-05-26T12:00:00"},
                 "201": {"ok": True, "name": "Stale landmark", "last": "2026-05-26T11:00:00"}},
    )

    rendered = dashboard._render_sky_eye_grid()

    assert "國道即時來源" in rendered
    assert "ch101" in rendered
    assert "ch201" not in rendered


def test_landmark_wall_renders_redacted_previews_and_selected_focus(monkeypatch, tmp_path):
    marker = tmp_path / "active_channels_file"
    config = tmp_path / "landmarks.yaml"
    config.write_text("channels: []\n", encoding="utf-8")
    marker.write_text(str(config), encoding="utf-8")
    monkeypatch.setattr(dashboard, "_NEMODIR", str(tmp_path))
    monkeypatch.setattr(
        dashboard._register_channels,
        "load_channels",
        lambda path, merge_discovered=True: [
            {"id": 201, "name": "New York"},
            {"id": 202, "name": "Sydney"},
        ],
    )
    monkeypatch.setattr(
        dashboard._feed_health,
        "state",
        lambda: {
            "201": {"ok": True, "name": "New York", "last": "2026-05-26T12:00:00"},
            "202": {"ok": True, "name": "Sydney", "last": "2026-05-26T12:01:00"},
        },
    )
    monkeypatch.setattr(
        dashboard.wall_snapshots,
        "preview",
        lambda channel: {"url": f"/wall/ch{channel}.jpg", "captured_at": "2026-05-26T12:00:00"},
    )

    rendered = dashboard._render_sky_eye_grid("202")

    assert "地標天眼牆" in rendered
    assert "/wall/ch201.jpg" in rendered
    assert "/wall/ch202.jpg" in rendered
    assert "Sydney" in rendered
    assert "監看 2" in rendered
    assert "正常 2" in rendered


def test_thought_stream_excludes_records_before_current_supervisor_start(monkeypatch):
    monkeypatch.setattr(
        dashboard._thoughts,
        "latest",
        lambda n: [
            {"ts": "2026-05-26T15:34:10", "source": "decision", "text": "test artifact"},
            {"ts": "2026-05-26T16:02:32", "source": "decision", "text": "live incident"},
        ],
    )
    monkeypatch.setattr(
        dashboard,
        "_supervisor_started_at",
        lambda: dashboard.datetime.datetime.fromisoformat("2026-05-26T15:59:53+08:00"),
    )

    rendered = dashboard._render_thoughts()

    assert "live incident" in rendered
    assert "test artifact" not in rendered
