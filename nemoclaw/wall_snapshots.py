#!/usr/bin/env python3
"""Privacy-processed latest patrol frames for the Sky Eye wall."""
import datetime
import json
import os
import re
from pathlib import Path

import redact


def snapshot_root():
    return Path(os.environ.get(
        "NEMOCLAW_WALL_SNAPSHOT_DIR",
        os.path.join(os.path.dirname(__file__), "wall_snapshots"),
    )).resolve()


def _safe_channel_id(channel_id):
    return re.sub(r"[^0-9A-Za-z_-]+", "_", str(channel_id)).strip("_") or "unknown"


def _paths(channel_id):
    stem = f"ch{_safe_channel_id(channel_id)}"
    root = snapshot_root()
    return root / f"{stem}.jpg", root / f"{stem}.json"


def publish(channel_id, name, frame_path, captured_at=None):
    """Atomically publish one redacted latest-frame preview; raw frames are never copied."""
    if not frame_path or not os.path.exists(frame_path):
        return None
    image_path, metadata_path = _paths(channel_id)
    image_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_image = image_path.with_name(f".{image_path.stem}.{os.getpid()}.jpg")
    try:
        redacted = redact.redact_pii(frame_path, str(tmp_image))
        if not redacted or not os.path.exists(redacted):
            return None
        os.replace(redacted, image_path)
        ts = captured_at or datetime.datetime.now().isoformat(timespec="seconds")
        metadata = {
            "channel": str(channel_id),
            "name": name,
            "captured_at": ts,
            "privacy_processed": True,
        }
        tmp_metadata = metadata_path.with_suffix(".json.tmp")
        with open(tmp_metadata, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False)
        os.replace(tmp_metadata, metadata_path)
        return {"path": str(image_path), **metadata}
    except Exception:
        try:
            tmp_image.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def preview(channel_id):
    """Return public preview metadata when a redacted wall snapshot exists."""
    image_path, metadata_path = _paths(channel_id)
    if not image_path.exists():
        return None
    metadata = {}
    try:
        metadata = json.load(open(metadata_path, encoding="utf-8"))
    except Exception:
        pass
    return {
        "url": f"/wall/{image_path.name}",
        "path": str(image_path),
        "captured_at": metadata.get("captured_at", ""),
        "privacy_processed": True,
    }


def resolve_public(rel):
    """Resolve only public redacted snapshot image names from `/wall/`."""
    name = os.path.basename(str(rel or ""))
    if name != rel or not re.fullmatch(r"ch[0-9A-Za-z_-]+\.jpg", name):
        return None
    target = snapshot_root() / name
    return target if target.exists() and target.is_file() else None
