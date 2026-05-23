#!/usr/bin/env python3
"""稽核軌跡:append jsonl(必)+ mongo(可選,失敗不影響主流程)。"""
import os, json, datetime

def append(record, jsonl_path=None, mongo_collection=None):
    rec = dict(record)
    rec.setdefault("ts_iso", datetime.datetime.now().isoformat(timespec="seconds"))
    jsonl_path = jsonl_path or os.environ.get("NEMOCLAW_AUDIT_PATH",
                                              os.path.join(os.path.dirname(__file__), "audit.jsonl"))
    os.makedirs(os.path.dirname(jsonl_path), exist_ok=True)
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if mongo_collection is not None:
        try:
            mongo_collection.insert_one(dict(rec))
        except Exception:
            pass
    return rec
