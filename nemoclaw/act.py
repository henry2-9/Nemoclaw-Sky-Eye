#!/usr/bin/env python3
"""政策閘核心:incident → policy.evaluate → (放行則 PII 馬賽克 + 通知) → 稽核。"""
import os, datetime, yaml
import policy, redact, audit, notify
import flight_recorder
import media
import thoughts as _thoughts

EVENT_TYPE_IDS = {
    "fire_smoke": 4,
    "abnormal_crowd": 5,
    "abnormal_weather": 6,
    "intrusion": 7,
    "traffic": 8,
    "security_anomaly": 9,
}

def load_policy(path=None):
    path = path or os.path.join(os.path.dirname(__file__), "policy.yaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

def _notification_text(incident, decision):
    sev = incident.get("severity", "").upper()
    text = f"🚨【{sev}】{incident.get('channel')} {incident.get('event_type')}\n{incident.get('summary','')}"
    if decision.get("escalated"):
        text = "🔴 二級升級(escalate)\n" + text
    if decision["injection_detected"]:
        text += "\n⚠️ 已偵測並忽略畫面內注入指令"
    artifacts = decision.get("media_artifacts") or {}
    urls = artifacts.get("urls") or {}
    if urls.get("trace"):
        text += f"\n事件頁: {urls['trace']}"
    if urls.get("clip"):
        text += f"\n錄影切片: {urls['clip']}"
    if urls.get("falcon_annotated"):
        text += f"\n感知標記圖: {urls['falcon_annotated']}"
    return text


def _persist_event(incident, decision):
    """Persist confirmed incidents to the selected event store when enabled."""
    if os.environ.get("NEMOCLAW_EVENT_STORE_ENABLED", "0") != "1":
        return None
    import db_factory
    artifacts = decision.get("media_artifacts") or {}
    return db_factory.event_db().insert_event({
        "event_id": incident.get("trace_id"),
        "camera_id": incident.get("channel"),
        "type_id": EVENT_TYPE_IDS.get(incident.get("event_type")),
        "description": incident.get("summary", ""),
        "image_path": artifacts.get("frame_path"),
        "clip_path": artifacts.get("clip_path"),
        "event_time": datetime.datetime.fromtimestamp(decision["ts"]).isoformat(timespec="seconds"),
        "metadata": {
            "severity": incident.get("severity"),
            "confidence": incident.get("confidence"),
            "decision": decision.get("decision"),
            "actions": decision.get("actions"),
            "governed_by": decision.get("governed_by"),
            "trigger_origin": decision.get("trigger_origin"),
            "urls": artifacts.get("urls") or {},
        },
    })

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
    decision["trigger_origin"] = incident.get("trigger_origin", "scheduled")
    decision["approval_required"] = bool(incident.get("approval_required", False))
    decision["redacted"] = False
    decision["notification_sent"] = False
    decision["media_artifacts"] = {}
    # 自主分級處置(由 NemoClaw 政策路由,無人核准):escalate=二級升級、report=自動產報告
    allow = decision["decision"] == "ALLOW"
    decision["escalated"] = allow and "escalate" in decision["actions"]
    decision["report_path"] = None

    if allow and os.environ.get("NEMOCLAW_MEDIA_ENABLED", "1") != "0":
        try:
            decision["media_artifacts"] = media.prepare_event_media(incident)
        except Exception as e:
            decision["reasons"].append(f"media artifact failed: {e}")

    if allow and "report" in decision["actions"]:
        try:
            import report
            decision["report_path"] = report.generate_incident_report(incident, decision)
        except Exception as e:
            decision["reasons"].append(f"report failed: {e}")

    if decision["decision"] == "ALLOW" and "notify" in decision["actions"]:
        if os.environ.get("NEMOCLAW_NOTIFY_DISABLED", "0") == "1":
            decision["reasons"].append("notify disabled by NEMOCLAW_NOTIFY_DISABLED")
        else:
            artifacts = decision.get("media_artifacts") or {}
            photo = artifacts.get("notify_photo")            # media 已產生 redacted 圖
            if photo:
                decision["redacted"] = True
            else:                                            # media 關閉 → 退回 sweep 幀並即時馬賽克
                refs = incident.get("media_refs") or []
                src = refs[0] if refs else None
                if src and not pol["privacy"].get("raw_media_egress", False):
                    photo = redact.redact_pii(src); decision["redacted"] = True
                elif src:
                    photo = src
            text = _notification_text(incident, decision)
            try:
                notify.notify_from_env(text, photo_path=photo)
                decision["notification_sent"] = True
            except Exception as e:
                decision["reasons"].append(f"notify failed: {e}")

    decision["event_id"] = None
    if allow:
        try:
            decision["event_id"] = _persist_event(incident, decision)
        except Exception as e:
            decision["reasons"].append(f"event persistence failed: {e}")

    audit.append(decision, jsonl_path=audit_path)
    flight_recorder.record_stage(decision.get("trace_id"), "policy_decision", decision)
    parts = [f"ch{incident.get('channel')} 決策:{decision['decision']}"]
    if decision.get("actions"):
        parts.append(f"動作:{','.join(decision['actions'])}")
    if decision.get("escalated"): parts.append("🔴 二級升級")
    if decision.get("report_path"): parts.append("📄 已產報告")
    if decision.get("injection_detected"): parts.append("⚠ 注入已擋")
    _thoughts.record(" · ".join(parts), source="decision")
    return decision
