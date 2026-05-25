#!/usr/bin/env python3
"""sentinel-event-query 的 SQLite 後端實作(NEMOCLAW_DB_BACKEND=sqlite)。

不依賴 bson / FPG mongo `database` 模組,純讀 sqlite_store 的 EventStore /
ChannelStore。支援與 mongo 版相同的基本指令:summary / latest / event /
media / cameras。輸出 JSON 形狀盡量對齊 mongo 版,但省去 FPG 專屬的
event type/class 名稱查表(那需要 mongo 的 event_type/class 資料庫)。

事件名稱別名僅支援 sentinel-video-ingest 自包含的 type(4-7,火煙/人流/
氣候/闖入)與內建 0-3;非數字的 class 別名需 mongo 後端。"""
import argparse
import glob
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from sqlite_store import EventStore, ChannelStore  # noqa: E402

WORKSPACE_ROOT = os.path.abspath(
    os.environ.get("SENTINEL_WORKSPACE", os.path.expanduser("~/sentinel-workspace"))
)
EVENT_DATA_ROOT = os.path.join(WORKSPACE_ROOT, "event_data")

# 自包含的 type 對照(不需 mongo)。涵蓋內建 0-3 與 video-ingest 的 4-7。
TYPE_ALIASES = {
    "ppe": 0, "behavior": 1, "behaviour": 1, "intrusion": 2, "safety": 3,
    "火煙偵測": 4, "fire_smoke": 4, "fire smoke": 4, "fire": 4,
    "異常人流": 5, "abnormal_crowd": 5, "abnormal crowd": 5,
    "異常氣候": 6, "abnormal_weather": 6, "abnormal weather": 6,
    "人員闖入": 7, "person_intrusion": 7, "video_intrusion": 7,
}
TYPE_NAMES = {
    0: "PPE", 1: "Behavior", 2: "Intrusion", 3: "Safety",
    4: "火煙偵測", 5: "異常人流", 6: "異常氣候", 7: "人員闖入",
}


def emit(payload, code=0):
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def fail(message, code=1):
    emit({"ok": False, "error": message}, code)


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            try:
                dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _event_dt(ev):
    return _parse_dt(ev.get("event_time")) or _parse_dt(ev.get("created_time"))


def local_time(value):
    dt = _parse_dt(value)
    if dt:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return str(value) if value else None


def cameras_map():
    cams = {}
    for r in ChannelStore().get_all_channels():
        cid = int(r.get("channel_id", 0))
        cams[cid] = {
            "channel_id": cid,
            "channel_name": r.get("channel_name") or f"cam{cid}",
            "location": r.get("location") or "",
            "source_type": r.get("source_type") or "",
            "is_active": bool(r.get("is_active", 1)),
            "is_delete": bool(r.get("is_delete", 0)),
        }
    return cams


def _cand(abs_path):
    is_file = os.path.isfile(abs_path)
    return {
        "absolute_path": abs_path,
        "relative_path": os.path.relpath(abs_path, WORKSPACE_ROOT),
        "exists": is_file,
        "kind": "file" if is_file else "missing",
    }


def media_candidates(eid, ev):
    """組事件媒體候選:先看 row 的 image_path/clip_path,再掃 event_data/{eid}*。"""
    full, video = [], []
    seen = set()

    def add(bucket, path):
        if not path:
            return
        ap = path if os.path.isabs(path) else os.path.join(EVENT_DATA_ROOT, path)
        if ap in seen:
            return
        seen.add(ap)
        bucket.append(_cand(ap))

    add(full, ev.get("image_path"))
    add(video, ev.get("clip_path"))
    for p in sorted(glob.glob(os.path.join(EVENT_DATA_ROOT, f"{eid}*"))):
        low = p.lower()
        if low.endswith((".jpg", ".jpeg", ".png")):
            add(full, p)
        elif low.endswith((".mp4", ".avi")):
            add(video, p)
    return {"full_image": full, "video": video}


def media_directive(ordered):
    """從候選挑第一個存在的檔,產出相對路徑的 MEDIA: 指令。"""
    for kind in ("full_image", "video"):
        for c in ordered.get(kind, []):
            if c.get("exists"):
                rel = "./" + c["relative_path"].lstrip("./")
                return {
                    "preferred_media_kind": kind,
                    "preferred_media": c,
                    "media_path": rel,
                    "media_directive": f"MEDIA:{rel}",
                }
    return {}


