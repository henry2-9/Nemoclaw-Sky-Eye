#!/usr/bin/env python3
"""模擬 live:依牆鐘計算播放頭,抽當前幀。
YouTube URL 自動透過 yt-dlp 解成可放的 HLS(10 分快取),供 ffmpeg 抓幀。"""
import os, time, json, subprocess

_YT_TTL = 600       # 10 分鐘快取(YouTube HLS 通常 ~6h 內有效,保守取)
_YT_CACHE = {}      # url -> (resolved_hls, expires_at)


def _is_youtube(url):
    s = str(url or "").lower()
    return ("youtube.com" in s) or ("youtu.be" in s)


def resolve_url(url):
    """YouTube → yt-dlp 取 HLS;非 YouTube 原樣回傳。解析失敗回 None。"""
    if not _is_youtube(url):
        return url
    now = time.time()
    cached = _YT_CACHE.get(url)
    if cached and cached[1] > now:
        return cached[0]
    try:
        r = subprocess.run(["yt-dlp", "-g", url],
                           capture_output=True, text=True, timeout=20)
        out = (r.stdout or "").strip().splitlines()
        if out and out[0].startswith("http"):
            _YT_CACHE[url] = (out[0], now + _YT_TTL)
            return out[0]
    except Exception:
        pass
    return None

def playhead(duration, now=None, start=0.0):
    if duration <= 0:
        return 0.0
    now = time.time() if now is None else now
    return (now - start) % duration

def video_duration(path):
    r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json",
                        "-show_format", path], capture_output=True, text=True)
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0

def grab_frame(video_path, out_path, second=None, scale=512):
    """抽一幀到 out_path。
    - 本地檔:依 second(預設=當前 playhead)抽幀。
    - live 串流(rtsp/http(s)):直接抓當前幀(不用 playhead、抓完即關,省資源)。
    - YouTube URL:先用 yt-dlp 解 HLS(快取 10 分),解析失敗回 None。"""
    real_path = resolve_url(video_path)
    if real_path is None:
        return None
    is_stream = str(real_path).lower().startswith(("rtsp://", "http://", "https://"))
    if is_stream:
        cmd = ["ffmpeg", "-y", "-i", real_path, "-frames:v", "1",
               "-vf", f"scale={scale}:-1", "-q:v", "3", out_path]
    else:
        if second is None:
            second = playhead(video_duration(real_path))
        cmd = ["ffmpeg", "-y", "-ss", str(second), "-i", real_path,
               "-frames:v", "1", "-vf", f"scale={scale}:-1", "-q:v", "3", out_path]
    subprocess.run(cmd, capture_output=True, timeout=40)
    return out_path if os.path.exists(out_path) else None


def capture_stream_clip(video_path, out_path, duration=4, scale=960):
    """從 live 來源在候選觸發當下開始保存短片，供後續事件證據使用。"""
    real_path = resolve_url(video_path)
    if real_path is None or not str(real_path).lower().startswith(("rtsp://", "http://", "https://")):
        return None
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", real_path,
        "-t", str(float(duration)), "-vf", f"scale={scale}:-1",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
        "-an", "-movflags", "+faststart", out_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=float(duration) + 45)
    except Exception:
        return None
    return out_path if os.path.exists(out_path) and os.path.getsize(out_path) > 0 else None
