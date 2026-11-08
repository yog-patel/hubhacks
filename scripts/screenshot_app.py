"""Take full-page screenshots of every page of the running Streamlit app with Playwright (dev tool).

    streamlit run app/streamlit_app.py --server.headless true &
    python scripts/screenshot_app.py --out outputs/screenshots/after
    python scripts/screenshot_app.py --out outputs/screenshots/before --nav radio   # the v1 app (sidebar radio)

Only connects to the local app (default http://localhost:8501). Playwright and its headless Chromium are
development tools; AquaLens itself never needs them.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

V1_PAGES = ["Analyze", "Results", "Review queue", "Species registry"]
V2_PAGES = {"": "Analyze", "results": "Results", "review": "Review queue", "registry": "Species registry",
            "privacy": "Model & privacy"}


def settle(page: Page, extra: float = 1.5, timeout: float = 120.0) -> None:
    """Wait until Streamlit has finished running the script (no 'running' status widget)."""
    page.wait_for_selector('[data-testid="stApp"]', timeout=timeout * 1000)
    t0 = time.time()
    time.sleep(1.0)
    while time.time() - t0 < timeout:
        running = page.locator('[data-testid="stStatusWidget"]').count()
        skeleton = page.locator('[data-testid="stSkeleton"]').count()
        if not running and not skeleton:
            break
        time.sleep(0.5)
    time.sleep(extra)


def full_shot(page: Page, out: Path, width: int) -> None:
    """Streamlit scrolls inside its main container, so grow the viewport to the content height first."""
    h = page.evaluate("""() => {
        const m = document.querySelector('[data-testid="stMain"]') || document.querySelector('section.main');
        const s = document.querySelector('[data-testid="stSidebarContent"]');
        return Math.max(m ? m.scrollHeight : 0, s ? s.scrollHeight : 0, document.body.scrollHeight);
    }""")
    page.set_viewport_size({"width": width, "height": int(min(max(h, 900), 9000))})
    time.sleep(1.0)
    page.screenshot(path=str(out), full_page=True)
    page.set_viewport_size({"width": width, "height": 900})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8501")
    ap.add_argument("--out", required=True)
    ap.add_argument("--nav", choices=["url", "radio"], default="url")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--reviewer", default="Demo Biologist")
    ap.add_argument("--suffix", default="")
    ap.add_argument("--dark", action="store_true", help="emulate prefers-color-scheme: dark")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": a.width, "height": 900}, device_scale_factor=1,
                                  color_scheme="dark" if a.dark else "light")
        page = ctx.new_page()
        if a.nav == "radio":
            page.goto(a.url)
            settle(page)
            for i, name in enumerate(V1_PAGES, start=1):
                page.locator('[data-testid="stSidebar"]').get_by_text(name, exact=True).click()
                settle(page, extra=3.0)
                f = out / f"{i}_{name.lower().replace(' ', '_')}{a.suffix}.png"
                full_shot(page, f, a.width)
                print("saved", f)
        else:
            for i, (slug, name) in enumerate(V2_PAGES.items(), start=1):
                page.goto(f"{a.url}/{slug}?reviewer={a.reviewer.replace(' ', '+')}")
                settle(page, extra=3.0)
                f = out / f"{i}_{slug or 'analyze'}{a.suffix}.png"
                full_shot(page, f, a.width)
                print("saved", f)
        browser.close()


if __name__ == "__main__":
    main()
