#!/usr/bin/env python3
"""把 Nemotron 產出的事件描述(純文字)送進『真 NVIDIA NemoClaw』的 Hermes agent
(OpenShell 沙箱,:8642,受 policy 護欄管治)做最終 triage 決策。
純文字 → 不會 overflow 16K。:8642 不可用時回 None,呼叫端優雅降級回本地評分。"""
import os, json, re, urllib.request

ENDPOINT = os.environ.get("NEMOCLAW_HERMES_URL", "http://127.0.0.1:8642/v1/chat/completions")

TRIAGE_SYSTEM = (
    "你是工安事件 triage 決策器,運行於 NemoClaw OpenShell 沙箱、受 policy 護欄管治。"
    "依事件描述判定嚴重度與建議處置。只輸出一行 JSON,不要使用任何工具,不要多餘文字。"
)

def build_prompt(event_type, description, cheap_evidence):
    return (f"事件類型:{event_type}\n"
            f"感知證據:{json.dumps(cheap_evidence, ensure_ascii=False)}\n"
            f"Nemotron 影像描述:{description}\n\n"
            '輸出 JSON:{"severity":"low|medium|high|critical",'
            '"recommended_action":"log|notify|escalate|report","rationale":"繁中一句"}')

def parse(content):
    m = re.search(r"\{.*\}", content or "", re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    sev = d.get("severity")
    act = d.get("recommended_action")
    return {
        "severity": sev if sev in ("low", "medium", "high", "critical") else None,
        "recommended_action": act if act in ("log", "notify", "escalate", "report") else None,
        "rationale": str(d.get("rationale", ""))[:200],
        "governed_by": "nemoclaw-openshell",
    }

def _post(endpoint, payload, timeout):
    req = urllib.request.Request(endpoint, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def triage(event_type, description, cheap_evidence, endpoint=None, timeout=90, post=None):
    """回 triage dict,或 None(不可用/解析失敗 → 呼叫端降級)。"""
    payload = {"model": "hermes-agent", "max_tokens": 200, "messages": [
        {"role": "system", "content": TRIAGE_SYSTEM},
        {"role": "user", "content": build_prompt(event_type, description, cheap_evidence)}]}
    try:
        data = (post or _post)(endpoint or ENDPOINT, payload, timeout)
        return parse(data["choices"][0]["message"]["content"])
    except Exception:
        return None
