#!/usr/bin/env python3
"""每 channel 的「來源是否還活著」追蹤。sweep 抓幀成功/失敗 → mark();
狀態翻轉時(線上→離線、離線→線上)回傳 transition,呼叫端記思考。

讓「天眼」自主管理外部直播來源:某個 YouTube live 下線了 agent 自己標離線,
活回來自己重新上線——把外部不穩變成自主性的證據。"""
import datetime
import json
import os


def _path():
    return os.environ.get(
        "NEMOCLAW_FEED_HEALTH_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "feed_health.json"),
    )


def _load():
    p = _path()
    if not os.path.exists(p):
        return {}
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}


def _save(state):
    p = _path()
    try:
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(p + ".tmp", p)
    except Exception:
        pass


def mark(channel_id, name, ok, reason=None, now=None):
    """更新狀態。回傳 transition: 'online'(剛上線)、'offline'(剛離線)、None(無變動)。"""
    state = _load()
    k = str(channel_id)
    prev = state.get(k, {})
    prev_ok = prev.get("ok")
    transition = None
    if prev_ok is True and not ok:
        transition = "offline"
    elif prev_ok is False and ok:
        transition = "online"
    elif prev_ok is None and not ok:
        transition = "offline"   # 首次就失敗也算離線
    ts = (now or datetime.datetime.now()).isoformat(timespec="seconds") if not isinstance(now, str) else now
    state[k] = {"ok": bool(ok), "name": name, "last": ts,
                "reason": reason, "id": int(channel_id) if str(channel_id).isdigit() else channel_id}
    _save(state)
    return transition


def state():
    return _load()
