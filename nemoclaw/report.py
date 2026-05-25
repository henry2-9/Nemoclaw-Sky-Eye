#!/usr/bin/env python3
"""自主事件報告:agent 確認事件後(政策路由含 'report')自動產出單一事件報告。

無人核准、不查 DB——直接用手上的 incident + decision 產 Markdown 報告,
寫到該事件的 media 目錄。供「agent 會做(不只通知)」的自主閉環。"""
import datetime
import os

_SEV_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _media_root():
    return os.environ.get(
        "NEMOCLAW_MEDIA_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "media_events"),
    )


def generate_incident_report(incident, decision, out_dir=None):
    """產出單一事件 Markdown 報告,回傳檔案路徑。"""
    incident = incident or {}
    decision = decision or {}
    trace = str(incident.get("trace_id") or "unknown")
    out_dir = out_dir or os.path.join(_media_root(), trace)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "incident_report.md")

    sev = str(incident.get("severity", "")).upper()
    cites = incident.get("evidence_citations") or []
    urls = (decision.get("media_artifacts") or {}).get("urls") or {}

    lines = [
        f"# 事件報告 · {sev or 'N/A'} · {incident.get('event_type', '')}",
        "",
        f"- 產生時間:{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 追蹤碼:{trace}",
        f"- 頻道:{incident.get('channel', '')}",
        f"- 嚴重度:{sev or '—'}",
        f"- 信心:{incident.get('confidence', '—')}",
        f"- 治理:{decision.get('governed_by', '—')}",
        f"- 決策:{decision.get('decision', '—')} · 動作:{', '.join(decision.get('actions') or []) or '—'}",
        "",
        "## 摘要",
        incident.get("summary", "") or "—",
    ]
    if incident.get("triage_guardrail"):
        lines += ["", "## 安全護欄", str(incident["triage_guardrail"])]
    if decision.get("injection_detected"):
        lines += ["", "## 注入防禦", "已偵測畫面內注入指令並忽略,依真實視覺判定處置。"]
    if cites:
        lines += ["", "## 證據引用"]
        lines += [f"- {c.get('tool', '')}:{c.get('finding', '')}" for c in cites]
    if urls:
        lines += ["", "## 媒體"]
        lines += [f"- {k}:{urls[k]}" for k in ("clip", "falcon_annotated", "frame", "trace") if urls.get(k)]
    lines += ["", "---", "*本報告由 NemoClaw Sentinel 自動產生,全程無人工介入。*"]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path
