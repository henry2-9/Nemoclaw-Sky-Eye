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
import wall_snapshots
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
try:
    import register_channels as _register_channels
except Exception:
    _register_channels = None
try:
    import correlation as _correlation
except Exception:
    _correlation = None
try:
    import hermes_followup as _followup
except Exception:
    _followup = None

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


def _runtime_flight_rows():
    """Dashboard statistics exclude deterministic unit-test traces accidentally written by old runs."""
    synthetic = {"t1", "t-high", "t-crit"}
    return [r for r in flight_recorder.load() if r.get("trace_id") not in synthetic]


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
        by = flight_recorder.group_by_trace(_runtime_flight_rows())
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
SEVERITY_ZH = {"critical": "嚴重", "high": "高", "medium": "中", "low": "低"}


def _sev_zh(s):
    return SEVERITY_ZH.get(str(s or "").lower(), str(s or "—"))

# ── 深色玻璃擬態主題(主頁與 trace 頁共用)──
STYLE = """
*{box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,-apple-system,'Noto Sans TC',sans-serif;margin:0;
  min-height:100vh;color:#edf0f2;background:#0a0f12}
.wrap{max-width:1460px;margin:0 auto;padding:20px 22px 52px}
a{color:#7fd6ff;text-decoration:none} a:hover{text-decoration:underline}
code{color:#a7f3d0;background:rgba(255,255,255,.06);padding:1px 6px;border-radius:6px;font-size:12px}
.glass{background:#10171c;border:1px solid #253039;border-radius:8px;
  box-shadow:0 8px 20px rgba(0,0,0,.22)}
.head{display:flex;justify-content:space-between;align-items:center;gap:16px;
  padding:18px 24px;margin-bottom:20px;flex-wrap:wrap}
.brand{font-size:23px;font-weight:800;letter-spacing:0;color:#eef4f4}
.sub{color:#9aa3c7;font-size:12.5px;margin-top:3px}
.status{display:flex;gap:15px;flex-wrap:wrap;font-size:12.5px;color:#c7cdf0;align-items:center}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;
  background:#34d399;box-shadow:0 0 9px #34d399;animation:pulse 2.4s infinite}
.dot.off{background:#f87171;box-shadow:0 0 9px #f87171;animation:none}
.dot.unknown{background:#94a3b8;box-shadow:none;animation:none}
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
th{color:#aab2da;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:0}
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
.tag{font-size:11px;font-weight:700;padding:3px 8px;border-radius:5px;text-transform:uppercase;letter-spacing:0}
.tag-live{background:#113126;color:#47db9a;border:1px solid #285a46}
.tag-test{background:#382122;color:#ff8c8c;border:1px solid #6f3638}
.primary-grid{display:grid;grid-template-columns:minmax(610px,1.6fr) minmax(340px,.82fr);gap:16px;align-items:start}
.primary-grid .panel{margin-bottom:0}
.ops{display:grid;grid-template-columns:repeat(5,minmax(125px,1fr));gap:1px;background:#253039;
  border:1px solid #253039;border-radius:8px;overflow:hidden;margin:16px 0}
.op{background:#10171c;padding:12px 15px}.op-label{display:block;color:#8d9aa3;font-size:11px;margin-bottom:5px}
.op strong{font-size:17px;color:#eef4f4}.op strong.good{color:#47db9a}
.op-note{font-size:11px;color:#8d9aa3;margin-top:4px}
.drill video{display:block;width:100%;height:auto;aspect-ratio:16/10;max-height:none;object-fit:cover;border-radius:6px}
.drill-result{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px}
.drill-result div{padding:9px 8px;background:#151e24;border-radius:6px;text-align:center}
.drill-result span{display:block;color:#8d9aa3;font-size:11px;margin-bottom:4px}
.drill-result strong{font-size:13px}
.drill-actions{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-top:12px;font-size:12px}
.cta{display:inline-flex;align-items:center;padding:8px 12px;background:#18323b;border:1px solid #2c6472;border-radius:6px;font-weight:700}
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
.wall-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap;margin-bottom:14px}
.wall-head h3{margin-bottom:0}
.wall-totals{display:flex;gap:8px;flex-wrap:wrap}
.wall-layout{display:grid;grid-template-columns:minmax(360px,1.28fr) minmax(300px,1fr);gap:14px;align-items:start}
.wall-focus{padding:10px;border:1px solid #26323a;border-radius:6px;background:#0b1115}
.wall-focus-media,.se-thumb{aspect-ratio:16/9;background:rgba(0,0,0,.32);border-radius:6px;overflow:hidden}
.wall-focus-media img,.se-thumb img{height:100%;max-height:none;border:0;border-radius:0;object-fit:cover}
.wall-empty{height:100%;display:flex;align-items:center;justify-content:center;color:#8b93b8;font-size:12px;border:1px dashed rgba(255,255,255,.13);border-radius:6px}
.wall-focus-meta{display:flex;justify-content:space-between;gap:12px;margin-top:10px;align-items:flex-start}
.wall-focus-name{font-size:16px;font-weight:700;color:#e2e6ff;line-height:1.35}
.wall-rule{font-size:12px;color:#9aa3c7;margin-top:6px}
.se-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.se-tile{display:block;padding:7px;position:relative;border:1px solid #253039;border-left:3px solid var(--state);border-radius:6px;background:#121b20}
.se-tile:hover{background:rgba(255,255,255,.08);text-decoration:none}
.se-tile.active{border-color:var(--state);background:rgba(255,255,255,.08)}
.se-id{color:#7d86ad;font-size:11px;font-family:ui-monospace,monospace}
.se-name{color:#e2e6ff;font-size:12.5px;font-weight:600;margin:7px 0 5px;line-height:1.3;min-height:33px}
.se-status{font-size:12px;font-weight:700}
.se-ts{color:#7d86ad;font-size:11px;margin-top:3px;font-family:ui-monospace,monospace}
@media (max-width:860px){.wall-layout{grid-template-columns:1fr}.se-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:1100px){.primary-grid{grid-template-columns:1fr}.ops{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:520px){.se-grid{grid-template-columns:1fr}.wall-layout{display:block}.wall-focus{margin-bottom:12px}.ops{grid-template-columns:repeat(2,minmax(0,1fr))}}
details.drawer{margin-top:18px;border-top:1px solid #253039;padding-top:14px}
details.drawer summary{cursor:pointer;display:inline-flex;padding:9px 13px;color:#b4c0c7;
  border:1px solid #29363d;border-radius:6px;background:#10171c;font-weight:600}
details.drawer[open] summary{margin-bottom:16px}
details.audit-more{margin-top:10px}
details.audit-more summary{cursor:pointer;padding:8px 12px;border-radius:8px;
  background:rgba(255,255,255,.04);color:#9aa3c7;font-size:12.5px;user-select:none;list-style:none}
details.audit-more summary::before{content:'▸ ';color:#7d86ad}
details.audit-more[open] summary::before{content:'▾ '}
details.audit-more summary:hover{background:rgba(255,255,255,.08);color:#e2e6ff}
details.audit-more[open] summary{background:rgba(255,255,255,.06);color:#e2e6ff;margin-bottom:6px}
details.audit-more table{font-size:12.5px}
.corr-grid{display:grid;gap:10px}
.corr-card{background:rgba(245,158,11,.06);border:1px solid rgba(245,158,11,.35);
  border-radius:10px;padding:10px 12px}
.corr-card.crit{background:rgba(248,113,113,.08);border-color:rgba(248,113,113,.45)}
.corr-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.corr-head .et{font-weight:700;color:#fed7aa;font-size:14px}
.corr-head.crit .et{color:#fecaca}
.corr-meta{font-size:11.5px;color:#9aa3c7}
.corr-ev{font-size:12px;color:#cbd5e1;margin-top:4px;padding-left:8px;border-left:2px solid rgba(255,255,255,.1)}
.corr-ev div{padding:2px 0}
.fu-grid{display:grid;gap:12px}
.fu-card{background:rgba(34,211,238,.05);border:1px solid rgba(34,211,238,.3);
  border-radius:10px;padding:11px 13px}
.fu-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.fu-head .ch{font-weight:700;color:#a5f3fc;font-size:14px}
.fu-conc{font-size:12.5px;color:#e2e8f0;margin:6px 0;line-height:1.5}
.fu-cmds{font-family:ui-monospace,Consolas,monospace;font-size:11.5px;
  background:rgba(0,0,0,.3);border-radius:6px;padding:8px;color:#cbd5e1;margin-top:6px}
.fu-cmds .c{color:#7dd3fc;margin-top:6px}.fu-cmds .c:first-child{margin-top:0}
.fu-cmds .p{color:#94a3b8;font-size:11px;margin-left:14px}
.fu-cmds .o{color:#d1d5db;margin-left:14px;white-space:pre-wrap;max-height:80px;overflow:auto}
.fu-foot{display:flex;gap:10px;font-size:11px;color:#9aa3c7;margin-top:6px;flex-wrap:wrap}
.fu-foot .gov{color:#67e8f9}
.fu-foot .plan-auto{color:#86efac;background:rgba(34,197,94,.1);padding:2px 7px;border-radius:6px}
.fu-foot .plan-fallback{color:#fbbf24;background:rgba(245,158,11,.1);padding:2px 7px;border-radius:6px}
.fu-foot .plan-multi{color:#c4b5fd;background:rgba(139,92,246,.1);padding:2px 7px;border-radius:6px}
.tag-unlinked{background:#292f35;color:#cbd5e1;border:1px solid #46515b}
.fu-warning{color:#fbbf24;background:rgba(245,158,11,.10);border:1px solid rgba(245,158,11,.30);
  border-radius:6px;padding:7px 9px;margin:8px 0;font-size:12px}
.fu-unlinked{margin-top:12px}
.fu-unlinked summary{cursor:pointer;color:#cbd5e1;font-size:13px;padding:8px 10px;
  background:rgba(255,255,255,.04);border-radius:6px;list-style:none}
.fu-unlinked[open] summary{margin-bottom:10px}
.fu-verdict{margin:8px 0;background:rgba(0,0,0,.25);border-radius:8px;padding:8px 10px}
.fu-verdict .vr{font-size:12.5px;line-height:1.65;padding:2px 0}
.fu-verdict .vr-confirm{color:#86efac}
.fu-verdict .vr-refute{color:#fca5a5}
.fu-verdict .vr-nosig{color:#9aa3c7}
.fu-verdict .vr-final{color:#fed7aa;font-weight:600;border-top:1px solid rgba(255,255,255,.08);
  margin-top:4px;padding-top:6px}
.fu-verdict .vr-advice{color:#a5f3fc}
.fu-verdict .vr-misc{color:#cbd5e1}
/* 主頁監控牆(暗色 glass) */
.wd-head{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:14px}
.wd-head h3{margin:0}
.wd-tools{display:flex;gap:14px;align-items:center;flex-wrap:wrap}
.lay-chooser{display:flex;gap:5px;align-items:center;font-size:12px;color:#9aa3c7}
.lay-btn{background:rgba(255,255,255,.05);border:1px solid #2a3640;color:#c7cdf0;
  padding:3px 10px;border-radius:5px;font-weight:600;text-decoration:none;font-size:12px}
.lay-btn:hover{background:rgba(255,255,255,.1);text-decoration:none}
.lay-btn.on{background:#10b981;color:#0a0f12;border-color:#10b981}
.wd-grid{display:grid;gap:10px}
.wd-cell{position:relative;aspect-ratio:16/9;background:#1a2128;border-radius:6px;
  background-size:cover;background-position:center;overflow:hidden;
  border:1px solid #2a3640;display:flex;align-items:center;justify-content:center;
  text-decoration:none}
.wd-cell:hover{border-color:#34d399;text-decoration:none}
.wd-cell.empty{background:#10171c;border:1px dashed #2a3640}
.wd-placeholder{width:9px;height:9px;border-radius:50%;background:#4b5563}
.wd-chip{position:absolute;top:6px;left:6px;display:flex;align-items:center;gap:6px;
  background:rgba(0,0,0,.7);color:#edf0f2;font-size:11px;font-weight:600;
  padding:3px 8px;border-radius:4px;max-width:calc(100% - 80px);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;backdrop-filter:blur(4px)}
.wd-chip .wd-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;background:#34d399;
  box-shadow:0 0 5px #34d399;animation:pulse 2.4s infinite}
.wd-chip .wd-dot.off{background:#f87171;box-shadow:0 0 5px #f87171;animation:none}
.wd-chip .wd-dot.unknown{background:#94a3b8;box-shadow:none;animation:none}
.wd-ts{position:absolute;top:6px;right:6px;background:rgba(0,0,0,.7);color:#edf0f2;
  font-size:10.5px;padding:2px 6px;border-radius:3px;font-family:ui-monospace,Consolas,monospace;
  backdrop-filter:blur(4px)}
/* 主頁右側即時事件 panel(暗色) */
.dev-list{display:flex;flex-direction:column;gap:6px;max-height:520px;overflow-y:auto}
.dev{background:rgba(255,255,255,.03);border-left:3px solid #4b5563;border-radius:6px;
  padding:9px 12px;font-size:12.5px;line-height:1.55}
.dev.sev-critical{border-left-color:#f87171;background:rgba(248,113,113,.07)}
.dev.sev-high{border-left-color:#fbbf24;background:rgba(251,191,36,.07)}
.dev.sev-medium{border-left-color:#60a5fa;background:rgba(96,165,250,.06)}
.dev-ts{color:#9aa3c7;font-size:10.5px;font-family:ui-monospace,Consolas,monospace;display:flex;
  justify-content:space-between;align-items:center;margin-bottom:2px}
.dev-name{color:#edf0f2;font-weight:600;margin:1px 0}
.dev-sum{color:#c7cdf0;font-size:12px}
.dev-empty{padding:32px 14px;text-align:center;color:#6b7280;font-size:12.5px}
.dev a{color:#7fd6ff;text-decoration:none;font-size:11px}
.dev a:hover{text-decoration:underline}
/* 監控牆 /wall */
body.wall-body{background:#f5f6f7;color:#1f2937}
.wall-wrap{max-width:1760px;margin:0 auto;padding:18px 22px 28px}
.whead{display:flex;justify-content:space-between;align-items:flex-end;
  margin-bottom:18px;gap:20px;flex-wrap:wrap}
.whead h1{margin:0;font-size:22px;color:#111827;font-weight:800}
.whead .wsub{color:#6b7280;font-size:13px;margin-top:4px}
.lay-chooser{display:flex;gap:6px;align-items:center;font-size:13px;color:#374151}
.lay-chooser a{background:#fff;border:1px solid #d1d5db;color:#374151;
  padding:5px 12px;border-radius:6px;font-weight:600;text-decoration:none}
.lay-chooser a:hover{background:#f3f4f6}
.lay-chooser a.on{background:#10b981;color:#fff;border-color:#10b981}
.wmain{display:grid;grid-template-columns:1fr 280px;gap:14px}
@media (max-width:980px){.wmain{grid-template-columns:1fr}}
.wgrid{display:grid;gap:10px}
.wcell{position:relative;aspect-ratio:16/9;background:#9ca3af;border-radius:6px;
  background-size:cover;background-position:center;overflow:hidden;
  border:1px solid #9ca3af;display:flex;align-items:center;justify-content:center}
.wcell.empty{background:#9ca3af;border:2px dashed #6b7280}
.wcell .placeholder-dot{width:10px;height:10px;border-radius:50%;background:#4b5563}
.wchip{position:absolute;top:6px;left:6px;display:flex;align-items:center;gap:6px;
  background:rgba(17,24,39,.78);color:#fff;font-size:11.5px;font-weight:600;
  padding:4px 9px;border-radius:5px;max-width:calc(100% - 90px);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wchip .wdot{width:8px;height:8px;border-radius:50%;flex-shrink:0;background:#10b981;
  box-shadow:0 0 6px #10b981}
.wchip .wdot.off{background:#ef4444;box-shadow:0 0 6px #ef4444}
.wchip .wdot.unknown{background:#9ca3af;box-shadow:none}
.wts{position:absolute;top:6px;right:6px;background:rgba(17,24,39,.78);color:#fff;
  font-size:11px;padding:3px 7px;border-radius:4px;font-family:ui-monospace,Consolas,monospace}
.wside{background:#fff;border:1px solid #e5e7eb;border-radius:8px;display:flex;flex-direction:column;
  max-height:calc(100vh - 140px);overflow:hidden}
.whdr{padding:14px 16px;border-bottom:1px solid #e5e7eb;font-weight:700;color:#111827;
  font-size:14px;background:#f9fafb;border-radius:8px 8px 0 0}
.wfeed{flex:1;overflow-y:auto;padding:8px}
.wev{padding:10px 12px;border-radius:6px;margin-bottom:6px;background:#f9fafb;
  border-left:3px solid #d1d5db;font-size:12.5px;line-height:1.5}
.wev.sev-critical{border-left-color:#dc2626;background:#fef2f2}
.wev.sev-high{border-left-color:#f59e0b;background:#fffbeb}
.wev.sev-medium{border-left-color:#3b82f6;background:#eff6ff}
.wev-ts{color:#6b7280;font-size:11px;font-family:ui-monospace,Consolas,monospace}
.wev-name{color:#111827;font-weight:600;margin:2px 0}
.wev-sum{color:#374151}
.wev-empty{padding:40px 16px;text-align:center;color:#9ca3af;font-size:13px}
.wnav{display:flex;gap:6px;font-size:12.5px}
.wnav a{color:#6b7280;text-decoration:none}
.wnav a:hover{color:#10b981}
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


def _supervisor_started_at():
    log = os.path.join(_NEMODIR, "supervisor.log")
    try:
        with open(log, encoding="utf-8") as f:
            starts = [line for line in f if "supervisor start" in line]
        if starts:
            return datetime.datetime.fromisoformat(starts[-1].split()[0])
    except Exception:
        pass
    return None


def _uptime_str():
    start = _supervisor_started_at()
    if start:
        secs = (datetime.datetime.now(start.tzinfo) - start).total_seconds()
        return f"{int(secs // 3600)}h {int((secs % 3600) // 60)}m"
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
        state = health.get(k)
        cls = "" if state == "up" else (" off" if state == "down" else " unknown")
        suffix = "" if state == "up" else (" 異常" if state == "down" else " 未知")
        out.append(f"<span><span class='dot{cls}'></span>{label}{suffix}</span>")
    return "".join(out)


def _cascade_html():
    all_rows = _runtime_flight_rows()
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
    live_rows = [r for r in rows if r.get("trigger_origin") == "scheduled"]
    scheduled = len(live_rows)
    demos = sum(1 for r in rows if r.get("trigger_origin") == "demo_manual")
    uptime = _uptime_str()
    health = health if health is not None else _health_now()
    now = time.time()
    active_live = [r for r in live_rows if r.get("decision") == "ALLOW"
                   and (now - r.get("ts", 0)) <= 3600]
    live_label, live_color = (_threat(active_live, now=now) if active_live
                              else ("無現行警報", "#34d399"))
    demo = _latest_demo_row(rows)
    demo_label = _sev_zh(demo.get("severity")) if demo else "—"
    demo_color = _THREAT[_SEV_RANK.get((demo or {}).get("severity"), 0)][1]
    demo_ts = str((demo or {}).get("ts_iso", "")).replace("T", " ")[:16] or "尚無演練"
    service_ok = all(health.get(k) == "up" for k in ("nemotron", "falcon", "nemoclaw")) if health else False
    service = "正常" if service_ok else ("異常" if health else "未知")
    service_cls = "good" if service_ok else ("bad" if health else "")
    return f"""<section class=ops>
  <div class=op><span class=op-label>服務</span><strong class='{service_cls}'>{service}</strong></div>
  <div class=op><span class=op-label>處置模式</span><strong class=good>自動</strong></div>
  <div class=op><span class=op-label>運行時間</span><strong>{uptime}</strong></div>
  <div class=op><span class=op-label>LIVE 狀態</span><strong style='color:{live_color}'>{live_label}</strong>
    <div class=op-note>累計確認 {scheduled} 起</div></div>
  <div class=op><span class=op-label>TEST 最近結果</span><strong style='color:{demo_color}'>{demo_label}</strong>
    <div class=op-note>{html.escape(demo_ts)} · 共 {demos} 筆</div></div>
