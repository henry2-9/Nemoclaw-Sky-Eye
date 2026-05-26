import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import thoughts as th


def test_record_and_latest(tmp_path, monkeypatch):
    monkeypatch.setenv("NEMOCLAW_THOUGHTS_PATH", str(tmp_path / "t.jsonl"))
    th.record("掃 ch5", source="sweep")
    th.record("ch5 確認 high", source="investigate")
    th.record("ch5 ALLOW notify", source="decision")
    items = th.latest(10)
    assert len(items) == 3
    assert items[-1]["text"].startswith("ch5 ALLOW")
    assert {i["source"] for i in items} == {"sweep", "investigate", "decision"}


def test_rotate_caps_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("NEMOCLAW_THOUGHTS_PATH", str(tmp_path / "t.jsonl"))
    for i in range(800):
        th.record(f"思考 {i}")
    lines = open(tmp_path / "t.jsonl", encoding="utf-8").readlines()
    assert len(lines) <= 600   # 500 cap + 1.4× rotate trigger


def test_record_empty_noops(tmp_path, monkeypatch):
    monkeypatch.setenv("NEMOCLAW_THOUGHTS_PATH", str(tmp_path / "t.jsonl"))
    th.record("")
    assert not os.path.exists(tmp_path / "t.jsonl")
