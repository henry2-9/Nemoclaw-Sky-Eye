import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import notify

def test_send_text_posts_to_telegram(monkeypatch):
    captured = {}
    def fake_post(url, data=None, files=None, timeout=None):
        captured["url"] = url; captured["data"] = data
        class R:
            status_code = 200
            def raise_for_status(self): pass
        return R()
    monkeypatch.setattr(notify.requests, "post", fake_post)
    notify.send_text("TOKEN", "123", "火災警報")
    assert "botTOKEN/sendMessage" in captured["url"]
    assert captured["data"]["chat_id"] == "123"
    assert captured["data"]["text"] == "火災警報"