</section>"""


_THOUGHT_TAGS = {
    "sweep": ("👁", "#7dd3fc"), "baseline": ("📊", "#fbbf24"),
    "curiosity": ("🔎", "#a78bfa"), "investigate": ("🧠", "#22d3ee"),
    "decision": ("🛡", "#34d399"), "watchdog": ("🩺", "#fb923c"),
    "briefing": ("🗒", "#c4b5fd"), "agent": ("🤖", "#9aa3c7"),
}


def _render_sky_eye_grid(selected_channel=None, layout=16):
    """N×N 監控牆視覺(暗色 glass,首頁主視角)。layout ∈ {1,4,6,9,16,25}。
    每 cell 為 16:9 snapshot + 左上 chip(LED+名稱)+ 右上 ts;沒 snapshot 顯示中央灰點。"""
    if not _feed_health or not _register_channels:
        return ""
    active_marker = os.path.join(_NEMODIR, "active_channels_file")
    active_file = os.environ.get("NEMOCLAW_CHANNELS_FILE", "")
    try:
        marked = open(active_marker, encoding="utf-8").read().strip()
        active_file = marked or active_file
    except OSError:
        pass
    if not active_file:
        return ""
    try:
        channels = _register_channels.load_channels(
            active_file,
            merge_discovered=_register_channels.discovery_enabled(),
        )
    except Exception:
        return ""
    full = _feed_health.state()
    if not channels:
        return ""
    source_name = {
        "landmarks.yaml": "全球地標天眼",
        "world_channels.yaml": "世界路口交通來源",
        "channels.yaml": "本地 Replay",
    }.get(os.path.basename(active_file), "已設定來源")
    entries = []
    for c in channels:
        k = str(c.get("id", ""))
        v = full.get(k, {"name": c.get("name", ""), "last": "", "ok": None})
        entries.append((c, k, v, wall_snapshots.preview(k)))
    online = sum(1 for _, _, v, _ in entries if v.get("ok") is True)
    offline = sum(1 for _, _, v, _ in entries if v.get("ok") is False)
    pending = len(entries) - online - offline

    layout = layout if layout in _WALL_LAYOUTS else 16
    cols = _WALL_LAYOUTS[layout]

    cells = []
    for i in range(layout):
        if i < len(entries):
            c, k, v, snap = entries[i]
            name = html.escape((c.get("name") or "")[:36])
            ok = v.get("ok")
            dot = "on" if ok is True else ("off" if ok is False else "unknown")
            ts = ""
            if snap and snap.get("captured_at"):
                ts = html.escape(str(snap["captured_at"])[-8:])
            elif v.get("last"):
                ts = html.escape(str(v["last"])[-8:])
            if snap and snap.get("url"):
                version = urllib.parse.quote(str(snap.get("captured_at", "")))
                bg = f"style=\"background-image:url('{html.escape(snap['url'])}?v={version}')\""
                center = ""
            else:
                bg = ""
                center = "<div class=wd-placeholder></div>"
            ts_html = f"<div class=wd-ts>{ts}</div>" if ts else ""
            cells.append(
                f"<a class=wd-cell href='/trace?trace_id=' {bg}>"
                f"<div class=wd-chip><span class='wd-dot {dot}'></span>{name}</div>"
                f"{ts_html}{center}</a>")
        else:
            cells.append("<div class='wd-cell empty'><div class=wd-placeholder></div></div>")

    chooser = "".join(
        f"<a class='lay-btn{' on' if n == layout else ''}' "
        f"href='/?layout={n}'>{n}</a>"
        for n in (1, 4, 6, 9, 16, 25))

    totals = (
        f"<span class='badge b-gov'>監看 {len(entries)}</span>"
        f"<span class='badge b-allow'>正常 {online}</span>"
        f"<span class='badge b-block'>離線 {offline}</span>"
        f"<span class='badge b-dedup'>待檢 {pending}</span>"
    )
    return (f"<section class='panel glass'><div class=wd-head>"
            f"<h3><span class='tag tag-live'>LIVE</span> {html.escape(source_name)} "
            f"<span class=muted style='font-size:11px;font-weight:400'>正常巡檢</span></h3>"
            f"<div class=wd-tools>{totals}"
            f"<span class=lay-chooser>版面 {chooser}</span></div></div>"
            f"<div class=wd-grid style='grid-template-columns:repeat({cols},1fr)'>"
            f"{''.join(cells)}</div></section>")


_WALL_LAYOUTS = {1: 1, 4: 2, 6: 3, 9: 3, 16: 4, 25: 5}


def _wall_entries():
    """Reuse the sky-eye-grid logic to pull active channels + snapshots."""
    if not _feed_health or not _register_channels:
        return [], ""
    active_marker = os.path.join(_NEMODIR, "active_channels_file")
    active_file = os.environ.get("NEMOCLAW_CHANNELS_FILE", "")
    try:
        marked = open(active_marker, encoding="utf-8").read().strip()
        active_file = marked or active_file
    except OSError:
        pass
    if not active_file:
        return [], ""
    try:
        channels = _register_channels.load_channels(
            active_file, merge_discovered=_register_channels.discovery_enabled())
    except Exception:
        return [], ""
    full = _feed_health.state()
    entries = []
    for c in channels:
        k = str(c.get("id", ""))
        v = full.get(k, {"name": c.get("name", ""), "last": "", "ok": None})
        entries.append((c, k, v, wall_snapshots.preview(k)))
    return entries, active_file


def _wall_events(rows, limit=12):
    """Pull recent severity ≥ medium audit rows for the right-side feed."""
    out = []
    for r in reversed(rows):
        sev = (r.get("severity") or "").lower()
        if sev not in ("medium", "high", "critical"):
            continue
        ts = (r.get("ts_iso") or "")[-8:]
        ch = r.get("channel") or ""
        name = ""
        for cand in (r.get("channel_name"), (r.get("media_artifacts") or {}).get("channel_name")):
            if cand:
                name = cand; break
        if not name:
            name = f"ch{ch}"
        out.append({"ts": ts, "channel": ch, "name": name, "severity": sev,
                    "summary": (r.get("summary") or "")[:120],
                    "trace_id": r.get("trace_id", "")})
        if len(out) >= limit:
            break
    return out


def _render_wall_page(layout=16):
    """Pure surveillance-wall view at /wall.  N×N camera grid + right-side live event feed."""
    layout = layout if layout in _WALL_LAYOUTS else 16
    cols = _WALL_LAYOUTS[layout]
    entries, active_file = _wall_entries()
    source_label = {
        "landmarks.yaml": "全球地標天眼",
        "world_channels.yaml": "世界路口/道路監視器",
        "channels.yaml": "本地 Replay",
    }.get(os.path.basename(active_file or ""), "已設定來源")

    cells = []
    for i in range(layout):
        if i < len(entries):
            c, k, v, snap = entries[i]
            name = html.escape((c.get("name") or "")[:36])
            ok = v.get("ok")
            dot = "on" if ok is True else ("off" if ok is False else "unknown")
            ts = html.escape((snap.get("captured_at", "") if snap else "")[-8:])
            if snap and snap.get("url"):
                bg = f"style=\"background-image:url('{html.escape(snap['url'])}')\""
                center = ""
            else:
                bg = ""
                center = "<div class=placeholder-dot></div>"
            ts_html = f"<div class=wts>{ts}</div>" if ts else ""
            cells.append(
                f"<div class=wcell {bg}><div class=wchip>"
                f"<span class='wdot {dot}'></span>{name}</div>{ts_html}{center}</div>")
        else:
            cells.append("<div class='wcell empty'><div class=placeholder-dot></div></div>")

    rows = _rows()
    events = _wall_events(rows, limit=12)
    if events:
        feed_html = "".join(
            f"<div class='wev sev-{e['severity']}'>"
            f"<div class=wev-ts>{html.escape(e['ts'])} · ch{html.escape(str(e['channel']))} · "
            f"{_sev_zh(e['severity'])}</div>"
            f"<div class=wev-name>{html.escape(e['name'])}</div>"
            f"<div class=wev-sum>{html.escape(e['summary'])}</div></div>"
            for e in events)
    else:
        feed_html = "<div class=wev-empty>等待後端推送或稍後再試</div>"

    chooser = "".join(
        f"<a class='{('on' if n == layout else '')}' href='/wall?layout={n}'>{n}</a>"
        for n in (1, 4, 6, 9, 16, 25))

    return f"""<!doctype html><html lang=zh-Hant><head><meta charset=utf-8>
