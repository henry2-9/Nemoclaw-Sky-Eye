#!/usr/bin/env python3
"""
sentinel-perception — query the falcon-perception inference service for object
detection / segmentation in an image.

Container variant: HTTP-only. The host-side legacy script could fall back to
in-process PyTorch when the server was down; that fallback has been removed
because the openclaw container does not (and should not) carry a PyTorch
runtime — the perception model lives in its own GPU-owning container service.

Usage:
  sentinel-perception --image <path>      --query "person, helmet"
  sentinel-perception --event-id <id>     --query "car"
  sentinel-perception --channel <id>      --query "person" --task detection

Output: JSON
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

WORKSPACE_ROOT = Path(os.environ.get("SENTINEL_WORKSPACE", "/state")).resolve()
PERCEPTION_SERVER_URL = os.environ.get(
    "FALCON_PERCEPTION_SERVER", "http://falcon-perception:18793"
).rstrip("/")
PICTSHARE_URL = os.environ.get("PICTSHARE_URL", "").rstrip("/")
PICTSHARE_UPLOAD_CODE = os.environ.get("PICTSHARE_UPLOAD_CODE", "")

os.chdir(WORKSPACE_ROOT)
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))


def upload_image(path: str) -> str | None:
    """Upload to pictshare and return the canonical URL, or None if not configured / failed."""
    if not PICTSHARE_URL or not PICTSHARE_UPLOAD_CODE:
        return None
    try:
        import requests
        with open(path, "rb") as fh:
            mime = "image/jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "image/png"
            r = requests.post(
                f"{PICTSHARE_URL}/api/upload.php",
                files={"file": (Path(path).name, fh, mime)},
                data={"uploadcode": PICTSHARE_UPLOAD_CODE},
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            h = data.get("hash") or ""
            if h:
                return f"{PICTSHARE_URL}/{h.lstrip('/')}"
            raw = data.get("url") or ""
            if raw.startswith("http"):
                return raw
            if raw:
                return f"{PICTSHARE_URL}/{raw.lstrip('/')}"
    except Exception:
        return None
    return None


def get_event_image(event_id: str) -> str | None:
    """Look up the representative image for an event by id, then by file scan."""
    try:
        from database import EventDatabase
        db = EventDatabase()
        ev = db.get_event_by_id(event_id)
        if ev:
            for key in ("combined_image", "image_path", "clip_path"):
                p = ev.get(key)
                if p and os.path.exists(p):
                    return p
    except Exception:
        pass
    event_data = WORKSPACE_ROOT / "event_data"
    for ext in ("jpg", "jpeg", "png"):
        cands = list(event_data.rglob(f"*{event_id}*.{ext}"))
        if cands:
            return str(cands[0])
    return None


def grab_frame_from_channel(channel_id: int) -> str | None:
    """Use ffmpeg to grab a single frame from the channel's RTSP/file source."""
    try:
        from database import StreamSourceDatabase
        db = StreamSourceDatabase()
        sources = db.get_stream_sources_with_channel_ids()
        match = next((url for url, cid in sources if cid == channel_id), None)
        if not match:
            return None
        is_rtsp = match.lower().startswith("rtsp://")
        if not is_rtsp and not os.path.exists(match):
            return None
        out = f"/tmp/fp_frame_{channel_id}.jpg"
        if is_rtsp:
            cmd = ["ffmpeg", "-y", "-rtsp_transport", "tcp",
                   "-i", match, "-frames:v", "1",
                   "-vf", "scale=1280:-1", "-q:v", "2", out]
        else:
            cmd = ["ffmpeg", "-y", "-ss", "1", "-i", match,
                   "-frames:v", "1", "-vf", "scale=1280:-1", "-q:v", "2", out]
        subprocess.run(cmd, capture_output=True, timeout=30)
        return out if os.path.exists(out) else None
    except Exception:
        return None


def call_perception_server(image_path: str, query: str, task: str) -> dict | None:
    """POST to the falcon-perception service. Returns dict on success, None on failure."""
    try:
        payload = json.dumps({
            "image_path": image_path,
            "query": query,
            "task": task,
        }).encode()
        req = urllib.request.Request(
            f"{PERCEPTION_SERVER_URL}/infer",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--image",    help="圖片路徑")
    group.add_argument("--event-id", help="Event ID(從事件資料庫取圖)")
    group.add_argument("--channel",  type=int, help="頻道 ID(截取目前畫面)")

    parser.add_argument("--query", required=True,
                        help="要偵測的類別,多個用逗號分隔,例如 'person, helmet, car'")
    parser.add_argument("--task", choices=["detection", "segmentation"],
                        default="detection", help="偵測模式(預設 detection)")
    args = parser.parse_args()

    # ---- 1. resolve image source ----
    image_path = None
    source_desc = ""
    if args.image:
        image_path = args.image
        source_desc = args.image
        if not os.path.exists(image_path):
            print(json.dumps({"ok": False, "error": f"圖片不存在: {image_path}"}, ensure_ascii=False))
            sys.exit(1)
    elif args.event_id:
        image_path = get_event_image(args.event_id)
        source_desc = f"event:{args.event_id}"
        if not image_path:
            print(json.dumps({"ok": False, "error": f"找不到 event {args.event_id} 的圖片"}, ensure_ascii=False))
            sys.exit(1)
    elif args.channel is not None:
        image_path = grab_frame_from_channel(args.channel)
        source_desc = f"channel:{args.channel}"
        if not image_path:
            print(json.dumps({"ok": False, "error": f"無法從 channel {args.channel} 截取畫面"}, ensure_ascii=False))
            sys.exit(1)

    # ---- 2. call falcon-perception service ----
    result = call_perception_server(image_path, args.query, args.task)
    if result is None:
        print(json.dumps({
            "ok": False,
            "error": f"falcon-perception 服務無法回應 ({PERCEPTION_SERVER_URL}/infer)。"
                     "請確認 docker compose 中的 falcon-perception 容器為 healthy。",
        }, ensure_ascii=False))
        sys.exit(1)

    # ---- 3. (optional) upload annotated image to pictshare ----
    annotated_path = result.get("annotated_path")
    public_url = upload_image(annotated_path) if annotated_path else None

    counts = result.get("counts", {})
    total = sum(counts.values()) if isinstance(counts, dict) else 0
    print(json.dumps({
        "ok": True,
        "source": source_desc,
        "query": args.query,
        "task": result.get("task", args.task),
        "counts": counts,
        "total_detected": total,
        "annotated_image_url": public_url,
        "annotated_path": annotated_path,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
