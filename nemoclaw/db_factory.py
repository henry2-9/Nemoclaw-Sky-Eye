#!/usr/bin/env python3
"""DB 後端工廠。
NEMOCLAW_DB_BACKEND=sqlite → nemoclaw 本地 SQLite(sqlite_store);
其他/未設 → FPG 共用的 MongoDB(database 模組,沿用舊行為)。
工具與 register 都透過這裡取得 DB,切換後端不必改各處程式。"""
import os
import sys

_NEMODIR = os.path.dirname(os.path.abspath(__file__))


def backend():
    return os.environ.get("NEMOCLAW_DB_BACKEND", "mongo").strip().lower()


def _mongo_path():
    sys.path.insert(0, os.environ.get("SENTINEL_WORKSPACE", os.path.expanduser("~/sentinel-workspace")))


def channel_db():
    if backend() == "sqlite":
        sys.path.insert(0, _NEMODIR)
        from sqlite_store import ChannelStore
        return ChannelStore()
    _mongo_path()
    from database import StreamSourceDatabase
    return StreamSourceDatabase()


def event_db():
    if backend() == "sqlite":
        sys.path.insert(0, _NEMODIR)
        from sqlite_store import EventStore
        return EventStore()
    _mongo_path()
    from database import EventDatabase
    return EventDatabase()