<meta http-equiv=refresh content=5><title>即時事件監控 · NemoClaw Sky Eye</title>
<style>{STYLE}</style></head><body class=wall-body>
<div class=wall-wrap>
<header class=whead>
  <div>
    <h1>即時事件監控</h1>
    <div class=wsub>多路攝影機監控牆與即時偵測框疊圖 ({html.escape(source_label)} · {len(entries)} 路在巡)</div>
  </div>
  <div class=lay-chooser>
    <span class=wnav><a href='/'>← 綜合儀表板</a></span>
    <span style='color:#9ca3af;margin:0 8px'>·</span>
    版面 {chooser}
  </div>
</header>
<main class=wmain>
  <div class=wgrid style='grid-template-columns:repeat({cols},1fr)'>{''.join(cells)}</div>
  <aside class=wside>
    <div class=whdr>即時事件</div>
    <div class=wfeed>{feed_html}</div>
  </aside>
</main>
</div></body></html>"""


def _render_live_events(rows):
    """主頁右側即時事件 panel(暗色 glass,取代 attack_scene)。
    拉 audit ≥medium 最近 12 條,critical/high/medium 上色標出,含 trace_id 跳轉。"""
    events = _wall_events(rows, limit=12)
    if events:
        items = []
        for e in events:
            trace = e.get("trace_id") or ""
            link = (f"<a href='/trace?trace_id={urllib.parse.quote(trace)}'>查證據鏈 →</a>"
                    if trace else "")
            items.append(
                f"<div class='dev sev-{e['severity']}'>"
                f"<div class=dev-ts><span>{html.escape(e['ts'])} · ch{html.escape(str(e['channel']))} · "
                f"{_sev_zh(e['severity'])}</span>{link}</div>"
                f"<div class=dev-name>{html.escape(e['name'])}</div>"
                f"<div class=dev-sum>{html.escape(e['summary'])}</div></div>")
        body = f"<div class=dev-list>{''.join(items)}</div>"
    else:
        body = "<div class=dev-empty>尚無 ≥ 中嚴重度事件 · 巡檢中</div>"
    return (f"<section class='panel glass'><h3>📡 即時事件 "
            f"<span class=muted style='font-size:11px;font-weight:400'>"
            f"嚴重度 ≥ 中 · 最近 12 條</span></h3>{body}</section>")


def _render_thoughts():
    if not _thoughts:
        return ""
    items = _thoughts.latest(100)
    start = _supervisor_started_at()
    if start:
        local_start = start.replace(tzinfo=None)
        visible = []
        for it in items:
            try:
                if datetime.datetime.fromisoformat(str(it.get("ts", ""))) >= local_start:
                    visible.append(it)
            except ValueError:
                continue
        items = visible
    items = items[-12:]
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


def _render_correlation():
    if not _correlation:
        return ""
    alerts = _correlation.latest(6)
    if not alerts:
        body = "<div class=empty>無跨地標關聯警報(過去 5 分鐘內各地標獨立)</div>"
    else:
        cards = []
        for a in alerts:
            crit = " crit" if a.get("severity_inferred") == "critical" else ""
            ts = (a.get("ts_iso") or "")[-8:]
            ev_html = "".join(
                f"<div>ch{html.escape(str(e.get('channel','')))} · "
                f"{html.escape((e.get('summary') or '')[:80])}</div>"
                for e in (a.get("evidence") or [])[:4])
            cards.append(
                f"<div class='corr-card{crit}'>"
                f"<div class='corr-head{crit}'>"
                f"<span class=et>🌐 {html.escape(a.get('event_type',''))} "
                f"× {a.get('channel_count','')} 路同時</span>"
                f"<span class=corr-meta>{html.escape(ts)} · "
                f"升級 {_sev_zh(a.get('severity_inferred'))}</span></div>"
                f"<div class=corr-ev>{ev_html}</div></div>")
        body = f"<div class=corr-grid>{''.join(cards)}</div>"
    return (f"<section class='panel glass'><h3>🌐 跨地標關聯偵測 "
            f"<span class=muted style='font-size:11px;font-weight:400'>"
            f"5min 窗 · ≥2 路同類事件升級</span></h3>{body}</section>")


_VERDICT_ICON = {"證實": ("✅", "confirm"), "否認": ("❌", "refute"),
                 "無訊號": ("⚪", "nosig")}


def _render_verdict_lines(text):
    """把 Hermes 結論的「來源N [...]: 證實|否認|無訊號 · ...」逐行 parse 並上 icon。
    無法 parse 的行原樣印,確保即使 Hermes 偏離格式也不會掉訊息。"""
    if not text:
        return "<div class=empty>(無結論)</div>"
    out_rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        verdict = None
        for k in _VERDICT_ICON:
            if k in line[:30]:
                verdict = k
                break
        if verdict and "來源" in line[:6]:
            icon, cls = _VERDICT_ICON[verdict]
            out_rows.append(f"<div class='vr vr-{cls}'>{icon} {html.escape(line)}</div>")
        elif line.startswith("綜合判斷"):
            out_rows.append(f"<div class='vr vr-final'>🧠 {html.escape(line)}</div>")
        elif line.startswith("建議"):
            out_rows.append(f"<div class='vr vr-advice'>📋 {html.escape(line)}</div>")
        else:
            out_rows.append(f"<div class='vr vr-misc'>{html.escape(line)}</div>")
    return "".join(out_rows)


def _render_followups(audit_rows=None):
    if not _followup:
        return ""
    audit_by_trace = {r.get("trace_id"): r for r in (audit_rows or []) if r.get("trace_id")}
    items = _followup.latest(5)
    if not items:
        body = ("<div class=empty>無 sandbox 二次調查(等待 high/critical 事件觸發)</div>")
    else:
        cards = []
        unlinked = []
        for f in items:
            audit_row = audit_by_trace.get(f.get("trace_id"), {})
            origin = f.get("trigger_origin") or audit_row.get("trigger_origin")
            ts = (f.get("ts_iso") or "時間未知").replace("T", " ")
            elapsed = f.get("elapsed_ms", 0)
            cmds_html = ""
            for c in (f.get("commands") or [])[:3]:
                stdout = (c.get("stdout") or "").strip()[:300]
                cmds_html += (
                    f"<div class=c>$ {html.escape(c.get('cmd',''))}</div>"
                    f"<div class=p># {html.escape(c.get('purpose',''))} · rc={c.get('rc')} · {c.get('elapsed_ms')}ms</div>"
                    f"<div class=o>{html.escape(stdout) or '<span class=muted>(empty)</span>'}</div>")
            plan_src = f.get("plan_source", "multi-source-recipe")
            src_badge_map = {
                "multi-source-recipe": "<span class=plan-multi>🧩 3 源固定交叉驗證</span>",
                "hermes-autonomous": "<span class=plan-auto>🧠 Hermes 自主規劃</span>",
                "fallback-recipe": "<span class=plan-fallback>📜 fallback recipe</span>",
            }
            src_badge = src_badge_map.get(plan_src, src_badge_map["multi-source-recipe"])
            loc = f.get("channel_name") or f"ch{f.get('channel','')}"
            verdict_html = _render_verdict_lines(f.get("conclusion") or "")
            origin_badge = {
                "scheduled": "<span class='tag tag-live'>LIVE 觸發</span>",
                "demo_manual": "<span class='tag tag-test'>TEST 受控演練</span>",
            }.get(origin, "<span class='tag tag-unlinked'>未連結</span>")
            warning = ("" if origin else
                       "<div class=fu-warning>未連結 LIVE/TEST 事件，不代表目前告警狀態。</div>")
            trace_html = ""
            if audit_row:
                q = urllib.parse.urlencode({"trace_id": f.get("trace_id", "")})
                trace_html = f"<a href='/trace?{q}'>查看證據鏈</a>"
            card = (
                f"<div class=fu-card>"
                f"<div class=fu-head><span class=ch>{origin_badge} 🛰 {html.escape(loc)} · "
                f"{html.escape(f.get('event_type',''))} "
                f"({_sev_zh(f.get('severity'))})</span>"
                f"<span class=muted style='font-size:11.5px'>{html.escape(ts)} · {elapsed}ms</span></div>"
                f"{warning}"
                f"<div class=fu-verdict>{verdict_html}</div>"
                f"<div class=fu-cmds>{cmds_html}</div>"
                f"<div class=fu-foot>{src_badge}<span class=gov>🛡 OpenShell 沙箱治理</span>"
                f"<span>· {len(f.get('commands') or [])} 個獨立來源 · 真上網爬公共 API</span>"
                f"{trace_html}</div></div>")
            if origin:
                cards.append(card)
            else:
                unlinked.append(card)
        linked_body = (f"<div class=fu-grid>{''.join(cards)}</div>" if cards else
                       "<div class=empty>無已標示來源的二次調查事件</div>")
        archive = (
            f"<details class=fu-unlinked><summary>未連結事件紀錄 {len(unlinked)} 筆 · "
            f"不代表 LIVE 現況</summary><div class=fu-grid>{''.join(unlinked)}</div></details>"
            if unlinked else "")
        body = linked_body + archive
    return (f"<section class='panel glass'><h3>🛰 OpenShell 沙箱二次調查紀錄 "
            f"<span class=muted style='font-size:11px;font-weight:400'>"
            f"Hermes 自主規劃 read-only 指令 → 跑沙箱 → 寫結論</span></h3>{body}</section>")


def _latest_media_row(rows):
    """Select the latest significant event with media, including manual attack demos."""
    for r in reversed(rows):
        if r.get("severity") in (None, "", "low"):
            continue
        urls = (r.get("media_artifacts") or {}).get("urls") or {}
        if urls.get("clip") or urls.get("falcon_annotated") or urls.get("frame"):
            return r
    return None


def _latest_demo_row(rows):
    for r in reversed(rows):
        if r.get("trigger_origin") == "demo_manual" and _latest_media_row([r]):
            return r
    return None


def _render_attack_scene(rows):
    """Render deterministic abnormal proof separately from the normal live wall."""
    r = _latest_demo_row(rows)
    if not r:
        return ("<section class='panel glass drill'>"
                "<h3><span class='tag tag-test'>TEST</span> 攻擊演練</h3>"
                "<div class=empty>尚無演練紀錄</div>"
                "</section>")
    urls = (r.get("media_artifacts") or {}).get("urls") or {}
    clip = urls.get("clip") or ""
    poster = urls.get("frame") or urls.get("falcon_annotated") or ""
    sev = _sev_zh(r.get("severity"))
    q = urllib.parse.urlencode({"trace_id": r.get("trace_id", "")})
    poster_attr = f" poster='{html.escape(poster)}'" if poster else ""
    video_html = (f"<video controls muted loop playsinline preload='metadata'{poster_attr} "
                  f"src='{html.escape(clip)}'></video>" if clip else "<div class=empty>無錄影切片</div>")
    blocked = "已阻擋" if r.get("injection_detected") else "未標記"
    action = "已升級" if r.get("escalated") else "已判定"
    return f"""<section class='panel glass drill'>
  <div class=wall-head><h3><span class='tag tag-test'>TEST</span> 攻擊演練</h3>
    <span class='badge b-dedup'>受控重現</span></div>
  {video_html}
  <div class=drill-result>
    <div><span>場景</span><strong>火煙</strong></div>
    <div><span>假指令</span><strong class=bad>{blocked}</strong></div>
    <div><span>結果</span><strong class=bad>{sev} · {action}</strong></div>
  </div>
  <div class=drill-actions><span class=muted>NemoClaw 防護</span><a class=cta href='/trace?{q}'>查看證據鏈</a></div>
