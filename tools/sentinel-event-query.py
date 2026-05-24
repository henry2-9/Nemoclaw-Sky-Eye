#!/usr/bin/env python3
import argparse
import json
import os
import sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


WORKSPACE_ROOT = Path(os.environ.get("SENTINEL_WORKSPACE", os.path.expanduser("~/sentinel-workspace"))).resolve()
EVENT_DATA_ROOT = WORKSPACE_ROOT / "event_data"
LOCAL_TZ = ZoneInfo("Asia/Taipei") if ZoneInfo else timezone(timedelta(hours=8))
PICTSHARE_URL = str(os.environ.get("PICTSHARE_URL", "")).strip().rstrip("/")
PICTSHARE_PUBLIC_URL = str(os.environ.get("PICTSHARE_PUBLIC_URL", "")).strip().rstrip("/")
PICTSHARE_UPLOAD_CODE = str(os.environ.get("PICTSHARE_UPLOAD_CODE", "YourSecretCode123")).strip()
PUBLIC_MEDIA_CACHE: dict[str, str | None] = {}

os.environ.setdefault("AI_VERBOSE", "0")
os.chdir(WORKSPACE_ROOT)
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

with redirect_stdout(sys.stderr):
    from database.event_database import EventDatabase
    from database.stream_source_database import StreamSourceDatabase
    from database.channel_setting_database import ChannelSettingDatabase


event_db = EventDatabase()
stream_db = StreamSourceDatabase()
channel_setting_db = ChannelSettingDatabase()


TYPE_ALIASES = {
    "ppe": 0,
    "personal protective equipment": 0,
    "behavior": 1,
    "behaviour": 1,
    "action": 1,
    "intrusion": 2,
    "safety": 3,
    # sentinel-video-ingest types
    "火煙偵測": 4, "fire_smoke": 4, "fire smoke": 4,
    "異常人流": 5, "abnormal_crowd": 5, "abnormal crowd": 5,
    "異常氣候": 6, "abnormal_weather": 6, "abnormal weather": 6,
    "人員闖入": 7, "person_intrusion": 7, "video_intrusion": 7,
}

CLASS_ALIASES = {
    0: {
        "no helmet": 0,
        "no_helmet": 0,
        "未戴安全帽": 0,
        "helmet": 1,
        "安全帽": 1,
        "no vest": 2,
        "no_vest": 2,
        "未穿背心": 2,
        "vest": 3,
        "背心": 3,
        "no belt": 4,
        "no_belt": 4,
        "未繫安全帶": 4,
        "belt": 5,
        "安全帶": 5,
    },
    1: {
        "fall": 0,
        "fall down": 0,
        "跌倒": 0,
        "throw cigarette": 1,
        "亂丟菸蒂": 1,
        "hands up": 2,
        "舉手": 2,
        "fight": 3,
        "打架": 3,
        "throwing": 4,
        "拋擲": 4,
        "smoking": 5,
        "抽菸": 5,
        "dashboard": 6,
        "dashboard_red": 7,
        "dashboard_orange": 8,
        "sitting still": 9,
        "久坐不動": 9,
    },
    2: {
        "enter": 0,
        "進入": 0,
        "exit": 1,
        "離開": 1,
        "direction": 2,
        "directional crossing": 3,
        "dwell": 4,
        "逗留": 4,
        "appear": 5,
        "disappear": 6,
        "abandoned": 7,
        "removed": 8,
        "presence": 9,
        "有人": 9,
    },
    3: {
        "hot_work": 0,
        "hot work": 0,
        "熱工": 0,
        "熱工事件": 0,
        "熱工作業": 0,
        "動火": 0,
        "動火作業": 0,
        "明火作業": 0,
        "elevated_work": 1,
        "elevated work": 1,
        "高架作業": 1,
        "高處作業": 1,
        "work_at_height": 2,
        "work at height": 2,
        "高空作業": 2,
        "lifting": 3,
        "吊掛": 3,
        "吊掛作業": 3,
        "高空吊掛作業": 3,
        "hanging operation": 3,
        "confined_space": 4,
        "confined space": 4,
        "侷限作業": 4,
        "侷限空間作業": 4,
        "侷限空間": 4,
        "局限作業": 4,
        "局限空間作業": 4,
        "局限空間": 4,
        "confined_space_count": 5,
        "confined space count": 5,
        "侷限作業人員計數": 5,
        "進洞計數": 5,
        "work_at_height_panorama": 6,
        "work at height panorama": 6,
        "高空作業全景": 6,
        "confined_space_oxygen_supervisor": 7,
        "confined space oxygen supervisor": 7,
        "侷限作業氧氣瓶主管": 7,
        "氧氣瓶主管": 7,
    },
    # sentinel-video-ingest class aliases
    4: {
        "fire": 0, "火": 0, "火焰": 0,
        "smoke": 1, "煙": 1, "煙霧": 1,
    },
    5: {
        "fight": 0, "打架": 0, "衝突": 0,
        "fleeing": 1, "逃跑": 1, "奔逃": 1,
    },
    6: {
        "typhoon": 1, "颱風": 1, "強風": 1,
        "fog": 2, "霧": 2, "濃霧": 2,
        "landslide": 3, "土石流": 3, "山崩": 3,
    },
    7: {
        "intrusion": 0, "闖入": 0, "入侵": 0,
    },
}
SAFETY_TASK_ALIASES: dict[str, str] = {}


