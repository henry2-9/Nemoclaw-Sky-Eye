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
MAX_CMDS = 3
MAX_OUTPUT_CHARS = 600


PLAN_SYSTEM = (
    "你是 NemoClaw OpenShell 沙箱內的安全分析師。事件嚴重,你必須主動 curl **即時** API 交叉驗證。"
    "已開通白名單(無 key、GET only、皆為 sub-hourly 即時資料):"
    "(a) https://api.weather.gov/alerts/active?area=<US_STATE>  即時氣象警報"
    "(b) https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson  過去 1h 地震"
    "(c) https://opensky-network.org/api/states/all?lamin=&lomin=&lamax=&lomax=  該區域即時航班"
    "(d) https://hn.algolia.com/api/v1/search_by_date?query=<keyword>&tags=story&hitsPerPage=3  即時討論"
    "依事件選最相關 1-2 條。火災/煙→(a)+(d);爆炸/地震→(b)+(d);航空/低空異常→(c)+(d);"
    "其他→(a)+(d)。**禁止** wikipedia / nominatim / 任何靜態查詢。"
    f"最多 {MAX_CMDS} 條。只輸出 JSON 一行,不要 markdown。"
)

CONCLUDE_SYSTEM = (
    "你是 NemoClaw OpenShell 內的分析師。剛才你跑了多個獨立來源的 read-only 指令做交叉驗證。"
    "請以繁體中文嚴格按此格式回答(每行一個項目,不要 JSON、不要 markdown):\n"
    "來源1 [<簡名>]: 證實|否認|無訊號 · <一句根據,≤30 字>\n"
    "來源2 [<簡名>]: 證實|否認|無訊號 · <根據>\n"
    "來源3 [<簡名>]: 證實|否認|無訊號 · <根據>\n"
    "綜合判斷: 真實|誤報|需更多證據 · <一句理由>\n"
    "建議: <下一步具體動作>\n"
    "規則:每行 ≤60 字。簡名用 weather.gov / HN / USGS / OpenSky 等。"
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
    loc = incident.get("channel_name") or f"ch{incident.get('channel')}"
    user = (f"事件:[{loc} · {incident.get('event_type')} · "
            f"severity={incident.get('severity')}]\n"
            f"描述:{(incident.get('summary') or '')[:200]}\n\n"
            f"地點關鍵字請用於 wiki/nominatim 查詢(例:Times_Square、Eiffel_Tower)。"
            '輸出 JSON 範本:{"commands":[{"cmd":"curl -s https://...","purpose":"..."}],'
            '"rationale":"一句話"}')
    raw = _hermes_chat(PLAN_SYSTEM, user, max_tokens=500, timeout=60)
    cmds = _extract_commands(raw)
    if not cmds:
        return None
    rat = re.search(r'"rationale"\s*:\s*"([^"]{0,200})"', raw or "")
    return {"commands": cmds, "rationale": (rat.group(1) if rat else "")}


def _extract_commands(raw):
    """容錯解析:Hermes 可能 truncate JSON 或把 rationale 塞進 commands 陣列。
    直接用 regex 把 {"cmd":"...","purpose":"..."} 配對抓出來,validate 後回 list。"""
    cmds = []
    if not raw:
        return cmds
    for m in re.finditer(
        r'\{\s*"cmd"\s*:\s*"((?:\\"|[^"])*)"\s*,\s*"purpose"\s*:\s*"((?:\\"|[^"])*)"',
        raw):
        cs = m.group(1).replace('\\"', '"').strip()
        if validate_cmd(cs):
            cmds.append({"cmd": cs, "purpose": m.group(2)[:120]})
        if len(cmds) >= MAX_CMDS:
            break
    return cmds


_CURL_OK = re.compile(r"^https://[A-Za-z0-9.\-_:/?&=%@~+,;!*'()$]+$")


_SHELL_CONTROL_TOKENS = {";", "&", "|", "&&", "||", ";;", "<", ">", ">>", "<<", "`"}


def validate_cmd(cmd):
    """嚴格 allowlist:首 token in ALLOWED_CMDS,curl 必須 https://,ping 必須 -c≤3。
    先 shlex.split,再對 token 級別查 shell control / subshell — 這樣引號內
    的 `&`(URL query separator)不會誤觸 metachar 規則。"""
    if not cmd:
        return False
    try:
        toks = shlex.split(cmd)
    except Exception:
        return False
    if not toks or toks[0] not in ALLOWED_CMDS:
        return False
    for t in toks:
        if t in _SHELL_CONTROL_TOKENS:
            return False
        if "`" in t or "$(" in t or t.startswith("$"):
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
    """把多個獨立來源 stdout 餵 Hermes,寫多源 verdict 融合結論。"""
    pairs = "\n".join(
        f"[來源{i+1} · {r['purpose']}]\n{(r['stdout'] or '<empty>')[:280]}"
        for i, r in enumerate(results))
    user = (f"事件:[ch{incident.get('channel')} {incident.get('event_type')} "
            f"severity={incident.get('severity')}]\n"
            f"描述:{(incident.get('summary') or '')[:150]}\n\n"
            f"多源獨立查證輸出:\n{pairs}\n\n"
            f"嚴格按 system 指定格式回答。")
    try:
        return _hermes_chat(CONCLUDE_SYSTEM, user, max_tokens=400, timeout=70)[:700]
    except Exception:
        return None


def multi_source_recipe(incident):
    """**固定 3 個獨立來源**做交叉驗證——政府 + 網友 + 科學/航空儀器。
    不讓 Hermes 自選來源(因為 LLM 規劃會偏向 1-2 條同類);3 條獨立來源
    才有真正的交叉驗證價值,讓 conclude 階段能寫「證實/否認/無訊號」逐源 verdict。"""
    et = incident.get("event_type") or ""
    name = (incident.get("channel_name") or "").split("·")[0].strip() or "Times Square"
    kw = name.replace(" ", "+")
    weather = ("curl -s -m 8 https://api.weather.gov/alerts/active?area=NY",
               "weather.gov · 美國政府即時氣象警報")
    hn = (f"curl -s -m 8 'https://hn.algolia.com/api/v1/search_by_date"
          f"?query={kw}&tags=story&hitsPerPage=3'",
          f"HN · 即時討論「{name}」")
    quake = ("curl -s -m 8 https://earthquake.usgs.gov/earthquakes/feed/v1.0/"
             "summary/all_hour.geojson",
             "USGS · 過去 1h 全球地震")
    flights = ("curl -s -m 8 'https://opensky-network.org/api/states/all"
               "?lamin=40.7&lomin=-74.0&lamax=40.8&lomax=-73.9'",
               "OpenSky · NYC 區即時航班")
    if et in ("fire_smoke", "abnormal_weather"):
        triplet = [weather, hn, quake]
        why = "政府氣象 + 網友討論 + 地震排除"
    elif et in ("intrusion", "abnormal_crowd"):
        triplet = [hn, weather, flights]
        why = "網友討論 + 政府氣象 + 航空異常"
    else:
        triplet = [weather, hn, quake]
        why = "政府氣象 + 網友討論 + 地震排除"
    return {"commands": [{"cmd": c, "purpose": p} for c, p in triplet
                         if validate_cmd(c)][:MAX_CMDS],
            "rationale": f"三源獨立交叉驗證({why})"}


def fallback_plan(incident):
    """Hermes 規劃完全失敗時的兜底——等同於 multi_source_recipe。"""
    return multi_source_recipe(incident)


def run(incident, plan_fn=None, exec_fn=None, conclude_fn=None):
    """主入口:plan → exec → conclude。預設用 multi_source_recipe 跑固定 3 個獨立
    來源(政府+網友+科學儀器),Hermes 在 conclude 階段做交叉驗證融合。
    傳 plan_fn 可注入測試或讓 Hermes 自主規劃(失敗時 fallback 回 recipe)。"""
    plan_fn = plan_fn or multi_source_recipe
    exec_fn = exec_fn or exec_in_sandbox
    conclude_fn = conclude_fn or conclude
    t0 = time.time()
    try:
        p = plan_fn(incident)
    except Exception:
        p = None
    used_fallback = False
    if not p or not p.get("commands"):
        p = fallback_plan(incident)
        used_fallback = True
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
        "channel_name": incident.get("channel_name"),
        "event_type": incident.get("event_type"),
        "severity": incident.get("severity"),
        "rationale": p.get("rationale", ""),
        "commands": results,
        "conclusion": text,
        "elapsed_ms": int((time.time() - t0) * 1000),
        "ts": time.time(),
        "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "governed_by": "nemoclaw-openshell-sandbox",
        "plan_source": "fallback-recipe" if used_fallback else (
            "hermes-autonomous" if plan_fn is plan else "multi-source-recipe"),
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
