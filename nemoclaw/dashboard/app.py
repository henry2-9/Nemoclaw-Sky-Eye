#!/usr/bin/env python3
"""NemoClaw Sentinel dashboard: audit log + incident flight recorder."""
import html
import os
import json
import mimetypes
import shutil
import sys
import time
import datetime
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import flight_recorder
import media
try:
    import watchdog as _watchdog
except Exception:
    _watchdog = None
try:
    import briefing as _briefing
except Exception:
    _briefing = None
try:
    import thoughts as _thoughts
except Exception:
    _thoughts = None
try:
    import feed_health as _feed_health
except Exception:
    _feed_health = None

AUDIT = os.environ.get("NEMOCLAW_AUDIT_PATH",
                       os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "audit.jsonl"))
ATTACK_MATRIX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "attack_matrix.json")

def _rows():
    if not os.path.exists(AUDIT):
        return []
    out = []
    for l in open(AUDIT, encoding="utf-8"):
        try:
            out.append(json.loads(l))
        except Exception:
            pass
    return out

def _stats(rows):
    s = {"ALLOW": 0, "BLOCK": 0, "DEDUP": 0, "ABSTAIN": 0}
    notified = inj = gov = 0
    for r in rows:
        s[r.get("decision", "")] = s.get(r.get("decision", ""), 0) + 1
        if _notified(r):
            notified += 1
        if r.get("injection_detected"):
            inj += 1
        if r.get("governed_by") == "nemoclaw-openshell":
            gov += 1
    return s, notified, inj, gov

def _notified(row):
    if "notification_sent" in row:
        return bool(row.get("notification_sent"))
    return row.get("decision") == "ALLOW" and "notify" in (row.get("actions") or [])

