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


def create_clip(video_path, out_path, center_sec=None, pre_roll=None, duration=None):
    if not video_path or not os.path.exists(video_path):
        return None
    duration = float(duration or os.environ.get("NEMOCLAW_CLIP_SECONDS", "8"))
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

    frame_path = _copy(frame_src, out_dir / "frame.jpg")
    if not frame_path and source_video:
        frame_path = extract_frame(source_video, str(out_dir / "frame.jpg"), playhead)

    clip_path = create_clip(source_video, str(out_dir / "clip.mp4"), playhead) if source_video else None
    ann = annotate_frame(
        frame_path,
        str(out_dir / "falcon_annotated.jpg"),
        event_type=incident.get("event_type"),
        query=incident.get("falcon_query"),
    ) if frame_path else {"ok": False, "error": "no frame for falcon annotation"}

    manifest = {
        "trace_id": safe_trace_id(trace_id),
        "source_video_path": source_video,
        "playhead_sec": playhead,
        "frame_path": frame_path,
        "clip_path": clip_path,
        "falcon_annotated_path": ann.get("annotated_path"),
        "falcon_query": ann.get("query") or incident.get("falcon_query"),
        "falcon_counts": ann.get("counts", {}),
        "falcon_error": ann.get("error"),
    }
    manifest["urls"] = {
        "trace": trace_url(trace_id, absolute=True),
        "frame": media_url(frame_path, absolute=True) if frame_path else "",
        "clip": media_url(clip_path, absolute=True) if clip_path else "",
        "falcon_annotated": media_url(ann.get("annotated_path"), absolute=True) if ann.get("annotated_path") else "",
    }
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest
