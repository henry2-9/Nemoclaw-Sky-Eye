#!/usr/bin/env python3
"""NemoClaw Sentinel dashboard: audit log + incident flight recorder."""
import html
import os
import json
import mimetypes
import shutil
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import flight_recorder
import media

AUDIT = os.environ.get("NEMOCLAW_AUDIT_PATH",
                       os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "audit.jsonl"))

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
        return "<section class=media><h3>事件媒體</h3><p class=muted>尚無錄影切片或 Falcon 標記圖。</p></section>"
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
    return f"""<section class=media>
<h3>事件媒體</h3>
<div class=media-grid>
  <div><h4>錄影切片</h4>{video_html}</div>
  <div><h4>{html.escape(image_title)}</h4>{image_html}</div>
</div>
<p class=muted>Falcon query: <code>{html.escape(str(query))}</code> · counts: <code>{html.escape(json.dumps(counts, ensure_ascii=False))}</code></p>
</section>"""

def _render_trace(trace_id):
    traces = flight_recorder.group_by_trace(flight_recorder.load())
    rows = traces.get(trace_id, [])
    audit_row = _audit_for_trace(trace_id)
    media_panel = _render_media_panel(audit_row)
    items = "".join(
        "<tr>"
        f"<td>{i}</td>"
        f"<td>{html.escape(r.get('ts_iso', ''))}</td>"
        f"<td>{html.escape(r.get('stage', ''))}</td>"
        f"<td>{html.escape(flight_recorder.compact_payload(r.get('payload'), width=900))}</td>"
        "</tr>"
        for i, r in enumerate(rows, 1)
    )
    if not rows:
        items = "<tr><td colspan=4>No records for this trace.</td></tr>"
    return f"""<html><head><meta charset=utf-8>
<title>Incident Flight Recorder</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px;background:#0b0e14;color:#cdd}}
a{{color:#6cf}} table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border:1px solid #243;padding:6px 8px;text-align:left;vertical-align:top}} th{{background:#162}}
code{{color:#9ef}} .media{{margin:18px 0 22px}} .media-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
video,img{{width:100%;max-height:440px;background:#05070a;border:1px solid #243;object-fit:contain}}
h3,h4{{margin:8px 0}} .muted{{color:#9ab}} .empty{{border:1px dashed #345;padding:32px;color:#789}}</style></head><body>
<h2>Incident Flight Recorder</h2>
<p><a href="/">← audit dashboard</a></p>
<p><code>{html.escape(trace_id or "")}</code></p>
{media_panel}
<table><tr><th>#</th><th>時間</th><th>階段</th><th>payload</th></tr>{items}</table>
</body></html>"""

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
        cards = (f"<b>{len(rows)}</b> 決策 &nbsp;|&nbsp; "
                 f"<span style='color:#0a7'>ALLOW {s['ALLOW']}</span> &nbsp; "
                 f"<span style='color:#c33'>BLOCK {s['BLOCK']}</span> &nbsp; "
                 f"<span style='color:#888'>DEDUP {s['DEDUP']}</span> &nbsp; "
                 f"<span style='color:#e90'>ABSTAIN {s['ABSTAIN']}</span> &nbsp;|&nbsp; "
                 f"📣 實際送出 {notified} &nbsp;|&nbsp; ⚠️ 注入阻擋 {inj} &nbsp;|&nbsp; "
                 f"<span style='color:#6cf'>🛡️ NemoClaw 治理 {gov}</span> &nbsp;|&nbsp; "
                 f"🧾 Flight Recorder {flight_count}")
        m = _efficiency_metrics()
        eff = (f"🔁 cycles {m['cycles']} &nbsp;|&nbsp; 👁️ cheap候選 {m['candidates']} &nbsp;|&nbsp; "
               f"<span style='color:#6cf'>🧠 Nemotron 喚醒 {m['investigations']}</span> &nbsp; "
               f"✅ 確認 {m['confirmed']} &nbsp; 🚫 過濾正常 {m['filtered']} &nbsp; ⏭️ cheap擋下未送 {m['capped']} "
               f"&nbsp;|&nbsp; ⏱️ 調查延遲 中位 {m['median_latency']}s / p95 {m['p95_latency']}s")
        items = "".join(
            f"<tr><td>{r.get('ts_iso','')}</td><td>{r.get('channel','')}</td>"
            f"<td>{r.get('event_type','')}</td>"
            f"<td style='color:{COLOR.get(r.get('decision',''),'#000')};font-weight:700'>{r.get('decision','')}</td>"
            f"<td>{'🛡️' if r.get('governed_by')=='nemoclaw-openshell' else ''}</td>"
            f"<td>{'⚠️' if r.get('injection_detected') else ''}</td>"
            f"<td>{', '.join(r.get('actions') or [])}</td>"
            f"<td>{_trace_link(r.get('trace_id'))}</td>"
            f"<td>{_media_links(r)}</td>"
            f"<td>{'; '.join(r.get('reasons') or [])}</td></tr>"
            for r in reversed(rows[-60:]))
        html = f"""<html><head><meta charset=utf-8><meta http-equiv=refresh content=5>
<title>NemoClaw Sentinel</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px;background:#0b0e14;color:#cdd}}
h2{{margin:0}} .bar{{margin:12px 0;font-size:15px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border:1px solid #243;padding:6px 8px;text-align:left}} th{{background:#162}}
</style></head><body>
<h2>🛡️ NemoClaw Sentinel — 自主巡檢治理稽核</h2>
<div class=bar>{cards}</div>
<div class=bar style="font-size:14px;color:#9bd">⚡ 級聯效率:{eff}</div>
<table><tr><th>時間</th><th>Ch</th><th>類型</th><th>決策</th><th>治理</th><th>注入</th><th>動作</th><th>Flight</th><th>媒體</th><th>理由</th></tr>
{items}</table></body></html>"""
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
