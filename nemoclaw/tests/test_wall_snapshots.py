import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import wall_snapshots


def test_publish_exposes_only_redacted_wall_image(monkeypatch, tmp_path):
    raw = tmp_path / "raw.jpg"
    raw.write_bytes(b"raw")

    def fake_redact(source, out_path=None):
        assert source == str(raw)
        with open(out_path, "wb") as f:
            f.write(b"redacted")
        return out_path

    monkeypatch.setattr(wall_snapshots.redact, "redact_pii", fake_redact)
    published = wall_snapshots.publish(201, "Landmark", str(raw), captured_at="2026-05-26T16:00:00")

    assert published["privacy_processed"] is True
    assert wall_snapshots.preview(201)["url"] == "/wall/ch201.jpg"
    assert wall_snapshots.resolve_public("ch201.jpg").read_bytes() == b"redacted"


def test_public_snapshot_path_rejects_traversal(tmp_path):
    assert wall_snapshots.resolve_public("../ch201.jpg") is None
