#!/usr/bin/env python3
"""OpenShell sandbox 二次調查:嚴重事件後,讓真 NemoClaw Hermes 在沙箱內
主動跑 1-2 個 read-only 指令做交叉驗證(時間/外部 API/系統狀態),把 stdout
餵回 Hermes 寫結論。證明真 NemoClaw 不只是 prompt wrapper,是能執行 shell
的 agent;同時用 allowlist + per-cmd timeout 守住安全邊界。"""
import json
import os
import re
import shlex
import subprocess
import time
import urllib.request

try:
    from . import thoughts as _thoughts
    from . import flight_recorder
except Exception:
    import thoughts as _thoughts
    import flight_recorder


HERMES_URL = os.environ.get("NEMOCLAW_HERMES_URL", "http://127.0.0.1:8642/v1/chat/completions")
SANDBOX_NAME = os.environ.get("NEMOCLAW_SANDBOX_NAME", "sentinel")
ALLOWED_CMDS = {"date", "uname", "echo", "curl", "dig", "host", "jq", "cat", "ls",
                "wc", "head", "tail", "grep", "ping"}
PER_CMD_TIMEOUT = 15
MAX_CMDS = 2
MAX_OUTPUT_CHARS = 800


PLAN_SYSTEM = (
    "你是 NemoClaw OpenShell 沙箱內的安全分析師。事件已被 Nemotron 確認為嚴重。"
    f"你只能在沙箱內跑 read-only 指令(允許:{', '.join(sorted(ALLOWED_CMDS))})做交叉驗證,"
    "例如:date -u(對時間)、curl -s -m 5 公開 API(查氣象/新聞/官方狀態)、"
    "dig +short(查 DNS)。不得寫入、不得安裝、不得執行非 allowlist 內指令。"
    f"最多輸出 {MAX_CMDS} 條指令。只輸出 JSON 一行。"
)

CONCLUDE_SYSTEM = (
    "你是 NemoClaw OpenShell 內的分析師。剛才你跑了幾個 read-only 指令做交叉驗證,"
    "請根據 stdout 結果,以繁體中文一段(≤120 字)寫結論:本次事件「可能是真的/可能是誤報/"
    "需更多證據」,並給出一句下一步建議。只輸出純文字,不用 JSON。"
)


