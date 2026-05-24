#!/usr/bin/env python3
"""
sentinel-video-ingest — 分析指定類別影片並寫入事件至 MongoDB
用法:
  sentinel-video-ingest --type <中文類別>
  支援: 火煙偵測 / 異常人流 / 異常氣候 / 人員闖入
輸出: JSON
"""
import argparse
import base64
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_ROOT = Path(os.environ.get("SENTINEL_WORKSPACE", "/state")).resolve()
VIDEO_DIR = Path(os.environ.get("Sentinel_VIDEO_DIR", "/data/video"))
EVENT_TYPES_DIR = Path(os.environ.get("EVENT_TYPES_DIR", "/config/event-types"))
os.chdir(WORKSPACE_ROOT)
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

API_URL = os.environ.get("VLM_API_URL", "http://llama-server:8080/v1/chat/completions")
API_KEY = os.environ.get("VLM_API_KEY", "dummy")
MODEL = os.environ.get("VLM_MODEL", "qwen3.6-35b-a3b")
PICTSHARE_URL = os.environ.get("PICTSHARE_URL", "").rstrip("/")
PICTSHARE_UPLOAD_CODE = os.environ.get("PICTSHARE_UPLOAD_CODE", "")
MAX_FRAMES = int(os.environ.get("VLM_MAX_FRAMES", "8"))  # cap to avoid HTTP 400 from oversized payloads

DESCRIBE_PROMPT = (
    "請用流暢的繁體中文段落，詳細描述這段監控畫面中發生了什麼事。"
    "包含：場景特徵、人物外觀與行為、事件如何發展、最終結果。"
    "使用敘事語氣，不要條列，不要使用第一人稱，不要提及秒數、幀數或任何影片格式資訊。"
    "直接描述畫面內容，長度約 80 到 150 字。"
)


