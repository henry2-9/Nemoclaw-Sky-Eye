#!/usr/bin/env python3
"""
sentinel-analyze-video — 分析 Sentinel 頻道影片，或擷取指定秒數的幀
用法:
  sentinel-analyze-video --channel <id|name> --question <問題> [--fps <n>] [--max-tokens <n>]
  sentinel-analyze-video --channel <id|name> --extract-frame <秒數>
輸出: JSON
"""
import argparse
import base64
import json
import math
import os
import subprocess
import sys
import urllib.request
import urllib.parse
from pathlib import Path

WORKSPACE_ROOT = Path(os.environ.get("SENTINEL_WORKSPACE", os.path.expanduser("~/sentinel-workspace"))).resolve()
os.chdir(WORKSPACE_ROOT)
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

API_URL   = os.environ.get("VLM_API_URL",   "http://127.0.0.1:1234/v1/chat/completions")
API_KEY   = os.environ.get("VLM_API_KEY",   "lmstudio")
MODEL     = os.environ.get("VLM_MODEL",     "qwen3.6-35b-a3b")
PICTSHARE_URL = os.environ.get("PICTSHARE_URL", "").rstrip("/")
PICTSHARE_UPLOAD_CODE = os.environ.get("PICTSHARE_UPLOAD_CODE", "YourSecretCode123")


# ── Pictshare 上傳 ────────────────────────────────────────────────────────────

def upload_image(path: str) -> str | None:
    try:
        import urllib.request as ur
        import urllib.parse as up
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

        req = ur.Request(
            f"{PICTSHARE_URL}/api/upload.php",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with ur.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        # 優先用 hash 組合正確 URL，pictshare 回傳的 url 欄位可能缺 domain
        h = data.get("hash") or ""
        if h:
            return f"{PICTSHARE_URL}/{h.lstrip('/')}"
        raw = data.get("url") or ""
        if raw.startswith("http://") and raw.count("/") <= 3:
            # 修正 "http:///xxx.jpg" → 加上正確 domain
            filename = raw.rsplit("/", 1)[-1]
            return f"{PICTSHARE_URL}/{filename}"
        if raw.startswith("http"):
            return raw
        return f"{PICTSHARE_URL}/{raw.lstrip('/')}" if raw else None
    except Exception:
        return None


# ── 影片處理 ──────────────────────────────────────────────────────────────────

def get_video_info(path: str):
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", path],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            duration = float(s.get("duration", 0) or 0)
            r = s.get("avg_frame_rate", "25/1")
            num, den = r.split("/")
            src_fps = float(num) / float(den) if float(den) else 25.0
            return duration, src_fps
    raise ValueError(f"找不到影片串流: {path}")


def extract_one_frame(source: str, second: float) -> str | None:
    """擷取影片第 second 秒的幀，回傳暫存路徑"""
    out = f"/tmp/sentinel_frame_at_{int(second)}.jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(second), "-i", source,
         "-frames:v", "1", "-vf", "scale=1280:-1", "-q:v", "2", out],
        capture_output=True
    )
    return out if os.path.exists(out) else None


def extract_frames(source: str, fps: float = 1.0, max_frames: int = 120):
    """從影片依 fps 抽幀，回傳 (base64_list, duration)。
    live 串流(rtsp/http(s),無 duration)→ 一次 ffmpeg 抓當前數幀(省連線、不連續解碼)。"""
    is_stream = source.lower().startswith(("rtsp://", "http://", "https://"))
    try:
        duration, _ = get_video_info(source)
    except Exception:
        duration = 0.0
    if is_stream or duration <= 0:
        n = min(max_frames, 4)
        tmpl = "/tmp/sentinel_live_%03d.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-i", source, "-vf", "fps=1",
             "-frames:v", str(n), "-q:v", "3", tmpl],
            capture_output=True, timeout=60
        )
        frames = []
        for i in range(1, n + 1):
            p = tmpl % i
            if os.path.exists(p):
                with open(p, "rb") as f:
                    frames.append(base64.b64encode(f.read()).decode())
                os.remove(p)
        return frames, 0.0
    total = min(math.ceil(duration * fps), max_frames)
    frames = []
    for i in range(total):
        t = i / fps
        out = f"/tmp/sentinel_vframe_{i:05d}.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(t), "-i", source,
             "-frames:v", "1", "-vf", "scale=512:-1", "-q:v", "3", out],
            capture_output=True
        )
        if os.path.exists(out):
            with open(out, "rb") as f:
                frames.append(base64.b64encode(f.read()).decode())
            os.remove(out)
    return frames, duration


