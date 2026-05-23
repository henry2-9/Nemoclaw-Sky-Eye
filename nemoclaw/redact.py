#!/usr/bin/env python3
"""PII 馬賽克:對指定 bbox 高斯模糊;face 偵測用 OpenCV Haar(自帶,離線可用)。"""
import os, cv2

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
