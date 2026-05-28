#!/usr/bin/env python3
"""每相機自學基線:把每個 (channel, key) 最近 N 次 LocateAnything count 滑動視窗存起來,
agent 自己學「這個鏡頭平常多少人」,偏離才警示——取代靜態門檻,讓 sweep
看起來像在「適應現場」,不是查表。"""
import json
import os

_WINDOW = 20
_MIN_FOR_BASELINE = 4   # 樣本太少時 fallback 到保底門檻


def _path():
    return os.environ.get(
        "NEMOCLAW_BASELINE_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline.jsonl"),
    )


def _load():
    p = _path()
    if not os.path.exists(p):
        return {}
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}


def _save(state):
    p = _path()
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception:
        pass


def update_and_check(channel, key, count, floor=2):
    """更新滑動視窗,判斷此次 count 是否超出歷史(spike)。
    回 (is_anomaly, baseline_max_before)。
    冷啟動(樣本 <_MIN_FOR_BASELINE)用保底門檻 floor;否則 count > history_max 才算異常。"""
    state = _load()
    k = f"{channel}|{key}"
    samples = list(state.get(k, []))
    baseline_max = max(samples) if samples else 0
    count = int(count or 0)
    if len(samples) < _MIN_FOR_BASELINE:
        is_anomaly = count >= floor
    else:
        is_anomaly = count > baseline_max and count >= floor
    samples.append(count)
    if len(samples) > _WINDOW:
        samples = samples[-_WINDOW:]
    state[k] = samples
    _save(state)
    return is_anomaly, baseline_max


def baseline_summary(channel, key):
    """供 thoughts 描述用:回 (n_samples, max, median) 摘要。"""
    samples = _load().get(f"{channel}|{key}", [])
    if not samples:
        return (0, 0, 0)
    s = sorted(samples)
    med = s[len(s) // 2]
    return (len(s), max(s), med)
