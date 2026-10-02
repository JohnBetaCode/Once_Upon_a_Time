"""Capture UI screenshots of the running Streamlit app for the README / docs.

Usage:
    python capture.py [--base URL] [--out DIR] [--project NAME] [--only name,name]

Drives the app with Playwright using the system Google Chrome (channel="chrome"),
so no browser download is needed. The app must already be running (see the
run-app skill). Screens captured (file names are stable; the README links them):

    home              landing page: settings, usage, create project, project list
    usage             home page with the "Usage & costs" panel expanded
    workspace-source  project workspace, Source tab
    characters        Characters tab (tall viewport so a full card + sheet fits)
    passages          Passages tab
    locations         Locations tab
    gallery           Gallery tab
    export            sidebar "Export PDF" panel after building a PDF (writes a PDF into projects/)
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ALL = ["home", "usage", "workspace-source", "characters", "passages", "locations", "gallery", "export"]


def settle(page, ms: int = 2500) -> None:
    page.wait_for_load_state("networkidle")
    time.sleep(ms / 1000)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://localhost:8501")
    ap.add_argument("--out", default="shots")
    ap.add_argument("--project", default="The little prince", help="Project name as shown on the home page")
    ap.add_argument("--only", default="", help="Comma-separated subset of screens")
    args = ap.parse_args()

    wanted = [s.strip() for s in args.only.split(",") if s.strip()] or ALL
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    def shot(page, name: str) -> None:
        if name in wanted:
            path = out / f"{name}.png"
            page.screenshot(path=str(path))
            print("saved", path)

    def open_tab(page, label: str) -> None:
        page.get_by_role("tab", name=label).click()
        settle(page)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 1150}, color_scheme="light")
        page = ctx.new_page()
        page.goto(args.base)
        settle(page, 4000)
        shot(page, "home")

        if "usage" in wanted:
            page.set_viewport_size({"width": 1440, "height": 900})
            page.get_by_text("📊 Usage & costs").click()
            settle(page, 1500)
            shot(page, "usage")
            page.get_by_text("📊 Usage & costs").click()
            settle(page, 800)

        needs_project = [s for s in wanted if s not in ("home", "usage")]
        if needs_project:
            # The project card is a bordered horizontal block: name on the left, Open/Delete on the right.
            page.locator(
                f"xpath=//*[contains(text(), '{args.project}')]"
                "/ancestor::*[@data-testid='stHorizontalBlock'][1]//button[normalize-space()='Open']"
            ).click()
            settle(page, 4000)
            page.set_viewport_size({"width": 1440, "height": 900})
            shot(page, "workspace-source")

            if "characters" in wanted:
                page.set_viewport_size({"width": 1440, "height": 1500})
                open_tab(page, "Characters")
                settle(page, 3000)
                shot(page, "characters")
                page.set_viewport_size({"width": 1440, "height": 900})
            if "passages" in wanted:
                open_tab(page, "Passages")
                shot(page, "passages")
            if "locations" in wanted:
                open_tab(page, "Locations")
                shot(page, "locations")
            if "gallery" in wanted:
                page.set_viewport_size({"width": 1440, "height": 1100})
                open_tab(page, "Gallery")
                settle(page, 3000)
                shot(page, "gallery")
            if "export" in wanted:
                page.set_viewport_size({"width": 1440, "height": 920})
                open_tab(page, "Source")
                page.get_by_text("📄 Export PDF").click()
                settle(page, 1500)
                page.get_by_role("button", name="Build PDF").click()
                settle(page, 6000)
                shot(page, "export")

        browser.close()


if __name__ == "__main__":
    main()