def enrich(ev, cams):
    eid = str(ev.get("event_id"))
    cid = int(ev.get("camera_id") or 0)
    cam = cams.get(cid, {"channel_id": cid, "channel_name": f"cam{cid}", "location": ""})
    tid = ev.get("type_id")
    return {
        "event_id": eid,
        "event_time": local_time(ev.get("event_time")),
        "event_type_id": tid,
        "event_type_name": TYPE_NAMES.get(tid) if tid is not None else None,
        "event_class_id": ev.get("class_id"),
        "description": ev.get("description") or "",
        "channel_id": cid,
        "camera": cam,
        "location": cam.get("location") or "",
        "confirm_state": "auto",  # nemoclaw 全自動,無人工 confirm 流程
        "metadata": ev.get("metadata") or {},
    }


def _norm_type(raw):
    if not raw or str(raw).strip().lower() == "all":
        return None
    raw = str(raw).strip()
    if raw.isdigit():
        return int(raw)
    return TYPE_ALIASES.get(raw.lower())


def _norm_class(raw):
    if not raw or str(raw).strip().lower() == "all":
        return None
    raw = str(raw).strip()
    if raw.isdigit():
        return int(raw)
    return None  # 名稱別名 class 需 mongo 後端的 event_class 查表


def filter_events(args):
    """拉回全部事件(nemoclaw 量小),在記憶體套用時間/相機/type/class 過濾。"""
    rows = EventStore().get_latest_events(100000)
    info = {}
    now = datetime.now()
    start = end = None
    if getattr(args, "today", False):
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
        info["time_range"] = "today"
    if getattr(args, "hours", None) is not None:
        start = now - timedelta(hours=float(args.hours))
        end = now
    if getattr(args, "days", None) is not None:
        start = now - timedelta(days=float(args.days))
        end = now
    if getattr(args, "start", None):
        start = _parse_dt(args.start)
    if getattr(args, "end", None):
        end = _parse_dt(args.end)

    cam = getattr(args, "camera", None)
    type_id = _norm_type(getattr(args, "type", None))
    if getattr(args, "type", None) and str(args.type).strip().lower() != "all" and type_id is None:
        fail(f"Unknown event type: {args.type}", 2)
    class_id = _norm_class(getattr(args, "event_class", None))

    out = []
    for ev in rows:
        if cam is not None and int(ev.get("camera_id") or -1) != int(cam):
            continue
        if type_id is not None and ev.get("type_id") != type_id:
            continue
        if class_id is not None and ev.get("class_id") != class_id:
            continue
        if start or end:
            dt = _event_dt(ev)
            if dt is None:
                continue
            if start and dt < start:
                continue
            if end and dt >= end:
                continue
        out.append(ev)

    if cam is not None:
        info["camera"] = int(cam)
    if type_id is not None:
        info["event_type_id"] = type_id
        info["event_type_name"] = TYPE_NAMES.get(type_id)
    if class_id is not None:
        info["event_class_id"] = class_id
    if start:
        info["start_time"] = local_time(start)
    if end:
        info["end_time"] = local_time(end)
    status = getattr(args, "status", "all")
    if status and status != "all":
        # sqlite 後端不存 confirm 狀態(全自動),狀態過濾僅 mongo 後端支援
        info["status"] = status
        info["status_note"] = "sqlite 後端無人工 confirm 狀態,status 過濾未套用"
    return out, info


def cmd_cameras(_args=None):
    return {"ok": True, "command": "cameras", "backend": "sqlite",
            "cameras": list(cameras_map().values())}


def cmd_summary(args):
    rows, info = filter_events(args)
    cams = cameras_map()
    limit = max(1, min(int(args.limit), 20))
    by_type, by_class, by_cam = Counter(), Counter(), Counter()
    for ev in rows:
        by_type[ev.get("type_id")] += 1
        by_class[(ev.get("type_id"), ev.get("class_id"))] += 1
        by_cam[int(ev.get("camera_id") or 0)] += 1

    by_type_out = [
        {"event_type_id": t, "event_type_name": TYPE_NAMES.get(t), "count": n}
        for t, n in by_type.most_common()
    ]
    by_class_out = [
        {"event_type_id": tc[0], "event_type_name": TYPE_NAMES.get(tc[0]),
         "event_class_id": tc[1], "count": n}
        for tc, n in by_class.most_common(limit)
    ]
    by_camera_out = []
    for cid, n in by_cam.most_common():
        cam = cams.get(cid, {"channel_id": cid, "channel_name": f"cam{cid}", "location": ""})
        by_camera_out.append({"channel_id": cid, "channel_name": cam.get("channel_name"),
                              "location": cam.get("location"), "count": n})

    latest = [enrich(ev, cams) for ev in rows[:min(limit, 10)]]
    return {
        "ok": True, "command": "summary", "backend": "sqlite",
        "database": os.environ.get("NEMOCLAW_SQLITE_PATH"),
        "filters": info, "total_events": len(rows),
        "by_type": by_type_out, "by_class": by_class_out,
        "by_camera": by_camera_out, "latest": latest,
    }


