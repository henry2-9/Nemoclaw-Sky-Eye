#!/usr/bin/env python3
"""PII 馬賽克:對指定 bbox 高斯模糊;face 偵測用 OpenCV Haar(自帶,離線可用)。
另提供 redact_video:逐幀模糊人臉並轉出 browser 友善的 mp4(對外分享用)。"""
import os, subprocess, cv2

def blur_regions(image_path, bboxes, out_path=None):
    img = cv2.imread(image_path)
    for (x1, y1, x2, y2) in bboxes:
        roi = img[y1:y2, x1:x2]
        if roi.size:
            img[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (0, 0), sigmaX=15)
    out_path = out_path or os.path.splitext(image_path)[0] + "_redacted.jpg"
    cv2.imwrite(out_path, img)
    return out_path

def detect_faces(image_path):
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    gray = cv2.cvtColor(cv2.imread(image_path), cv2.COLOR_BGR2GRAY)
    return [(x, y, x + w, y + h) for (x, y, w, h) in
            cascade.detectMultiScale(gray, 1.1, 5)]

def redact_pii(image_path, out_path=None):
    return blur_regions(image_path, detect_faces(image_path), out_path)

def redact_video(in_path, out_path):
    """逐幀模糊人臉 → 轉出 H.264 mp4(對外分享)。失敗回 None,不丟例外。"""
    if not in_path or not os.path.exists(in_path):
        return None
    try:
        cap = cv2.VideoCapture(in_path)
        if not cap.isOpened():
            return None
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        fps = fps if fps and fps > 0 else 12.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if w <= 0 or h <= 0:
            cap.release(); return None
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        tmp = out_path + ".raw.avi"
        vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
        n = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            for (x, y, fw, fh) in cascade.detectMultiScale(gray, 1.1, 5):
                roi = frame[y:y + fh, x:x + fw]
                if roi.size:
                    frame[y:y + fh, x:x + fw] = cv2.GaussianBlur(roi, (0, 0), sigmaX=15)
            vw.write(frame); n += 1
        cap.release(); vw.release()
        if n == 0:
            os.path.exists(tmp) and os.remove(tmp); return None
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp,
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                        "-movflags", "+faststart", out_path],
                       capture_output=True, timeout=180)
        os.path.exists(tmp) and os.remove(tmp)
        return out_path if os.path.exists(out_path) and os.path.getsize(out_path) > 0 else None
    except Exception:
        return None
