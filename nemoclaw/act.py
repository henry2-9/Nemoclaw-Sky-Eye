#!/usr/bin/env python3
"""政策閘核心:incident → policy.evaluate → (放行則 PII 馬賽克 + 通知) → 稽核。"""
import os, datetime, yaml
import policy, redact, audit, notify
import flight_recorder
import media

def load_policy(path=None):
    path = path or os.path.join(os.path.dirname(__file__), "policy.yaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

def _notification_text(incident, decision):
    sev = incident.get("severity", "").upper()
    text = f"🚨【{sev}】{incident.get('channel')} {incident.get('event_type')}\n{incident.get('summary','')}"
    if decision["injection_detected"]:
        text += "\n⚠️ 已偵測並忽略畫面內注入指令"
    artifacts = decision.get("media_artifacts") or {}
    urls = artifacts.get("urls") or {}
    if urls.get("trace"):
        text += f"\n事件頁: {urls['trace']}"
    if urls.get("clip"):
        text += f"\n錄影切片: {urls['clip']}"
    if urls.get("falcon_annotated"):
        text += f"\nFalcon標記圖: {urls['falcon_annotated']}"
    return text

def run(incident, policy_path=None, recent=None, audit_path=None, now=None):
    pol = load_policy(policy_path)
    now = now or datetime.datetime.now()
    decision = policy.evaluate(incident, pol, recent=recent or [], now=now)
    decision["ts"] = now.timestamp()   # epoch,供跨呼叫去重
    decision["channel"] = incident.get("channel")
    decision["event_type"] = incident.get("event_type")
    decision["trace_id"] = incident.get("trace_id")
    decision["confidence"] = incident.get("confidence")
    decision["severity"] = incident.get("severity")
    decision["summary"] = incident.get("summary", "")
    decision["governed_by"] = incident.get("governed_by", "local")   # local | nemoclaw-openshell
    decision["redacted"] = False
    decision["notification_sent"] = False
    decision["media_artifacts"] = {}

    if decision["decision"] == "ALLOW" and os.environ.get("NEMOCLAW_MEDIA_ENABLED", "1") != "0":
        try:
            decision["media_artifacts"] = media.prepare_event_media(incident)
        except Exception as e:
            decision["reasons"].append(f"media artifact failed: {e}")

    if decision["decision"] == "ALLOW" and "notify" in decision["actions"]:
        if os.environ.get("NEMOCLAW_NOTIFY_DISABLED", "0") == "1":
            decision["reasons"].append("notify disabled by NEMOCLAW_NOTIFY_DISABLED")
        else:
            photo = None
            refs = incident.get("media_refs") or []
            artifacts = decision.get("media_artifacts") or {}
            photo_source = artifacts.get("falcon_annotated_path") or (refs[0] if refs else None)
            if photo_source and not pol["privacy"].get("raw_media_egress", False):
                photo = redact.redact_pii(photo_source)      # ② 外發前馬賽克
                decision["redacted"] = True
            elif photo_source:
                photo = photo_source
            text = _notification_text(incident, decision)
            try:
                notify.notify_from_env(text, photo_path=photo)
                decision["notification_sent"] = True
            except Exception as e:
                decision["reasons"].append(f"notify failed: {e}")

    audit.append(decision, jsonl_path=audit_path)
    flight_recorder.record_stage(decision.get("trace_id"), "policy_decision", decision)
    return decision
