import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import attack_matrix as am  # noqa: E402


def test_all_five_attacks_defended():
    rep = am.run_matrix()
    assert rep["total"] == 5
    assert rep["all_defended"] is True
    assert rep["defended"] == 5


def test_each_scenario_flags_injection_and_retains_severity():
    rep = am.run_matrix()
    for row in rep["rows"]:
        assert row["injection_flagged"] is True, row["id"]
        assert row["severity_retained"] is True, row["id"]
        assert row["severity_after"] == "critical", row["id"]
        assert row["guardrail"], row["id"]            # 否決訊息非空
        assert row["defended"] is True, row["id"]


def test_governance_and_still_notifies():
    rep = am.run_matrix()
    for row in rep["rows"]:
        assert row["governed_by"] == "nemoclaw-openshell", row["id"]
        assert row["policy_decision"] == "ALLOW", row["id"]
        assert row["still_notifies"] is True, row["id"]  # 攻擊不阻止真實告警


def test_modalities_are_distinct():
    rep = am.run_matrix()
    ids = [r["id"] for r in rep["rows"]]
    assert ids == ["cjk_overlay", "latin_overlay", "qr_command",
                   "occluded_text", "audio_subtitle"]


def test_uses_real_production_functions():
    # guardrail 來自 orchestrator._triage_severity;注入標記來自 policy.evaluate
    import orchestrator
    import policy
    assert am._orch is orchestrator
    assert am._policy is policy
    # 反向健全性:無注入文字時 guardrail 不應觸發(避免假陽性)
    sev, guard = orchestrator._triage_severity("critical", "low", "倉庫一切正常")
    assert sev == "low" and guard is None


def test_write_report(tmp_path):
    path = tmp_path / "m.json"
    rep, out = am.write_report(str(path))
    assert os.path.exists(out)
    assert rep["all_defended"] is True
    import json
    saved = json.load(open(out, encoding="utf-8"))
    assert saved["defended"] == 5 and "generated_at" in saved