def strip_known_prefixes(value: str) -> set[str]:
    normalized = " ".join(str(value or "").strip().split())
    if not normalized:
        return set()
    lowered = normalized.lower()
    prefixes = (
        "safety - ",
        "safety: ",
        "safety/",
        "safety ",
        "safety analysis - ",
        "safety analysis: ",
        "safety analysis ",
        "safety 分析 - ",
        "safety 分析: ",
        "safety 分析 ",
        "safety分析 - ",
        "safety分析: ",
        "safety分析 ",
    )
    stripped: set[str] = set()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            candidate = normalized[len(prefix):].strip(" -:/")
            if candidate:
                stripped.add(candidate)
    return stripped


def confined_space_variants(value: str) -> set[str]:
    variants: set[str] = set()
    replacements = (
        ("侷限作業", "侷限空間作業"),
        ("局限作業", "局限空間作業"),
        ("侷限空間作業", "侷限作業"),
        ("局限空間作業", "局限作業"),
    )
    for source, target in replacements:
        if source in value:
            variants.add(value.replace(source, target))
    return variants


def alias_variants(raw: str | None) -> set[str]:
    text = " ".join(str(raw or "").strip().split())
    if not text:
        return set()
    variants: set[str] = set()
    queue = [text, text.lower(), *strip_known_prefixes(text), *strip_known_prefixes(text.lower())]
    seen: set[str] = set()
    while queue:
        value = queue.pop()
        if not value or value in seen:
            continue
        seen.add(value)
        variants.add(value)
        normalized = value.replace("_", " ").replace("-", " ").replace("/", " ")
        collapsed = normalized.replace(" ", "")
        underscored = normalized.replace(" ", "_")
        hyphenated = normalized.replace(" ", "-")
        derived = {normalized, collapsed, underscored, hyphenated}
        if normalized.endswith("作業"):
            stem = normalized[:-2].strip()
            if stem:
                derived.update({stem, f"{stem}事件"})
        if normalized.endswith("事件"):
            stem = normalized[:-2].strip()
            if stem:
                derived.add(stem)
        if "侷" in normalized:
            derived.add(normalized.replace("侷", "局"))
        if "局" in normalized:
            derived.add(normalized.replace("局", "侷"))
        for item in list(derived) + [value]:
            derived.update(strip_known_prefixes(item))
            derived.update(confined_space_variants(item))
        for item in derived:
            if item and item not in seen:
                queue.append(item)
    return {item.strip().lower() for item in variants if item and item.strip()}


