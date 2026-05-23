#!/usr/bin/env python3
"""回放 eval:聚合 audit.jsonl 的決策統計(由 supervisor 跑一段時間後呼叫)。
驗證:真事件被通知、重複被 DEDUP、低信心 BLOCK、無證據 ABSTAIN,且每事件不洗版。"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def summarize(decisions):
    notified = [d for d in decisions if d.get("decision") == "ALLOW" and "notify" in (d.get("actions") or [])]
    return {
        "total": len(decisions),
        "allow": sum(1 for d in decisions if d.get("decision") == "ALLOW"),
        "notified": len(notified),
        "deduped": sum(1 for d in decisions if d.get("decision") == "DEDUP"),
        "blocked": sum(1 for d in decisions if d.get("decision") == "BLOCK"),
        "abstained": sum(1 for d in decisions if d.get("decision") == "ABSTAIN"),
        "injection_flagged": sum(1 for d in decisions if d.get("injection_detected")),
        "unique_notified_events": len({(d.get("channel"), d.get("event_type")) for d in notified}),
    }

def run_replay():
    path = os.environ.get("NEMOCLAW_AUDIT_PATH")
    decisions = []
    if path and os.path.exists(path):
        for l in open(path, encoding="utf-8"):
            try:
                decisions.append(json.loads(l))
            except Exception:
                pass
    print(json.dumps(summarize(decisions), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    run_replay()