def cmd_latest(args):
    rows, info = filter_events(args)
    cams = cameras_map()
    limit = max(1, min(int(args.limit), 50))
    events = [enrich(ev, cams) for ev in rows[:limit]]
    if limit == 1 and events:
        ev0 = rows[0]
        m = media_candidates(str(ev0.get("event_id")), ev0)
        events[0]["full_image"] = {"candidates": m["full_image"]}
        events[0]["video"] = {"candidates": m["video"]}
        events[0].update(media_directive(m))
    return {"ok": True, "command": "latest", "backend": "sqlite",
            "filters": info, "events": events}


def cmd_event(args):
    ev = EventStore().get_event_by_id(args.id)
    if not ev:
        fail(f"Event not found: {args.id}", 2)
    cams = cameras_map()
    out = enrich(ev, cams)
    m = media_candidates(str(ev.get("event_id")), ev)
    out["full_image"] = {"candidates": m["full_image"]}
    out["video"] = {"candidates": m["video"]}
    out.update(media_directive(m))
    return {"ok": True, "command": "event", "backend": "sqlite", "event": out}


def cmd_media(args):
    if getattr(args, "id", None):
        ev = EventStore().get_event_by_id(args.id)
    else:
        rows, _info = filter_events(args)
        ev = rows[0] if rows else None
    if not ev:
        fail("No matching event with media found", 2)
    cams = cameras_map()
    en = enrich(ev, cams)
    m = media_candidates(str(ev.get("event_id")), ev)
    payload = {
        "ok": True, "command": "media", "backend": "sqlite",
        "event": {k: en[k] for k in (
            "event_id", "event_time", "event_type_id", "event_type_name",
            "event_class_id", "channel_id", "camera", "confirm_state")},
    }
    kind = getattr(args, "kind", "all")
    if kind in ("all", "full"):
        payload["full_image"] = {"candidates": m["full_image"]}
    if kind in ("all", "video"):
        payload["video"] = {"candidates": m["video"]}
    if kind in ("all", "crop"):
        payload["crop_image"] = {"candidates": []}  # sqlite 不存 crop 圖

    if kind == "full":
        ordered = {"full_image": m["full_image"]}
    elif kind == "video":
        ordered = {"video": m["video"]}
    elif kind == "crop":
        ordered = {}
    else:
        ordered = m
    payload.update(media_directive(ordered))
    return payload


def add_common_filters(parser):
    parser.add_argument("--hours", type=float, help="Look back N hours")
    parser.add_argument("--days", type=float, help="Look back N days")
    parser.add_argument("--today", action="store_true", help="Filter by current calendar day")
    parser.add_argument("--start", help="Start time in ISO format")
    parser.add_argument("--end", help="End time in ISO format")
    parser.add_argument("--camera", type=int, help="Filter by camera/channel id")
    parser.add_argument("--type", help="Event type name or id")
    parser.add_argument("--class", dest="event_class", help="Event class id (name needs mongo backend)")
    parser.add_argument("--status", choices=["all", "pending", "confirmed", "rejected"], default="all")


def build_parser():
    parser = argparse.ArgumentParser(description="Read-only Sentinel SQLite event query helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    summary = subparsers.add_parser("summary")
    add_common_filters(summary)
    summary.add_argument("--limit", type=int, default=5)

    latest = subparsers.add_parser("latest")
    add_common_filters(latest)
    latest.add_argument("--limit", type=int, default=10)

    event = subparsers.add_parser("event")
    event.add_argument("--id", "--event-id", dest="id", required=True)

    media = subparsers.add_parser("media")
    add_common_filters(media)
    media.add_argument("--id", "--event-id", dest="id")
    media.add_argument("--kind", choices=["all", "crop", "full", "video"], default="all")

    subparsers.add_parser("cameras")
    return parser


def main():
    args = build_parser().parse_args()
    if args.command == "summary":
        emit(cmd_summary(args))
    elif args.command == "latest":
        emit(cmd_latest(args))
    elif args.command == "event":
        emit(cmd_event(args))
    elif args.command == "media":
        emit(cmd_media(args))
    elif args.command == "cameras":
        emit(cmd_cameras(args))
    else:
        fail(f"Unsupported command: {args.command}", 2)


if __name__ == "__main__":
    main()
