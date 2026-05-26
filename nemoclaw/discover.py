#!/usr/bin/env python3
"""自主地標探索:不再由人指定 16 路——agent 自己上 YouTube 搜尋候選直播,
yt-dlp 解 HLS + ffmpeg 抓 1 幀做存活驗證,Nemotron 看畫面判定「是否為著名地標」,
通過則加入 discovered.yaml 並登錄 sqlite。Sweep 下一輪自動包含。

每一步都記到 thoughts.jsonl(source=discover),讓「天眼自己找天眼」看得見。"""
import base64
import json
import os
import re
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import thoughts as _thoughts

SEARCH_QUERIES = (
    "famous landmark live webcam 24/7",
    "iconic city live cam 24/7",
    "tourist attraction live stream",
    "national park live cam",
)

DISCOVERED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "discovered.yaml")
LANDMARKS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "landmarks.yaml")
START_ID = 220   # discovered 從 ch220 起算(landmarks.yaml 用 201-219)


def yt_search(query, n=8):
    """`yt-dlp ytsearchN:` 取候選直播。回 list[{id,title,url}]。"""
    try:
        r = subprocess.run(
            ["yt-dlp", "-j", "--flat-playlist", "--no-warnings",
             f"ytsearch{n}:{query}"],
            capture_output=True, text=True, timeout=40)
    except Exception:
        return []
    out = []
    for line in (r.stdout or "").splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        vid = d.get("id")
        if not vid:
            continue
        out.append({
            "id": vid,
            "title": d.get("title") or "",
            "url": d.get("url") or f"https://www.youtube.com/watch?v={vid}",
        })
    return out


