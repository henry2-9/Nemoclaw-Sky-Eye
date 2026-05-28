#!/usr/bin/env python3
"""Incident flight recorder.

Records one JSONL row per pipeline stage so demo reviewers can inspect how an
incident moved through sweep, Nemotron, NemoClaw triage, policy, and egress.
Disabled unless NEMOCLAW_FLIGHT_RECORDER=1 to keep unit tests side-effect free.
"""
import datetime
import json
import os
import uuid


STAGE_LABELS = {
    "sweep_selected": "LocateAnything sweep selected candidate",
    "nemotron_question": "Nemotron question built",
    "nemotron_raw_answer": "Nemotron raw answer",
    "nemotron_grading": "Nemotron parsed grading",
    "nemoclaw_triage": "NemoClaw Hermes triage",
    "incident_built": "Incident JSON built",
    "policy_decision": "Policy gate decision",
}


def enabled():
    return os.environ.get("NEMOCLAW_FLIGHT_RECORDER", "0") == "1"


def default_path():
    return os.environ.get(
        "NEMOCLAW_FLIGHT_RECORDER_PATH",
        os.path.join(os.path.dirname(__file__), "flight_recorder.jsonl"),
    )


def new_trace_id(channel, event_type, now=None):
    now = now or datetime.datetime.now()
    return f"{now.strftime('%Y%m%dT%H%M%S')}-ch{channel}-{event_type}-{uuid.uuid4().hex[:8]}"


def _clean(value):
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(k): _clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_clean(v) for v in value]
        return str(value)


def record_stage(trace_id, stage, payload=None, path=None, ts=None):
    if not enabled() or not trace_id:
        return None
    ts = ts or datetime.datetime.now()
    rec = {
        "trace_id": trace_id,
        "stage": stage,
        "label": STAGE_LABELS.get(stage, stage),
        "ts": ts.timestamp(),
        "ts_iso": ts.isoformat(timespec="seconds"),
        "payload": _clean(payload or {}),
    }
    path = path or default_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def load(path=None):
    path = path or default_path()
    if not os.path.exists(path):
        return []
    rows = []
    for line in open(path, encoding="utf-8"):
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def group_by_trace(rows):
    traces = {}
    for row in rows:
        traces.setdefault(row.get("trace_id"), []).append(row)
    return {k: sorted(v, key=lambda r: r.get("ts", 0)) for k, v in traces.items() if k}


def latest_traces(rows, limit=5):
    traces = group_by_trace(rows)
    ordered = sorted(
        traces.items(),
        key=lambda item: max((r.get("ts", 0) for r in item[1]), default=0),
        reverse=True,
    )
    return ordered[:limit]


def compact_payload(payload, width=220):
    text = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= width else text[: width - 3] + "..."


def render_text(trace_id, rows):
    lines = [f"Incident flight recorder: {trace_id}"]
    for i, row in enumerate(sorted(rows, key=lambda r: r.get("ts", 0)), 1):
        lines.append(
            f"{i:02d}. {row.get('ts_iso', '')} | {row.get('stage')} | "
            f"{compact_payload(row.get('payload'))}"
        )
    return "\n".join(lines)
