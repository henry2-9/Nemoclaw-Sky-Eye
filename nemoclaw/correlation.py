#!/usr/bin/env python3
"""跨地標關聯分析:掃近 N 秒 audit.jsonl,同 event_type 在 ≥2 個不同 channel
觸發 → 視為「全球協同/同源注入」高優先警報。避免重複 alert 用 hash dedup。
寫 correlation_alerts.jsonl 並 push 思考流。"""
import datetime
import hashlib
import json
import os

try:
    from . import thoughts as _thoughts
except Exception:
    import thoughts as _thoughts


WINDOW_SEC = 300
MIN_CHANNELS = 2
DEDUP_TTL = 1800


def _alerts_path():
    return os.environ.get(
        "NEMOCLAW_CORRELATION_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "correlation_alerts.jsonl"),
    )


def _audit_path():
    p = os.environ.get("NEMOCLAW_AUDIT_PATH")
    return p or os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit.jsonl")


def _scan_audit(audit_path, window_sec, now_ts):
    if not audit_path or not os.path.exists(audit_path):
        return []
    rows = []
    try:
        with open(audit_path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                ts = r.get("ts") or 0
                if (now_ts - ts) > window_sec:
                    continue
                if r.get("decision") not in ("ALLOW", "ESCALATE"):
                    continue
                if not r.get("event_type") or r.get("channel") is None:
                    continue
                rows.append(r)
    except Exception:
        return []
    return rows


def _group(rows, min_channels):
    by_type = {}
    for r in rows:
        et = r["event_type"]
        by_type.setdefault(et, []).append(r)
    out = []
    for et, items in by_type.items():
        channels = {}
        for r in items:
            channels.setdefault(str(r["channel"]), r)
        if len(channels) >= min_channels:
            out.append({
                "event_type": et,
                "channels": sorted(channels.keys(), key=lambda x: int(x) if x.isdigit() else 999),
                "evidence": [{
                    "channel": str(r["channel"]),
                    "ts_iso": r.get("ts_iso"),
                    "severity": r.get("severity"),
                    "summary": (r.get("summary") or "")[:120],
                    "trace_id": r.get("trace_id"),
                } for r in sorted(channels.values(), key=lambda x: x.get("ts", 0))],
            })
    return out


def _alert_key(alert):
    raw = alert["event_type"] + "|" + "|".join(alert["channels"])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _recent_dedup_keys(path, ttl, now_ts):
    keys = set()
    if not os.path.exists(path):
        return keys
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if (now_ts - r.get("ts", 0)) <= ttl and r.get("key"):
                    keys.add(r["key"])
    except Exception:
        pass
    return keys


def _append(path, rec):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def scan(window_sec=WINDOW_SEC, min_channels=MIN_CHANNELS, dedup_ttl=DEDUP_TTL, now_ts=None):
    """掃描一次。回新發現的 alerts(已 dedup),並把它們寫入 correlation_alerts.jsonl
    與思考流。同一組 (event_type+channels) 在 dedup_ttl 內不重複 alert。"""
    import time
    now_ts = now_ts or time.time()
    audit_p = _audit_path()
    out_p = _alerts_path()
    rows = _scan_audit(audit_p, window_sec, now_ts)
    if not rows:
        return []
    groups = _group(rows, min_channels)
    if not groups:
        return []
    seen = _recent_dedup_keys(out_p, dedup_ttl, now_ts)
    new_alerts = []
    for g in groups:
        key = _alert_key(g)
        if key in seen:
            continue
        rec = {
            "ts": now_ts,
            "ts_iso": datetime.datetime.fromtimestamp(now_ts).isoformat(timespec="seconds"),
            "key": key,
            "event_type": g["event_type"],
            "channels": g["channels"],
            "channel_count": len(g["channels"]),
            "window_sec": window_sec,
            "evidence": g["evidence"],
            "severity_inferred": "critical" if len(g["channels"]) >= 3 else "high",
        }
        _append(out_p, rec)
        new_alerts.append(rec)
        _thoughts.record(
            f"🌐 跨地標關聯:{rec['channel_count']} 路 {rec['window_sec']}s 內同類事件"
            f"({g['event_type']} · ch {','.join(g['channels'])})— 升級 {rec['severity_inferred']}",
            source="correlation")
    return new_alerts


def latest(n=10):
    p = _alerts_path()
    if not os.path.exists(p):
        return []
    out = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f.readlines()[-n:]:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return list(reversed(out))


if __name__ == "__main__":
    import sys
    alerts = scan()
    print(json.dumps({"new_alerts": len(alerts), "alerts": alerts},
                     ensure_ascii=False, indent=2))
