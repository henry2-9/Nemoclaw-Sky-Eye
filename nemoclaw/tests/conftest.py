import pytest


@pytest.fixture(autouse=True)
def isolate_runtime_outputs(monkeypatch, tmp_path):
    """A sourced production env must not let unit tests pollute live dashboard data."""
    monkeypatch.setenv("NEMOCLAW_FLIGHT_RECORDER_PATH", str(tmp_path / "flight_recorder.jsonl"))
    monkeypatch.setenv("NEMOCLAW_AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("NEMOCLAW_MEDIA_DIR", str(tmp_path / "media_events"))
    monkeypatch.setenv("NEMOCLAW_WALL_SNAPSHOT_DIR", str(tmp_path / "wall_snapshots"))
    monkeypatch.setenv("NEMOCLAW_SQLITE_PATH", str(tmp_path / "sentinel.db"))
    monkeypatch.setenv("NEMOCLAW_THOUGHTS_PATH", str(tmp_path / "thoughts.jsonl"))
    monkeypatch.setenv("NEMOCLAW_BASELINE_PATH", str(tmp_path / "baseline.json"))
    monkeypatch.setenv("NEMOCLAW_FEED_HEALTH_PATH", str(tmp_path / "feed_health.json"))
    monkeypatch.setenv("NEMOCLAW_CORRELATION_PATH", str(tmp_path / "correlation_alerts.jsonl"))
    monkeypatch.setenv("NEMOCLAW_FOLLOWUPS_PATH", str(tmp_path / "followups.jsonl"))
