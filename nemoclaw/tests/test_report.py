import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import report


def test_generate_incident_report_writes_readable_md(tmp_path):
    inc = {
        "trace_id": "t-rep-1", "channel": "5", "event_type": "fire_smoke",
        "severity": "critical", "confidence": 0.95, "summary": "大量濃煙與火焰",
        "governed_by": "nemoclaw-openshell",
        "triage_guardrail": "triage downgrade low->critical ignored: scene text is untrusted",
        "evidence_citations": [{"tool": "sentinel-analyze-video", "finding": "confirmed fire"}],
    }
    dec = {"decision": "ALLOW", "actions": ["log", "notify", "escalate", "report"],
           "injection_detected": True, "governed_by": "nemoclaw-openshell",
           "trigger_origin": "demo_manual", "approval_required": False,
           "media_artifacts": {"urls": {"clip": "http://d/clip.mp4"}}}
    path = report.generate_incident_report(inc, dec, out_dir=str(tmp_path))
    assert os.path.exists(path)
    body = open(path, encoding="utf-8").read()
    assert "事件報告" in body and "CRITICAL" in body
    assert "大量濃煙與火焰" in body
    assert "安全護欄" in body              # guardrail 入報
    assert "注入防禦" in body              # injection 入報
    assert "confirmed fire" in body        # 證據引用
    assert "http://d/clip.mp4" in body     # 媒體連結
    assert "處置無人工核准" in body
    assert "觸發來源:demo_manual" in body
    assert "人工核准流程:不需要" in body
