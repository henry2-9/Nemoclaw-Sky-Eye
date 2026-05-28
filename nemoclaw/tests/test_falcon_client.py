import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import falcon_client


class _Resp:
    def __init__(self, body):
        self._body = body if isinstance(body, bytes) else body.encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_locate_detect_parses_counts(monkeypatch):
    """LocateAnything 後端 /infer 同 Falcon contract — 直接回 counts dict。"""
    monkeypatch.setattr(falcon_client, "PERCEPTION_BACKEND", "locate")
    body = json.dumps({"counts": {"person": 2, "car": 3}, "backend": "locate-anything-3b"})
    monkeypatch.setattr(falcon_client.urllib.request, "urlopen", lambda *a, **k: _Resp(body))
    out = falcon_client.detect("/tmp/x.jpg", "person, car", server_url="http://fake")
    assert out["counts"] == {"person": 2, "car": 3}
    assert out["backend"] == "locate-anything-3b"


def test_locate_detect_returns_none_on_error(monkeypatch):
    monkeypatch.setattr(falcon_client, "PERCEPTION_BACKEND", "locate")
    monkeypatch.setattr(falcon_client.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert falcon_client.detect("/tmp/x.jpg", "person", server_url="http://fake") is None


def test_falcon_fallback_parses_counts(monkeypatch):
    """NEMOCLAW_PERCEPTION=falcon 走 OWL-ViT 後端,維持原 JSON contract。"""
    monkeypatch.setattr(falcon_client, "PERCEPTION_BACKEND", "falcon")
    body = json.dumps({"task": "detection", "counts": {"person": 2}, "annotated_path": "/x.jpg"})
    monkeypatch.setattr(falcon_client.urllib.request, "urlopen", lambda *a, **k: _Resp(body))
    out = falcon_client.detect("/tmp/x.jpg", "person", server_url="http://fake")
    assert out["counts"]["person"] == 2


def test_falcon_fallback_returns_none_on_error(monkeypatch):
    monkeypatch.setattr(falcon_client, "PERCEPTION_BACKEND", "falcon")
    monkeypatch.setattr(falcon_client.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert falcon_client.detect("/tmp/x.jpg", "person", server_url="http://fake") is None