# ── VLM 呼叫 ─────────────────────────────────────────────────────────────────

def ask_vlm(frames, question: str, max_tokens: int = 800) -> str:
    user_text = (question or "").strip()

    content = [{"type": "text", "text": user_text}]
    for b64 in frames:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })
    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "user", "content": content},
        ],
        "max_tokens": max_tokens,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        API_URL, data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {API_KEY}"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = json.load(resp)["choices"][0]["message"]["content"]
    import re
    return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()


# ── 查詢 channel source_url ───────────────────────────────────────────────────

def resolve_channel(channel_input: str):
    from database import StreamSourceDatabase
    db = StreamSourceDatabase()
    if channel_input.strip().isdigit():
        sources = db.get_stream_sources_with_channel_ids()
        match = next(((url, cid) for url, cid in sources
                      if str(cid) == channel_input.strip()), None)
    else:
        ch = db.get_channel_by_name(channel_input.strip())
        match = (ch["source_url"], ch.get("channel_id")) if ch else None
    return match


# ── 主程式 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", required=True, help="頻道 ID 或名稱")
    parser.add_argument("--question", default="請描述這段影片中發生了什麼事？",
                        help="要問 VLM 的問題（分析模式用）")
    parser.add_argument("--fps", type=float, default=1.0, help="每秒抽幾幀（預設 1）")
    parser.add_argument("--max-frames", type=int, default=120, help="最多抽幾幀（預設 120）")
    parser.add_argument("--max-tokens", type=int, default=800, help="VLM 最大 token 數")
    parser.add_argument("--extract-frame", type=float, default=None,
                        metavar="SECOND",
                        help="擷取指定秒數的幀並上傳，回傳圖片 URL（不呼叫 VLM）")
    args = parser.parse_args()

    # 查 channel
    try:
        match = resolve_channel(args.channel)
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"資料庫查詢失敗: {e}"}, ensure_ascii=False))
        sys.exit(1)

    if not match:
        print(json.dumps({"ok": False, "error": f"找不到頻道: {args.channel}"}, ensure_ascii=False))
        sys.exit(1)

    source_url, channel_id = match

    is_stream = source_url.lower().startswith(("rtsp://", "http://", "https://"))
    if not is_stream and not os.path.exists(source_url):
        print(json.dumps({"ok": False, "error": f"影片檔案不存在: {source_url}"}, ensure_ascii=False))
        sys.exit(1)

    # ── 模式一：擷取單幀並上傳 ──────────────────────────────────────────────
    if args.extract_frame is not None:
        frame_path = extract_one_frame(source_url, args.extract_frame)
        if not frame_path:
            print(json.dumps({"ok": False, "error": f"無法擷取第 {args.extract_frame} 秒的幀"}, ensure_ascii=False))
            sys.exit(1)

        public_url = upload_image(frame_path)
        # 保留本地檔案供 sentinel-perception --image 使用（不刪除）

        print(json.dumps({
            "ok": True,
            "channel_id": channel_id,
            "source_url": source_url,
            "second": args.extract_frame,
            "local_path": frame_path,
            "image_url": public_url or "(上傳失敗)",
        }, ensure_ascii=False, indent=2))
        return

    # ── 模式二：分析影片 ────────────────────────────────────────────────────
    try:
        frames, duration = extract_frames(source_url, args.fps, args.max_frames)
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"抽幀失敗: {e}"}, ensure_ascii=False))
        sys.exit(1)

    if not frames:
        print(json.dumps({"ok": False, "error": "無法從影片抽取任何幀"}, ensure_ascii=False))
        sys.exit(1)

    try:
        answer = ask_vlm(frames, args.question, args.max_tokens)
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"VLM 呼叫失敗: {e}"}, ensure_ascii=False))
        sys.exit(1)

    print(json.dumps({
        "ok": True,
        "channel_id": channel_id,
        "source_url": source_url,
        "duration_sec": round(duration, 1),
        "frames_analyzed": len(frames),
        "fps": args.fps,
        "question": args.question,
        "answer": answer,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
