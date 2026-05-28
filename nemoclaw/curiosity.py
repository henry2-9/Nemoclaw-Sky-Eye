#!/usr/bin/env python3
"""自我初始任務(curiosity):agent 不只反應 sweep 的候選——它也會主動關心
「太久沒巡的鏡頭」。每輪選一個最久未被處理的 channel,加進候選池,讓
investigate 自己決定要不要當事件。讓 agent 看起來會「找事做」。"""
import json
import os
import time


def _last_seen(audit_path, channels):
    """從 audit 讀每個 channel 最後一次處理時間(ALLOW 或任何決策皆算)。"""
    seen = {str(c.get("id")): 0.0 for c in channels}
    if audit_path and os.path.exists(audit_path):
        try:
            with open(audit_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    ch = str(r.get("channel"))
                    if ch in seen:
                        seen[ch] = max(seen[ch], float(r.get("ts", 0)))
        except Exception:
            pass
    return seen


def stale_pick(channels, audit_path=None, min_idle_minutes=15, now=None):
    """回傳「最久沒巡」且超過 min_idle_minutes 的 channel 物件;沒有合條件則 None。
    僅針對 file 來源(本地有檔可重看);stream(live)channel 略過(它們本來就持續變)。"""
    now = now if now is not None else time.time()
    local = [c for c in channels if c.get("path") and not str(c.get("path")).startswith(("http", "rtsp"))]
    if not local:
        return None
    seen = _last_seen(audit_path, local)
    idle = [(c, now - seen.get(str(c["id"]), 0)) for c in local]
    idle.sort(key=lambda x: -x[1])
    top, gap = idle[0]
    if gap < min_idle_minutes * 60:
        return None
    return top, int(gap // 60)


def curiosity_candidate(channel, *, now=None):
    """把一個 stale channel 包成 sweep 風格的候選(無 LocateAnything 證據,
    investigate 仍會用 Nemotron 親自確認;source=curiosity 供軌跡識別)。"""
    return {
        "channel": channel["id"], "channel_name": channel.get("name", ""),
        "event_type": channel.get("event_type") or "abnormal_crowd",
        "frame_path": None, "video_path": channel.get("path"),
        "playhead_sec": 0.0, "falcon_query": "(curiosity)",
        "cheap_evidence": {"counts": {}, "source": "curiosity"},
        "ts": now if now is not None else time.time(),
        "source": "curiosity",
    }
