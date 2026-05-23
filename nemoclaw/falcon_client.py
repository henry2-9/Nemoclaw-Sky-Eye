#!/usr/bin/env python3
"""Falcon Perception /infer HTTP 客戶端。"""
import os, json, urllib.request

DEFAULT_SERVER = os.environ.get("FALCON_PERCEPTION_SERVER", "http://127.0.0.1:18793")

def detect(image_path, query, task="detection", server_url=None, timeout=120):
    server_url = server_url or DEFAULT_SERVER
    try:
        data = json.dumps({"image_path": image_path, "query": query, "task": task}).encode()
        req = urllib.request.Request(f"{server_url.rstrip('/')}/infer", data=data,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None
