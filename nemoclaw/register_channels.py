#!/usr/bin/env python3
"""讀 channels.yaml,把 16 部影片登錄成 file channel。冪等:已存在則略過。"""
import os, sys
import yaml

def _load_one(yaml_path):
    if not yaml_path or not os.path.exists(yaml_path):
        return {"channels": []}
    with open(yaml_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {"channels": []}


def load_channels(yaml_path):
    """讀主 yaml,並合併同目錄下 `discovered.yaml`(若存在)——
    讓 agent 自主探索新增的地標下一輪自動進入巡檢。"""
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
    discovered_path = os.path.join(os.path.dirname(os.path.abspath(yaml_path)), "discovered.yaml")
    for c in _load_one(discovered_path).get("channels", []) or []:
        if c.get("id") in seen_ids:
            continue
        c = dict(c); c["path"] = os.path.expandvars(c.get("url", ""))
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
    chans = load_channels(channels_file())
    register(chans, db_factory.channel_db())
    print(f"registered/verified {len(chans)} channels from {channels_file()} "
          f"[backend={db_factory.backend()}]")

if __name__ == "__main__":
    main()