def validate(url, out_path=None):
    """yt-dlp 解 HLS + ffmpeg 抓 1 幀;回 (frame_path, hls_url) 或 (None,None)。"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from feed import resolve_url
        hls = resolve_url(url)
    except Exception:
        hls = None
    if not hls or not hls.startswith("http"):
        return None, None
    out = out_path or f"/tmp/discover_{abs(hash(url)) % 999999}.jpg"
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", hls,
                        "-frames:v", "1", "-q:v", "3",
                        "-vf", "scale=640:-1", out],
                       capture_output=True, timeout=30)
    except Exception:
        return None, None
    if os.path.exists(out) and os.path.getsize(out) > 1500:
        return out, hls
    return None, None


def vlm_image_text(image_path, prompt, max_tokens=180, timeout=60):
    """送圖 + 文字給 Nemotron(vLLM 多模態 chat completions)。失敗回 ''。"""
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    except Exception:
        return ""
    body = json.dumps({
        "model": os.environ.get("VLM_MODEL", "nemotron_3_nano_omni"),
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
        "max_tokens": max_tokens, "temperature": 0.2,
    }).encode()
    url = os.environ.get("VLM_API_URL", "http://127.0.0.1:31010/v1/chat/completions")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        return data["choices"][0]["message"]["content"] or ""
    except Exception:
        return ""


def score_landmark(frame_path, title="", vlm_fn=None):
    """Nemotron 看畫面 + 影片標題,判定是否為「著名地標 / 知名景點 / 大眾關注的 24/7 直播」。
    回 (is_landmark: bool, confidence: float, name: str)。"""
    vlm_fn = vlm_fn or vlm_image_text
    q = (f"影片標題:{title}\n"
         "你看見的這張畫面是某個 live 攝影機當下的一幀。請判斷:"
         "這是否為「世界知名地標 / 著名觀光景點 / 大眾關注的 24/7 直播」?"
         "城市街道、自然景觀、火車鐵道、海洋畫面等若具觀賞性也算。"
         "只輸出一行 JSON:"
         '{"is_landmark": true 或 false, "name": "繁中地標/場景名稱", "confidence": 0-1}')
    ans = vlm_fn(frame_path, q)
    m = re.search(r"\{.*\}", ans or "", re.DOTALL)
    if not m:
        return False, 0.0, title or ""
    try:
        d = json.loads(m.group(0))
    except Exception:
        return False, 0.0, title or ""
    return (bool(d.get("is_landmark")),
            float(d.get("confidence") or 0),
            str(d.get("name") or title)[:80])


def _load_yaml(path):
    if not os.path.exists(path):
        return {"channels": []}
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
        d.setdefault("channels", [])
        return d
    except Exception:
        return {"channels": []}


def _save_yaml(path, doc):
    import yaml
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)


def existing_urls():
    """已知 URL 集合(landmarks.yaml + discovered.yaml + sqlite channels)。"""
    urls = set()
    for p in (LANDMARKS_PATH, DISCOVERED_PATH):
        for c in _load_yaml(p).get("channels", []):
            if c.get("url"):
                urls.add(c["url"])
    try:
        import db_factory
        for row in db_factory.channel_db().get_all_channels():
            u = row.get("source_url")
            if u:
                urls.add(u)
    except Exception:
        pass
    return urls


def _next_id():
    """從 discovered.yaml + sqlite 找下一個未用 id(≥ START_ID)。"""
    used = {int(c["id"]) for c in _load_yaml(DISCOVERED_PATH).get("channels", [])
            if c.get("id") is not None}
    try:
        import db_factory
        for row in db_factory.channel_db().get_all_channels():
            cid = row.get("channel_id")
            if cid is not None:
                used.add(int(cid))
    except Exception:
        pass
    n = START_ID
    while n in used:
        n += 1
    return n


def _register(entry):
    """寫入 discovered.yaml + sqlite。entry={id,name,url,event_type}。"""
    doc = _load_yaml(DISCOVERED_PATH)
    doc.setdefault("channels", []).append(entry)
    _save_yaml(DISCOVERED_PATH, doc)
    try:
        import db_factory
        db = db_factory.channel_db()
        if hasattr(db, "add_stream_channel"):
            db.add_stream_channel(entry["name"], entry["url"], entry["id"], "天眼-探索")
    except Exception:
        pass


def discover(max_new=3, vlm_fn=None, search_fn=None, validate_fn=None, score_fn=None):
    """自主探索:搜尋→驗證→評分→註冊。回新加入的 list[entry]。
    所有依賴皆可注入,方便單元測試。"""
    search_fn = search_fn or yt_search
    validate_fn = validate_fn or validate
    score_fn = score_fn or score_landmark
    known = existing_urls()
    _thoughts.record(f"我要自己上 YouTube 找新地標(目標 {max_new} 路;已知 {len(known)} 路)", source="discover")
    seen = set()
    candidates = []
    for q in SEARCH_QUERIES:
        for r in search_fn(q, n=6):
            u = r.get("url")
            if not u or u in known or u in seen:
                continue
            seen.add(u)
            candidates.append(r)
    _thoughts.record(f"搜尋彙整出 {len(candidates)} 個未見過的候選,開始驗證+評分", source="discover")

    scored = []
    for c in candidates[:18]:    # 避免一次太多;最多驗 18 個
        frame, _ = validate_fn(c["url"])
        if not frame:
            continue
        is_lm, conf, name = score_fn(frame, c.get("title", ""), vlm_fn)
        if is_lm and conf >= 0.6:
            scored.append({"url": c["url"], "title": c.get("title", ""),
                           "score": conf, "name": name})

    scored.sort(key=lambda x: -x["score"])
    added = []
    for s in scored[:max_new]:
        eid = _next_id()
        entry = {"id": eid, "name": f"{s['name'][:36]} · 自主發現",
                 "url": s["url"], "event_type": "abnormal_crowd"}
        _register(entry)
        added.append(entry)
        _thoughts.record(
            f"發現新天眼地標:{entry['name']}(信心 {s['score']:.2f})→ ch{eid} 加入巡檢",
            source="discover")
    if not added:
        _thoughts.record(f"這輪找到 {len(scored)} 個合格候選但都已在巡檢中或不夠強,沒新增", source="discover")
    return added


def main():
    import argparse
    p = argparse.ArgumentParser(description="自主地標探索(讓 agent 自己找新天眼)")
    p.add_argument("--max", type=int, default=3, help="本次最多新增幾路")
    args = p.parse_args()
    added = discover(max_new=args.max)
    print(json.dumps({"added": len(added), "channels": added}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