def _load_event_types() -> tuple[dict, dict]:
    """
    Build TYPE_MAP and CLASS_ID_MAP from /config/event-types/*.yaml.

    Each YAML must conform to schemas/event-type.schema.json. The map is
    indexed by the human-readable `name` (Chinese), which is what the agent
    passes via `--type`. We also accept lookup by `key` (slug) so future
    integrations don't have to know the localized name.

    Backward-compatible shape:
        TYPE_MAP[name] = {
            "type_id":   int,
            "prefix":    str,        # name (used to glob video files)
            "classes":   [str, ...], # ordered list of class keys
            "prompt":    str,
            "class_ids": {key: id},
            "output_guards": dict | None,
            "vlm":       dict | None,
        }
        CLASS_ID_MAP[type_id] = {key: id, ...}
    """
    try:
        import yaml  # type: ignore
    except ImportError:
        sys.stderr.write(
            "[sentinel-video-ingest] PyYAML missing; cannot load event-types from "
            f"{EVENT_TYPES_DIR}. Install PyYAML or fix the openclaw image.\n"
        )
        return {}, {}

    type_map: dict = {}
    class_id_map: dict = {}
    if not EVENT_TYPES_DIR.is_dir():
        sys.stderr.write(
            f"[sentinel-video-ingest] event-types directory not found: {EVENT_TYPES_DIR}\n"
        )
        return type_map, class_id_map

    for path in sorted(EVENT_TYPES_DIR.glob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as e:
            sys.stderr.write(f"[sentinel-video-ingest] failed to parse {path}: {e}\n")
            continue
        if not isinstance(doc, dict) or doc.get("enabled") is False:
            continue

        try:
            type_id   = int(doc["id"])
            name      = str(doc["name"])
            classes   = doc["classes"]
            prompt    = doc["vlm"]["prompt"]
        except (KeyError, TypeError, ValueError) as e:
            sys.stderr.write(f"[sentinel-video-ingest] {path} missing required field: {e}\n")
            continue

        class_keys = [str(c["key"]) for c in classes]
        class_ids  = {str(c["key"]): int(c["id"]) for c in classes}

        entry = {
            "type_id":       type_id,
            "prefix":        name,
            "classes":       class_keys,
            "prompt":        str(prompt),
            "class_ids":     class_ids,
            "output_guards": doc.get("output_guards") or {},
            "vlm":           doc.get("vlm") or {},
            "key":           str(doc.get("key") or ""),
        }
        # index by both display name (legacy) and key (machine-readable)
        type_map[name] = entry
        if entry["key"]:
            type_map[entry["key"]] = entry
        class_id_map[type_id] = class_ids

    return type_map, class_id_map


TYPE_MAP, CLASS_ID_MAP = _load_event_types()

def get_video_duration(video_path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", video_path],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            return float(s.get("duration", 0) or 0)
    return 0.0


def extract_frames_1fps(video_path: str, fps: float = 1.0) -> tuple:
    """每秒抽 fps 幀，回傳 (base64列表, duration, 代表幀路徑)"""
    import math
    duration = get_video_duration(video_path)
    total = max(1, math.ceil(duration * fps))
    stem = Path(video_path).stem
    frames = []
    thumb_path = None
    mid = total // 2
    for i in range(total):
        t = i / fps
        out = f"/tmp/sentinel_vi_{stem}_{i:04d}.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(t), "-i", video_path,
             "-frames:v", "1", "-vf", "scale=512:-1", "-q:v", "3", out],
            capture_output=True
        )
        if os.path.exists(out):
            with open(out, "rb") as f:
                frames.append(base64.b64encode(f.read()).decode())
            if i == mid:
                # 代表幀用較高解析度重新擷取
                thumb = f"/tmp/sentinel_vi_{stem}_thumb.jpg"
                subprocess.run(
                    ["ffmpeg", "-y", "-ss", str(t), "-i", video_path,
                     "-frames:v", "1", "-vf", "scale=1280:-1", "-q:v", "2", thumb],
                    capture_output=True
                )
                thumb_path = thumb if os.path.exists(thumb) else out
            os.remove(out)
    if not thumb_path:
        # fallback：用第 1 秒
        thumb = f"/tmp/sentinel_vi_{stem}_thumb.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", "1", "-i", video_path,
             "-frames:v", "1", "-vf", "scale=1280:-1", "-q:v", "2", thumb],
            capture_output=True
        )
        thumb_path = thumb if os.path.exists(thumb) else None
    return frames, duration, thumb_path


MAX_PAYLOAD_BYTES = int(os.environ.get("VLM_MAX_PAYLOAD_MB", "4")) * 1024 * 1024  # 預設 4 MB


def _subsample(frames: list, n: int) -> list:
    if n >= len(frames):
        return frames
    step = len(frames) / n
    return [frames[int(i * step)] for i in range(n)]


def ask_vlm(frames: list, prompt: str, prefill: str | None = "{", max_tokens: int = 800, max_frames: int = None) -> str:
    import time
    import urllib.error
    import urllib.request
    cap = max_frames if max_frames is not None else MAX_FRAMES
    frames = _subsample(frames, cap)
    while len(frames) > 1:
        total = sum(len(b) for b in frames)
        if total <= MAX_PAYLOAD_BYTES:
            break
        frames = _subsample(frames, max(1, len(frames) - 1))
    # Append /no_think to suppress Qwen3-style chain-of-thought leaking into
    # the response body. The token is a no-op for non-thinking models.
    user_text = str(prompt or "").strip()
    if "/no_think" not in user_text and "/nothink" not in user_text:
        user_text = f"{user_text}\n\n/no_think"
    content = [{"type": "text", "text": user_text}]
    for b64 in frames:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    messages = [{"role": "user", "content": content}]
    if prefill:
        messages.append({"role": "assistant", "content": prefill})
    payload_obj = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
    }
    for attempt in range(3):
        try:
            payload = json.dumps(payload_obj).encode()
            req = urllib.request.Request(
                API_URL, data=payload,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {API_KEY}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                raw = json.load(resp)["choices"][0]["message"]["content"]
            import re as _re
            raw = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
            # 若模型把 prefill 當 thinking 輸出，</think> 後才是乾淨結果
            if "</think>" in raw:
                raw = raw.split("</think>")[-1].strip()
            if prefill and not raw.startswith(prefill):
                raw = prefill + raw
            return raw
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            print(f"[ask_vlm] HTTP {e.code} attempt {attempt+1}: {body}", file=sys.stderr)
            if attempt < 2:
                time.sleep(10)
            else:
                raise


def _strip_markup(text: str) -> str:
    import re
    text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)
    text = re.sub(r'[{}"\'\\]', "", text)
    return text.strip()


