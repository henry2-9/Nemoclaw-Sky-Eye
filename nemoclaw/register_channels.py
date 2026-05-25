#!/usr/bin/env python3
"""讀 channels.yaml,把 16 部影片登錄成 file channel。冪等:已存在則略過。"""
import os, sys
import yaml

def load_channels(yaml_path):
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    vdir = os.path.expandvars(os.path.expanduser(data.get("video_dir", "")))
    out = []
    for c in data["channels"]:
        c = dict(c)
        if c.get("url"):                       # live 串流 channel(世界攝影機)
            c["path"] = os.path.expandvars(c["url"])
        else:                                  # 本地檔 channel
            c["path"] = os.path.abspath(os.path.join(vdir, c["file"]))
        out.append(c)
    return out

def _add_stream_channel(db, name, url, channel_id, location="NemoClaw Sentinel"):
    """直接插入 live 串流 channel(URL),繞過 add_file_channel 的檔案存在檢查。"""
    import datetime
    if db.get_channel_by_name(name):
        return
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
    sys.path.insert(0, os.environ.get("SENTINEL_WORKSPACE", os.path.expanduser("~/sentinel-workspace")))
    from database import StreamSourceDatabase
    chans = load_channels(channels_file())
    register(chans, StreamSourceDatabase())
    print(f"registered/verified {len(chans)} channels from {channels_file()}")

if __name__ == "__main__":
    main()
