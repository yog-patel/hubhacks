"""Drive the DEMO.md flow through the real app with Playwright and screenshot every step (dev/QA tool).

    python scripts/reset_demo.py                          # clean starting state
    streamlit run app/streamlit_app.py &                  # the app on http://localhost:8501
    python scripts/demo_check.py --out outputs/screenshots/demo

Clicks exactly what a presenter would: Analyze (custom window 1280 s / 75 s) -> Results -> Review queue (approve item #1
as "European green crab" with the N shortcut) -> Species registry -> Analyze again -> Results -> Model & privacy.
Prints PASS/FAIL per check. Only talks to localhost.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from screenshot_app import full_shot, settle  # noqa: E402

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)


def wait_run(page: Page, timeout_s: float = 900) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if page.get_by_text("Finished in", exact=False).count():
            return
        if page.get_by_text("The analysis stopped", exact=False).count():
            raise RuntimeError("analysis failed in the app")
        time.sleep(2)
    raise TimeoutError("analysis did not finish")


def analyze(page: Page, url: str, out: Path, tag: str) -> None:
    page.goto(f"{url}/?reviewer=Demo+Biologist")
    settle(page, 3)
    page.get_by_text("Custom window", exact=True).click()
    settle(page, 2)
    for label, val in (("Start (seconds)", "1280"), ("Length (seconds)", "75")):
        box = page.get_by_label(label)
        box.fill(val)
        box.press("Enter")
        settle(page, 1)
    t0 = time.time()
    page.get_by_role("button", name=re.compile("Analyze video")).click()
    time.sleep(3)
    full_shot(page, out / f"{tag}_a_running.png", 1440)
    wait_run(page)
    settle(page, 2)
    full_shot(page, out / f"{tag}_b_finished.png", 1440)
    body = page.inner_text("body")
    m = re.search(r"External network connections during the run: (\d+)", body)
    check(f"{tag}: analysis finished in the app", True, f"{time.time() - t0:.0f} s wall clock")
    check(f"{tag}: 0 external network connections reported", bool(m and m.group(1) == "0"), m.group(0) if m else "not shown")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8501")
    ap.add_argument("--out", default="outputs/screenshots/demo")
    ap.add_argument("--name", default="European green crab")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_context(viewport={"width": 1440, "height": 900}).new_page()
        # 1. murky frame preview (default moment 420 s)
        page.goto(f"{a.url}/?reviewer=Demo+Biologist")
        settle(page, 4)
        body = page.inner_text("body")
        check("1: murky frame shows 'too murky'", "too murky" in body)
        full_shot(page, out / "1_analyze_murky.png", 1440)
        # 2. run the demo window
        analyze(page, a.url, out, "2_run1")
        page.goto(f"{a.url}/results?reviewer=Demo+Biologist")
        settle(page, 4)
        full_shot(page, out / "3_results_before.png", 1440)
        check("3: results show the species table", "Counts by species" in page.inner_text("body"))
        # 3. review queue: item 1 should be the crab (21:3x)
        page.goto(f"{a.url}/review?reviewer=Demo+Biologist")
        settle(page, 5)
        full_shot(page, out / "4_review_item1.png", 1440)
        body = page.inner_text("body")
        first = re.search(r"(\d+:\d\d)–(\d+:\d\d)", body[body.find("Item 1 of"):]) if "Item 1 of" in body else None
        check("4: review item #1 is 'unfamiliar'", "Possibly a species not in the registry" in body)
        check("4: item #1 is in the crab's time span (21:3x)", bool(first and first.group(1).startswith("21:3")),
              first.group(0) if first else "no time found")
        box = page.get_by_placeholder("Pick from the Nova Scotia list, or type a name")
        box.click()
        box.fill(a.name)
        page.keyboard.press("Enter")
        page.mouse.click(1000, 60)  # leave the text box so the shortcut is not typed into it
        time.sleep(1)
        page.keyboard.press("n")
        settle(page, 5)
        full_shot(page, out / "5_review_after_approve.png", 1440)
        # 4. registry
        page.goto(f"{a.url}/registry?reviewer=Demo+Biologist")
        settle(page, 4)
        body = page.inner_text("body")
        full_shot(page, out / "6_registry.png", 1440)
        check("6: registry shows the new species with the 'New' badge", a.name.lower() in body.lower() and "added in review" in body)
        check("6: approved by Demo Biologist", "Demo Biologist" in body)
        # 5. re-run: the new species is recognised
        analyze(page, a.url, out, "7_run2")
        page.goto(f"{a.url}/results?reviewer=Demo+Biologist")
        settle(page, 4)
        full_shot(page, out / "8_results_after.png", 1440)
        check("8: results now list the approved species", a.name.lower() in page.inner_text("body").lower())
        # 6. model & privacy
        page.goto(f"{a.url}/privacy?reviewer=Demo+Biologist")
        settle(page, 4)
        full_shot(page, out / "9_privacy.png", 1440)
        body = page.inner_text("body")
        check("9: privacy page shows 0 external network calls", "0 external network calls during the last run" in body)
        check("9: offline mode on", "Offline mode" in body and "On" in body)
        b.close()
    n_fail = sum(not ok for _, ok, _ in CHECKS)
    print(f"\n{len(CHECKS) - n_fail}/{len(CHECKS)} checks passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
