import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dashboard import app as dashboard


def test_attack_demo_incident_can_be_featured_on_home_page():
    row = {"channel": "19", "severity": "critical", "trigger_origin": "demo_manual",
           "injection_detected": True, "escalated": True,
           "media_artifacts": {"urls": {"clip": "/media/demo/redacted_clip.mp4",
                                        "frame": "/media/demo/frame_redacted.jpg"}}}
    assert dashboard._latest_media_row([row]) is row
    rendered = dashboard._render_attack_scene([row])
    assert "攻擊演練" in rendered
    assert "已阻擋" in rendered
    assert "查看證據鏈" in rendered
    assert "poster='/media/demo/frame_redacted.jpg'" in rendered
    assert "autoplay" not in rendered


def test_command_center_separates_live_state_from_latest_test_result(monkeypatch):
    monkeypatch.setattr(dashboard, "_uptime_str", lambda: "1h 2m")
    rows = [
        {"severity": "high", "trigger_origin": "demo_manual",
         "ts_iso": "2026-05-26T17:26:22",
         "media_artifacts": {"urls": {"frame": "/media/demo/frame_redacted.jpg"}}},
    ]

    rendered = dashboard._render_command_center(
        rows, health={"nemotron": "up", "falcon": "up", "nemoclaw": "up"})

    assert "LIVE 狀態" in rendered
    assert "無現行警報" in rendered
    assert "累計確認 0 起" in rendered
    assert "TEST 最近結果" in rendered
    assert ">高</strong>" in rendered
    assert "2026-05-26 17:26" in rendered


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


def test_followup_inherits_test_origin_from_linked_audit_event(monkeypatch):
    monkeypatch.setattr(
        dashboard._followup,
        "latest",
        lambda n: [{"trace_id": "t-test", "channel": "19", "event_type": "fire_smoke",
                    "severity": "high", "ts_iso": "2026-05-26T17:26:22",
                    "commands": [], "conclusion": "綜合判斷: 真實 · 測試事件"}],
    )

    rendered = dashboard._render_followups(
        [{"trace_id": "t-test", "trigger_origin": "demo_manual"}])

    assert "TEST 受控演練" in rendered
    assert "查看證據鏈" in rendered
    assert "2026-05-26 17:26:22" in rendered
    assert "不代表目前告警狀態" not in rendered


def test_followup_without_audit_origin_is_collapsed_as_non_live(monkeypatch):
    monkeypatch.setattr(
        dashboard._followup,
        "latest",
        lambda n: [{"trace_id": "fusion-001", "channel": "201",
                    "event_type": "fire_smoke", "severity": "critical",
                    "commands": [], "conclusion": "綜合判斷: 真實"}],
    )

    rendered = dashboard._render_followups([])

    assert "無已標示來源的二次調查事件" in rendered
    assert "未連結事件紀錄 1 筆" in rendered
    assert "不代表 LIVE 現況" in rendered
    assert "不代表目前告警狀態" in rendered