</section>"""


def _render_attack_matrix():
    """Policy regression panel; the recorded attack scene proves video-to-governance behavior."""
    if not os.path.exists(ATTACK_MATRIX):
        return ""
    try:
        rep = json.load(open(ATTACK_MATRIX, encoding="utf-8"))
    except Exception:
        return ""
    rows = ""
    for r in rep.get("rows", []):
        blocked = "<span class=ok>✅ 通過</span>" if r.get("defended") else "<span class=bad>❌ 失敗</span>"
        recognized = ("<span class='badge b-inj'>⚠ 識破</span>" if r.get("injection_flagged")
                      else "<span class=muted>—</span>")
        sev = ("<span class=ok>維持嚴重</span>" if r.get("severity_retained")
               else f"<span class=bad>被降為{_sev_zh(r.get('severity_after'))}</span>")
        action = "ALLOW · notify 路由" if r.get("still_notifies") else html.escape(str(r.get("policy_decision", "")))
        rows += (f"<tr><td><b>{html.escape(r.get('name',''))}</b></td>"
                 f"<td><code>{html.escape(r.get('modality',''))}</code></td>"
                 f"<td class=muted>{html.escape(r.get('attack',''))}</td>"
                 f"<td>{recognized}</td><td>{sev}</td><td>{blocked}</td>"
                 f"<td><span class='badge b-gov'>🛡 NemoClaw 治理</span></td>"
                 f"<td>{action}</td></tr>")
    n, t = rep.get("defended", 0), rep.get("total", 0)
    badge = (f"<span class='badge b-allow' style='font-size:13px'>{n}/{t} 回歸案例通過</span>"
             if rep.get("all_defended") else f"<span class='badge b-block' style='font-size:13px'>{n}/{t} 有缺口</span>")
    gen = html.escape(str(rep.get("generated_at", "")))
    return (f"<section class='panel glass'><h3>🛡 Guardrail 回歸測試矩陣 {badge}"
            f"<span class=muted style='font-size:11px;font-weight:400'>{gen}</span></h3>"
            f"<p class=muted style='margin:0 0 14px;font-size:13px'>"
            f"此矩陣以 production policy 函式對 5 種已解碼文字情境做 deterministic regression;"
            f"影片攻擊演練證據請見 attack scene 的 flight recorder。"
            f"</p>"
            f"<table><thead><tr><th>輸入案例</th><th>已解碼來源</th><th>假指令內容</th><th>識破</th>"
            f"<th>嚴重等級</th><th>回歸結果</th><th>治理者</th><th>處置</th></tr></thead>"
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
        return "<section class='panel glass media'><h3>事件媒體</h3><p class=muted>尚無事件影像。</p></section>"
    video_html = (
        f"<video controls preload='metadata' src='{html.escape(clip)}'></video>"
        if clip else "<div class=empty>無錄影切片</div>"
    )
    image_url = annot or frame
    marked = bool(counts and any(int(v or 0) > 0 for v in counts.values()))
    image_title = "Falcon 標記圖" if annot and marked else "事件影格"
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
        if parsed.path.startswith("/wall/"):
            self._send_wall_snapshot(parsed.path[len("/wall/"):], head_only=True)
            return
        if parsed.path.startswith("/media/"):
            self._send_media(parsed.path[len("/media/"):], head_only=True)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/wall":
            qs = urllib.parse.parse_qs(parsed.query)
            try:
                layout = int((qs.get("layout") or ["16"])[0])
            except ValueError:
                layout = 16
            self._send_html(_render_wall_page(layout))
            return
        if parsed.path == "/trace":
            qs = urllib.parse.parse_qs(parsed.query)
            trace_id = (qs.get("trace_id") or [""])[0]
            self._send_html(_render_trace(trace_id))
            return
        if parsed.path.startswith("/media/"):
            self._send_media(parsed.path[len("/media/"):])
            return
        if parsed.path.startswith("/wall/"):
            self._send_wall_snapshot(parsed.path[len("/wall/"):])
            return
        qs = urllib.parse.parse_qs(parsed.query)
        selected_channel = (qs.get("channel") or [""])[0]
        try:
            layout = int((qs.get("layout") or ["16"])[0])
        except ValueError:
            layout = 16
        rows = _rows()
        s, notified, inj, gov = _stats(rows)
        flight_count = len(flight_recorder.group_by_trace(_runtime_flight_rows()))
        m = _efficiency_metrics()
        health = _health_now()
        command_center = _render_command_center(rows, health)
        sky_eye_grid = _render_sky_eye_grid(selected_channel, layout=layout)
        thoughts_panel = _render_thoughts()
        attack_scene = _render_attack_scene(rows)
        live_events = _render_live_events(rows)
        status_html = (_health_dots(health)
                       + "<span class=muted>每 5s 更新 · 檢視時暫停</span>")
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
        recent = list(reversed(rows[-60:]))
        items = "".join(_incident_row(r) for r in recent[:12])
        rest_count = max(0, len(recent) - 12)
        audit_expand = (
            f"<details class=audit-more><summary>展開全部 · 另 {rest_count} 列</summary>"
            f"<table><tbody>{''.join(_incident_row(r) for r in recent[12:])}</tbody></table></details>"
            if rest_count > 0 else "")
        attack_matrix = _render_attack_matrix()
        correlation_panel = _render_correlation()
        followups_panel = _render_followups(rows)
        html = f"""<!doctype html><html lang=zh-Hant><head><meta charset=utf-8>
