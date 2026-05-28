#!/usr/bin/env python3
"""健康監測 watchdog:探測核心服務(Nemotron / LocateAnything / NemoClaw)健康。

供 dashboard 即時顯示與降級判斷。CLI 模式會把健康變化記入 health.jsonl;
服務重新可用時記錄 recovered 狀態，實際重啟由服務管理機制負責。"""
import datetime
import json
import os
import sys
import time
import urllib.request


def _services():
    """Probe the perception backend chosen by NEMOCLAW_PERCEPTION (default: locate).
    Dashboard health key is "falcon" for back-compat (label is now LocateAnything)."""
    perception = os.environ.get("NEMOCLAW_PERCEPTION", "locate")
    if perception == "falcon":
        peri = os.environ.get("FALCON_PERCEPTION_SERVER", "http://127.0.0.1:18793").rstrip("/")
    else:
        peri = os.environ.get("LOCATE_ANYTHING_SERVER", "http://127.0.0.1:18794").rstrip("/")
    hermes = os.environ.get("NEMOCLAW_HERMES_URL", "http://127.0.0.1:8642/v1/chat/completions")
    hermes_models = hermes.replace("/v1/chat/completions", "/v1/models")
    vlm = os.environ.get("VLM_API_URL", "http://127.0.0.1:31010/v1/chat/completions")
    vlm_models = vlm.replace("/v1/chat/completions", "/v1/models")
    return [
        ("nemotron", os.environ.get("VLM_HEALTH_URL", vlm_models)),
        ("falcon", peri + "/health"),
        ("nemoclaw", hermes_models),
    ]


def _probe(url, timeout=12):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=timeout) as r:
            return 200 <= getattr(r, "status", 200) < 500
    except Exception:
        return False


def service_health(services=None, probe=_probe):
    services = services if services is not None else _services()
    return {name: ("up" if probe(url) else "down") for name, url in services}


def healthy(health=None):
    health = health if health is not None else service_health()
    return bool(health) and all(v == "up" for v in health.values())


def health_log_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "health.jsonl")


def _record_transition(prev, cur, path=None):
    """只在健康狀態改變時記一筆(degrade/recovered),避免洗檔。回傳是否有記。"""
    if prev == cur:
        return False
    path = path or health_log_path()
    rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
           "health": cur, "healthy": healthy(cur),
           "event": "recover" if healthy(cur) else "degrade"}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return True


def main():
    interval = int(os.environ.get("NEMOCLAW_WATCHDOG_INTERVAL", "30"))
    once = "--once" in sys.argv
    prev = None
    while True:
        cur = service_health()
        _record_transition(prev, cur, )
        prev = cur
        print(json.dumps({"healthy": healthy(cur), **cur}, ensure_ascii=False))
        if once:
            break
        time.sleep(interval)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
