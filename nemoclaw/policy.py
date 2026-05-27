#!/usr/bin/env python3
"""NemoClaw 政策閘純決策邏輯。evaluate() 回傳 decision dict。"""
import re, datetime

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

def detect_injection(text, patterns):
    if not text:
        return []
    return [p for p in patterns if re.search(p, text, flags=re.IGNORECASE)]

def _in_quiet_hours(now, q):
    start = datetime.time(*map(int, q["start"].split(":")))
    end = datetime.time(*map(int, q["end"].split(":")))
    t = now.time()
    return (start <= t or t < end) if start > end else (start <= t < end)

def evaluate(incident, policy, recent, now=None):
    now = now or datetime.datetime.now()
    g, pr, gr, rs = policy["gating"], policy["privacy"], policy["grounding"], policy["resource"]
    reasons, hits = [], []

    cheap_text = incident.get("cheap_text", "") or " ".join(
        str(e.get("finding", "")) for e in incident.get("evidence_citations", []))
    injection = bool(detect_injection(cheap_text, gr.get("injection_patterns", [])))
    if injection:
        hits.append("injection_detected→stripped (content treated as evidence only)")

    out = {"decision": "ALLOW", "actions": [], "channels": [],
           "reasons": reasons, "policy_hits": hits, "injection_detected": injection}

    # ③ 接地:無證據引用 → abstain
    if gr.get("require_citations") and not incident.get("evidence_citations"):
        out.update(decision="ABSTAIN", reasons=reasons + ["missing evidence citations"])
        return out

    # ① 信心門檻
    if incident.get("confidence", 0) < g["confidence_threshold"]:
        out.update(decision="BLOCK", reasons=reasons + [
            f"confidence {incident.get('confidence')} < {g['confidence_threshold']}"])
        return out

    # ① 去重:severity 升級不是重複事件;尤其 critical 不可被早先低嚴重度告警壓掉。
    win = g["dedup_window_seconds"]
    for r in recent:
        if (str(r.get("channel")) == str(incident.get("channel"))
                and r.get("event_type") == incident.get("event_type")
                and (now.timestamp() - r.get("ts", 0)) <= win):
            incoming = SEVERITY_RANK.get(incident.get("severity"), 0)
            previous = SEVERITY_RANK.get(r.get("severity"), -1)
            if incoming > previous:
                reasons.append(
                    f"severity escalation bypassed dedup: {r.get('severity', 'unknown')}→{incident.get('severity')}")
                hits.append("severity_escalation")
                break
            out.update(decision="DEDUP", reasons=reasons + [f"duplicate within {win}s"])
            return out

    # ① severity 路由
    route = g["severity_routing"].get(incident.get("severity", "low"), {"actions": ["log"]})
    actions = list(route.get("actions", ["log"]))
    channels = list(route.get("channels", []))

    # ① allowlist
    actions = [a for a in actions if a in g["action_allowlist"]]

    # ④ 安靜時段:非允許 severity → 僅 log
    q = rs.get("quiet_hours")
    if q and _in_quiet_hours(now, q) and incident.get("severity") not in q.get("allow_severity", []):
        actions, channels = ["log"], []
        reasons.append("quiet hours → log only")

    # ④ rate limit(高上限保險;critical 永遠穿透,超量非 critical → RATE_LIMITED 只記 log)
    rl = rs.get("max_notifications_per_hour")
    if rl and "notify" in actions and incident.get("severity") != "critical":
        recent_notifs = sum(1 for r in recent
                            if "notify" in (r.get("actions") or [])
                            and (now.timestamp() - r.get("ts", 0)) <= 3600)
        if recent_notifs >= int(rl):
            actions = [a for a in actions if a == "log"] or ["log"]
            channels = []
            reasons.append(f"RATE_LIMITED: >{rl} notifications/hr (non-critical)")
            hits.append("rate_limited")

    out.update(actions=actions, channels=channels, reasons=reasons)
    return out