# Patterns that strongly indicate the VLM leaked its reasoning into the
# `description` value instead of giving us a clean event description. These
# fire even when /no_think is honored partially. When matched we discard the
# contaminated text and substitute a safe default.
_THINKING_LEAK_PATTERNS = (
    r"^thought\s*[:：]",
    r"^analysis\s*[:：]",
    r"分析請求",
    r"分析步驟",
    r"^let'?s\b",
    r"^首先(?:[，,])?",
    r"^\*\*[^*]+\*\*[\n：:]",         # markdown bold heading
    r"^\d+\s*[\.\)、]\s+\*?\*?",      # "1. **" enumerated steps
    r"\bstep\s*\d+\b",
)


def _looks_like_thinking_leak(text: str) -> bool:
    import re
    if not text:
        return False
    sample = text.strip()[:240]
    return any(re.search(p, sample, re.IGNORECASE | re.MULTILINE) for p in _THINKING_LEAK_PATTERNS)


def _apply_description_guards(desc: str, default_label: str, guards: dict | None) -> str:
    """
    Enforce output_guards from the event-type YAML:
      • no_thinking_leak — replace contaminated text with a safe default
      • description_length — clip overly long output, reject too-short stub
    """
    import re
    desc = (desc or "").strip()
    g = guards or {}

    if g.get("no_thinking_leak", True) and _looks_like_thinking_leak(desc):
        return f"偵測到{default_label}事件"

    # collapse whitespace / newlines (descriptions must be single paragraph)
    desc = re.sub(r"\s+", "", desc) if any('一' <= ch <= '鿿' for ch in desc) else re.sub(r"\s+", " ", desc).strip()

    rng = g.get("description_length")
    if isinstance(rng, (list, tuple)) and len(rng) == 2:
        lo, hi = int(rng[0]), int(rng[1])
        if hi > 0 and len(desc) > hi:
            desc = desc[:hi].rstrip("，。、 ") + "…"
        if lo > 0 and len(desc) < lo:
            return f"偵測到{default_label}事件"

    return desc or f"偵測到{default_label}事件"


def parse_vlm_response(
    text: str,
    valid_classes: list,
    default_class: str,
    guards: dict | None = None,
) -> tuple:
    import re
    text = re.sub(r"<think>.*?</think>", "", str(text or ""), flags=re.DOTALL).strip()
    default_label = default_class

    # 嘗試完整 JSON 解析
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start:end])
            cls = data.get("class", "").strip()
            desc = data.get("description", "").strip()
            if cls not in valid_classes:
                cls = default_class
            desc = _apply_description_guards(desc, cls, guards)
            return cls, desc
        except Exception:
            pass

    # JSON 截斷時：用 regex 單獨抽出 description 值
    desc_m = re.search(r'"description"\s*:\s*"(.+?)(?:"|$)', text, re.DOTALL)
    cls_m = re.search(r'"class"\s*:\s*"(\w+)"', text)
    if desc_m:
        desc = desc_m.group(1).strip().rstrip('",}')
        cls = cls_m.group(1).strip() if cls_m else ""
        if cls not in valid_classes:
            cls = default_class
        desc = _apply_description_guards(desc, cls, guards)
        return cls, desc

    # 最後 fallback：找 class 關鍵字，描述清除 JSON 符號
    chosen_cls = default_class
    for cls in valid_classes:
        if cls in text.lower():
            chosen_cls = cls
            break
    desc = _strip_markup(text[:400])
    desc = _apply_description_guards(desc, chosen_cls, guards)
    return chosen_cls, desc