def _post(payload, timeout=45):
    req = urllib.request.Request(HERMES_URL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _hermes_chat(system, user, max_tokens=300, timeout=60):
    payload = {"model": "hermes-agent", "max_tokens": max_tokens, "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user}]}
    data = _post(payload, timeout=timeout)
    return data["choices"][0]["message"]["content"]


def plan(incident):
    """請 Hermes 規劃 1-2 個 read-only 指令做交叉驗證。"""
    user = (f"事件:[ch{incident.get('channel')} {incident.get('event_type')} "
            f"severity={incident.get('severity')}]\n"
            f"描述:{incident.get('summary','')}\n\n"
            '輸出 JSON:{"commands":[{"cmd":"date -u","purpose":"對時"}],'
            '"rationale":"繁中一句你為何選這些指令"}')
    raw = _hermes_chat(PLAN_SYSTEM, user, max_tokens=300, timeout=45)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    cmds = []
    for c in (d.get("commands") or [])[:MAX_CMDS]:
        cs = (c.get("cmd") or "").strip()
        if validate_cmd(cs):
            cmds.append({"cmd": cs, "purpose": str(c.get("purpose", ""))[:120]})
    if not cmds:
        return None
    return {"commands": cmds, "rationale": str(d.get("rationale", ""))[:200]}


_CURL_OK = re.compile(r"^https://[A-Za-z0-9.\-_:/?&=%@~+,;!*'()$]+$")


def validate_cmd(cmd):
    """嚴格 allowlist:首 token in ALLOWED_CMDS,curl 必須 https://,ping 必須 -c 1。
    禁止 redirect / pipe / subshell / 環境變數注入。"""
    if not cmd or any(ch in cmd for ch in [">", "<", "|", ";", "&", "`", "$("]):
        return False
    try:
        toks = shlex.split(cmd)
    except Exception:
        return False
    if not toks or toks[0] not in ALLOWED_CMDS:
        return False
    if toks[0] == "curl":
        if "-X" in toks or "--data" in toks or "--upload-file" in toks:
            return False
        urls = [t for t in toks[1:] if t.startswith("http")]
        if not urls or not all(_CURL_OK.match(u) for u in urls):
            return False
    if toks[0] == "ping":
        if "-c" not in toks:
            return False
        try:
            idx = toks.index("-c")
            if int(toks[idx + 1]) > 3:
                return False
        except (ValueError, IndexError):
            return False
    return True


def exec_in_sandbox(cmd, sandbox=None, timeout=PER_CMD_TIMEOUT):
    """執行單條指令於 nemohermes sandbox。回 (stdout, stderr, rc, elapsed_ms)。"""
    sandbox = sandbox or SANDBOX_NAME
    t0 = time.time()
    try:
        toks = shlex.split(cmd)
    except Exception as e:
        return "", f"shlex error: {e}", 2, 0
    try:
        p = subprocess.run(
            ["nemohermes", sandbox, "exec", "--no-tty",
             "--timeout", str(timeout), "--", *toks],
            capture_output=True, text=True, timeout=timeout + 5)
        out = (p.stdout or "")[:MAX_OUTPUT_CHARS]
        err = (p.stderr or "")[:300]
        return out, err, p.returncode, int((time.time() - t0) * 1000)
    except subprocess.TimeoutExpired:
        return "", "timeout", 124, int((time.time() - t0) * 1000)
    except Exception as e:
        return "", str(e)[:200], 1, int((time.time() - t0) * 1000)


def conclude(incident, results):
    """把 stdout 結果餵 Hermes,寫一段繁中結論。"""
    pairs = "\n".join(f"$ {r['cmd']}\n[purpose: {r['purpose']}]\n{r['stdout'][:300]}"
                      for r in results)
    user = (f"事件:[ch{incident.get('channel')} {incident.get('event_type')} "
            f"severity={incident.get('severity')}]\n"
            f"描述:{incident.get('summary','')}\n\n"
            f"二次調查指令與輸出:\n{pairs}")
    try:
        return _hermes_chat(CONCLUDE_SYSTEM, user, max_tokens=250, timeout=60)[:400]
    except Exception:
        return None


def run(incident, plan_fn=None, exec_fn=None, conclude_fn=None):
    """主入口:plan → exec → conclude。失敗時回 None,呼叫端視為「未做二次調查」。
    plan_fn/exec_fn/conclude_fn 允許測試時注入 mock。"""
    plan_fn = plan_fn or plan
    exec_fn = exec_fn or exec_in_sandbox
    conclude_fn = conclude_fn or conclude
    t0 = time.time()
    try:
        p = plan_fn(incident)
    except Exception:
        p = None
    if not p or not p.get("commands"):
        return None
    results = []
    for c in p["commands"]:
        out, err, rc, ms = exec_fn(c["cmd"])
        results.append({"cmd": c["cmd"], "purpose": c["purpose"],
                        "stdout": out, "stderr": err, "rc": rc, "elapsed_ms": ms})
    try:
        text = conclude_fn(incident, results) or ""
    except Exception:
        text = ""
    record = {
        "trace_id": incident.get("trace_id"),
        "channel": incident.get("channel"),
        "event_type": incident.get("event_type"),
        "severity": incident.get("severity"),
        "rationale": p.get("rationale", ""),
        "commands": results,
        "conclusion": text,
        "elapsed_ms": int((time.time() - t0) * 1000),
        "ts": time.time(),
        "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "governed_by": "nemoclaw-openshell-sandbox",
    }
    _append_jsonl(record)
    try:
        flight_recorder.record_stage(incident.get("trace_id"), "hermes_followup", {
            "command_count": len(results),
            "rcs": [r["rc"] for r in results],
            "conclusion": text[:200],
        })
    except Exception:
        pass
    _thoughts.record(
        f"🛰 sandbox 二次調查 ch{incident.get('channel')}: "
        f"跑了 {len(results)} 條指令 → {(text or '無結論')[:80]}",
        source="followup")
    return record


def _followups_path():
    return os.environ.get(
        "NEMOCLAW_FOLLOWUPS_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "followups.jsonl"),
    )


def _append_jsonl(rec):
    try:
        with open(_followups_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def latest(n=8):
    p = _followups_path()
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
