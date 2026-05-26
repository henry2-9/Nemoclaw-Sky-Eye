#!/usr/bin/env python3
"""便宜感知 sweep:掃所有 channel 當前幀,產生候選或 [SILENT]。"""
import os, json, time, tempfile
import feed, falcon_client
import baseline as _baseline
import thoughts as _thoughts

# event_type → (Falcon query, 觸發關鍵類別, 門檻)
RULES = {
    "fire_smoke":      ("fire, smoke",        ["fire", "smoke"],  1),
    "intrusion":       ("person",             ["person"],         1),
    "abnormal_crowd":  ("person",             ["person"],         3),
    "abnormal_weather":("flood, smoke, fire, fallen tree", ["flood","fallen tree","smoke","fire"], 1),
    # 世界公開交通攝影機(國道 CCTV 等):偵測車輛/人,有就當候選
    "traffic":         ("car, person, truck, motorcycle", ["car","person","truck","motorcycle"], 1),
}

def _hit(counts, keys, threshold):
    return sum(int(counts.get(k, 0)) for k in keys) >= threshold

def sweep_channels(channels):
    cands = []
    for c in channels:
        query, keys, thr = RULES.get(c["event_type"], ("person", ["person"], 1))
        duration = feed.video_duration(c["path"])
        playhead = feed.playhead(duration)
        frame = feed.grab_frame(
            c["path"], os.path.join(tempfile.gettempdir(), f"sweep_{c['id']}.jpg"),
            second=playhead,
        )
        if not frame:
            continue
        res = falcon_client.detect(frame, query)
        if not res:
            continue
        counts = res.get("counts", {}) or {}
        # abnormal_crowd:agent 自學每相機人數基線,偏離歷史才升級(不再靜態 ≥3)
        if c["event_type"] == "abnormal_crowd":
            person = int(counts.get("person", 0))
            is_anom, bmax = _baseline.update_and_check(c["id"], "person", person)
            fired = is_anom
            if fired:
                _thoughts.record(
                    f"ch{c['id']}({c.get('name','')}) 人數 {person} 偏離我學到的基線(歷史上限 {bmax})→ 升級為候選",
                    source="baseline")
        else:
            fired = _hit(counts, keys, thr)
            if fired:
                hit = {k: counts[k] for k in keys if counts.get(k)}
                _thoughts.record(
                    f"ch{c['id']}({c.get('name','')}) 看到 {hit} → {c['event_type']} 候選",
                    source="sweep")
        if fired:
            cands.append({
                "channel": c["id"], "channel_name": c.get("name", ""),
                "event_type": c["event_type"], "frame_path": frame,
                "video_path": c["path"], "playhead_sec": playhead,
                "falcon_query": query,
                "cheap_evidence": {"counts": counts}, "ts": time.time(),
            })
    return cands

def format_output(cands):
    if not cands:
        return "[SILENT]"
    return json.dumps(cands, ensure_ascii=False, indent=2)
