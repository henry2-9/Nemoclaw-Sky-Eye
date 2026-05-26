#!/usr/bin/env python3
"""Incident media artifacts: event clip, representative frame, Falcon overlay."""
import json
import mimetypes
import os
import re
import shutil
import subprocess
from pathlib import Path

import falcon_client
import redact


EVENT_QUERY = {
    "fire_smoke": "fire, smoke",
    "intrusion": "person",
    "abnormal_crowd": "person",
    "abnormal_weather": "flood, fallen tree, smoke, fire",
}


def media_root():
    return Path(os.environ.get(
        "NEMOCLAW_MEDIA_DIR",
        os.path.join(os.path.dirname(__file__), "media_events"),
    )).resolve()


def dashboard_base_url():
    return os.environ.get("NEMOCLAW_DASHBOARD_PUBLIC_URL") or os.environ.get(
        "NEMOCLAW_DASHBOARD_URL",
        f"http://127.0.0.1:{os.environ.get('NEMOCLAW_DASHBOARD_PORT', '8099')}",
    )


def safe_trace_id(trace_id):
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", str(trace_id or "no-trace")).strip("_") or "no-trace"


def artifact_dir(trace_id):
    path = media_root() / safe_trace_id(trace_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def relative_media_path(path):
    try:
        return str(Path(path).resolve().relative_to(media_root())).replace(os.sep, "/")
    except Exception:
        return ""


def media_url(path, absolute=False):
    rel = relative_media_path(path)
    if not rel:
        return ""
    local = f"/media/{rel}"
    return f"{dashboard_base_url().rstrip('/')}{local}" if absolute else local


def trace_url(trace_id, absolute=False):
    local = f"/trace?trace_id={safe_trace_id(trace_id)}"
    return f"{dashboard_base_url().rstrip('/')}{local}" if absolute else local


def guess_mime(path):
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def _copy(src, dst):
    if not src or not os.path.exists(src):
        return None
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return str(dst)


def _probe_duration(video_path):
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=10,
        )
        out = (proc.stdout or "").strip()
        return float(out) if out else 0.0
    except Exception:
        return 0.0


def extract_frame(video_path, out_path, second=None):
    if not video_path or not os.path.exists(video_path):
        return None
    if second is None:
        duration = _probe_duration(video_path)
        second = duration * 0.5 if duration > 0 else 0.0
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, float(second)):.3f}",
        "-i", video_path, "-frames:v", "1", "-vf", "scale=960:-1", "-q:v", "3", out_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30)
    except Exception:
        return None
    return out_path if os.path.exists(out_path) and os.path.getsize(out_path) > 0 else None


STREAM_PREFIXES = ("rtsp://", "http://", "https://")

def is_stream(path):
    return str(path or "").lower().startswith(STREAM_PREFIXES)


def create_clip(video_path, out_path, center_sec=None, pre_roll=None, duration=None):
    duration = float(duration or os.environ.get("NEMOCLAW_CLIP_SECONDS", "8"))
    if is_stream(video_path):
        # live 串流無法回放:從事件當下往後錄製 forward clip(post-event)。
        # YouTube URL 先用 yt-dlp 解成 HLS,ffmpeg 才吃得到。
        try:
            from feed import resolve_url
            real = resolve_url(video_path) or video_path
        except Exception:
            real = video_path
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error", "-i", real,
            "-t", f"{duration:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
            "-an", "-movflags", "+faststart", out_path,
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=duration + 60)
        except Exception:
            return None
        return out_path if os.path.exists(out_path) and os.path.getsize(out_path) > 0 else None
    if not video_path or not os.path.exists(video_path):
        return None
    pre_roll = float(pre_roll or os.environ.get("NEMOCLAW_CLIP_PREROLL", "3"))
    center_sec = float(center_sec) if center_sec is not None else (_probe_duration(video_path) * 0.5)
    start = max(0.0, center_sec - pre_roll)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", video_path,
        "-t", f"{duration:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
        "-an", "-movflags", "+faststart", out_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=90)
    except Exception:
        return None
    return out_path if os.path.exists(out_path) and os.path.getsize(out_path) > 0 else None


