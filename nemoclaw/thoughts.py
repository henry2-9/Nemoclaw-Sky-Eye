#!/usr/bin/env python3
"""Agent 第一人稱思考流:把 sweep / 自學基線 / 自我初始任務 / 投票決策等
關鍵時刻的「我現在在想什麼」寫進 thoughts.jsonl。dashboard 把最近 N 條
攤成 ticker,讓「自主性」看得見,而不是只是一個黑盒在跑腳本。"""
import datetime
import json
import os

_MAX_KEEP = 500   # 滾動上限,避免檔案無限漲


def _path():
    return os.environ.get(
        "NEMOCLAW_THOUGHTS_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "thoughts.jsonl"),
    )


def record(text, source="agent", ts=None):
    """寫一條思考。source ∈ sweep/baseline/curiosity/investigate/decision/watchdog/briefing。"""
    if not text:
        return
    p = _path()
    rec = {"ts": (ts or datetime.datetime.now()).isoformat(timespec="seconds") if not isinstance(ts, str) else ts,
           "source": source, "text": str(text)[:240]}
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _rotate(p)
    except Exception:
        pass


def _rotate(p, keep=_MAX_KEEP):
    try:
        with open(p, encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > keep * 1.4:
            with open(p, "w", encoding="utf-8") as f:
                f.writelines(lines[-keep:])
    except Exception:
        pass


def latest(n=12):
    p = _path()
    if not os.path.exists(p):
        return []
    out = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f.readlines()[-n:]:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return out
