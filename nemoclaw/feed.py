#!/usr/bin/env python3
"""模擬 live:依牆鐘計算播放頭,抽當前幀。"""
import os, time, json, subprocess

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
    - live 串流(rtsp/http(s)):直接抓當前幀(不用 playhead、抓完即關,省資源)。"""
    is_stream = str(video_path).lower().startswith(("rtsp://", "http://", "https://"))
    if is_stream:
        cmd = ["ffmpeg", "-y", "-i", video_path, "-frames:v", "1",
               "-vf", f"scale={scale}:-1", "-q:v", "3", out_path]
    else:
        if second is None:
            second = playhead(video_duration(video_path))
        cmd = ["ffmpeg", "-y", "-ss", str(second), "-i", video_path,
               "-frames:v", "1", "-vf", f"scale={scale}:-1", "-q:v", "3", out_path]
    subprocess.run(cmd, capture_output=True, timeout=30)
    return out_path if os.path.exists(out_path) else None