<title>NemoClaw Sentinel</title>
<style>{STYLE}</style></head><body><div class=wrap>
<header class='head glass'>
  <div><div class=brand>NEMOCLAW · SKY EYE</div>
  <div class=sub>世界路口監控牆 / 異常演練 · GB10 · <a href='/wall' style='color:#7fd6ff'>全螢幕監控牆 →</a></div></div>
  <div class=status>{status_html}</div>
</header>
<main class=primary-grid>{sky_eye_grid}{live_events}</main>
{command_center}
{correlation_panel}
{followups_panel}
<details class=drawer><summary>事件紀錄與技術證據</summary>
<div class=tiles>{tiles}</div>
<section class='panel glass'><h3>級聯效率</h3>
<div class=stats>{eff}</div></section>
{attack_scene}
{attack_matrix}
{thoughts_panel}
<section class='panel glass'><h3>決策稽核軌跡 <span class=muted style='font-size:11px;font-weight:400'>最新 {len(recent)} 列</span></h3>
<table><thead><tr><th>時間</th><th>Ch</th><th>類型</th><th>決策</th><th>治理</th><th>注入</th><th>動作</th><th>Flight</th><th>媒體</th><th>理由</th></tr></thead>
<tbody>{items}</tbody></table>{audit_expand}</section>
</details>
</div><script>
window.setInterval(() => {{
  const videoPlaying = Array.from(document.querySelectorAll("video"))
    .some(video => !video.paused && !video.ended);
  const reading = document.querySelector("details[open]") || window.scrollY > 40;
  if (!document.hidden && !videoPlaying && !reading) window.location.reload();
}}, 5000);
</script></body></html>"""
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

    def _send_wall_snapshot(self, rel, head_only=False):
        target = wall_snapshots.resolve_public(urllib.parse.unquote(rel).lstrip("/"))
        if not target:
            self.send_error(404)
            return
        size = target.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            with open(target, "rb") as f:
                shutil.copyfileobj(f, self.wfile)

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    port = int(os.environ.get("NEMOCLAW_DASHBOARD_PORT", "8099"))
    bind = os.environ.get("NEMOCLAW_DASHBOARD_BIND", "127.0.0.1")
    print(f"dashboard on {bind}:{port} (audit={AUDIT})")
    HTTPServer((bind, port), H).serve_forever()
