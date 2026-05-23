#!/usr/bin/env python3
"""確定性自主編排:sweep → 挑選 → Nemotron 確認/分級 → 政策閘。
Nemotron 仍是核心推理(每個候選的確認與分級都由它做);編排由程式碼掌控以求穩定。
純函式可單元測試;run_cycle 以注入式 fn 便於測試。"""
import re, json

EVENT_PRIORITY = {"fire_smoke": 0, "intrusion": 1, "abnormal_crowd": 2, "abnormal_weather": 3}
HAZARD = {
    "fire_smoke": "火災或濃煙",
    "intrusion": "未授權人員闖入",
    "abnormal_crowd": "異常人群聚集或擁擠",
    "abnormal_weather": "異常天候(淹水/強風/倒樹等)",
}

def select_candidates(cands, max_n=4):
    """依事件優先序排序後取前 max_n,控制每輪 Nemotron 推理量。"""
    return sorted(cands, key=lambda c: EVENT_PRIORITY.get(c.get("event_type"), 9))[:max_n]

def build_question(event_type):
    hazard = HAZARD.get(event_type, "異常狀況")
    return (f"畫面中是否確實有{hazard}?只輸出一行 JSON,不要其他文字,格式:"
            '{"confirmed": true 或 false, "confidence": 0到1的數字, '
            '"severity": "low|medium|high|critical", "summary": "繁體中文一句描述與依據"}')

def parse_grading(answer):
    """從 Nemotron 自由文字中抽出評分 JSON;失敗則保守視為未確認。"""
    default = {"confirmed": False, "confidence": 0.0, "severity": "low", "summary": (answer or "")[:120]}
    m = re.search(r"\{.*\}", answer or "", re.DOTALL)
    if not m:
        return default
    try:
        d = json.loads(m.group(0))
    except Exception:
        return default
    sev = d.get("severity", "low")
    try:
        conf = float(d.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    return {
        "confirmed": bool(d.get("confirmed", False)),
        "confidence": max(0.0, min(1.0, conf)),
        "severity": sev if sev in ("low", "medium", "high", "critical") else "low",
        "summary": str(d.get("summary", ""))[:200],
    }

def investigate(candidate, analyze_fn):
    """呼叫 Nemotron 確認+分級;未確認回 None,確認則組 incident。"""
    answer = analyze_fn(candidate["channel"], build_question(candidate["event_type"]))
    g = parse_grading(answer)
    if not g["confirmed"]:
        return None
    return {
        "channel": str(candidate["channel"]),
        "event_type": candidate["event_type"],
        "confidence": g["confidence"],
        "severity": g["severity"],
        "summary": g["summary"],
        "media_refs": [candidate["frame_path"]] if candidate.get("frame_path") else [],
        "evidence_citations": [
            {"tool": "fpg-analyze-video", "finding": g["summary"]},
            {"tool": "nemoclaw-sweep",
             "finding": f"falcon counts {candidate.get('cheap_evidence', {}).get('counts')}"},
        ],
        "cheap_text": candidate.get("cheap_text", ""),
    }

def run_cycle(channels, sweep_fn, analyze_fn, act_fn, max_n=4):
    cands = sweep_fn(channels)
    if not cands:
        return {"candidates": 0, "investigated": 0, "incidents": 0, "results": []}
    selected = select_candidates(cands, max_n)
    results = []
    for c in selected:
        inc = investigate(c, analyze_fn)
        if inc:
            results.append(act_fn(inc))
    return {"candidates": len(cands), "investigated": len(selected),
            "incidents": len(results), "results": results}