def upload_image(path: str):
    import urllib.request
    try:
        boundary = "----FormBoundary7MA4YWxkTrZu0gW"
        with open(path, "rb") as f:
            file_data = f.read()
        fname = Path(path).name
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="uploadcode"\r\n\r\n'
            f"{PICTSHARE_UPLOAD_CODE}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{fname}"\r\n'
            f"Content-Type: image/jpeg\r\n\r\n"
        ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            f"{PICTSHARE_URL}/api/upload.php",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        h = data.get("hash") or ""
        if h:
            return f"{PICTSHARE_URL}/{h.lstrip('/')}"
        raw = data.get("url") or ""
        if raw.startswith("http"):
            return raw
        return f"{PICTSHARE_URL}/{raw.lstrip('/')}" if raw else None
    except Exception:
        return None


def upload_video(path: str) -> str | None:
    """Upload a video file to Pictshare and return its public URL."""
    import urllib.request
    try:
        boundary = "----FormBoundarySentinelVideo"
        with open(path, "rb") as f:
            file_data = f.read()
        fname = Path(path).name
        mime = "video/mp4" if path.lower().endswith(".mp4") else "video/mpeg"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="uploadcode"\r\n\r\n'
            f"{PICTSHARE_UPLOAD_CODE}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{fname}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            f"{PICTSHARE_URL}/api/upload.php",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        h = data.get("hash") or ""
        if h:
            # /raw/<hash> serves video/mp4 directly (LINE requires correct Content-Type)
            return f"{PICTSHARE_URL}/raw/{h.lstrip('/')}"
        raw = data.get("url") or ""
        if raw.startswith("http"):
            fname = raw.rsplit("/", 1)[-1]
            return f"{PICTSHARE_URL}/raw/{fname}"
        return None
    except Exception:
        return None


def insert_event(type_id: int, class_id: int, description: str,
                 video_path: str, image_url, frame_path: str,
                 key_time: float = None, channel_id: int = 0) -> str:
    import shutil
    with redirect_stdout(sys.stderr):
        from database.event_database import EventDatabase
    db = EventDatabase()
    video_ext = Path(video_path).suffix or ".mp4"
    result = db.insert_event({
        "Event_type_id": type_id,
        "Event_class_id": class_id,
        "Channel_id": channel_id,
        "Event_time": datetime.now(),
        "Confirm_state": "pending",
        "Description": description,
        "Full_image": True,
        "Full_video": True,
        "metadata": {
            "source": "video_ingest",
            "video_path": str(video_path),
            "image_url": image_url,
        },
    })
    oid = str(result.inserted_id)
    cam = f"cam{channel_id}"
    event_data = WORKSPACE_ROOT / "event_data"
    event_data.mkdir(exist_ok=True)
    try:
        shutil.copy2(frame_path, event_data / f"{oid}_{cam}_f.jpg")
    except Exception:
        pass
    # 截取關鍵 5 秒片段（事件前 2 秒 + 事件後 3 秒）
    dest_video = event_data / f"{oid}_{cam}_v.mp4"
    clipped = False
    if key_time is not None:
        try:
            start = max(0.0, key_time - 2.0)
            clip_tmp = f"/tmp/sentinel_clip_{oid}.mp4"
            r = subprocess.run(
                ["ffmpeg", "-y", "-ss", str(start), "-i", video_path,
                 "-t", "5", "-c:v", "libx264", "-crf", "23",
                 "-c:a", "copy", "-movflags", "+faststart", clip_tmp],
                capture_output=True, timeout=60,
            )
            if r.returncode == 0 and os.path.exists(clip_tmp):
                shutil.move(clip_tmp, dest_video)
                clipped = True
        except Exception:
            pass
    if not clipped:
        try:
            shutil.copy2(video_path, dest_video)
        except Exception:
            pass
    return oid


