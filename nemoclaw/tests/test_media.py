import os, sys, tempfile
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import media


def _jpg(path, value=80):
    img = np.full((64, 96, 3), value, dtype=np.uint8)
    cv2.imwrite(path, img)
    return path


def test_prepare_event_media_copies_frame_and_falcon_overlay(monkeypatch):
    root = tempfile.mkdtemp()
    monkeypatch.setenv("NEMOCLAW_MEDIA_DIR", root)
    monkeypatch.setenv("NEMOCLAW_DASHBOARD_URL", "http://dash")
    src = _jpg(os.path.join(tempfile.mkdtemp(), "frame.jpg"), 80)
    ann = _jpg(os.path.join(tempfile.mkdtemp(), "ann.jpg"), 160)

    def fake_detect(image_path, query, task="segmentation"):
        return {"ok": True, "annotated_path": ann, "counts": {"smoke": 1}, "task": task}

    monkeypatch.setattr(media.falcon_client, "detect", fake_detect)
    out = media.prepare_event_media({
        "trace_id": "trace-1",
        "event_type": "fire_smoke",
        "media_refs": [src],
        "falcon_query": "fire, smoke",
    })
    assert os.path.exists(out["frame_path"])
    assert os.path.exists(out["falcon_annotated_path"])
    assert out["falcon_counts"] == {"smoke": 1}
    assert out["urls"]["falcon_annotated"].startswith("http://dash/media/trace-1/")


def test_trace_url_uses_safe_trace_id(monkeypatch):
    monkeypatch.setenv("NEMOCLAW_DASHBOARD_URL", "http://dash")
    assert media.trace_url("a/b c", absolute=True) == "http://dash/trace?trace_id=a_b_c"


def test_live_media_prefers_candidate_onset_clip(monkeypatch, tmp_path):
    monkeypatch.setenv("NEMOCLAW_MEDIA_DIR", str(tmp_path / "media"))
    candidate = tmp_path / "candidate.mp4"
    candidate.write_bytes(b"candidate-onset-clip")
    src = _jpg(str(tmp_path / "fallback.jpg"))

    def fake_extract(video_path, out_path, second=None):
        return _jpg(out_path)

    monkeypatch.setattr(media, "extract_frame", fake_extract)
    monkeypatch.setattr(media, "create_clip",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("fallback used")))
    monkeypatch.setattr(media, "annotate_frame",
                        lambda path, out_path, **kwargs: {"ok": True, "annotated_path": _jpg(out_path)})
    monkeypatch.setattr(media.redact, "redact_pii", lambda path, out_path=None: media._copy(path, out_path))
    monkeypatch.setattr(media.redact, "redact_video", lambda path, out_path=None: media._copy(path, out_path))

    out = media.prepare_event_media({
        "trace_id": "live-onset",
        "source_video_path": "https://camera.example/live.m3u8",
        "candidate_clip_path": str(candidate),
        "event_type": "traffic",
        "media_refs": [src],
    })
    assert out["evidence_mode"] == "trigger_onset_clip"
    assert out["clip_status"] == "ok"
    assert os.path.exists(out["clip_path"])
