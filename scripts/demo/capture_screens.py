"""
Capture clean screenshots of the running app for the idea deck.

    python scripts/demo/capture_screens.py

Expects the frontend on http://localhost:3000 and the backend on :8000.
Nothing here writes to the database: the citizen flow stops at the draft
confirmation step and never presses "file".

Three things make these shots usable in a submission:
  - reduced motion is emulated, so every reveal, count-up and ring is already
    in its final state instead of caught half-way;
  - the Next.js development overlay is hidden, so no "N" button or issue pill
    sits in the corner;
  - phone shots use real device emulation, not a narrow desktop window, which
    desktop Chrome refuses to make narrower than about 500px.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:3000"
API = "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parents[2] / "docs" / "screenshots"

HIDE_DEV_OVERLAY = """
nextjs-portal, [data-nextjs-toast], [data-next-badge-root],
#__next-build-watcher { display: none !important; }
"""


def first_reference() -> str:
    with urllib.request.urlopen(f"{API}/api/officer/queue?limit=5", timeout=10) as r:
        rows = json.load(r)["rows"]
    if not rows:
        sys.exit("The queue is empty - file at least one grievance first.")
    return rows[0]["reference_no"]


def prepare(page) -> None:
    page.add_style_tag(content=HIDE_DEV_OVERLAY)
    # web fonts and map tiles are what usually arrive last
    page.evaluate("document.fonts.ready")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(600)


def shoot(page, url: str, name: str, *, before=None, full_page=False) -> None:
    page.goto(url, wait_until="networkidle")
    prepare(page)
    if before:
        before(page)
        prepare(page)
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=full_page)
    print(f"  {name}.png")
    if full_page:
        return
    # a full-length twin of every desktop page, so the deck can crop a tall
    # region instead of shrinking a wide, mostly-margin viewport
    if page.viewport_size and page.viewport_size["width"] >= 1000 and not before:
        page.screenshot(path=str(OUT / f"{name}_full.png"), full_page=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ref = first_reference()
    print(f"case used for detail shots: {ref}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        desktop = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1.5,
            reduced_motion="reduce",
        )
        d = desktop.new_page()
        print("desktop:")
        shoot(d, f"{BASE}/", "01_home")
        shoot(d, f"{BASE}/officer", "02_queue")
        shoot(d, f"{BASE}/officer/{ref}", "03_case")

        def to_reasoning(p):
            # scroll so the section heading sits near the top of the frame
            p.evaluate(
                """() => {
                  const h = [...document.querySelectorAll('h2')]
                    .find(e => e.textContent.includes('Why the system decided this'));
                  if (h) window.scrollTo(0, h.getBoundingClientRect().top + window.scrollY - 110);
                }"""
            )

        shoot(d, f"{BASE}/officer/{ref}", "03b_case_reasoning", before=to_reasoning)
        shoot(d, f"{BASE}/officer/hotspots", "04_hotspots_map")

        def ranked(p):
            p.get_by_role("button", name="Ranked list").click()
            p.get_by_role("button", name="Ranked list").scroll_into_view_if_needed()

        shoot(d, f"{BASE}/officer/hotspots", "04b_hotspots_ranked", before=ranked)
        shoot(d, f"{BASE}/compliance", "05_compliance")
        desktop.close()

        phone = browser.new_context(
            **pw.devices["iPhone 13"], reduced_motion="reduce"
        )
        m = phone.new_page()
        print("phone:")
        shoot(m, f"{BASE}/citizen", "06_citizen_mobile")

        def draft(p):
            box = p.get_by_placeholder("Describe the problem")
            box.fill(
                "The street light near Shivaji Chowk in Biloli has not worked for "
                "two weeks and the road is completely dark at night."
            )
            p.get_by_role("button", name="Send").click()
            p.get_by_text("Draft for your confirmation").wait_for(timeout=30000)
            p.get_by_text("Draft for your confirmation").scroll_into_view_if_needed()

        shoot(m, f"{BASE}/citizen", "06b_citizen_draft_mobile", before=draft)

        def marathi(p):
            p.get_by_role("button", name="मराठी").first.click()

        shoot(m, f"{BASE}/citizen", "06c_citizen_marathi_mobile", before=marathi)
        shoot(m, f"{BASE}/track?ref={ref}", "07_track_mobile")
        phone.close()
        browser.close()


if __name__ == "__main__":
    main()
