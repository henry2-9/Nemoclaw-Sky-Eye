import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import falcon_client

def test_detect_parses_counts(monkeypatch):
    class FakeResp:
        def read(self): return json.dumps({"task":"detection","counts":{"person":2},"annotated_path":"/x.jpg"}).encode()
        def __enter__(self): return self
        def __exit__(self,*a): return False
    monkeypatch.setattr(falcon_client.urllib.request, "urlopen", lambda *a, **k: FakeResp())
    out = falcon_client.detect("/tmp/x.jpg", "person", server_url="http://fake")
    assert out["counts"]["person"] == 2

def test_detect_returns_none_on_error(monkeypatch):
    def boom(*a, **k): raise OSError("down")
    monkeypatch.setattr(falcon_client.urllib.request, "urlopen", boom)
    assert falcon_client.detect("/tmp/x.jpg", "person", server_url="http://fake") is None
