"""Headless smoke test for the cancer overlay + tab. Captures console errors
and screenshots the map overlay, county card, and cancer correlation tab."""
import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8080"
OUT = "scripts"


def main() -> int:
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 950})
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"PAGEERROR: {e}"))
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(1500)

        # 1) enable cancer map overlay (now a mutually-exclusive radio)
        page.check('input[name="choropleth"][value="cancer"]')
        page.wait_for_timeout(1200)
        cancer_meta = page.text_content("#cancer-meta")
        page.screenshot(path=f"{OUT}/shot_1_overlay.png")

        # 2) open a county (Tuscola-ish agricultural county via search)
        page.fill("#search", "Huron")
        page.wait_for_timeout(600)
        page.click("#search-results .item")
        page.wait_for_timeout(1000)
        cancer_rows = page.eval_on_selector_all("#county-cancer-table tbody tr", "els => els.length")
        page.screenshot(path=f"{OUT}/shot_2_county.png")

        # 3) switch to Cancer tab
        page.click('#view-switch button[data-view="cancer"]')
        page.wait_for_timeout(1500)
        matrix_cells = page.eval_on_selector_all(".matrix-table td.mcell", "els => els.length")
        stat_r = page.text_content("#cancer-stat-r")
        page.screenshot(path=f"{OUT}/shot_3_tab.png", full_page=True)

        # 4) open evidence modal
        page.click("#cancer-matrix-evidence")
        page.wait_for_timeout(600)
        ev_rows = page.eval_on_selector_all("#cancer-evidence-table tr", "els => els.length")
        page.screenshot(path=f"{OUT}/shot_4_evidence.png")

        browser.close()

    print(f"cancer_meta: {cancer_meta!r}")
    print(f"county cancer rows: {cancer_rows}")
    print(f"matrix cells: {matrix_cells}")
    print(f"scatter Pearson r: {stat_r!r}")
    print(f"evidence rows (incl header): {ev_rows}")
    if errors:
        print("\nCONSOLE/PAGE ERRORS:")
        for e in errors[:20]:
            print("  -", e)
        return 1
    print("\nNo console/page errors. OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
