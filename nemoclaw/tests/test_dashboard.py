import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dashboard import app as dashboard


def test_command_center_shows_live_state_only(monkeypatch):
    monkeypatch.setattr(dashboard, "_uptime_str", lambda: "1h 2m")
    rendered = dashboard._render_command_center(
        [], health={"nemotron": "up", "falcon": "up", "nemoclaw": "up"})
    assert "LIVE 狀態" in rendered
    assert "無現行警報" in rendered
    assert "累計確認 0 起" in rendered
    assert "TEST" not in rendered
    assert "攻擊" not in rendered


def test_health_dots_identify_down_and_unknown_services():
    rendered = dashboard._health_dots({"nemotron": "up", "falcon": "down"})

    assert "Falcon 異常" in rendered
    assert "dot off" in rendered
    assert "NemoClaw 未知" in rendered
    assert "dot unknown" in rendered


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

    assert "世界路口交通來源" in rendered
    assert "Road source" in rendered
    assert "Stale landmark" not in rendered


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

    assert "全球地標天眼" in rendered
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


def test_followup_links_trace_when_audit_row_present(monkeypatch):
    monkeypatch.setattr(
        dashboard._followup,
        "latest",
        lambda n: [{"trace_id": "t-001", "channel": "201", "channel_name": "Times Square",
                    "event_type": "fire_smoke", "severity": "high",
                    "ts_iso": "2026-05-26T17:26:22",
                    "commands": [], "conclusion": "綜合判斷: 真實 · 火災事件"}],
    )

    rendered = dashboard._render_followups([{"trace_id": "t-001"}])

    assert "Times Square" in rendered
    assert "查看證據鏈" in rendered
    assert "2026-05-26 17:26:22" in rendered


def test_followup_renders_without_audit_link(monkeypatch):
    monkeypatch.setattr(
        dashboard._followup,
        "latest",
        lambda n: [{"trace_id": "fusion-001", "channel": "201",
                    "event_type": "fire_smoke", "severity": "critical",
                    "commands": [], "conclusion": "綜合判斷: 真實"}],
    )

    rendered = dashboard._render_followups([])

    assert "fire_smoke" in rendered
    assert "綜合判斷" in rendered
    assert "查看證據鏈" not in rendered
