#!/usr/bin/env python3
"""自主攝影機探索:agent 自己上 YouTube 搜尋候選直播,
yt-dlp 解 HLS + ffmpeg 抓 1 幀做存活驗證,Nemotron 看畫面判定是否符合 profile。

profile=landmark 找城市地標/公共場域,通過則加入 discovered.yaml。
profile=traffic 找世界各地路口/道路監視器,通過則加入 discovered_traffic.yaml。
Sweep 下一輪在對應來源檔啟用 discovery 時自動包含。

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

LANDMARK_SEARCH_QUERIES = (
    "city street live webcam 24/7",
    "downtown live cam plaza square",
    "transit station airport live cam",
    "tourist landmark live surveillance",
)
TRAFFIC_SEARCH_QUERIES = (
    "live traffic camera intersection 24/7",
    "city intersection live cam traffic light",
    "downtown traffic webcam road intersection live",
    "public traffic CCTV live street camera",
    "live road camera intersection crosswalk",
    "Tokyo Shibuya crossing live cam 24/7",
    "London traffic intersection live cam",
    "New York Manhattan street live cam",
    "San Francisco intersection live cam 24/7",
    "Seoul Gangnam intersection live cam",
    "Singapore traffic live cam",
    "Berlin street live cam intersection",
    "Paris boulevard live cam traffic",
    "Sydney CBD intersection live cam",
    "highway live cam 24/7 traffic",
)

DISCOVERED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "discovered.yaml")
DISCOVERED_TRAFFIC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "discovered_traffic.yaml")
LANDMARKS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "landmarks.yaml")
WORLD_CHANNELS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "world_channels.yaml")
START_ID = 220   # discovered 從 ch220 起算(landmarks.yaml 用 201-219)
TRAFFIC_START_ID = 120   # world_channels.yaml 目前使用 ch101-106


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
         "你看見的這張畫面是某個 live 攝影機當下的一幀。"
         "我們是**安全/異常監控系統**——只收**城市街道 / 公共廣場 / 交通樞紐 / 知名公共地標**這類能監看可疑事件的畫面。"
         "純自然景觀 / 野生動物 / 海洋海底 / 太空 / 純空鏡頭 → is_landmark=false。"
         "城市街道、地鐵站、機場、知名公共空間 → is_landmark=true。"
         "只輸出一行 JSON:"
         '{"is_landmark": true 或 false, "name": "繁中具體地點名稱", "confidence": 0-1}')
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


def score_traffic_camera(frame_path, title="", vlm_fn=None):
    """Nemotron 看畫面 + 標題,判定是否為可巡檢的路口/道路公開監視器。
    回 (is_traffic_camera: bool, confidence: float, name: str)。"""
    vlm_fn = vlm_fn or vlm_image_text
    q = (f"影片標題:{title}\n"
         "你看見的是 live 攝影機的一幀。請判斷它是否適合作為**世界路口/道路交通安全監控**來源。"
         "合格條件:畫面主要是公共道路、路口、斑馬線、號誌、車道、橋梁或高速道路,可長時間觀察車流/行人/事故。"
         "優先收:intersection/crosswalk/traffic light/downtown street/highway CCTV。"
         "拒收:純地標觀光、室內、自然風景、海灘、滑雪場、動物、太空、新聞剪輯、非 live、遊戲畫面、畫面太模糊。"
         "若只是地標遠景且看不清道路/路口,也拒收。"
         "只輸出一行 JSON:"
         '{"is_traffic_camera": true 或 false, "name": "繁中具體地點或路口名稱", "confidence": 0-1}')
    ans = vlm_fn(frame_path, q)
    m = re.search(r"\{.*\}", ans or "", re.DOTALL)
    if not m:
        return False, 0.0, title or ""
    try:
        d = json.loads(m.group(0))
    except Exception:
        return False, 0.0, title or ""
    return (bool(d.get("is_traffic_camera")),
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
    """已知 URL 集合(landmarks/world/discovered + sqlite channels)。"""
    urls = set()
    for p in (LANDMARKS_PATH, WORLD_CHANNELS_PATH, DISCOVERED_PATH, DISCOVERED_TRAFFIC_PATH):
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


def _next_id(profile="landmark"):
    """從 yaml + sqlite 找下一個未用 id。"""
    used = set()
    for p in (LANDMARKS_PATH, WORLD_CHANNELS_PATH, DISCOVERED_PATH, DISCOVERED_TRAFFIC_PATH):
        used.update(int(c["id"]) for c in _load_yaml(p).get("channels", [])
                    if c.get("id") is not None)
    try:
        import db_factory
        for row in db_factory.channel_db().get_all_channels():
            cid = row.get("channel_id")
            if cid is not None:
                used.add(int(cid))
    except Exception:
        pass
    n = TRAFFIC_START_ID if profile == "traffic" else START_ID
    while n in used:
        n += 1
    return n


def _register(entry, profile="landmark"):
    """寫入 discovered.yaml + sqlite。entry={id,name,url,event_type}。"""
    path = DISCOVERED_TRAFFIC_PATH if profile == "traffic" else DISCOVERED_PATH
    doc = _load_yaml(path)
    doc.setdefault("channels", []).append(entry)
    _save_yaml(path, doc)
    try:
        import db_factory
        db = db_factory.channel_db()
        if hasattr(db, "add_stream_channel"):
            location = "天眼-交通探索" if profile == "traffic" else "天眼-地標探索"
            db.add_stream_channel(entry["name"], entry["url"], entry["id"], location)
    except Exception:
        pass


def _profile_config(profile):
    if profile == "traffic":
        return {
            "queries": TRAFFIC_SEARCH_QUERIES,
            "score_fn": score_traffic_camera,
            "event_type": "traffic",
            "suffix": "交通探索",
            "target": "世界路口/道路監視器",
            "discovered_path": DISCOVERED_TRAFFIC_PATH,
        }
    return {
        "queries": LANDMARK_SEARCH_QUERIES,
        "score_fn": score_landmark,
        "event_type": "security_anomaly",
        "suffix": "自主發現",
        "target": "城市地標/公共場域",
        "discovered_path": DISCOVERED_PATH,
    }


def discover(max_new=3, vlm_fn=None, search_fn=None, validate_fn=None, score_fn=None, profile="landmark"):
    """自主探索:搜尋→驗證→評分→註冊。回新加入的 list[entry]。
    所有依賴皆可注入,方便單元測試。"""
    if profile not in ("landmark", "traffic"):
        raise ValueError(f"unknown discovery profile: {profile}")
    cfg = _profile_config(profile)
    search_fn = search_fn or yt_search
    validate_fn = validate_fn or validate
    score_fn = score_fn or cfg["score_fn"]
    known = existing_urls()
    _thoughts.record(f"我要自己上 YouTube 找新{cfg['target']}(目標 {max_new} 路;已知 {len(known)} 路)",
                     source="discover")
    seen = set()
    candidates = []
    for q in cfg["queries"]:
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
        eid = _next_id(profile)
        entry = {"id": eid, "name": f"{s['name'][:36]} · {cfg['suffix']}",
                 "url": s["url"], "event_type": cfg["event_type"]}
        _register(entry, profile=profile)
        added.append(entry)
        _thoughts.record(
            f"發現新天眼來源:{entry['name']}(profile={profile};信心 {s['score']:.2f})→ ch{eid} 加入巡檢",
            source="discover")
    if not added:
        _thoughts.record(f"這輪找到 {len(scored)} 個合格候選但都已在巡檢中或不夠強,沒新增", source="discover")
    return added


def main():
    import argparse
    p = argparse.ArgumentParser(description="自主攝影機探索(讓 agent 自己找新天眼)")
    p.add_argument("--max", type=int, default=3, help="本次最多新增幾路")
    p.add_argument("--profile", choices=("landmark", "traffic"),
                   default=os.environ.get("NEMOCLAW_DISCOVERY_PROFILE", "landmark"),
                   help="landmark=地標/公共場域; traffic=世界路口/道路監視器")
    args = p.parse_args()
    added = discover(max_new=args.max, profile=args.profile)
    print(json.dumps({"profile": args.profile, "added": len(added), "channels": added},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
