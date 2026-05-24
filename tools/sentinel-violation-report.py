#!/usr/bin/env python3
import argparse
import importlib.util
import json
import mimetypes
import os
import re
import sys
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, quoteattr

import requests
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


WORKSPACE_ROOT = Path(os.environ.get("SENTINEL_WORKSPACE", os.path.expanduser("~/sentinel-workspace"))).resolve()
REPORT_DIR = WORKSPACE_ROOT / "event_data" / "reports"
QUERY_MODULE_PATH = WORKSPACE_ROOT / ".openclaw" / "bin" / "sentinel-event-query.py"


def load_query_module():
    spec = importlib.util.spec_from_file_location("sentinel_event_query_module", QUERY_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load query module: {QUERY_MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    with redirect_stdout(sys.stderr):
        spec.loader.exec_module(module)
    return module


QUERY = load_query_module()


def emit(payload: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def fail(message: str, code: int = 1) -> None:
    emit({"ok": False, "error": message}, code)


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", str(value or "").strip())
    slug = slug.strip("_")
    return slug or "report"


def merge_with_and(query: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    if not query:
        return dict(extra)
    return {"$and": [query, extra]}


def register_fonts() -> tuple[str, str]:
    regular = "STSong-Light"
    bold = "HeiseiKakuGo-W5"
    pdfmetrics.registerFont(UnicodeCIDFont(regular))
    pdfmetrics.registerFont(UnicodeCIDFont(bold))
    return regular, bold


FONT_REGULAR, FONT_BOLD = register_fonts()


def build_styles():
    base = getSampleStyleSheet()
    title = ParagraphStyle(
        "ReportTitle",
        parent=base["Title"],
        fontName=FONT_BOLD,
        fontSize=18,
        leading=24,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#132238"),
        spaceAfter=8,
    )
    meta = ParagraphStyle(
        "ReportMeta",
        parent=base["Normal"],
        fontName=FONT_REGULAR,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#425466"),
        spaceAfter=4,
    )
    header = ParagraphStyle(
        "TableHeader",
        parent=base["Normal"],
        fontName=FONT_BOLD,
        fontSize=9,
        leading=12,
        textColor=colors.white,
    )
    cell = ParagraphStyle(
        "TableCell",
        parent=base["Normal"],
        fontName=FONT_REGULAR,
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#18212f"),
    )
    cell_small = ParagraphStyle(
        "TableCellSmall",
        parent=cell,
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#526171"),
    )
    empty = ParagraphStyle(
        "EmptyState",
        parent=base["Normal"],
        fontName=FONT_REGULAR,
        fontSize=11,
        leading=16,
        textColor=colors.HexColor("#526171"),
    )
    return {
        "title": title,
        "meta": meta,
        "header": header,
        "cell": cell,
        "cell_small": cell_small,
        "empty": empty,
    }


STYLES = build_styles()


def format_filter_summary(args: argparse.Namespace, info: dict[str, Any], event_count: int) -> list[str]:
    lines = [
        f"產生時間：{datetime.now(QUERY.LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')}",
        f"事件數量：{event_count}",
        f"狀態：{args.status}",
        f"相機：{args.camera if args.camera is not None else '全部'}",
        f"類型：{info.get('event_type_name') or args.type or '全部'}",
        f"類別：{args.event_class or info.get('event_class_name') or '全部'}",
    ]
    if info.get("time_range") == "today":
        lines.append("期間：今日（Asia/Taipei）")
    elif info.get("start_time") or info.get("end_time"):
        lines.append(f"期間：{info.get('start_time') or '起始未指定'} 至 {info.get('end_time') or '結束未指定'}")
    elif args.days is not None:
        lines.append(f"期間：最近 {args.days} 天")
    elif args.hours is not None:
        lines.append(f"期間：最近 {args.hours} 小時")
    else:
        lines.append("期間：全部")
    if not args.all_events:
        lines.append("模式：違規事件優先")
    return lines


def pick_thumbnail_candidate(event: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("full_image", "crop_image"):
        block = event.get(key) or {}
        for candidate in block.get("candidates") or []:
            if candidate.get("kind") == "file" and candidate.get("exists"):
                next_candidate = dict(candidate)
                next_candidate["media_kind"] = key
                return next_candidate
    return None


def fit_image(path: str, max_width: float, max_height: float) -> Image:
    with PILImage.open(path) as img:
        width, height = img.size
    width = max(1, int(width))
    height = max(1, int(height))
    scale = min(max_width / float(width), max_height / float(height))
    scale = min(scale, 1.0)
    return Image(path, width=width * scale, height=height * scale)


def build_link_paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    raw = str(text or "").strip()
    if not raw:
        return Paragraph("無圖片連結", style)
    if raw.startswith("http://") or raw.startswith("https://"):
        return Paragraph(f"<link href={quoteattr(raw)}>{escape(raw)}</link>", style)
    return Paragraph(escape(raw), style)


def build_note_text(event: dict[str, Any]) -> str:
    note_lines: list[str] = []
    ai_summary = str(event.get("ai_summary") or "").strip()
    description = str(event.get("description") or "").strip()
    if ai_summary:
        note_lines.append(f"AI 摘要：{ai_summary}")
    if description and description != ai_summary:
        note_lines.append(f"備註：{description}")
    if not note_lines:
        note_lines.append("無")
    return "\n".join(note_lines)


def event_type_and_class(event: dict[str, Any]) -> str:
    event_type_name = str(event.get("event_type_name") or "").strip()
    event_class_title = str(event.get("event_class_title") or event.get("event_class_name") or "").strip()
    if event_class_title and event_class_title != event_type_name:
        return f"{event_type_name} / {event_class_title}"
    return event_type_name or event_class_title or "Unknown"


def build_event_table(events: list[dict[str, Any]]) -> Table:
    data: list[list[Any]] = [
        [
            Paragraph("事件時間", STYLES["header"]),
            Paragraph("攝影機", STYLES["header"]),
            Paragraph("事件類型 / 類別", STYLES["header"]),
            Paragraph("位置", STYLES["header"]),
            Paragraph("縮圖 / 圖片連結", STYLES["header"]),
            Paragraph("備註 / AI 摘要", STYLES["header"]),
        ]
    ]

    for event in events:
        camera = event.get("camera") or {}
        camera_parts = [
            str(camera.get("channel_name") or f"cam{event.get('channel_id', 0)}").strip(),
            f"ID {event.get('channel_id', 0)}",
        ]
        location = str(event.get("location") or camera.get("location") or "").strip() or "無"
        thumb_candidate = pick_thumbnail_candidate(event)
        thumb_flowables: list[Any] = []
        if thumb_candidate:
            absolute_path = str(thumb_candidate.get("absolute_path") or "").strip()
            if absolute_path and os.path.exists(absolute_path):
                thumb_flowables.append(fit_image(absolute_path, 48 * mm, 30 * mm))
                thumb_flowables.append(Spacer(1, 2 * mm))
            link_value = str(thumb_candidate.get("public_url") or "").strip()
            if not link_value:
                rel = str(thumb_candidate.get("relative_path") or "").strip()
                if rel:
                    link_value = f"./{rel.lstrip('./')}"
            thumb_flowables.append(build_link_paragraph(link_value or "無圖片連結", STYLES["cell_small"]))
        else:
            thumb_flowables.append(Paragraph("無縮圖", STYLES["cell_small"]))

        data.append(
            [
                Paragraph(escape(str(event.get("event_time") or "未知")), STYLES["cell"]),
                Paragraph(escape("<br/>".join(camera_parts)), STYLES["cell"]),
                Paragraph(escape(event_type_and_class(event)), STYLES["cell"]),
                Paragraph(escape(location), STYLES["cell"]),
                thumb_flowables,
                Paragraph(escape(build_note_text(event)).replace("\n", "<br/>"), STYLES["cell"]),
            ]
        )

    table = Table(
        data,
        repeatRows=1,
        colWidths=[34 * mm, 24 * mm, 40 * mm, 48 * mm, 58 * mm, 58 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4b6e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c9d3df")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f9fc")]),
            ]
        )
    )
    return table


def generate_pdf(report_path: Path, report_title: str, summary_lines: list[str], events: list[dict[str, Any]]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(report_path),
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )
    story: list[Any] = [Paragraph(escape(report_title), STYLES["title"])]
    for line in summary_lines:
        story.append(Paragraph(escape(line), STYLES["meta"]))
    story.append(Spacer(1, 5 * mm))

    if events:
        story.append(build_event_table(events))
    else:
        story.append(Paragraph("此條件下沒有符合的事件。", STYLES["empty"]))

    doc.build(story)


def upload_report(report_path: Path) -> tuple[str | None, str | None]:
    if not report_path.is_file():
        return None, "Report file not found"
    upload_url = str(getattr(QUERY, "PICTSHARE_URL", "") or "").strip().rstrip("/")
    public_base = str(getattr(QUERY, "PICTSHARE_PUBLIC_URL", "") or "").strip().rstrip("/")
    upload_code = str(getattr(QUERY, "PICTSHARE_UPLOAD_CODE", "") or "").strip()
    if not upload_url:
        return None, "PICTSHARE_URL is not configured"
    mime_type = mimetypes.guess_type(report_path.name)[0] or "application/octet-stream"
    try:
        with report_path.open("rb") as fh:
            response = requests.post(
                f"{upload_url}/api/upload.php",
                files={"file": (report_path.name, fh, mime_type)},
                data={"uploadcode": upload_code} if upload_code else {},
                timeout=15.0,
            )
        response.raise_for_status()
        body = response.json() if response.content else {}
    except Exception as exc:
        return None, f"Upload failed: {exc}"
    if str(body.get("status") or "").lower() != "ok":
        reason = str(body.get("reason") or body.get("error") or "Upload rejected").strip()
        return None, reason
    raw_url = str(body.get("url") or body.get("hash") or "").strip()
    if not raw_url:
        return None, "Upload response did not include a URL"
    if raw_url.startswith("http://") or raw_url.startswith("https://"):
        return raw_url, None
    if raw_url.startswith("/"):
        return f"{public_base or upload_url}{raw_url}", None
    return f"{public_base or upload_url}/{raw_url.lstrip('/')}", None


def build_media_directive(public_url: str | None, output_path: Path) -> str:
    delivery_target = public_url or str(output_path.resolve())
    return f"MEDIA:{delivery_target}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a PDF violation-event report with thumbnails and notes")
    QUERY.add_common_filters(parser)
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of events to include")
    parser.add_argument("--output", help="Output PDF path")
    parser.add_argument("--title", default="違規事件報告", help="Report title")
    parser.add_argument("--all-events", action="store_true", help="Include all matching events instead of prioritizing violations")
    parser.add_argument("--upload", action="store_true", help="Upload the generated PDF and return a public URL when possible")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    query, info = QUERY.build_filter(args)
    if not args.all_events:
        violation_clause = {"$or": [{"Event_type_id": {"$ne": 3}}, {"metadata.has_violation": True}]}
        query = merge_with_and(query, violation_clause)
        info["violations_only"] = True

    limit = max(1, min(int(args.limit), 200))
    docs = list(QUERY.event_db.collection.find(query, QUERY.projection()).sort("Event_time", -1).limit(limit))
    events = [QUERY.attach_media_delivery(QUERY.enrich_event(doc)) for doc in docs]

    now_str = datetime.now(QUERY.LOCAL_TZ).strftime("%Y%m%d_%H%M%S")
    output_path = Path(args.output).expanduser() if args.output else REPORT_DIR / f"{safe_slug(args.title)}_{now_str}.pdf"
    if output_path.suffix.lower() != ".pdf":
        output_path = output_path.with_suffix(".pdf")

    summary_lines = format_filter_summary(args, info, len(events))
    generate_pdf(output_path, args.title, summary_lines, events)

    public_url = None
    upload_error = None
    if args.upload:
        public_url, upload_error = upload_report(output_path)

    report = {
        "title": args.title,
        "absolute_path": str(output_path.resolve()),
        "relative_path": os.path.relpath(output_path.resolve(), WORKSPACE_ROOT),
        "public_url": public_url,
        "media_directive": build_media_directive(public_url, output_path),
    }
    if upload_error:
        report["upload_error"] = upload_error

    emit(
        {
            "ok": True,
            "command": "violation-report",
            "filters": info,
            "event_count": len(events),
            "report": report,
        }
    )


if __name__ == "__main__":
    main()