def augment_safety_aliases() -> None:
    aliases = CLASS_ALIASES.setdefault(3, {})
    task_aliases = SAFETY_TASK_ALIASES
    class_rows = event_db.event_class_database.get_classes_by_type_id(3) or []
    class_name_to_id = {
        str(row.get("event_class_name") or "").strip(): int(row.get("event_class_id"))
        for row in class_rows
        if str(row.get("event_class_name") or "").strip()
    }
    if not class_name_to_id:
        return

    for class_name, class_id in class_name_to_id.items():
        for variant in alias_variants(class_name):
            aliases.setdefault(variant, class_id)
            task_aliases.setdefault(variant, class_name)

    task_to_class_name = {name: name for name in class_name_to_id}
    task_to_class_name.update(
        {
            "confined_space_bw": "confined_space",
        }
    )

    try:
        from safety_work.task_profiles import TASK_PROFILES
    except Exception:
        TASK_PROFILES = {}
    for task_id, profile in (TASK_PROFILES or {}).items():
        task_id = str(task_id).strip()
        canonical_class = task_to_class_name.get(str(task_id).strip())
        if not canonical_class:
            continue
        class_id = class_name_to_id.get(canonical_class)
        if class_id is None:
            continue
        for variant in alias_variants(task_id):
            aliases.setdefault(variant, class_id)
            task_aliases.setdefault(variant, task_id)
        for variant in alias_variants(getattr(profile, "title", "")):
            aliases.setdefault(variant, class_id)
            task_aliases.setdefault(variant, task_id)
        for variant in alias_variants(getattr(profile, "subtitle", "")):
            aliases.setdefault(variant, class_id)
            task_aliases.setdefault(variant, task_id)

    try:
        from ui_utils.event_display_utils import _SAFETY_TASK_ALIASES
    except Exception:
        _SAFETY_TASK_ALIASES = {}
    for alias, task_id in (_SAFETY_TASK_ALIASES or {}).items():
        canonical_class = task_to_class_name.get(str(task_id).strip())
        if not canonical_class:
            continue
        class_id = class_name_to_id.get(canonical_class)
        if class_id is None:
            continue
        for variant in alias_variants(alias):
            aliases.setdefault(variant, class_id)
            task_aliases.setdefault(variant, str(task_id).strip())


augment_safety_aliases()