def annotate_frame(frame_path, out_path, event_type=None, query=None, task="segmentation"):
    if not frame_path or not os.path.exists(frame_path):
        return {"ok": False, "error": "frame missing"}
    query = query or EVENT_QUERY.get(event_type or "", "person")
    result = falcon_client.detect(frame_path, query, task=task)
    if not result:
        copied = _copy(frame_path, out_path)
        return {"ok": False, "error": "falcon unavailable", "annotated_path": copied, "query": query}
    annotated = result.get("annotated_path") or ""
    if annotated and os.path.exists(annotated):
        _copy(annotated, out_path)
    else:
        _copy(frame_path, out_path)
    return {
        "ok": bool(result.get("ok", True)),
        "annotated_path": out_path if os.path.exists(out_path) else None,
        "query": query,
        "task": result.get("task", task),
        "counts": result.get("counts", {}),
        "error": result.get("error"),
    }


def prepare_event_media(incident):
    """Create durable media artifacts for an incident.

    Returns an artifact dict suitable for audit.jsonl and dashboard rendering.
    All failures are represented in the return value rather than raised so the
    alerting path never blocks on media generation.
    """
    trace_id = incident.get("trace_id") or f"{incident.get('channel')}-{incident.get('event_type')}"
    out_dir = artifact_dir(trace_id)
    source_video = incident.get("source_video_path") or incident.get("video_path") or ""
    playhead = incident.get("playhead_sec")
    frame_src = (incident.get("media_refs") or [None])[0]
    live = is_stream(source_video)
    clip_status = "ok"

    if live:
        # live URL:往後錄製 forward clip,再從 clip 抽代表幀(與影片一致)
        clip_path = create_clip(source_video, str(out_dir / "clip.mp4"))
        frame_path = extract_frame(clip_path, str(out_dir / "frame.jpg")) if clip_path else None
        if not frame_path:                      # clip/抽幀失敗 → 退回 sweep 當下那張幀
            frame_path = _copy(frame_src, out_dir / "frame.jpg")
        if not clip_path:
            clip_status = "stream_unavailable"
    else:
        frame_path = _copy(frame_src, out_dir / "frame.jpg")
        if not frame_path and source_video:
            frame_path = extract_frame(source_video, str(out_dir / "frame.jpg"), playhead)
        clip_path = create_clip(source_video, str(out_dir / "clip.mp4"), playhead) if source_video else None
        if not source_video:
            clip_status = "no_source"
        elif not clip_path:
            clip_status = "clip_failed"
    ann = annotate_frame(
        frame_path,
        str(out_dir / "falcon_annotated.jpg"),
        event_type=incident.get("event_type"),
        query=incident.get("falcon_query"),
    ) if frame_path else {"ok": False, "error": "no frame for falcon annotation"}

    # ── P0.2 隱私:對外只發 redacted 版本,原始素材僅留本機 ──────────────
    raw_annot = ann.get("annotated_path")
    red_frame = redact.redact_pii(frame_path, str(out_dir / "frame_redacted.jpg")) if frame_path else None
    red_annot = redact.redact_pii(raw_annot, str(out_dir / "falcon_annotated_redacted.jpg")) if raw_annot else None
    red_clip = redact.redact_video(clip_path, str(out_dir / "redacted_clip.mp4")) if clip_path else None
    privacy_processed = bool((red_frame or not frame_path) and (red_clip or not clip_path))

    manifest = {
        "trace_id": safe_trace_id(trace_id),
        "source_video_path": source_video,
        "is_live": live,
        "clip_status": clip_status,
        "privacy_processed": privacy_processed,
        "playhead_sec": playhead,
        # 對外公開路徑 = redacted;原始僅本機(raw,不轉成 URL)
        "frame_path": red_frame,
        "clip_path": red_clip,
        "falcon_annotated_path": red_annot,
        "notify_photo": red_annot or red_frame,
        "raw": {"frame": frame_path, "clip": clip_path, "falcon_annotated": raw_annot},
        "falcon_query": ann.get("query") or incident.get("falcon_query"),
        "falcon_counts": ann.get("counts", {}),
        "falcon_error": ann.get("error"),
    }
    manifest["urls"] = {                          # 只暴露 redacted artifact
        "trace": trace_url(trace_id, absolute=True),
        "frame": media_url(red_frame, absolute=True) if red_frame else "",
        "clip": media_url(red_clip, absolute=True) if red_clip else "",
        "falcon_annotated": media_url(red_annot, absolute=True) if red_annot else "",
    }
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest
