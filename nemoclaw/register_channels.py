#!/usr/bin/env python3
"""讀 channels.yaml,把 16 部影片登錄成 file channel。冪等:已存在則略過。"""
import os, sys
import yaml


def discovery_enabled():
    return os.environ.get("NEMOCLAW_DISCOVERY_ENABLED", "0") == "1"

def _load_one(yaml_path):
    if not yaml_path or not os.path.exists(yaml_path):
        return {"channels": []}
    with open(yaml_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {"channels": []}


def load_channels(yaml_path, merge_discovered=False):
    """讀主 yaml。merge_discovered=True 時合併同目錄下 `discovered.yaml`(若存在)——
    讓 agent 自主探索新增的地標下一輪自動進入巡檢。生產(cycle/CLI)預設開啟,
    單元測試預設關閉避免被 runtime discovered 污染。"""
    data = _load_one(yaml_path)
    vdir = os.path.expandvars(os.path.expanduser(data.get("video_dir", "")))
    out, seen_ids = [], set()
    for c in data.get("channels", []) or []:
        c = dict(c)
        if c.get("url"):
            c["path"] = os.path.expandvars(c["url"])
        else:
            c["path"] = os.path.abspath(os.path.join(vdir, c["file"]))
        out.append(c); seen_ids.add(c["id"])
    # 自主發現來源只合併至對應 profile；不得污染本地 replay 或其他來源。
    base = os.path.basename(os.path.abspath(yaml_path))
    discovered_name = None
    if merge_discovered and base == "landmarks.yaml":
        discovered_name = "discovered.yaml"
    elif merge_discovered and base == "world_channels.yaml":
        discovered_name = "discovered_traffic.yaml"
    if discovered_name:
        discovered_path = os.path.join(os.path.dirname(os.path.abspath(yaml_path)), discovered_name)
        for c in _load_one(discovered_path).get("channels", []) or []:
            if c.get("id") in seen_ids:
                continue
            c = dict(c); c["path"] = os.path.expandvars(c.get("url", ""))
            if base == "landmarks.yaml" and c.get("event_type") == "abnormal_crowd":
                c["event_type"] = "security_anomaly"  # migrate pre-security-gate discoveries in memory
            if base == "world_channels.yaml":
                c["event_type"] = "traffic"
            out.append(c); seen_ids.add(c["id"])
    return out

def _add_stream_channel(db, name, url, channel_id, location="NemoClaw Sentinel"):
    """登錄 live 串流 channel(URL),繞過 add_file_channel 的檔案存在檢查。
    SQLite 後端有 add_stream_channel;Mongo 後端則直接插入 collection。"""
    if db.get_channel_by_name(name):
        return
    if hasattr(db, "add_stream_channel"):          # SQLite ChannelStore
        db.add_stream_channel(name, url, channel_id, location)
        return
    import datetime                                 # Mongo StreamSourceDatabase
    db.collection.insert_one({
        "channel_id": channel_id, "channel_name": name,
        "source_type": "stream", "source_url": url, "location": location,
        "is_active": True, "is_delete": False,
        "created_time": datetime.datetime.now(), "updated_time": datetime.datetime.now(),
    })

def register(channels, db):
    for c in channels:
        if db.get_channel_by_channel_id(c["id"]):
            if c.get("url") and hasattr(db, "update_stream_channel"):
                db.update_stream_channel(c["id"], c["name"], c["path"], "NemoClaw Sentinel")
            continue
        if c.get("url"):                       # live 串流(世界攝影機)
            _add_stream_channel(db, c["name"], c["path"], c["id"])
        else:                                  # 本地檔
            db.add_file_channel(channel_name=c["name"], file_path=c["path"],
                                channel_id=c["id"], location="NemoClaw Sentinel")

def channels_file():
    return os.environ.get("NEMOCLAW_CHANNELS_FILE",
                          os.path.join(os.path.dirname(__file__), "channels.yaml"))

def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import db_factory
    chans = load_channels(channels_file(), merge_discovered=discovery_enabled())
    register(chans, db_factory.channel_db())
    print(f"registered/verified {len(chans)} channels from {channels_file()} "
          f"[backend={db_factory.backend()}]")

if __name__ == "__main__":
    main()