def emit(payload: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def fail(message: str, code: int = 1) -> None:
    emit({"ok": False, "error": message}, code)


def local_time(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return str(value)
    if dt.tzinfo is None:
        # Sentinel writes Event_time with datetime.now(), so naive datetimes are local wall clock.
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    dt = dt.astimezone(LOCAL_TZ)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def normalize_query_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(LOCAL_TZ).replace(tzinfo=None)


def resolve_today_window() -> tuple[datetime, datetime]:
    now_local = datetime.now()
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local, now_local


def jsonable(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    return value


def camera_meta_map() -> dict[int, dict[str, Any]]:
    cameras: dict[int, dict[str, Any]] = {}
    for row in stream_db.get_all_channels():
        channel_id = int(row.get("channel_id", 0))
        cameras[channel_id] = {
            "channel_id": channel_id,
            "channel_name": row.get("channel_name") or f"cam{channel_id}",
            "location": row.get("location") or "",
            "source_type": row.get("source_type") or "",
            "is_active": bool(row.get("is_active", False)),
            "is_delete": bool(row.get("is_delete", False)),
        }
    for row in channel_setting_db.get_all_camera_settings():
        channel_id = int(row.get("Channel_id", 0))
        cameras.setdefault(
            channel_id,
            {
                "channel_id": channel_id,
                "channel_name": f"cam{channel_id}",
                "location": "",
                "source_type": "",
                "is_active": True,
                "is_delete": False,
            },
        )
        cameras[channel_id]["ai_model"] = row.get("AI_model") or ""
        cameras[channel_id]["updated_time"] = local_time(row.get("Updated_time"))
    return cameras


CAMERAS = camera_meta_map()


def normalize_type_id(raw: str | None) -> int | None:
    if not raw or raw.lower() == "all":
        return None
    if raw.isdigit():
        return int(raw)
    type_id = TYPE_ALIASES.get(raw.lower())
    if type_id is not None:
        return type_id
    found = event_db.event_type_database.get_event_type_id_by_name(raw)
    return int(found) if found is not None else None


def normalize_class(type_id: int | None, raw: str | None) -> tuple[int | None, int | None]:
    if not raw or raw.lower() == "all":
        return type_id, None
    if raw.isdigit():
        return type_id, int(raw)

    lookup_keys = alias_variants(raw) or {raw.lower()}
    all_type_ids = [int(row.get("event_type_id")) for row in event_db.event_type_database.get_all_event_types()]
    if not all_type_ids:
        all_type_ids = [0, 1, 2, 3]

    type_ids = [type_id] if type_id is not None else all_type_ids
    for candidate_type_id in type_ids:
        for lookup_key in lookup_keys:
            alias_id = CLASS_ALIASES.get(candidate_type_id, {}).get(lookup_key)
            if alias_id is not None:
                return candidate_type_id, alias_id
        found = event_db.event_class_database.get_event_class_id_by_name(candidate_type_id, raw)
        if found is not None:
            return candidate_type_id, int(found)
        for lookup_key in lookup_keys:
            found = event_db.event_class_database.get_event_class_id_by_name(candidate_type_id, lookup_key)
            if found is not None:
                return candidate_type_id, int(found)

    if type_id is not None:
        for candidate_type_id in all_type_ids:
            if candidate_type_id == type_id:
                continue
            for lookup_key in lookup_keys:
                alias_id = CLASS_ALIASES.get(candidate_type_id, {}).get(lookup_key)
                if alias_id is not None:
                    return candidate_type_id, alias_id
            found = event_db.event_class_database.get_event_class_id_by_name(candidate_type_id, raw)
            if found is not None:
                return candidate_type_id, int(found)
            for lookup_key in lookup_keys:
                found = event_db.event_class_database.get_event_class_id_by_name(candidate_type_id, lookup_key)
                if found is not None:
                    return candidate_type_id, int(found)
    return type_id, None


def resolve_safety_task_id(raw: str | None) -> str | None:
    for lookup_key in alias_variants(raw):
        task_id = SAFETY_TASK_ALIASES.get(lookup_key)
        if task_id:
            return task_id
    return None


def resolve_status_filter(status: str) -> dict[str, Any]:
    if status == "pending":
        return {
            "$or": [
                {"Confirm_state": {"$regex": "^pending$", "$options": "i"}},
                {"$and": [{"Is_confirmed": False}, {"Confirm_state": {"$nin": ["confirmed", "rejected"]}}]},
                {"$and": [{"Confirm_state": {"$exists": False}}, {"Is_confirmed": {"$exists": False}}]},
                {"Confirm_state": None, "Is_confirmed": {"$ne": True}},
                {"Confirm_state": "", "Is_confirmed": {"$ne": True}},
            ]
        }
    if status == "confirmed":
        return {"$or": [{"Confirm_state": "confirmed"}, {"Is_confirmed": True}]}
    if status == "rejected":
        return {"Confirm_state": "rejected"}
    return {}


def build_filter(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    query: dict[str, Any] = {}
    info: dict[str, Any] = {}

    now = datetime.now()
    start_dt = None
    end_dt = None
    if args.today:
        start_dt, end_dt = resolve_today_window()
        info["time_range"] = "today"
    if args.hours is not None:
        start_dt = now - timedelta(hours=float(args.hours))
        end_dt = now
    if args.days is not None:
        start_dt = now - timedelta(days=float(args.days))
        end_dt = now
    if args.start:
        start_dt = normalize_query_datetime(datetime.fromisoformat(args.start.replace("Z", "+00:00")))
    if args.end:
        end_dt = normalize_query_datetime(datetime.fromisoformat(args.end.replace("Z", "+00:00")))
    if start_dt or end_dt:
        query["Event_time"] = {}
        if start_dt:
            query["Event_time"]["$gte"] = start_dt
            info["start_time"] = local_time(start_dt)
        if end_dt:
            query["Event_time"]["$lt"] = end_dt
            info["end_time"] = local_time(end_dt)

    if args.camera is not None:
        query["Channel_id"] = int(args.camera)
        info["camera"] = int(args.camera)

    type_id = normalize_type_id(args.type)
    if args.type and str(args.type).strip() and str(args.type).strip().lower() != "all" and type_id is None:
        fail(f"Unknown event type: {args.type}", 2)
    type_id, class_id = normalize_class(type_id, args.event_class)
    if args.event_class and str(args.event_class).strip() and str(args.event_class).strip().lower() != "all" and class_id is None:
        fail(f"Unknown event class: {args.event_class}", 2)

    safety_task_id = resolve_safety_task_id(args.event_class) if type_id == 3 else None
    if type_id is not None:
        query["Event_type_id"] = int(type_id)
        info["event_type_id"] = int(type_id)
        info["event_type_name"] = event_db.event_type_database.get_event_type_by_id(int(type_id))
    if class_id is not None:
        query["Event_class_id"] = int(class_id)
        info["event_class_id"] = int(class_id)
        info["event_class_name"] = event_db.event_class_database.get_event_class_by_id(int(type_id), int(class_id))
    if safety_task_id:
        task_query = event_db._build_safety_task_query("Safety", safety_task_id)
        if task_query:
            query.update(task_query)
            info["event_class_name"] = safety_task_id
            info["safety_task_id"] = safety_task_id

    query.update(resolve_status_filter(args.status))
    if args.status != "all":
        info["status"] = args.status
    return query, info


def with_media_candidates(base_name: str | None, kind: str) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    if not base_name:
        return {"name": None, "candidates": []}

    paths: list[Path] = []
    if kind in {"full", "crop"}:
        filename = base_name if base_name.endswith(".jpg") else f"{base_name}.jpg"
        paths.append(EVENT_DATA_ROOT / filename)
    elif kind == "video":
        if base_name.endswith(".mp4") or base_name.endswith(".avi"):
            paths.append(EVENT_DATA_ROOT / base_name)
        else:
            paths.append(EVENT_DATA_ROOT / f"{base_name}.mp4")
            paths.append(EVENT_DATA_ROOT / f"{base_name}.avi")
            paths.append(EVENT_DATA_ROOT / f"{base_name}_frames")

    seen: set[str] = set()
    for path in paths:
        path_str = str(path)
        if path_str in seen:
            continue
        seen.add(path_str)
        candidates.append(
            {
                "absolute_path": path_str,
                "relative_path": os.path.relpath(path, WORKSPACE_ROOT),
                "exists": path.exists(),
                "kind": "directory" if path.is_dir() else ("file" if path.is_file() else "missing"),
            }
        )
    return {"name": base_name, "candidates": candidates}


def _guess_upload_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".gif":
        return "image/gif"
    if suffix == ".webp":
        return "image/webp"
    return "application/octet-stream"


def upload_public_media_url(path_str: str | None) -> str | None:
    normalized = str(path_str or "").strip()
    if not normalized:
        return None
    cached = PUBLIC_MEDIA_CACHE.get(normalized, None)
    if normalized in PUBLIC_MEDIA_CACHE:
        return cached

    path = Path(normalized)
    if not path.is_file():
        PUBLIC_MEDIA_CACHE[normalized] = None
        return None
    if not PICTSHARE_URL:
        PUBLIC_MEDIA_CACHE[normalized] = None
        return None

    try:
        import requests
    except Exception:
        PUBLIC_MEDIA_CACHE[normalized] = None
        return None

    data: dict[str, str] = {}
    if PICTSHARE_UPLOAD_CODE:
        data["uploadcode"] = PICTSHARE_UPLOAD_CODE

    try:
        with path.open("rb") as fh:
            response = requests.post(
                f"{PICTSHARE_URL}/api/upload.php",
                files={"file": (path.name, fh, _guess_upload_mime(path))},
                data=data,
                timeout=8.0,
            )
        if response.status_code >= 400:
            PUBLIC_MEDIA_CACHE[normalized] = None
            return None
        body = response.json() if response.content else {}
    except Exception:
        PUBLIC_MEDIA_CACHE[normalized] = None
        return None

    if not isinstance(body, dict) or str(body.get("status") or "").lower() != "ok":
        PUBLIC_MEDIA_CACHE[normalized] = None
        return None

    url_base = PICTSHARE_PUBLIC_URL or PICTSHARE_URL
    raw_url = str(body.get("url") or "").strip()
    if raw_url.startswith("http://") or raw_url.startswith("https://"):
        if PICTSHARE_PUBLIC_URL:
            try:
                from urllib.parse import urlparse

                parsed = urlparse(raw_url)
                path_part = str(parsed.path or "").strip("/")
                if path_part:
                    public_url = f"{url_base}/{path_part}"
                    PUBLIC_MEDIA_CACHE[normalized] = public_url
                    return public_url
            except Exception:
                pass
        PUBLIC_MEDIA_CACHE[normalized] = raw_url
        return raw_url
    if raw_url.startswith("/"):
        public_url = f"{url_base}{raw_url}"
        PUBLIC_MEDIA_CACHE[normalized] = public_url
        return public_url
    if raw_url:
        public_url = f"{url_base}/{raw_url.lstrip('/')}"
        PUBLIC_MEDIA_CACHE[normalized] = public_url
        return public_url

    image_hash = str(body.get("hash") or "").strip().lstrip("/")
    if image_hash:
        public_url = f"{url_base}/{image_hash}"
        PUBLIC_MEDIA_CACHE[normalized] = public_url
        return public_url

    PUBLIC_MEDIA_CACHE[normalized] = None
    return None


def with_public_media_candidates(media: dict[str, Any]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for candidate in media.get("candidates") or []:
        next_candidate = dict(candidate)
        if next_candidate.get("kind") == "file":
            public_url = upload_public_media_url(next_candidate.get("absolute_path"))
            if public_url:
                next_candidate["public_url"] = public_url
        candidates.append(next_candidate)
    return {**media, "candidates": candidates}


def resolve_media_delivery(blocks: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    for kind, block in blocks:
        for candidate in block.get("candidates") or []:
            if candidate.get("kind") != "file":
                continue
            public_url = str(candidate.get("public_url") or "").strip()
            relative_path = str(candidate.get("relative_path") or "").strip()
            if public_url:
                return {
                    "preferred_media_kind": kind,
                    "preferred_media": candidate,
                    "media_url": public_url,
                    "media_directive": f"MEDIA:{public_url}",
                }
            if relative_path:
                rel_value = f"./{relative_path.lstrip('./')}"
                return {
                    "preferred_media_kind": kind,
                    "preferred_media": candidate,
                    "media_path": rel_value,
                    "media_directive": f"MEDIA:{rel_value}",
                }
    return {}


def attach_media_delivery(event: dict[str, Any]) -> dict[str, Any]:
    crop_image = with_public_media_candidates(event["crop_image"])
    full_image = with_public_media_candidates(event["full_image"])
    video = event["video"]
    event["crop_image"] = crop_image
    event["full_image"] = full_image
    event["video"] = video
    event.update(
        resolve_media_delivery(
            [
                ("full_image", full_image),
                ("crop_image", crop_image),
                ("video", video),
            ]
        )
    )
    return event


def enrich_event(doc: dict[str, Any]) -> dict[str, Any]:
    enriched = event_db._enrich_event_info(doc)
    metadata = jsonable(enriched.get("metadata") or {})
    safety_task_id = str(metadata.get("task_id") or "").strip() or None
    safety_task_title = str(metadata.get("task_title") or "").strip() or None
    raw_event_class_name = enriched.get("Event_class_name")
    description = str(
        enriched.get("Description")
        or metadata.get("primary_description")
        or metadata.get("description")
        or ""
    ).strip()
    ai_summary = str(
        enriched.get("ai_summary")
        or metadata.get("ai_summary")
        or ""
    ).strip()
    channel_id = int(enriched.get("Channel_id", 0))
    camera = CAMERAS.get(
        channel_id,
        {
            "channel_id": channel_id,
            "channel_name": f"cam{channel_id}",
            "location": "",
            "source_type": "",
            "is_active": True,
            "is_delete": False,
        },
    )
    return {
        "event_id": str(enriched.get("_id")),
        "event_time": local_time(enriched.get("Event_time")),
        "event_time_utc": jsonable(enriched.get("Event_time")),
        "event_type_id": enriched.get("Event_type_id"),
        "event_type_name": enriched.get("Event_type_name"),
        "event_class_id": enriched.get("Event_class_id"),
        "event_class_name": safety_task_id or raw_event_class_name,
        "event_class_raw_name": raw_event_class_name,
        "event_class_title": safety_task_title or raw_event_class_name,
        "safety_task_id": safety_task_id,
        "safety_task_title": safety_task_title,
        "description": description,
        "ai_summary": ai_summary,
        "channel_id": channel_id,
        "camera": camera,
        "confirm_state": enriched.get("Confirm_state") or "pending",
        "is_confirmed": bool(enriched.get("Is_confirmed", False)),
        "location": enriched.get("Location") or camera.get("location") or "",
        "confidence": enriched.get("confidence"),
        "track_id": enriched.get("track_id"),
        "bbox": jsonable(enriched.get("bbox")),
        "metadata": metadata,
        "full_image": with_media_candidates(enriched.get("Full_image"), "full"),
        "crop_image": with_media_candidates(enriched.get("Crop_image"), "crop"),
        "video": with_media_candidates(enriched.get("Full_video"), "video"),
    }


def projection() -> dict[str, int]:
    return {
        "_id": 1,
        "Event_type_id": 1,
        "Event_class_id": 1,
        "Channel_id": 1,
        "Event_time": 1,
        "Location": 1,
        "Full_image": 1,
        "Crop_image": 1,
        "Full_video": 1,
        "Confirm_state": 1,
        "Is_confirmed": 1,
        "Confirmed_at": 1,
        "Rejected_at": 1,
        "Imported_test_video": 1,
        "confidence": 1,
        "track_id": 1,
        "Description": 1,
        "ai_summary": 1,
        "metadata": 1,
        "bbox": 1,
    }


def command_summary(args: argparse.Namespace) -> None:
    query, info = build_filter(args)
    limit = max(1, min(int(args.limit), 20))
    result = list(
        event_db.collection.aggregate(
            [
                {"$match": query},
                {
                    "$facet": {
                        "totals": [{"$count": "events"}],
                        "by_status": [{"$group": {"_id": "$Confirm_state", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}],
                        "by_type": [{"$group": {"_id": "$Event_type_id", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}],
                        "by_class": [
                            {"$group": {"_id": {"type": "$Event_type_id", "class": "$Event_class_id"}, "count": {"$sum": 1}}},
                            {"$sort": {"count": -1}},
                            {"$limit": limit},
                        ],
                        "by_camera": [{"$group": {"_id": "$Channel_id", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}],
                        "latest": [{"$sort": {"Event_time": -1}}, {"$limit": min(limit, 10)}, {"$project": projection()}],
                    }
                },
            ]
        )
    )
    data = result[0] if result else {}
    total_rows = data.get("totals") or []
    total_events = int(total_rows[0]["events"]) if total_rows else 0

    by_type = []
    for row in data.get("by_type") or []:
        type_id = int(row["_id"])
        by_type.append(
            {
                "event_type_id": type_id,
                "event_type_name": event_db.event_type_database.get_event_type_by_id(type_id),
                "count": int(row["count"]),
            }
        )

    by_class = []
    for row in data.get("by_class") or []:
        type_id = int(row["_id"]["type"])
        class_id = int(row["_id"]["class"])
        by_class.append(
            {
                "event_type_id": type_id,
                "event_type_name": event_db.event_type_database.get_event_type_by_id(type_id),
                "event_class_id": class_id,
                "event_class_name": event_db.event_class_database.get_event_class_by_id(type_id, class_id),
                "count": int(row["count"]),
            }
        )

    by_camera = []
    for row in data.get("by_camera") or []:
        channel_id = int(row["_id"])
        camera = CAMERAS.get(channel_id, {"channel_id": channel_id, "channel_name": f"cam{channel_id}", "location": ""})
        by_camera.append(
            {
                "channel_id": channel_id,
                "channel_name": camera.get("channel_name"),
                "location": camera.get("location"),
                "count": int(row["count"]),
            }
        )

    emit(
        {
            "ok": True,
            "command": "summary",
            "workspace": str(WORKSPACE_ROOT),
            "database": "NemoClaw_test_db",
            "collection": "EVENT_RECORD",
            "filters": info,
            "total_events": total_events,
            "by_status": jsonable(data.get("by_status") or []),
            "by_type": by_type,
            "by_class": by_class,
            "by_camera": by_camera,
            "latest": [enrich_event(doc) for doc in (data.get("latest") or [])],
        }
    )


def command_latest(args: argparse.Namespace) -> None:
    query, info = build_filter(args)
    limit = max(1, min(int(args.limit), 50))
    docs = list(event_db.collection.find(query, projection()).sort("Event_time", -1).limit(limit))
    events = [enrich_event(doc) for doc in docs]
    if limit == 1 and events:
        events[0] = attach_media_delivery(events[0])
    emit({"ok": True, "command": "latest", "filters": info, "events": events})


def command_event(args: argparse.Namespace) -> None:
    doc = event_db.collection.find_one({"_id": ObjectId(args.id)}, projection())
    if not doc:
        fail(f"Event not found: {args.id}", 2)
    emit({"ok": True, "command": "event", "event": attach_media_delivery(enrich_event(doc))})


def command_media(args: argparse.Namespace) -> None:
    if args.id:
        doc = event_db.collection.find_one({"_id": ObjectId(args.id)}, projection())
    else:
        query, _info = build_filter(args)
        doc = event_db.collection.find_one(query, projection(), sort=[("Event_time", -1)])
    if not doc:
        fail("No matching event with media found", 2)

    enriched = attach_media_delivery(enrich_event(doc))
    crop_image = enriched["crop_image"]
    full_image = enriched["full_image"]
    video = enriched["video"]
    payload = {
        "ok": True,
        "command": "media",
        "event": {
            "event_id": enriched["event_id"],
            "event_time": enriched["event_time"],
            "event_type_name": enriched["event_type_name"],
            "event_class_name": enriched["event_class_name"],
            "event_class_raw_name": enriched["event_class_raw_name"],
            "event_class_title": enriched["event_class_title"],
            "safety_task_id": enriched["safety_task_id"],
            "safety_task_title": enriched["safety_task_title"],
            "channel_id": enriched["channel_id"],
            "camera": enriched["camera"],
            "confirm_state": enriched["confirm_state"],
        },
    }
    if args.kind in {"all", "crop"}:
        payload["crop_image"] = crop_image
    if args.kind in {"all", "full"}:
        payload["full_image"] = full_image
    if args.kind in {"all", "video"}:
        payload["video"] = video

    ordered_blocks: list[tuple[str, dict[str, Any]]] = []
    if args.kind == "crop":
        ordered_blocks = [("crop_image", crop_image)]
    elif args.kind == "full":
        ordered_blocks = [("full_image", full_image)]
    elif args.kind == "video":
        ordered_blocks = [("video", video)]
    else:
        ordered_blocks = [
            ("full_image", full_image),
            ("crop_image", crop_image),
            ("video", video),
        ]
    payload.update(resolve_media_delivery(ordered_blocks))
    emit(payload)


def command_cameras(_args: argparse.Namespace) -> None:
    emit({"ok": True, "command": "cameras", "cameras": list(CAMERAS.values())})


def add_common_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--hours", type=float, help="Look back N hours")
    parser.add_argument("--days", type=float, help="Look back N days")
    parser.add_argument("--today", action="store_true", help="Filter by current Asia/Taipei calendar day")
    parser.add_argument("--start", help="Start time in ISO format")
    parser.add_argument("--end", help="End time in ISO format")
    parser.add_argument("--camera", type=int, help="Filter by camera/channel id")
    parser.add_argument("--type", help="Event type name or id")
    parser.add_argument("--class", dest="event_class", help="Event class name or id")
    parser.add_argument("--status", choices=["all", "pending", "confirmed", "rejected"], default="all")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Sentinel MongoDB event query helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    summary = subparsers.add_parser("summary")
    add_common_filters(summary)
    summary.add_argument("--limit", type=int, default=5)

    latest = subparsers.add_parser("latest")
    add_common_filters(latest)
    latest.add_argument("--limit", type=int, default=10)

    event = subparsers.add_parser("event")
    event.add_argument("--id", "--event-id", dest="id", required=True)

    media = subparsers.add_parser("media")
    add_common_filters(media)
    media.add_argument("--id", "--event-id", dest="id")
    media.add_argument("--kind", choices=["all", "crop", "full", "video"], default="all")

    subparsers.add_parser("cameras")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "summary":
        command_summary(args)
    elif args.command == "latest":
        command_latest(args)
    elif args.command == "event":
        command_event(args)
    elif args.command == "media":
        command_media(args)
    elif args.command == "cameras":
        command_cameras(args)
    else:
        fail(f"Unsupported command: {args.command}", 2)


if __name__ == "__main__":
    main()
