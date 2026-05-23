#!/usr/bin/env python3
"""便宜感知 sweep:掃所有 channel 當前幀,產生候選或 [SILENT]。"""
import os, json, time, tempfile
import feed, falcon_client

# event_type → (Falcon query, 觸發關鍵類別, 門檻)
RULES = {
    "fire_smoke":      ("fire, smoke",        ["fire", "smoke"],  1),
    "intrusion":       ("person",             ["person"],         1),
    "abnormal_crowd":  ("person",             ["person"],         3),
    "abnormal_weather":("flood, smoke, fire, fallen tree", ["flood","fallen tree","smoke","fire"], 1),
}

def _hit(counts, keys, threshold):
    return sum(int(counts.get(k, 0)) for k in keys) >= threshold

def sweep_channels(channels):
    cands = []
    for c in channels:
        query, keys, thr = RULES.get(c["event_type"], ("person", ["person"], 1))
        frame = feed.grab_frame(c["path"], os.path.join(tempfile.gettempdir(), f"sweep_{c['id']}.jpg"))
        if not frame:
            continue
        res = falcon_client.detect(frame, query)
        if not res:
            continue
        counts = res.get("counts", {}) or {}
        if _hit(counts, keys, thr):
            cands.append({
                "channel": c["id"], "channel_name": c.get("name", ""),
                "event_type": c["event_type"], "frame_path": frame,
                "cheap_evidence": {"counts": counts}, "ts": time.time(),
            })
    return cands

def format_output(cands):
    if not cands:
        return "[SILENT]"
    return json.dumps(cands, ensure_ascii=False, indent=2)