def send_text_notification(channel: str, target: str, text: str) -> None:
    """Send a plain-text message via openclaw."""
    try:
        subprocess.run(
            ["openclaw", "message", "send",
             "--channel", channel, "--target", target, "--message", text],
            capture_output=True, timeout=30,
        )
    except Exception:
        pass


def _line_access_token() -> str:
    """Read LINE channelAccessToken from openclaw config."""
    try:
        cfg_path = Path(os.environ.get("OPENCLAW_ROOT", os.path.expanduser("~/.openclaw"))) / "openclaw.json"
        with open(cfg_path) as f:
            return json.load(f)["channels"]["line"]["channelAccessToken"]
    except Exception:
        return ""


def _normalize_line_target(to: str) -> str:
    """Strip routing prefixes so LINE pushMessage receives the bare id.

    Accepts any of: "C7a018...", "group:C7a018...", "room:R123...",
    "line:C7a018...", "line:group:C7a018...". LINE's pushMessage `to`
    field expects just the userId / groupId / roomId.
    """
    t = (to or "").strip()
    for prefix in ("line:group:", "line:room:", "line:user:", "line:",
                   "group:", "room:", "user:"):
        if t.startswith(prefix):
            t = t[len(prefix):]
            break
    return t


def _send_line_video(to: str, video_url: str, preview_url: str, caption: str = "") -> None:
    """Call LINE Messaging API directly with type=video message."""
    import urllib.request
    token = _line_access_token()
    if not token:
        return
    target = _normalize_line_target(to)
    if not target:
        return
    messages = []
    if caption:
        messages.append({"type": "text", "text": caption})
    messages.append({
        "type": "video",
        "originalContentUrl": video_url,
        "previewImageUrl": preview_url,
    })
    payload = json.dumps({"to": target, "messages": messages}).encode()
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30):
        pass


def send_video_notification(channel: str, target: str, video_path: str,
                            caption: str = "", preview_url: str = "") -> None:
    """Fire-and-forget video send."""
    import threading

    def _send():
        try:
            if not os.path.exists(video_path):
                return
            if channel == "line":
                # LINE requires public URLs and proper video message type
                video_url = upload_video(video_path)
                if not video_url:
                    return
                # Use provided preview or upload a frame as preview image
                prev = preview_url
                if not prev:
                    frame_tmp = f"/tmp/sentinel_prev_{Path(video_path).stem}.jpg"
                    subprocess.run(
                        ["ffmpeg", "-y", "-ss", "1", "-i", video_path,
                         "-frames:v", "1", "-vf", "scale=480:-1", "-q:v", "3", frame_tmp],
                        capture_output=True, timeout=15,
                    )
                    if os.path.exists(frame_tmp):
                        prev = upload_image(frame_tmp) or ""
                        try:
                            os.remove(frame_tmp)
                        except Exception:
                            pass
                if not prev:
                    return  # LINE requires previewImageUrl
                _send_line_video(target, video_url, prev, caption)
            else:
                # Upload to PictShare first, then send a plain-text message
                # containing the URL. Avoids streaming the mp4 through
                # openclaw → Telegram multipart (which stalls when the
                # upstream link has loss and leaves orphan child processes).
                video_url = upload_video(video_path)
                if not video_url:
                    print(f"[send_video] {channel} upload failed", file=sys.stderr)
                    return
                text = f"{caption}\n{video_url}" if caption else video_url
                cmd = ["openclaw", "message", "send",
                       "--channel", channel, "--target", target,
                       "--message", text]
                subprocess.run(cmd, capture_output=True, timeout=60,
                               start_new_session=True)
        except Exception as exc:
            print(f"[send_video] {channel} error: {exc}", file=sys.stderr)

    # daemon=False: main process waits for all send threads before exit,
    # so the openclaw / LINE API call is not killed mid-flight.
    threading.Thread(target=_send, daemon=False).start()


