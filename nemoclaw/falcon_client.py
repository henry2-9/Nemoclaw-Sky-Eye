#!/usr/bin/env python3
"""Perception 客戶端 — sweep cheap-gate 的偵測後端。

預設後端:**NVIDIA LocateAnything-3B**(transformers 常駐 server @ :18794,
contract 同 Falcon `/infer`,vLLM 不支援此 custom architecture)。

備援後端:Falcon Perception(OWL-ViT @ :18793),env `NEMOCLAW_PERCEPTION=falcon` 切回。

對外 API 不變:
    detect(image_path, query, task="detection") -> {"counts": {<cat>: <n>, ...}}
"""
import json
import os
import urllib.request


PERCEPTION_BACKEND = os.environ.get("NEMOCLAW_PERCEPTION", "locate")

LOCATE_SERVER = os.environ.get("LOCATE_ANYTHING_SERVER", "http://127.0.0.1:18794")
FALCON_SERVER = os.environ.get("FALCON_PERCEPTION_SERVER", "http://127.0.0.1:18793")


def _post_infer(server_url, payload, timeout):
    req = urllib.request.Request(
        f"{server_url.rstrip('/')}/infer",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _locate_detect(image_path, query, server_url=None, timeout=120):
    server_url = server_url or LOCATE_SERVER
    try:
        return _post_infer(server_url, {"image_path": image_path, "query": query}, timeout)
    except Exception:
        return None


def _falcon_detect(image_path, query, task="detection", server_url=None, timeout=120):
    server_url = server_url or FALCON_SERVER
    try:
        return _post_infer(server_url,
                           {"image_path": image_path, "query": query, "task": task},
                           timeout)
    except Exception:
        return None


def detect(image_path, query, task="detection", server_url=None, timeout=120):
    """Sweep cheap-gate 的對外入口。後端由 NEMOCLAW_PERCEPTION env 控制。"""
    if PERCEPTION_BACKEND == "falcon":
        return _falcon_detect(image_path, query, task=task,
                              server_url=server_url, timeout=timeout)
    return _locate_detect(image_path, query, server_url=server_url, timeout=timeout)
