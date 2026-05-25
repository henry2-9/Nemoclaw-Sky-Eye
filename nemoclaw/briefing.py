#!/usr/bin/env python3
"""自主情勢簡報:agent 按自己排程(非人問)把近 N 小時確認事件彙整成一段
給維運主管的繁中簡報。優先用 Nemotron 潤飾,失敗則用確定性 fallback。"""
import json
import os
import time

_SEV_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _here():
    return os.path.dirname(os.path.abspath(__file__))


def latest_path():
    return os.path.join(_here(), "latest_briefing.txt")


def recent_events(hours=1, audit_path=None, now=None):
    path = audit_path or os.environ.get("NEMOCLAW_AUDIT_PATH")
    now = now if now is not None else time.time()
    out = []
    if path and os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("decision") == "ALLOW" and (now - r.get("ts", 0)) <= hours * 3600:
                out.append(r)
    return out


def _fallback_brief(events, hours):
    if not events:
        return f"過去 {hours} 小時:無確認事件,一切正常。"
    from collections import Counter
    by_sev = Counter(e.get("severity") for e in events)
    worst = max(events, key=lambda e: _SEV_ORDER.get(e.get("severity"), 0))
    sev_str = "、".join(f"{k}×{v}" for k, v in by_sev.items())
    return (f"過去 {hours} 小時:共 {len(events)} 起確認事件({sev_str});"
            f"最嚴重:{worst.get('channel')} {worst.get('event_type')} — "
            f"{(worst.get('summary') or '')[:60]}。建議優先處理高/critical 事件。")


def generate_briefing(hours=1, vlm_fn=None, audit_path=None, now=None):
    events = recent_events(hours, audit_path=audit_path, now=now)
    base = _fallback_brief(events, hours)
    if vlm_fn and events:
        try:
            prompt = ("你是工安維運主管。把以下事件統計改寫成 2-3 句、給主管看的繁體中文情勢簡報,"
                      "點出重點與建議,不要逐條列出:\n" + base)
            text = vlm_fn(prompt)
            if text and text.strip():
                return text.strip()
        except Exception:
            pass
    return base


def write_latest(text, path=None):
    path = path or latest_path()
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n")
    return path


def read_latest(path=None):
    path = path or latest_path()
    return open(path, encoding="utf-8").read().strip() if os.path.exists(path) else ""


def _vlm_text(prompt):
    """文字 only 呼叫 Nemotron(vLLM OpenAI 相容)。失敗回 None,讓 fallback 接手。"""
    import urllib.request
    url = os.environ.get("VLM_API_URL", "http://127.0.0.1:31010/v1/chat/completions")
    body = json.dumps({
        "model": os.environ.get("VLM_MODEL", "nemotron_3_nano_omni"),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 200, "temperature": 0.3,
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def main():
    import argparse
    p = argparse.ArgumentParser(description="自主情勢簡報")
    p.add_argument("--hours", type=float, default=1)
    p.add_argument("--no-vlm", action="store_true", help="只用 fallback,不呼叫 Nemotron")
    args = p.parse_args()
    text = generate_briefing(hours=args.hours, vlm_fn=None if args.no_vlm else _vlm_text)
    write_latest(text)
    print(text)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, _here())
    main()
