#!/usr/bin/env python3
"""政策閘核心:incident → policy.evaluate → (放行則 PII 馬賽克 + 通知) → 稽核。"""
import os, yaml
import policy, redact, audit, notify

def load_policy(path=None):
    path = path or os.path.join(os.path.dirname(__file__), "policy.yaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

def run(incident, policy_path=None, recent=None, audit_path=None, now=None):
    pol = load_policy(policy_path)
    decision = policy.evaluate(incident, pol, recent=recent or [], now=now)
    decision["channel"] = incident.get("channel")
    decision["event_type"] = incident.get("event_type")
    decision["summary"] = incident.get("summary", "")
    decision["redacted"] = False

    if decision["decision"] == "ALLOW" and "notify" in decision["actions"]:
        photo = None
        media = incident.get("media_refs") or []
        if media and not pol["privacy"].get("raw_media_egress", False):
            photo = redact.redact_pii(media[0])      # ② 外發前馬賽克
            decision["redacted"] = True
        sev = incident.get("severity", "").upper()
        text = f"🚨【{sev}】{incident.get('channel')} {incident.get('event_type')}\n{incident.get('summary','')}"
        if decision["injection_detected"]:
            text += "\n⚠️ 已偵測並忽略畫面內注入指令"
        try:
            notify.notify_from_env(text, photo_path=photo)
        except Exception as e:
            decision["reasons"].append(f"notify failed: {e}")

    audit.append(decision, jsonl_path=audit_path)
    return decision
