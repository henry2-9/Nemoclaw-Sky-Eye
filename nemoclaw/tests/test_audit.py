import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import audit

def test_append_writes_jsonl_line():
    path = os.path.join(tempfile.mkdtemp(), "audit.jsonl")
    audit.append({"decision": "ALLOW", "channel": "7"}, jsonl_path=path)
    audit.append({"decision": "BLOCK", "channel": "5"}, jsonl_path=path)
    lines = open(path, encoding="utf-8").read().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["decision"] == "ALLOW"
    assert "ts_iso" in json.loads(lines[0])  # 自動加時間戳
