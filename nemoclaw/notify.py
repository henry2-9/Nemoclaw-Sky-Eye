#!/usr/bin/env python3
"""Telegram 通知(text + photo)。"""
import os, requests

API = "https://api.telegram.org"

def send_text(token, chat_id, text, timeout=30):
    r = requests.post(f"{API}/bot{token}/sendMessage",
                      data={"chat_id": chat_id, "text": text}, timeout=timeout)
    r.raise_for_status(); return r

def send_photo(token, chat_id, photo_path, caption="", timeout=60):
    with open(photo_path, "rb") as f:
        r = requests.post(f"{API}/bot{token}/sendPhoto",
                          data={"chat_id": chat_id, "caption": caption},
                          files={"photo": f}, timeout=timeout)
    r.raise_for_status(); return r

def notify_from_env(text, photo_path=None):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        raise RuntimeError("Telegram credentials are not configured")
    if photo_path and os.path.exists(photo_path):
        return send_photo(token, chat, photo_path, caption=text)
    return send_text(token, chat, text)
