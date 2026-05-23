#!/usr/bin/env python3
"""讀 channels.yaml,把 16 部影片登錄成 file channel。冪等:已存在則略過。"""
import os, sys
import yaml

def load_channels(yaml_path):
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    vdir = data["video_dir"]
    out = []
    for c in data["channels"]:
        c = dict(c)
        c["path"] = os.path.abspath(os.path.join(vdir, c["file"]))
        out.append(c)
    return out

def register(channels, db):
    for c in channels:
        if db.get_channel_by_channel_id(c["id"]):
            continue
        db.add_file_channel(channel_name=c["name"], file_path=c["path"],
                            channel_id=c["id"], location="NemoClaw Sentinel")

def main():
    sys.path.insert(0, os.environ.get("FPG_WORKSPACE_ROOT", "/home/aiunion/FPG"))
    from database import StreamSourceDatabase
    chans = load_channels(os.path.join(os.path.dirname(__file__), "channels.yaml"))
    register(chans, StreamSourceDatabase())
    print(f"registered/verified {len(chans)} channels")

if __name__ == "__main__":
    main()
