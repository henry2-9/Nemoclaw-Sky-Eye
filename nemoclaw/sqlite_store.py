#!/usr/bin/env python3
"""nemoclaw 專用 SQLite 後端(與 FPG 共用的 MongoDB 脫鉤,bot 不受影響)。
提供 ChannelStore / EventStore,介面對齊 sentinel-* 工具實際用到的方法子集。
DB 路徑由 NEMOCLAW_SQLITE_PATH 決定(預設 nemoclaw/sentinel.db)。"""
import os
import json
import sqlite3
import datetime
import uuid


def db_path():
    return os.environ.get(
        "NEMOCLAW_SQLITE_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "sentinel.db"),
    )


def _conn():
    c = sqlite3.connect(db_path(), timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS channels (
        channel_id INTEGER PRIMARY KEY, channel_name TEXT UNIQUE, source_type TEXT,
        source_url TEXT, location TEXT, is_active INTEGER DEFAULT 1,
        is_delete INTEGER DEFAULT 0, created_time TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS events (
        event_id TEXT PRIMARY KEY, camera_id INTEGER, type_id INTEGER, class_id INTEGER,
        description TEXT, metadata TEXT, image_path TEXT, clip_path TEXT,
        event_time TEXT, created_time TEXT)""")
    return c


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


class ChannelStore:
    """對齊 StreamSourceDatabase 中 nemoclaw/工具用到的方法。"""

    def get_channel_by_channel_id(self, cid):
        with _conn() as c:
            r = c.execute("SELECT * FROM channels WHERE channel_id=? AND is_delete=0",
                          (int(cid),)).fetchone()
            return dict(r) if r else None

    def get_channel_by_name(self, name):
        with _conn() as c:
            r = c.execute("SELECT * FROM channels WHERE channel_name=? AND is_delete=0",
                          (name,)).fetchone()
            return dict(r) if r else None

    def _add(self, name, stype, url, cid, location):
        if self.get_channel_by_name(name):
            return None
        with _conn() as c:
            if cid is None:
                cid = c.execute("SELECT COALESCE(MAX(channel_id),0)+1 FROM channels").fetchone()[0]
            elif c.execute("SELECT 1 FROM channels WHERE channel_id=?", (int(cid),)).fetchone():
                return None
            c.execute("""INSERT INTO channels
                (channel_id,channel_name,source_type,source_url,location,is_active,is_delete,created_time)
                VALUES (?,?,?,?,?,1,0,?)""", (int(cid), name, stype, url, location, _now()))
            c.commit()
        return str(cid)

    def add_file_channel(self, channel_name, file_path, channel_id=None, location=""):
        if not os.path.exists(file_path):
            return None
        return self._add(channel_name, "file", file_path, channel_id, location)

    def add_stream_channel(self, channel_name, url, channel_id=None, location=""):
        return self._add(channel_name, "stream", url, channel_id, location)

    def get_stream_sources_with_channel_ids(self):
        with _conn() as c:
            return [(r["source_url"], r["channel_id"]) for r in
                    c.execute("SELECT source_url,channel_id FROM channels WHERE is_active=1 AND is_delete=0")]

    def get_all_channels(self):
        with _conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM channels WHERE is_delete=0")]


class EventStore:
    """對齊 EventDatabase 中 nemoclaw/工具用到的方法子集(insert / 取回 / 近期)。"""

    def insert_event(self, event):
        ev = dict(event or {})
        eid = str(ev.get("event_id") or ev.get("_id") or uuid.uuid4().hex[:24])
        meta = ev.get("metadata")
        with _conn() as c:
            c.execute("""INSERT OR REPLACE INTO events
                (event_id,camera_id,type_id,class_id,description,metadata,image_path,clip_path,event_time,created_time)
                VALUES (?,?,?,?,?,?,?,?,?,?)""", (
                eid, ev.get("camera_id") or ev.get("channel_id"), ev.get("type_id"),
                ev.get("class_id"), ev.get("description"),
                json.dumps(meta, ensure_ascii=False) if meta is not None else None,
                ev.get("image_path") or ev.get("combined_image"), ev.get("clip_path"),
                str(ev.get("event_time") or _now()), _now()))
            c.commit()
        return eid

    def _row(self, r):
        d = dict(r)
        if d.get("metadata"):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except Exception:
                pass
        return d

    def get_event_by_id(self, event_id):
        with _conn() as c:
            r = c.execute("SELECT * FROM events WHERE event_id=?", (str(event_id),)).fetchone()
            return self._row(r) if r else None

    def get_latest_events(self, limit=20):
        with _conn() as c:
            return [self._row(r) for r in
                    c.execute("SELECT * FROM events ORDER BY created_time DESC LIMIT ?", (int(limit),))]

    def get_latest_events_by_camera(self, camera_id, limit=20):
        with _conn() as c:
            return [self._row(r) for r in c.execute(
                "SELECT * FROM events WHERE camera_id=? ORDER BY created_time DESC LIMIT ?",
                (camera_id, int(limit)))]
