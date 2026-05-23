#!/usr/bin/env python3
"""NemoClaw Sentinel 稽核 dashboard:讀 audit.jsonl,顯示決策統計 + 最近事件流。
治理可視化:每個對外決策(ALLOW/BLOCK/DEDUP/ABSTAIN)+ 理由 + 注入旗標。"""
import os, json
from http.server import BaseHTTPRequestHandler, HTTPServer

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
        if r.get("decision") == "ALLOW" and "notify" in (r.get("actions") or []):
            notified += 1
        if r.get("injection_detected"):
            inj += 1
        if r.get("governed_by") == "nemoclaw-openshell":
            gov += 1
    return s, notified, inj, gov

COLOR = {"ALLOW": "#0a7", "BLOCK": "#c33", "DEDUP": "#888", "ABSTAIN": "#e90"}

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        rows = _rows()
        s, notified, inj, gov = _stats(rows)
        cards = (f"<b>{len(rows)}</b> 決策 &nbsp;|&nbsp; "
                 f"<span style='color:#0a7'>ALLOW {s['ALLOW']}</span> &nbsp; "
                 f"<span style='color:#c33'>BLOCK {s['BLOCK']}</span> &nbsp; "
                 f"<span style='color:#888'>DEDUP {s['DEDUP']}</span> &nbsp; "
                 f"<span style='color:#e90'>ABSTAIN {s['ABSTAIN']}</span> &nbsp;|&nbsp; "
                 f"📣 已通知 {notified} &nbsp;|&nbsp; ⚠️ 注入阻擋 {inj} &nbsp;|&nbsp; "
                 f"<span style='color:#6cf'>🛡️ NemoClaw 治理 {gov}</span>")
        items = "".join(
            f"<tr><td>{r.get('ts_iso','')}</td><td>{r.get('channel','')}</td>"
            f"<td>{r.get('event_type','')}</td>"
            f"<td style='color:{COLOR.get(r.get('decision',''),'#000')};font-weight:700'>{r.get('decision','')}</td>"
            f"<td>{'🛡️' if r.get('governed_by')=='nemoclaw-openshell' else ''}</td>"
            f"<td>{'⚠️' if r.get('injection_detected') else ''}</td>"
            f"<td>{', '.join(r.get('actions') or [])}</td>"
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
<table><tr><th>時間</th><th>Ch</th><th>類型</th><th>決策</th><th>治理</th><th>注入</th><th>動作</th><th>理由</th></tr>
{items}</table></body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    port = int(os.environ.get("NEMOCLAW_DASHBOARD_PORT", "8088"))
    print(f"dashboard on :{port} (audit={AUDIT})")
    HTTPServer(("0.0.0.0", port), H).serve_forever()