def resolve_active_session() -> tuple:
    """Find the most recently active Sentinel session from sessions.json.

    sessions.json has an 'updatedAt' Unix-ms timestamp that is updated on
    every agent turn, making it far more reliable than commands.log (which
    only records session creation/reset events).
    """
    sessions_path = (
        Path(os.environ.get("OPENCLAW_ROOT", os.path.expanduser("~/.openclaw")))
        / "agents" / "sentinel" / "sessions" / "sessions.json"
    )
    try:
        sessions = json.loads(sessions_path.read_text())
    except Exception:
        return "", ""

    best_channel, best_target, best_ts = "", "", 0
    for key, info in sessions.items():
        # Only consider direct/group Sentinel sessions, skip meta keys like "agent:sentinel:main"
        parts = key.split(":")
        if len(parts) < 5 or parts[0] != "agent" or parts[1] != "sentinel":
            continue
        channel = info.get("lastChannel") or parts[2]
        if not channel:
            continue
        last_to = info.get("lastTo") or ""
        # lastTo format: "telegram:8755477259" or "line:Ue1a63b..." or "line:group:C93ba..."
        # Strip the leading "<channel>:" prefix to get the bare target
        prefix = f"{channel}:"
        target = last_to[len(prefix):] if last_to.startswith(prefix) else last_to
        if not target:
            continue
        ts = info.get("updatedAt") or 0
        if ts > best_ts:
            best_ts = ts
            best_channel, best_target = channel, target
    return best_channel, best_target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", required=True, dest="type_name",
                        help="偵測類別：火煙偵測 / 異常人流 / 異常氣候 / 人員闖入")
    parser.add_argument("--describe", action="store_true",
                        help="詳細敘述模式：重新分析影片並回傳詳細事發描述（不寫入 DB）")
    parser.add_argument("--channel", type=int, default=None,
                        help="指定 channel ID，describe 模式下只分析該頻道對應的影片")
    parser.add_argument("--notify-channel", dest="notify_channel", default="",
                        help="Channel to send text summary (e.g. telegram, line)")
    parser.add_argument("--notify-target", dest="notify_target", default="",
                        help="Recipient ID for text summary (Telegram user id or LINE user/group id)")
    args = parser.parse_args()

    # Session state is authoritative: override any agent-supplied values when
    # the most recent session resolves successfully. The agent often passes
    # senderId in group chats, which would push videos to the user's DM
    # instead of the group; the session's lastTo has the correct routing.
    auto_channel, auto_target = resolve_active_session()
    if auto_channel and auto_target:
        args.notify_channel = auto_channel
        args.notify_target = auto_target
    else:
        if not args.notify_channel:
            args.notify_channel = auto_channel
        if not args.notify_target:
            args.notify_target = auto_target

    if args.type_name not in TYPE_MAP:
        available = sorted({v["prefix"] for v in TYPE_MAP.values()})
        print(json.dumps({
            "ok": False,
            "error": f"Unknown type: {args.type_name}",
            "available_types": available,
            "config_dir": str(EVENT_TYPES_DIR),
        }, ensure_ascii=False))
        sys.exit(1)

    # 建立 video 路徑 → channel_id 對照表
    _path_to_ch: dict[str, int] = {}
    try:
        from database import StreamSourceDatabase as _SSD
        for _url, _cid in _SSD().get_stream_sources_with_channel_ids():
            _path_to_ch[str(Path(_url).resolve())] = _cid
    except Exception:
        pass

    def _video_label(video_path: str) -> str:
        stem = Path(video_path).stem
        cid = _path_to_ch.get(str(Path(video_path).resolve()))
        return f"ch{cid} {stem}" if cid is not None else stem

    cfg = TYPE_MAP[args.type_name]
    type_id = cfg["type_id"]
    prefix = cfg["prefix"]
    valid_classes = cfg["classes"]
    prompt = cfg["prompt"]
    default_class = valid_classes[0]

    videos = sorted(VIDEO_DIR.glob(f"{prefix}*"))
    if not videos:
        print(json.dumps({"ok": False, "error": f"找不到影片：{VIDEO_DIR}/{prefix}*"}, ensure_ascii=False))
        sys.exit(1)

    # --channel 指定時，過濾只保留該頻道對應的影片
    if args.channel is not None:
        ch_to_path = {cid: Path(url) for url, cid in _path_to_ch.items()}
        target_path = ch_to_path.get(args.channel)
        if target_path is None:
            print(json.dumps({"ok": False, "error": f"找不到 channel {args.channel} 對應的影片"}, ensure_ascii=False))
            sys.exit(1)
        videos = [v for v in videos if v.resolve() == target_path.resolve()]
        if not videos:
            print(json.dumps({"ok": False, "error": f"channel {args.channel} 不屬於類型 {args.type_name}"}, ensure_ascii=False))
            sys.exit(1)

    # ── 詳細敘述模式 ──────────────────────────────────────────────────────────
    if args.describe:
        descriptions = []
        for video in videos:
            try:
                frames, _, _ = extract_frames_1fps(str(video), fps=0.5)
            except Exception as e:
                descriptions.append({"error": f"抽幀失敗: {e}"})
                continue
            if not frames:
                descriptions.append({"error": "無法從影片抽取任何幀"})
                continue
            try:
                import re
                raw = ask_vlm(frames, DESCRIBE_PROMPT, prefill="監控畫面中，", max_tokens=300, max_frames=4)
                raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
                descriptions.append({"description": raw})
            except Exception as e:
                descriptions.append({"error": f"VLM 失敗: {e}"})
        print(json.dumps({
            "ok": True,
            "type": args.type_name,
            "descriptions": descriptions,
        }, ensure_ascii=False, indent=2))
        return

    events = []
    for video in videos:
        video_str = str(video)
        entry = {"video": video.name, "class": None, "description": None,
                 "event_id": None, "error": None}

        try:
            frames, duration, thumb_path = extract_frames_1fps(video_str, fps=0.5)
        except Exception as e:
            entry["error"] = f"抽幀失敗: {e}"
            events.append(entry)
            continue

        if not frames:
            entry["error"] = "無法從影片抽取任何幀"
            events.append(entry)
            continue

        try:
            vlm_text = ask_vlm(frames, prompt)
        except Exception as e:
            entry["error"] = f"VLM 失敗: {e}"
            events.append(entry)
            continue

        cls, desc = parse_vlm_response(
            vlm_text, valid_classes, default_class,
            guards=cfg.get("output_guards"),
        )
        class_id = cfg["class_ids"].get(cls, 0)
        image_url = upload_image(thumb_path) if thumb_path else None
        ch_id = _path_to_ch.get(str(Path(video_str).resolve()), 0)

        try:
            key_time = duration / 2.0 if duration else None
            event_id = insert_event(type_id, class_id, desc, video_str, image_url, thumb_path, key_time=key_time, channel_id=ch_id)
        except Exception as e:
            entry["error"] = f"DB 寫入失敗: {e}"
            entry.update({"class": cls, "description": desc})
            events.append(entry)
            continue
        finally:
            if thumb_path:
                try:
                    os.remove(thumb_path)
                except Exception:
                    pass

        entry.update({
            "class": cls, "description": desc,
            "event_id": event_id,
        })
        events.append(entry)
        # 每筆分析完立即發送，不等其他影片
        if args.notify_channel and args.notify_target:
            label = _video_label(video_str)
            caption = f"{label}｜{cls}：{desc}"
            clip_path = str(WORKSPACE_ROOT / "event_data" / f"{event_id}_cam{ch_id}_v.mp4")
            send_video_notification(args.notify_channel, args.notify_target,
                                    clip_path, caption=caption, preview_url=image_url or "")

    ok_events = [e for e in events if e["error"] is None]

    print(json.dumps({
        "ok": True,
        "type": args.type_name,
        "type_id": type_id,
        "videos_analyzed": len(videos),
        "events_recorded": len(ok_events),
        "events": events,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
