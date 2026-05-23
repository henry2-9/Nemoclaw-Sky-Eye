import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import eval as ev

def test_summary_counts_and_unique_events():
    decisions = [
        {"channel":"1","event_type":"fire_smoke","decision":"ALLOW","actions":["log","notify"]},
        {"channel":"1","event_type":"fire_smoke","decision":"DEDUP"},          # 重複被擋
        {"channel":"5","event_type":"intrusion","decision":"BLOCK"},           # 低信心
        {"channel":"6","event_type":"intrusion","decision":"ALLOW","actions":["log"]},  # log-only 不算 notified
        {"channel":"7","event_type":"fire_smoke","decision":"ABSTAIN"},
        {"channel":"8","event_type":"fire_smoke","decision":"ALLOW","actions":["log","notify"],"injection_detected":True},
    ]
    s = ev.summarize(decisions)
    assert s["total"] == 6
    assert s["notified"] == 2          # 只有帶 notify 的兩筆
    assert s["deduped"] == 1
    assert s["blocked"] == 1
    assert s["abstained"] == 1
    assert s["injection_flagged"] == 1
    assert s["unique_notified_events"] == 2
