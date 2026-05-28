#!/usr/bin/env python3
"""自動錄 NemoClaw Sky Eye demo 影片(2:30,對應 DEMO_SCRIPT.md 7 分鏡)。

用 Playwright(headless chromium)操作 dashboard:導頁、滑頁、停留,
全程錄成 webm。事後用 ffmpeg + SRT 字幕燒成 MP4。
"""
import os
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT_DIR = Path(os.environ.get("DEMO_OUT_DIR", "/tmp/demo_recording"))
DASHBOARD = os.environ.get("DASHBOARD_URL", "http://127.0.0.1:8099/")
VIEWPORT = {"width": 1920, "height": 1080}

OUT_DIR.mkdir(parents=True, exist_ok=True)
# clean previous
for f in OUT_DIR.glob("*.webm"):
    f.unlink()


def wait_visible(page, sel, ms=4000):
    try:
        page.wait_for_selector(sel, timeout=ms)
    except Exception:
        pass


def scroll_to_text(page, text):
    """Scroll the first element containing the text into view smoothly."""
    page.evaluate(f"""
    () => {{
      const it = [...document.querySelectorAll('h3, summary, h1')]
        .find(n => n.textContent.includes({text!r}));
      if (it) it.scrollIntoView({{behavior:'smooth', block:'center'}});
    }}""")


def open_drawer(page):
    page.evaluate("""
    () => {
      const d = document.querySelector('details.drawer');
      if (d && !d.open) d.open = true;
    }""")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        context = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(OUT_DIR),
            record_video_size=VIEWPORT,
            locale="zh-TW",
        )
        page = context.new_page()
        # Total target ~150s (matches SRT). Sleep generously so subtitles align.
        print("== 1. home page (0:00-0:25)")
        page.goto(DASHBOARD, wait_until="domcontentloaded", timeout=30000)
        wait_visible(page, "section.panel", ms=6000)
        page.wait_for_timeout(10000)
        # show layout chooser interaction (16 → 9 → 16)
        page.goto(f"{DASHBOARD}?layout=9", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(7000)
        page.goto(f"{DASHBOARD}?layout=16", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(8000)

        print("== 2. status row top (0:25-0:50)")
        page.evaluate("window.scrollTo({top:0, behavior:'smooth'})")
        page.wait_for_timeout(15000)

        print("== 3. open drawer + scroll to thoughts stream (0:50-1:15)")
        open_drawer(page)
        page.wait_for_timeout(2000)
        scroll_to_text(page, "Agent 思考即時流")
        page.wait_for_timeout(13000)

        print("== 4. scroll to followup panel (1:15-1:45)")
        scroll_to_text(page, "OpenShell 沙箱二次調查紀錄")
        page.wait_for_timeout(30000)

        print("== 5. scroll to correlation (1:45-2:05)")
        scroll_to_text(page, "跨地標關聯偵測")
        page.wait_for_timeout(20000)

        print("== 6. scroll to audit table + flight links (2:05-2:20)")
        scroll_to_text(page, "決策稽核軌跡")
        page.wait_for_timeout(15000)

        print("== 7. back to home wall (2:20-2:30)")
        page.evaluate("window.scrollTo({top:0, behavior:'smooth'})")
        page.wait_for_timeout(10000)

        # Close context to flush video to disk
        context.close()
        browser.close()

    # Move the recorded webm to a known name
    webms = sorted(OUT_DIR.glob("*.webm"), key=lambda p: p.stat().st_mtime)
    if not webms:
        raise RuntimeError("no webm recorded — check Playwright video output")
    final = OUT_DIR / "demo-raw.webm"
    shutil.move(webms[-1], final)
    print(f"\nRECORDED: {final}  ({final.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