def _efficiency_metrics():
    """級聯效率:從 supervisor.log 聚合掃描/喚醒/確認;從 flight_recorder 算調查延遲。"""
    import statistics
    log = os.path.join(os.environ.get("NEMOCLAW_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "supervisor.log")
    cycles = cand = inv = inc = 0
    if os.path.exists(log):
        for line in open(log, encoding="utf-8"):
            i = line.find("{")
            if i < 0:
                continue
            try:
                d = json.loads(line[i:])
            except Exception:
                continue
            if "candidates" not in d:
                continue
            cycles += 1
            cand += int(d.get("candidates", 0)); inv += int(d.get("investigated", 0)); inc += int(d.get("incidents", 0))
    lat = []
    try:
        by = flight_recorder.group_by_trace(flight_recorder.load())
        for stages in by.values():
            ts = {st.get("stage"): st.get("ts") for st in stages if st.get("ts")}
            if "nemotron_question" in ts and "policy_decision" in ts:
                dt = ts["policy_decision"] - ts["nemotron_question"]
                if 0 < dt < 600:
                    lat.append(dt)
    except Exception:
        pass
    med = round(statistics.median(lat), 1) if lat else 0.0
    p95 = round(sorted(lat)[max(0, int(len(lat) * 0.95) - 1)], 1) if len(lat) >= 2 else med
    return {"cycles": cycles, "candidates": cand, "investigations": inv, "confirmed": inc,
            "filtered": max(0, inv - inc), "capped": max(0, cand - inv),
            "median_latency": med, "p95_latency": p95}


COLOR = {"ALLOW": "#0a7", "BLOCK": "#c33", "DEDUP": "#888", "ABSTAIN": "#e90"}

# ── 深色玻璃擬態主題(主頁與 trace 頁共用)──
STYLE = """
*{box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,-apple-system,'Noto Sans TC',sans-serif;margin:0;
  min-height:100vh;color:#e7e9f3;background:#090a18;
  background-image:
    radial-gradient(900px 520px at 10% -10%, rgba(124,92,255,.30), transparent 60%),
    radial-gradient(820px 520px at 94% 4%, rgba(0,194,255,.22), transparent 55%),
    radial-gradient(760px 640px at 50% 116%, rgba(16,233,170,.14), transparent 60%),
    linear-gradient(160deg,#090a18 0%,#11122c 46%,#0a1226 100%);
  background-attachment:fixed}
.wrap{max-width:1220px;margin:0 auto;padding:24px 20px 64px}
a{color:#7fd6ff;text-decoration:none} a:hover{text-decoration:underline}
code{color:#a7f3d0;background:rgba(255,255,255,.06);padding:1px 6px;border-radius:6px;font-size:12px}
.glass{background:rgba(255,255,255,.055);backdrop-filter:blur(16px) saturate(140%);
  -webkit-backdrop-filter:blur(16px) saturate(140%);border:1px solid rgba(255,255,255,.10);
  border-radius:18px;box-shadow:0 12px 40px rgba(0,0,0,.45),inset 0 1px 0 rgba(255,255,255,.06)}
.head{display:flex;justify-content:space-between;align-items:center;gap:16px;
  padding:18px 24px;margin-bottom:20px;flex-wrap:wrap}
.brand{font-size:23px;font-weight:800;letter-spacing:.5px;
  background:linear-gradient(90deg,#a78bfa,#22d3ee,#34d399);-webkit-background-clip:text;
  background-clip:text;color:transparent}
.sub{color:#9aa3c7;font-size:12.5px;margin-top:3px}
.status{display:flex;gap:15px;flex-wrap:wrap;font-size:12.5px;color:#c7cdf0;align-items:center}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;
  background:#34d399;box-shadow:0 0 9px #34d399;animation:pulse 2.4s infinite}
@keyframes pulse{50%{opacity:.45}}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:14px;margin-bottom:18px}
.tile{padding:17px 18px;position:relative;overflow:hidden}
.tile .v{font-size:30px;font-weight:800;line-height:1.05}
.tile .l{color:#9aa3c7;font-size:12.5px;margin-top:5px}
.tile .accent{position:absolute;left:0;top:0;bottom:0;width:4px}
.panel{padding:18px 22px;margin-bottom:18px}
.panel h3{margin:0 0 14px;font-size:15px;font-weight:700;color:#e3e6ff;
  display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.muted{color:#8b93b8}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:14px}
.stat .v{font-size:22px;font-weight:700} .stat .v.hi{color:#22d3ee}
.stat .l{color:#9aa3c7;font-size:12px;margin-top:3px} .pct{font-size:13px;color:#34d399;font-weight:700}
table{border-collapse:separate;border-spacing:0;width:100%;font-size:13px}
th,td{padding:9px 11px;text-align:left;border-bottom:1px solid rgba(255,255,255,.07);vertical-align:top}
th{color:#aab2da;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.4px}
tbody tr:hover{background:rgba(255,255,255,.045)} tbody tr:last-child td{border-bottom:none}
.badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11.5px;font-weight:700;
  border:1px solid transparent;white-space:nowrap}
.b-allow{color:#34d399;background:rgba(52,211,153,.13);border-color:rgba(52,211,153,.32)}
.b-block{color:#f87171;background:rgba(248,113,113,.13);border-color:rgba(248,113,113,.32)}
.b-dedup{color:#94a3b8;background:rgba(148,163,184,.13);border-color:rgba(148,163,184,.32)}
.b-abstain{color:#fbbf24;background:rgba(251,191,36,.13);border-color:rgba(251,191,36,.32)}
.b-gov{color:#7dd3fc;background:rgba(125,211,252,.12);border-color:rgba(125,211,252,.3)}
.b-inj{color:#fca5a5;background:rgba(252,165,165,.12);border-color:rgba(252,165,165,.3)}
.ok{color:#34d399;font-weight:700} .bad{color:#f87171;font-weight:700}
.media-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
video,img{width:100%;max-height:440px;background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.1);
  border-radius:12px;object-fit:contain}
.empty{border:1px dashed rgba(255,255,255,.18);padding:32px;color:#8b93b8;border-radius:12px;text-align:center}
h4{margin:6px 0}
.kv{display:flex;gap:10px;margin:3px 0;line-height:1.5}
.kv .k{color:#8b93b8;min-width:86px;flex-shrink:0;font-size:12px}
.kv .v{color:#e2e6ff;word-break:break-word}
.cc{padding:20px 24px}
.cc-top{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}
.cc-proof{font-size:16px;color:#dfe3ff}
.cc-proof .zero{color:#34d399;font-size:19px}
.cc-threat{font-size:13px;color:#9aa3c7}
.threat{display:inline-block;padding:3px 13px;border-radius:999px;font-weight:800;border:1px solid;font-size:14px}
.cc-health{display:flex;gap:18px;margin-top:13px;font-size:13px;color:#c7cdf0;flex-wrap:wrap}
.cascade{display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.cascade .arrow{color:#5a6080;margin:0 1px}
.brief{margin-top:13px;padding:11px 15px;border-radius:12px;background:rgba(124,92,255,.13);
  border:1px solid rgba(124,92,255,.26);color:#e2e6ff;font-size:13px;line-height:1.55}
.thoughts{display:flex;flex-direction:column;gap:7px;max-height:330px;overflow-y:auto;font-size:13px}
.th{display:flex;gap:10px;align-items:flex-start;padding:6px 9px;border-radius:9px;
  background:rgba(255,255,255,.03);border-left:2px solid rgba(255,255,255,.10)}
.th:hover{background:rgba(255,255,255,.06)}
.th-ts{color:#7d86ad;font-family:ui-monospace,monospace;font-size:11.5px;min-width:64px;flex-shrink:0}
.th-icon{font-size:14px;min-width:18px;flex-shrink:0}
.th-text{color:#dfe3ff;word-break:break-word;line-height:1.45}
.se-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.se-tile{padding:13px 15px;position:relative}
.se-id{color:#7d86ad;font-size:11px;font-family:ui-monospace,monospace}
.se-name{color:#e2e6ff;font-size:13.5px;font-weight:600;margin:3px 0 6px;line-height:1.3}
.se-status{font-size:12px;font-weight:700}
.se-ts{color:#7d86ad;font-size:11px;margin-top:3px;font-family:ui-monospace,monospace}
"""

_BADGE_CLS = {"ALLOW": "b-allow", "BLOCK": "b-block", "DEDUP": "b-dedup", "ABSTAIN": "b-abstain"}


def _tile(value, label, accent):
    return (f"<div class='tile glass'>"
            f"<span class=accent style='background:{accent};box-shadow:0 0 16px {accent}'></span>"
            f"<div class=v>{value}</div><div class=l>{label}</div></div>")


def _eff_stat(value, label, hi=False):
    return (f"<div class=stat><div class='v{' hi' if hi else ''}'>{value}</div>"
            f"<div class=l>{label}</div></div>")


def _decision_badge(decision):
    d = str(decision or "")
    return f"<span class='badge {_BADGE_CLS.get(d, 'b-dedup')}'>{html.escape(d)}</span>"


def _incident_row(r):
    gov_b = "<span class='badge b-gov'>🛡 NemoClaw</span>" if r.get("governed_by") == "nemoclaw-openshell" else ""
    inj_b = "<span class='badge b-inj'>⚠ injection</span>" if r.get("injection_detected") else ""
    return ("<tr>"
            f"<td class=muted>{html.escape(str(r.get('ts_iso', '')))}</td>"
            f"<td>{html.escape(str(r.get('channel', '')))}</td>"
            f"<td>{html.escape(str(r.get('event_type', '')))}</td>"
            f"<td>{_decision_badge(r.get('decision', ''))}</td>"
            f"<td>{gov_b}</td><td>{inj_b}</td>"
            f"<td>{html.escape(', '.join(r.get('actions') or []))}</td>"
            f"<td>{_trace_link(r.get('trace_id'))}</td>"
            f"<td>{_media_links(r)}</td>"
            f"<td class=muted>{html.escape('; '.join(r.get('reasons') or []))}</td>"
            "</tr>")


# ── 把 flight 軌跡 payload 變成人類可讀(不顯示 JSON)──
_STAGE_LABELS = {
    "sweep_selected": "① 感知挑選", "nemotron_question": "② Nemotron 提問",
    "nemotron_raw_answer": "③ Nemotron 原始回答", "nemotron_grading": "④ 多模態分級",
    "nemoclaw_triage": "⑤ NemoClaw 治理", "incident_built": "⑥ 事件成形",
    "policy_decision": "⑦ 政策決策", "notification": "⑧ 通知送出",
}
_FIELD_LABELS = {
    "channel": "頻道", "event_type": "事件類型", "question": "提問", "answer": "模型回答",
    "confidence": "信心", "confirmed": "已確認", "severity": "嚴重度", "summary": "摘要",
    "visible_text": "畫面文字", "ocr_text": "OCR 文字", "cheap_evidence": "初步證據",
    "counts": "偵測數", "falcon_query": "Falcon 查詢", "frame_path": "影格", "playhead_sec": "播放秒數",
    "governed_by": "治理者", "rationale": "理由", "recommended_action": "建議處置", "cheap_text": "畫面文字",
    "triage_guardrail": "安全護欄", "decision": "決策", "actions": "動作", "channels": "通知管道",
    "injection_detected": "偵測注入", "reasons": "理由", "policy_hits": "政策命中", "media_refs": "媒體",
    "source_video_path": "來源影片", "video_path": "來源影片", "trace_id": "追蹤碼",
    "degraded": "降級", "evidence_citations": "證據引用", "finding": "發現", "tool": "工具",
}


def _stage_chip(stage):
    label = _STAGE_LABELS.get(stage, stage or "—")
    return f"<span class='badge b-gov'>{html.escape(label)}</span>"


def _try_parse_json(s):
    """字串若是(或內含)JSON,回傳解析後物件,否則 None。"""
    s = (s or "").strip()
    start = s.find("{")
    if start == -1:
        start = s.find("[")
    if start == -1:
        return None
    try:
        return json.loads(s[start:])
    except Exception:
        pass
    if s[start] != "{":
        return None
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(s[start:i + 1])
                except Exception:
                    return None
    return None


def _humanize_value(v):
    if isinstance(v, bool):
        return "是" if v else "否"
    if v is None:
        return "—"
    if isinstance(v, str):
        parsed = _try_parse_json(v)
        return _humanize_value(parsed) if parsed is not None else v
    if isinstance(v, dict):
        parts = []
        for k, val in v.items():
            lbl = _FIELD_LABELS.get(k, k)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                parts.append(f"{lbl}×{val}")
            else:
                parts.append(f"{lbl}:{_humanize_value(val)}")
        return "、".join(parts)
    if isinstance(v, (list, tuple)):
        return "、".join(_humanize_value(x) for x in v) if v else "—"
    return str(v)


def _clean_text(field, text):
    text = str(text)
    if field == "question":
        # 提問裡常內含「只輸出 JSON,格式:{...}」範本,UI 不顯示那段
        for marker in ("只輸出", "格式:", "格式:", "輸出 JSON", "回傳 JSON"):
            idx = text.find(marker)
            if idx > 0:
                text = text[:idx].rstrip("。,, \n")
                break
    return text if len(text) <= 280 else text[:277] + "…"


def _humanize_payload(payload):
    if not isinstance(payload, dict):
        return html.escape(str(payload)) if payload else "<span class=muted>—</span>"
    rows = []
    for k, v in payload.items():
        if v in (None, "", [], {}):
            continue
        val = _clean_text(k, _humanize_value(v))
        if not str(val).strip():
            continue
        rows.append(f"<div class=kv><span class=k>{html.escape(_FIELD_LABELS.get(k, k))}</span>"
                    f"<span class=v>{html.escape(str(val))}</span></div>")
    return "".join(rows) or "<span class=muted>—</span>"


# ── P0-2 自主運行指揮中心 ──
_NEMODIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SEV_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_THREAT = {0: ("低", "#34d399"), 1: ("中", "#fbbf24"), 2: ("高", "#fb923c"), 3: ("嚴重", "#f87171")}


def _uptime_str():
    log = os.path.join(_NEMODIR, "supervisor.log")
    try:
        with open(log, encoding="utf-8") as f:
            for line in f:
                if "supervisor start" in line:
                    start = datetime.datetime.fromisoformat(line.split()[0])
                    secs = (datetime.datetime.now(start.tzinfo) - start).total_seconds()
                    return f"{int(secs // 3600)}h {int((secs % 3600) // 60)}m"
    except Exception:
        pass
    return "—"


def _threat(rows, now=None):
    now = now if now is not None else time.time()
    lvl = 0
    for r in rows:
        if r.get("decision") == "ALLOW" and (now - r.get("ts", 0)) <= 3600:
            lvl = max(lvl, _SEV_RANK.get(r.get("severity"), 0))
    return _THREAT[lvl]


def _health_now():
    if not _watchdog:
        return {}
    try:
        return _watchdog.service_health()
    except Exception:
        return {}


def _health_dots(health):
    if not health:
        return "<span class=muted>服務狀態未知</span>"
    out = []
    for k, label in (("nemotron", "Nemotron"), ("falcon", "Falcon"), ("nemoclaw", "NemoClaw")):
        up = health.get(k) == "up"
        out.append(f"<span><span class='dot{'' if up else ' off'}'></span>{label}</span>")
    return "".join(out)


def _cascade_html():
    all_rows = flight_recorder.load()
    latest = flight_recorder.latest_traces(all_rows, 1)
    if not latest:
        return ""
    tid, recs = latest[0]
    chips = "<span class=arrow>→</span>".join(_stage_chip(r.get("stage", "")) for r in recs)
    q = urllib.parse.urlencode({"trace_id": tid})
    return (f"<div class=muted style='margin:10px 0 6px'>最新事件級聯 · "
            f"<a href='/trace?{q}'>{html.escape(tid.split('-')[-1])}</a></div>"
            f"<div class=cascade>{chips}</div>")


def _render_command_center(rows, health=None):
    handled = sum(1 for r in rows if r.get("decision") == "ALLOW")
    uptime = _uptime_str()
    health = health if health is not None else _health_now()
    tlabel, tcolor = _threat(rows)
    cascade = _cascade_html()
    brief = _briefing.read_latest() if _briefing else ""
    brief_html = (f"<div class=brief>🗒 最新情勢簡報:{html.escape(brief)}</div>" if brief else "")
    return f"""<section class='panel glass cc'>
  <div class=cc-top>
    <div class=cc-proof>🤖 <b>全自主運行</b> · 人工介入 <b class=zero>0</b> 次 · 已連續 <b>{uptime}</b> · 處理 <b>{handled}</b> 起</div>
    <div class=cc-threat>威脅等級 <span class=threat style='color:{tcolor};border-color:{tcolor}66;background:{tcolor}1f'>{tlabel}</span></div>
  </div>
  <div class=cc-health>{_health_dots(health)}</div>
  {cascade}
  {brief_html}
</section>"""


_THOUGHT_TAGS = {
    "sweep": ("👁", "#7dd3fc"), "baseline": ("📊", "#fbbf24"),
    "curiosity": ("🔎", "#a78bfa"), "investigate": ("🧠", "#22d3ee"),
    "decision": ("🛡", "#34d399"), "watchdog": ("🩺", "#fb923c"),
    "briefing": ("🗒", "#c4b5fd"), "agent": ("🤖", "#9aa3c7"),
}


def _render_sky_eye_grid():
    """天眼網格:每個全球地標頻道顯示 online/offline 狀態,agent 自主管理外部來源。"""
    if not _feed_health:
        return ""
    full = _feed_health.state()
    # 天眼網格僅顯示 landmark 頻道(id ≥ 200);舊本地/區域 cam 不入網格
    st = {k: v for k, v in full.items() if str(k).isdigit() and int(k) >= 200}
    if not st:
        return ""
    online = sum(1 for v in st.values() if v.get("ok"))
    tiles = []
    for k, v in sorted(st.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0):
        ok = v.get("ok")
        color = "#34d399" if ok else "#f87171"
        status = "🟢 online" if ok else "🔴 offline"
        ts = (v.get("last", "") or "")[-8:]
        tiles.append(
            f"<div class='se-tile glass' style='border-left:3px solid {color};box-shadow:0 0 14px {color}22'>"
            f"<div class=se-id>ch{html.escape(str(k))}</div>"
            f"<div class=se-name>{html.escape(v.get('name', ''))}</div>"
            f"<div class=se-status style='color:{color}'>{status}</div>"
            f"<div class=se-ts>{html.escape(ts)}</div></div>")
    return (f"<section class='panel glass'><h3>🌐 天眼 · 全球地標即時 "
            f"<span class=muted style='font-size:11px;font-weight:400'>{online}/{len(st)} 線上 · agent 自主管理外部來源</span></h3>"
            f"<div class=se-grid>{''.join(tiles)}</div></section>")


def _render_thoughts():
    if not _thoughts:
        return ""
    items = _thoughts.latest(12)
    if not items:
        return ""
    rows = []
    for it in items:
        icon, color = _THOUGHT_TAGS.get(it.get("source", "agent"), _THOUGHT_TAGS["agent"])
        ts = (it.get("ts") or "")[-8:]   # HH:MM:SS
        rows.append(
            f"<div class=th><span class=th-ts>{html.escape(ts)}</span>"
            f"<span class=th-icon style='color:{color}'>{icon}</span>"
            f"<span class=th-text>{html.escape(it.get('text', ''))}</span></div>"
        )
    return (f"<section class='panel glass'><h3>💭 Agent 思考即時流 "
            f"<span class=muted style='font-size:11px;font-weight:400'>第一人稱 · 最近 12 條</span></h3>"
            f"<div class=thoughts>{''.join(reversed(rows))}</div></section>")


def _latest_media_row(rows):
    """挑最近一筆 landmark(ch≥200)、severity ≥ medium 且有 media 的「可疑事件」。
    低嚴重度只是常態觀察,不上事件面板(會被計入思考流)。"""
    for r in reversed(rows):
        try:
            ch = int(r.get("channel"))
        except Exception:
            continue
        if ch < 200:
            continue
        if r.get("severity") in (None, "", "low"):
            continue
        urls = (r.get("media_artifacts") or {}).get("urls") or {}
        if urls.get("clip") or urls.get("falcon_annotated") or urls.get("frame"):
            return r
    return None


def _render_current_incident(rows):
    """首頁直接秀最新「天眼事件」的錄影切片 + Falcon 標記圖 + 自主處置標記。"""
    r = _latest_media_row(rows)
    if not r:
        return ("<section class='panel glass'>"
                "<h3>🎥 最新天眼事件 · 自主處置</h3>"
                "<p class=muted>天眼持續監看城市/交通/公共地標——目前無**可疑事件**;若偵測到火/煙/衝突/可疑物品/異常人群,將自動連同錄影切片在此呈現。日常觀察記入下方思考流。</p>"
                "</section>")
    urls = (r.get("media_artifacts") or {}).get("urls") or {}
    clip = urls.get("clip") or ""
    annot = urls.get("falcon_annotated") or urls.get("frame") or ""
    sev = str(r.get("severity", "")).upper()
    sevcls = {"CRITICAL": "b-block", "HIGH": "b-block",
              "MEDIUM": "b-abstain", "LOW": "b-dedup"}.get(sev, "b-dedup")
    marks = []
    if r.get("escalated"):
        marks.append("<span class='badge b-block'>🔴 二級升級</span>")
    if r.get("report_path"):
        marks.append("<span class='badge b-gov'>📄 已產報告</span>")
    if r.get("injection_detected"):
        marks.append("<span class='badge b-inj'>⚠ 注入已擋</span>")
    gov = "🛡 NemoClaw" if r.get("governed_by") == "nemoclaw-openshell" else str(r.get("governed_by") or "")
    q = urllib.parse.urlencode({"trace_id": r.get("trace_id", "")})
    video_html = (f"<video controls autoplay muted loop playsinline preload='metadata' "
                  f"src='{html.escape(clip)}'></video>" if clip else "<div class=empty>無錄影切片</div>")
    img_html = (f"<a href='{html.escape(annot)}'><img src='{html.escape(annot)}' alt='Falcon 標記圖'></a>"
                if annot else "<div class=empty>無標記圖</div>")
    return f"""<section class='panel glass'>
  <h3>🎥 最新天眼事件 · 自主處置 <span class='badge {sevcls}'>{sev or '—'}</span>
    <span class=muted style='font-weight:400'>{html.escape(str(r.get('channel','')))} · {html.escape(str(r.get('event_type','')))}</span>
    {' '.join(marks)}</h3>
  <div class=media-grid>
    <div><h4>錄影切片(已馬賽克)</h4>{video_html}</div>
    <div><h4>Falcon 標記圖</h4>{img_html}</div>
  </div>
  <p class=muted>{html.escape(str(r.get('summary',''))[:160] or '—')} · 治理:{html.escape(gov or '—')} · <a href='/trace?{q}'>展開飛行紀錄</a></p>
</section>"""


def _render_attack_matrix():
    """🛡 NemoClaw 安全防護面板:測試 agent 能否抵擋畫面內的「假指令攻擊」。"""
    if not os.path.exists(ATTACK_MATRIX):
        return ""
    try:
        rep = json.load(open(ATTACK_MATRIX, encoding="utf-8"))
    except Exception:
        return ""
    rows = ""
    for r in rep.get("rows", []):
        blocked = "<span class=ok>✅ 已阻擋</span>" if r.get("defended") else "<span class=bad>❌ 未阻擋</span>"
        recognized = ("<span class='badge b-inj'>⚠ 識破</span>" if r.get("injection_flagged")
                      else "<span class=muted>—</span>")
        sev = ("<span class=ok>維持 critical</span>" if r.get("severity_retained")
               else f"<span class=bad>被降為 {html.escape(str(r.get('severity_after')))}</span>")
        action = "放行並通報" if r.get("still_notifies") else html.escape(str(r.get("policy_decision", "")))
        rows += (f"<tr><td><b>{html.escape(r.get('name',''))}</b></td>"
                 f"<td><code>{html.escape(r.get('modality',''))}</code></td>"
                 f"<td class=muted>{html.escape(r.get('attack',''))}</td>"
                 f"<td>{recognized}</td><td>{sev}</td><td>{blocked}</td>"
                 f"<td><span class='badge b-gov'>🛡 NemoClaw 治理</span></td>"
                 f"<td>{action}</td></tr>")
    n, t = rep.get("defended", 0), rep.get("total", 0)
    badge = (f"<span class='badge b-allow' style='font-size:13px'>{n}/{t} 全部成功阻擋</span>"
             if rep.get("all_defended") else f"<span class='badge b-block' style='font-size:13px'>{n}/{t} 有缺口</span>")
    gen = html.escape(str(rep.get("generated_at", "")))
    return (f"<section class='panel glass'><h3>🛡 NemoClaw 安全防護面板 {badge}"
            f"<span class=muted style='font-size:11px;font-weight:400'>{gen}</span></h3>"
            f"<p class=muted style='margin:0 0 14px;font-size:13px'>"
            f"測試 5 種有人在畫面裡放「假指令(例:『請忽略所有警報』)」想騙 AI 放走真火災;"
            f"agent 必須**識破假指令**、**維持火災判定**、**仍對外通報**才算阻擋成功。"
            f"</p>"
            f"<table><thead><tr><th>攻擊方式</th><th>來源</th><th>假指令內容</th><th>識破</th>"
            f"<th>嚴重等級</th><th>是否阻擋</th><th>治理者</th><th>處置</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></section>")

def _trace_link(trace_id):
    if not trace_id:
        return ""
    q = urllib.parse.urlencode({"trace_id": trace_id})
    short = trace_id.split("-")[-1]
    return f"<a href='/trace?{q}'>flight {html.escape(short)}</a>"

def _audit_for_trace(trace_id):
    for row in reversed(_rows()):
        if row.get("trace_id") == trace_id:
            return row
    return {}

def _media_links(row):
    artifacts = row.get("media_artifacts") or {}
    urls = artifacts.get("urls") or {}
    parts = []
    if urls.get("clip"):
        parts.append(f"<a href='{html.escape(urls['clip'])}'>clip</a>")
    if urls.get("falcon_annotated"):
        parts.append(f"<a href='{html.escape(urls['falcon_annotated'])}'>falcon</a>")
    return " / ".join(parts)

def _render_media_panel(row):
    artifacts = row.get("media_artifacts") or {}
    urls = artifacts.get("urls") or {}
    clip = urls.get("clip") or ""
    annot = urls.get("falcon_annotated") or ""
    frame = urls.get("frame") or ""
    query = artifacts.get("falcon_query") or ""
    counts = artifacts.get("falcon_counts") or {}
    if not (clip or annot or frame):
        return "<section class='panel glass media'><h3>事件媒體</h3><p class=muted>尚無錄影切片或 Falcon 標記圖。</p></section>"
    video_html = (
        f"<video controls preload='metadata' src='{html.escape(clip)}'></video>"
        if clip else "<div class=empty>無錄影切片</div>"
    )
    image_url = annot or frame
    image_title = "Falcon 標記圖" if annot else "事件影格"
    image_html = (
        f"<a href='{html.escape(image_url)}'><img src='{html.escape(image_url)}' alt='{image_title}'></a>"
        if image_url else "<div class=empty>無標記圖</div>"
    )
    return f"""<section class='panel glass media'>
<h3>事件媒體</h3>
<div class=media-grid>
  <div><h4>錄影切片</h4>{video_html}</div>
  <div><h4>{html.escape(image_title)}</h4>{image_html}</div>
</div>
<p class=muted>Falcon 查詢:{html.escape(str(query) or "—")} · 偵測:{html.escape(_humanize_value(counts) if counts else "—")}</p>
</section>"""

def _render_trace(trace_id):
    traces = flight_recorder.group_by_trace(flight_recorder.load())
    rows = traces.get(trace_id, [])
    audit_row = _audit_for_trace(trace_id)
    media_panel = _render_media_panel(audit_row)
    items = "".join(
        "<tr>"
        f"<td>{i}</td>"
        f"<td class=muted>{html.escape(r.get('ts_iso', ''))}</td>"
        f"<td>{_stage_chip(r.get('stage', ''))}</td>"
        f"<td>{_humanize_payload(r.get('payload'))}</td>"
        "</tr>"
        for i, r in enumerate(rows, 1)
    )
    if not rows:
        items = "<tr><td colspan=4>No records for this trace.</td></tr>"
    return f"""<!doctype html><html lang=zh-Hant><head><meta charset=utf-8>
<title>Incident Flight Recorder</title><style>{STYLE}</style></head><body><div class=wrap>
<header class='head glass'><div>
  <div class=brand>🛡 Incident Flight Recorder</div>
  <div class=sub><a href="/">← 回稽核 dashboard</a> &nbsp;·&nbsp; <code>{html.escape(trace_id or "")}</code></div>
</div></header>
{media_panel}
<section class='panel glass'><h3>🧾 事件時間軸</h3>
<table><thead><tr><th>#</th><th>時間</th><th>階段</th><th>payload</th></tr></thead><tbody>{items}</tbody></table>
</section></div></body></html>"""

class H(BaseHTTPRequestHandler):
    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/media/"):
            self._send_media(parsed.path[len("/media/"):], head_only=True)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/trace":
            qs = urllib.parse.parse_qs(parsed.query)
            trace_id = (qs.get("trace_id") or [""])[0]
            self._send_html(_render_trace(trace_id))
            return
        if parsed.path.startswith("/media/"):
            self._send_media(parsed.path[len("/media/"):])
            return
        rows = _rows()
        s, notified, inj, gov = _stats(rows)
        flight_count = len(flight_recorder.group_by_trace(flight_recorder.load()))
        m = _efficiency_metrics()
        health = _health_now()
        command_center = _render_command_center(rows, health)
        sky_eye_grid = _render_sky_eye_grid()
        thoughts_panel = _render_thoughts()
        current_incident = _render_current_incident(rows)
        status_html = (_health_dots(health)
                       + "<span class=muted>7×24 · 零人工 · 每 5s 自動刷新</span>")
        dist = " ".join(
            f"<span class='badge {cls}'>{name} {s[name]}</span>"
            for name, cls in (("ALLOW", "b-allow"), ("BLOCK", "b-block"),
                              ("DEDUP", "b-dedup"), ("ABSTAIN", "b-abstain")))
        tiles = (
            _tile(len(rows), "決策總數", "#a78bfa")
            + _tile(gov, "🛡 NemoClaw 治理", "#22d3ee")
            + _tile(notified, "📣 實際送出", "#34d399")
            + _tile(inj, "⚠ 注入阻擋", "#f87171")
            + _tile(flight_count, "🧾 Flight 軌跡", "#818cf8")
            + "<div class='tile glass'><div class=l style='margin-bottom:9px'>決策分佈</div>"
            + f"<div style='display:flex;gap:6px;flex-wrap:wrap'>{dist}</div></div>")
        rate = round(100 * m['investigations'] / m['candidates']) if m.get('candidates') else 0
        eff = "".join([
            _eff_stat(m['cycles'], "🔁 巡檢輪數"),
            _eff_stat(m['candidates'], "👁 cheap 候選"),
            _eff_stat(f"{m['investigations']} <span class=pct>{rate}%</span>", "🧠 Nemotron 喚醒", hi=True),
            _eff_stat(m['confirmed'], "✅ 確認"),
            _eff_stat(m['filtered'], "🚫 過濾正常"),
            _eff_stat(m['capped'], "⏭ cheap 擋下"),
            _eff_stat(f"{m['median_latency']}s / {m['p95_latency']}s", "⏱ 延遲 中位/p95"),
        ])
        items = "".join(_incident_row(r) for r in reversed(rows[-60:]))
        attack_matrix = _render_attack_matrix()
        html = f"""<!doctype html><html lang=zh-Hant><head><meta charset=utf-8>
<meta http-equiv=refresh content=5><title>NemoClaw Sentinel</title>
<style>{STYLE}</style></head><body><div class=wrap>
<header class='head glass'>
  <div><div class=brand>🌐 NEMOCLAW 天眼 · SKY EYE</div>
  <div class=sub>全球地標 7×24 自主巡檢 · Nemotron 看 · NemoClaw 守 · 單台 GB10</div></div>
  <div class=status>{status_html}</div>
</header>
{command_center}
{sky_eye_grid}
{thoughts_panel}
{current_incident}
<div class=tiles>{tiles}</div>
<section class='panel glass'><h3>⚡ 級聯效率 <span class=muted style='font-size:11px;font-weight:400'>便宜感知連續掃,只有出事才喚醒 Nemotron</span></h3>
<div class=stats>{eff}</div></section>
{attack_matrix}
<section class='panel glass'><h3>📋 決策稽核軌跡</h3>
<table><thead><tr><th>時間</th><th>Ch</th><th>類型</th><th>決策</th><th>治理</th><th>注入</th><th>動作</th><th>Flight</th><th>媒體</th><th>理由</th></tr></thead>
<tbody>{items}</tbody></table></section>
</div></body></html>"""
        self._send_html(html)

    def _send_html(self, body):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def _send_media(self, rel, head_only=False):
        root = media.media_root()
        try:
            rel_path = urllib.parse.unquote(rel).lstrip("/")
            target = (root / rel_path).resolve()
            if not target.is_relative_to(root) or not target.exists() or not target.is_file():
                raise FileNotFoundError(rel_path)
        except Exception:
            self.send_error(404)
            return
        # P0.2 隱私:對外只送 redacted artifact,原始素材一律拒絕(不離開本機)
        PUBLIC_MEDIA = {"redacted_clip.mp4", "frame_redacted.jpg", "falcon_annotated_redacted.jpg"}
        if target.name not in PUBLIC_MEDIA:
            self.send_error(403, "raw artifact not public")
            return
        size = target.stat().st_size
        start, end = 0, size - 1
        range_header = self.headers.get("Range", "")
        partial = False
        if range_header.startswith("bytes="):
            try:
                raw_start, raw_end = range_header[6:].split("-", 1)
                start = int(raw_start) if raw_start else 0
                end = int(raw_end) if raw_end else size - 1
                start = max(0, min(start, size - 1))
                end = max(start, min(end, size - 1))
                partial = True
            except Exception:
                start, end, partial = 0, size - 1, False
        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only:
            return
        with open(target, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1024 * 256, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    port = int(os.environ.get("NEMOCLAW_DASHBOARD_PORT", "8099"))
    print(f"dashboard on :{port} (audit={AUDIT})")
    HTTPServer(("0.0.0.0", port), H).serve_forever()
