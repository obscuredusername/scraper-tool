"""
Scraper/parkers/specs_scraper.py

Extract full car specifications from Parkers by registration plate.
"""
import csv
import json
import logging
import os
import time
from typing import Optional

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from .models import ValuationPrices
from .scraper import _dismiss_overlays, _save_screenshot

logger = logging.getLogger(__name__)


class ParkersSpecsScraper:
    def __init__(self, headless: bool = True):
        self.headless = headless

    def scrape_by_reg(self, plate: str, save_screenshot: bool = False) -> Optional[str]:
        plate = plate.strip().upper().replace(" ", "")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-infobars",
                    "--window-size=1280,900",
                ],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="en-GB",
            )
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = context.new_page()
            try:
                # Step 1 — Homepage: Click "Specs" radio to reveal VRM input
                page.goto("https://www.parkers.co.uk/", wait_until="domcontentloaded", timeout=30000)
                _dismiss_overlays(page)
                page.wait_for_timeout(1500)
                specs_radio = page.locator(
                    ".home-review-specs-filters input[type='radio'][value='specs']"
                ).first
                specs_radio.wait_for(state="visible", timeout=10000)
                specs_radio.click()
                page.wait_for_timeout(1000)

                # Step 2 — Fill VRM and click Search
                reg_input = page.locator(
                    ".home-review-specs-filters input.vrm-lookup__input"
                ).first
                reg_input.wait_for(state="visible", timeout=8000)
                reg_input.click()
                reg_input.fill(plate)
                page.wait_for_timeout(300)
                search_btn = page.locator(
                    ".home-review-specs-filters button.vrm-lookup__button"
                ).first
                search_btn.wait_for(state="visible", timeout=8000)
                search_btn.click()
                try:
                    page.wait_for_url("**/car-specs/confirm/**", timeout=30000)
                except PlaywrightTimeout:
                    # Some Parkers flows require an Enter submit or get blocked by overlays.
                    _dismiss_overlays(page)
                    page.wait_for_timeout(300)
                    page.keyboard.press("Enter")
                    page.wait_for_url("**/car-specs/confirm/**", timeout=30000)

                if "/car-specs/confirm/" not in page.url:
                    raise RuntimeError(f"Did not reach confirm page. URL: {page.url}")
                logger.info(f"Confirm page reached: {page.url}")

                # Step 3 — Confirm page: select "curious" radio then click anchor
                curious = page.locator("input#curious, input[name='specsPurpose'][value='curious']").first
                try:
                    curious.wait_for(state="visible", timeout=8000)
                    curious.check()
                except Exception:
                    # Some Parkers pages style radio inputs as hidden; click the label instead.
                    curious.wait_for(state="attached", timeout=8000)
                    curious_label = page.locator("label[for='curious']").first
                    curious_label.wait_for(state="visible", timeout=8000)
                    curious_label.click()
                page.wait_for_timeout(500)

                _dismiss_overlays(page)
                nav_link = page.locator("a.specs-confirmation__actions__navigate-button").first
                nav_link.scroll_into_view_if_needed()
                nav_link.wait_for(state="visible", timeout=8000)
                href = nav_link.get_attribute("href")

                # Navigate via the anchor's href attribute (most reliable; avoids ad overlays intercepting clicks)
                if not href:
                    raise RuntimeError("Could not get href from specs nav link")
                full_url = href if href.startswith("http") else "https://www.parkers.co.uk" + href
                logger.info(f"Navigating to specs page: {full_url}")
                page.goto(full_url, wait_until="domcontentloaded", timeout=30000)

                if "/specs/" not in page.url:
                    raise RuntimeError(f"Did not reach specs page. URL: {page.url}")
                logger.info(f"Specs page: {page.url}")

                # Step 4 — Screenshot, parse, save as CSV (NOT JSON)
                os.makedirs("debug", exist_ok=True)
                os.makedirs("output", exist_ok=True)
                screenshot_path = f"debug/parkers_{plate}_specs.png"
                page.screenshot(path=screenshot_path)
                if save_screenshot:
                    _save_screenshot(page, screenshot_path)

                html = page.content()
                specs_data = parse_specs_page(html)

                out_path = f"output/parkers_{plate}_specs.json"
                with open(out_path, "w", encoding="utf-8") as fh:
                    json.dump(specs_data, fh, indent=2, ensure_ascii=False)
                logger.info(f"Specs saved to {out_path}")
                return out_path

            except PlaywrightTimeout as e:
                logger.error(f"Timeout during specs scrape: {e}")
                try:
                    os.makedirs("debug", exist_ok=True)
                    _save_screenshot(page, f"debug/parkers_{plate}_timeout.png")
                    with open(f"debug/parkers_{plate}_timeout.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                except Exception:
                    pass
                return None
            except Exception as e:
                logger.exception(f"Error during specs scrape: {e}")
                try:
                    os.makedirs("debug", exist_ok=True)
                    _save_screenshot(page, f"debug/parkers_{plate}_error.png")
                    with open(f"debug/parkers_{plate}_error.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                except Exception:
                    pass
                return None
            finally:
                browser.close()


def _save_specs_as_csv(specs_data: dict, path: str):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Section", "Label", "Value"])
        for section, content in specs_data.items():
            if section == "vehicle_name":
                writer.writerow(["Vehicle", "Name", content])
            elif section == "Equipment":
                for eq_type, groups in content.items():
                    for group_name, items in groups.items():
                        for item in items:
                            writer.writerow([f"Equipment - {eq_type}", group_name, item])
            else:
                for label, value in content.items():
                    writer.writerow([section, label, value])


def parse_specs_page(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    result = {}

    # Vehicle name
    for sel in ["h1.main-heading__title", "h1", ".specs-detail__heading h1"]:
        el = soup.select_one(sel)
        if el:
            result["vehicle_name"] = el.get_text(strip=True)
            break

    # Sections 1,3-8: structured key-value tables
    for table in soup.select(".specs-detail-table"):
        heading_el = table.select_one(".specs-detail-table__intro__heading")
        heading = heading_el.get_text(strip=True) if heading_el else "Unknown"
        items = {}
        for item in table.select(".specs-detail-table__item"):
            label_el = item.select_one(".specs-detail-table__item__label")
            value_el = item.select_one(".specs-detail-table__item__value")
            if label_el and value_el:
                label = label_el.get_text(" ", strip=True)
                value = value_el.get_text(" ", strip=True)
                items[label] = value
        if items:
            result[heading] = items

    # Section 2: Equipment
    equipment = {}
    for col in soup.select(".specs-detail__equipment__column"):
        heading_el = col.select_one(".specs-detail__equipment__heading")
        col_label = heading_el.get_text(strip=True) if heading_el else "Equipment"
        col_label = col_label.split("(")[0].strip()  # remove counts
        groups = {}
        for group in col.select(".specs-detail__equipment__group"):
            title_el = group.select_one(".specs-detail__equipment__group__title")
            title = title_el.get_text(strip=True) if title_el else "General"
            items = [li.get_text(strip=True) for li in group.select(".specs-detail__equipment__list li")]
            if items:
                groups[title] = items
        if groups:
            equipment[col_label] = groups
    if equipment:
        result["Equipment"] = equipment

    return result
