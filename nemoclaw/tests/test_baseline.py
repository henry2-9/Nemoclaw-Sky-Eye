import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import baseline


def test_cold_start_uses_floor(tmp_path, monkeypatch):
    monkeypatch.setenv("NEMOCLAW_BASELINE_PATH", str(tmp_path / "b.jsonl"))
    # 樣本不足(< _MIN_FOR_BASELINE),用保底門檻 floor=2
    is_anom, bmax = baseline.update_and_check(9, "person", 1)
    assert (is_anom, bmax) == (False, 0)
    is_anom, bmax = baseline.update_and_check(9, "person", 2)
    assert is_anom is True            # 達保底
    is_anom, bmax = baseline.update_and_check(9, "person", 1)
    assert is_anom is False


def test_learned_baseline_flags_spike(tmp_path, monkeypatch):
    monkeypatch.setenv("NEMOCLAW_BASELINE_PATH", str(tmp_path / "b.jsonl"))
    # 學一段「平常 1–2 人」
    for n in (1, 2, 1, 2, 1, 2):
        baseline.update_and_check(10, "person", n)
    # 突然 6 人 → 超出歷史上限(2),應為 anomaly
    is_anom, bmax = baseline.update_and_check(10, "person", 6)
    assert is_anom is True and bmax == 2
    # 之後再來 2 人(已不算 spike)→ 否
    is_anom, bmax = baseline.update_and_check(10, "person", 2)
    assert is_anom is False


def test_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("NEMOCLAW_BASELINE_PATH", str(tmp_path / "b.jsonl"))
    for n in (1, 1, 2, 1, 1):
        baseline.update_and_check(11, "person", n)
    n_s, mx, med = baseline.baseline_summary(11, "person")
    assert n_s == 5 and mx == 2 and med == 1
