#!/usr/bin/env python3
"""便宜感知 sweep:掃所有 channel 當前幀,產生候選或 [SILENT]。"""
import os, json, time, tempfile
import feed, falcon_client
import baseline as _baseline
import thoughts as _thoughts
import feed_health as _feed_health
import wall_snapshots as _wall_snapshots

# event_type → (Falcon query, 觸發關鍵類別, 門檻)
RULES = {
    "fire_smoke":      ("fire, smoke",        ["fire", "smoke"],  1),
    "intrusion":       ("person",             ["person"],         1),
    "abnormal_crowd":  ("person",             ["person"],         3),
    "abnormal_weather":("flood, smoke, fire, fallen tree", ["flood","fallen tree","smoke","fire"], 1),
    "security_anomaly":("fire, smoke, bag, suitcase, person", ["fire","smoke","bag","suitcase","person"], 1),
    # 世界交通鏡頭以跨輪基線濾掉正常車流,不再把「看到任何車」當事故。
    "traffic":         ("fire, smoke, person, car, truck, motorcycle",
                        ["fire","smoke","person","car","truck","motorcycle"], 1),
}

def _hit(counts, keys, threshold):
    return sum(int(counts.get(k, 0)) for k in keys) >= threshold


def _traffic_anomaly(channel, counts):
    """交通鏡頭的保守 cheap gate：火煙立即升級；人/車量僅在偏離基線時升級。"""
    if int(counts.get("fire", 0)) + int(counts.get("smoke", 0)) >= 1:
        return True, "fire/smoke"
    people = int(counts.get("person", 0))
    people_anom, _ = _baseline.update_and_check(channel, "road_person", people, floor=3)
    vehicles = sum(int(counts.get(k, 0)) for k in ("car", "truck", "motorcycle"))
    traffic_anom, _ = _baseline.update_and_check(channel, "vehicles", vehicles, floor=6)
    return (people_anom or traffic_anom), ("person spike" if people_anom else "vehicle density spike")


def _security_anomaly(channel, counts):
    if sum(int(counts.get(k, 0)) for k in ("fire", "smoke", "bag", "suitcase")) >= 1:
        return True, "hazard/object"
    people = int(counts.get("person", 0))
    crowd_anom, _ = _baseline.update_and_check(channel, "person", people)
    return crowd_anom, "crowd spike"


def _is_stream(path):
    return str(path or "").lower().startswith(("rtsp://", "http://", "https://"))


def _candidate_clip(channel):
    if os.environ.get("NEMOCLAW_LIVE_EVIDENCE_CLIP", "1") != "1" or not _is_stream(channel.get("path")):
        return None
    out = os.path.join(tempfile.gettempdir(), f"nemoclaw_candidate_{channel['id']}.mp4")
    return feed.capture_stream_clip(
        channel["path"], out,
        duration=float(os.environ.get("NEMOCLAW_LIVE_EVIDENCE_SECONDS", "4")),
    )


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
            t = _feed_health.mark(c["id"], c.get("name", ""), ok=False, reason="grab_frame failed")
            if t == "offline":
                _thoughts.record(
                    f"ch{c['id']}({c.get('name','')}) 來源無法取幀,我把它標離線(會自主重試)",
                    source="watchdog")
            continue
        # 展示牆只公開最新遮罩快照；原始巡檢幀仍留在本機暫存供偵測使用。
        _wall_snapshots.publish(c["id"], c.get("name", ""), frame)
        # 取幀成功:更新健康;轉回上線記思考
        t_up = _feed_health.mark(c["id"], c.get("name", ""), ok=True)
        if t_up == "online":
            _thoughts.record(
                f"ch{c['id']}({c.get('name','')}) 來源恢復連線——我重新納入巡檢",
                source="watchdog")
        res = falcon_client.detect(frame, query)
        if not res:
            continue
        counts = res.get("counts", {}) or {}
        gate_reason = ""
        # abnormal_crowd:agent 自學每相機人數基線,偏離歷史才升級(不再靜態 ≥3)
        if c["event_type"] == "abnormal_crowd":
            person = int(counts.get("person", 0))
            is_anom, bmax = _baseline.update_and_check(c["id"], "person", person)
            fired = is_anom
            gate_reason = "crowd baseline spike"
            if fired:
                _thoughts.record(
                    f"ch{c['id']}({c.get('name','')}) 人數 {person} 偏離我學到的基線(歷史上限 {bmax})→ 升級為候選",
                    source="baseline")
        elif c["event_type"] == "traffic":
            fired, gate_reason = _traffic_anomaly(c["id"], counts)
        elif c["event_type"] == "security_anomaly":
            fired, gate_reason = _security_anomaly(c["id"], counts)
        else:
            fired = _hit(counts, keys, thr)
        if fired and c["event_type"] != "abnormal_crowd":
            hit = {k: counts[k] for k in keys if counts.get(k)}
            detail = f" ({gate_reason})" if gate_reason else ""
            _thoughts.record(
                f"ch{c['id']}({c.get('name','')}) 看到 {hit} → {c['event_type']} 候選{detail}",
                source="sweep")
        if fired:
            candidate_clip = _candidate_clip(c)
            cands.append({
                "channel": c["id"], "channel_name": c.get("name", ""),
                "event_type": c["event_type"], "frame_path": frame,
                "video_path": c["path"], "playhead_sec": playhead,
                "falcon_query": query,
                "candidate_clip_path": candidate_clip,
                "cheap_evidence": {"counts": counts, "gate_reason": gate_reason}, "ts": time.time(),
            })
    return cands

def format_output(cands):
    if not cands:
        return "[SILENT]"
    return json.dumps(cands, ensure_ascii=False, indent=2)
