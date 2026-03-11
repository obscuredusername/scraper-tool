"""
Scraper/parkers/scraper.py

Valuates a car by registration plate using the Parkers website.
Uses stealth Playwright settings to avoid bot detection.
"""

import logging
import os
import re
import time
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from .models import ParkersConfig, ParkersResult, ValuationPrices

logger = logging.getLogger(__name__)

VALUATION_URL = "https://www.parkers.co.uk/"


class ParkersScraper:
    def __init__(self, config: Optional[ParkersConfig] = None, headless: bool = True):
        if config is None:
            config = ParkersConfig(headless=headless)
        self.config = config

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def valuate(self, config: ParkersConfig, screenshot: bool = False, save_json: bool = False) -> ParkersResult:
        """
        Valuate a vehicle using the provided config.
        
        Config can be either registration plate (Path A) or make/model/year (Path B).
        For now, only Path A (registration) is fully implemented.
        """
        if not config.reg_plate:
            from datetime import datetime, timezone
            return ParkersResult(
                config=config.to_dict() if hasattr(config, 'to_dict') else {},
                scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                reg_plate="",
                error="Only registration plate input (Path A) is currently supported",
            )
        
        # For now, just use valuate_by_reg
        return self.valuate_by_reg(config.reg_plate, save_screenshot=screenshot)

    def valuate_batch(
        self,
        configs: list[ParkersConfig],
        screenshot: bool = False,
        save_xlsx: bool = False,
    ) -> list[ParkersResult]:
        """Valuate multiple vehicles. Continues on individual failures."""
        from datetime import datetime, timezone
        results = []
        for config in configs:
            try:
                result = self.valuate(config, screenshot=screenshot)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to valuate {config.reg_plate or config.make}: {e}")
                results.append(ParkersResult(
                    config=config.to_dict() if hasattr(config, 'to_dict') else {},
                    scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    reg_plate=config.reg_plate or "",
                    error=str(e),
                ))
        return results

    def valuate_by_reg(self, plate: str, save_screenshot: bool = False) -> ParkersResult:
        plate = plate.strip().upper().replace(" ", "")
        logger.info(f"Valuating by reg plate: {plate}")

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=self.config.headless,
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
                # Step 1: Navigate to valuation page
                logger.info(f"Navigating to {VALUATION_URL}")
                page.goto(VALUATION_URL, wait_until="domcontentloaded", timeout=30_000)
                time.sleep(2)

                current_url = page.url
                logger.info(f"Landed on: {current_url}")

                # Step 2: Dismiss cookie banners / popups
                _dismiss_overlays(page)

                # Click the "Free car valuations" tab to reveal the vrm input
                try:
                    tab = page.locator("a[data-tabs-target='valuations']")
                    tab.wait_for(state="visible", timeout=5000)
                    tab.click()
                    page.wait_for_timeout(800)
                    logger.info("Clicked 'Free car valuations' tab")
                except Exception as e:
                    logger.warning(f"Could not click valuations tab: {e}")

                if save_screenshot:
                    _save_screenshot(page, f"debug/parkers_{plate}_landed.png")

                # Step 3: Fill reg plate input
                reg_input = _find_reg_input(page)
                if reg_input is None:
                    _save_screenshot(page, f"debug/parkers_{plate}_no_input.png")
                    from datetime import datetime, timezone
                    return ParkersResult(
                        config=self.config.to_dict() if hasattr(self.config, 'to_dict') else {},
                        scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        reg_plate=plate,
                        error="Could not find reg plate input"
                    )

                reg_input.click()
                reg_input.fill(plate)
                logger.info(f"Filled reg plate: {plate}")
                time.sleep(0.5)

                # Step 4: Submit the form
                if not _submit_valuation_form(page):
                    _save_screenshot(page, f"debug/parkers_{plate}_no_submit.png")
                    from datetime import datetime, timezone
                    return ParkersResult(
                        config=self.config.to_dict() if hasattr(self.config, 'to_dict') else {},
                        scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        reg_plate=plate,
                        error="Could not submit form"
                    )

                time.sleep(3)
                _dismiss_overlays(page)
                current_url = page.url
                logger.info(f"Post-submit URL: {current_url}")

                # Verify we're on a confirm page
                if "/confirm/" not in current_url:
                    error_msg = f"Unexpected post-submit URL: {current_url} (expected /confirm/)"
                    logger.error(error_msg)
                    raise RuntimeError(error_msg)

                # Handle /confirm/ page — select valuation purpose radio + click continue
                if "/confirm/" in page.url:
                    logger.info("Confirmation page detected — selecting purpose radio and continuing")
                    _handle_confirmation_page(page)
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                    time.sleep(2)
                    _dismiss_overlays(page)
                    if save_screenshot:
                        _save_screenshot(page, f"debug/parkers_{plate}_after_confirm.png")
                    logger.info(f"Post-confirm URL: {page.url}")

                # Handle select-a-valuation intermediate page
                if "select-a-valuation" in page.url:
                    handled = _handle_select_valuation_page(page)
                    if not handled:
                        logger.error("Could not navigate past select-a-valuation page")
                        from datetime import datetime, timezone
                        return ParkersResult(
                            config=self.config.to_dict() if hasattr(self.config, 'to_dict') else {},
                            scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            reg_plate=plate,
                            error="Could not navigate past select-a-valuation page"
                        )
                    logger.info(f"Post-valuation-select URL: {page.url}")

                if save_screenshot:
                    _save_screenshot(page, f"debug/parkers_{plate}_post_submit.png")

                # Step 5: Handle vehicle selection dropdown if shown
                if _vehicle_picker_present(page):
                    logger.info("Vehicle picker shown — selecting first option")
                    _select_first_vehicle(page)
                    time.sleep(3)
                    _dismiss_overlays(page)
                    if save_screenshot:
                        _save_screenshot(page, f"debug/parkers_{plate}_after_picker.png")

                # Step 6: Dismiss email gate
                _dismiss_email_gate(page)
                time.sleep(1)

                # Dismiss newsletter popup if present
                try:
                    close_btn = page.locator(".newsletter-signup__inner__close")
                    close_btn.wait_for(state="visible", timeout=3000)
                    close_btn.click()
                    page.wait_for_timeout(500)
                    logger.info("Dismissed newsletter popup")
                except Exception:
                    pass  # popup not present

                # Step 7: Wait for JS-rendered valuation prices to appear
                try:
                    page.wait_for_selector(
                        "[class*='valuation'], [class*='price'], .car-valuation__price",
                        timeout=15000
                    )
                    logger.info("Valuation price element found — ready to parse")
                except Exception:
                    logger.warning("Timed out waiting for valuation element — parsing anyway")

                # Parse results
                html = page.content()
                os.makedirs("debug", exist_ok=True)
                with open(f"debug/parkers_{plate}_results.html", "w", encoding="utf-8") as f:
                    f.write(html)

                from .parser import parse_valuation_prices, parse_vehicle_details
                prices = parse_valuation_prices(html)
                vehicle = parse_vehicle_details(html)

                if save_screenshot:
                    _save_screenshot(page, f"debug/parkers_{plate}_results.png")

                if not prices:
                    from datetime import datetime, timezone
                    return ParkersResult(
                        config=self.config.to_dict() if hasattr(self.config, 'to_dict') else {},
                        scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        reg_plate=plate,
                        error=f"Prices not found — check debug/parkers_{plate}_results.html",
                    )

                from datetime import datetime, timezone
                return ParkersResult(
                    config=self.config.to_dict() if hasattr(self.config, 'to_dict') else {},
                    scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    reg_plate=plate,
                    prices=prices,
                    error=None
                )

            except PlaywrightTimeout as e:
                logger.error(f"Timeout: {e}")
                _save_screenshot(page, f"debug/parkers_{plate}_timeout.png")
                from datetime import datetime, timezone
                return ParkersResult(
                    config=self.config.to_dict() if hasattr(self.config, 'to_dict') else {},
                    scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    reg_plate=plate,
                    error=f"Timeout: {e}"
                )
            except Exception as e:
                logger.error(f"Error: {e}", exc_info=True)
                _save_screenshot(page, f"debug/parkers_{plate}_error.png")
                from datetime import datetime, timezone
                return ParkersResult(
                    config=self.config.to_dict() if hasattr(self.config, 'to_dict') else {},
                    scraped_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    reg_plate=plate,
                    error=str(e)
                )
            finally:
                browser.close()


# ── Helper functions ────────────────────────────────────────────────────────

def _handle_select_valuation_page(page) -> bool:
    """
    Handle the /select-a-valuation/ intermediate page.
    This page offers multiple valuation types (free, private, trade, etc.).
    Click the "Get my free valuation" CTA button to navigate to free-valuation page.
    """
    if "select-a-valuation" not in page.url:
        return False

    logger.info("select-a-valuation page detected - navigating to free valuation")

    # Strategy 1: Click the free valuation CTA button directly
    try:
        btn = page.locator("a.valuation-primer-page__option__cta__link--free").first
        btn.wait_for(state="visible", timeout=8000)
        href = btn.get_attribute("href")
        if href:
            full_url = "https://www.parkers.co.uk" + href if href.startswith("/") else href
            logger.info(f"Navigating to free valuation: {full_url}")
            page.goto(full_url, wait_until="domcontentloaded", timeout=30000)
            return True
        else:
            btn.click()
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            return True
    except Exception as e:
        logger.warning(f"Free valuation button strategy failed: {e}")

    # Strategy 2: Derive URL by replacing path segment
    derived = page.url.replace("/select-a-valuation/", "/free-valuation/")
    logger.info(f"Derived free-valuation URL: {derived}")
    try:
        page.goto(derived, wait_until="domcontentloaded", timeout=30000)
        if "free-valuation" in page.url:
            return True
    except Exception as e:
        logger.warning(f"Derived URL strategy failed: {e}")

    # Save debug files if all strategies fail
    try:
        os.makedirs("debug", exist_ok=True)
        with open("debug/parkers_select_valuation.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        page.screenshot(path="debug/parkers_select_valuation.png")
        logger.warning("All strategies failed - saved debug files")
    except Exception:
        pass

    return False


def _dismiss_overlays(page):
    """Dismiss cookie banners, newsletter popups, GDPR notices."""
    selectors = [
        "button.bm-close-btn", "[class*='bm-close']",
        "button[aria-label*='close' i]", "button[aria-label*='dismiss' i]",
        "[class*='modal'] button[class*='close']",
        "[class*='popup'] button[class*='close']",
        "button[id*='accept' i]", "button[class*='accept' i]",
        "#onetrust-accept-btn-handler", ".cc-btn.cc-accept",
        "button[title*='Accept' i]", "[class*='sp-btn']",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=500):
                btn.click(timeout=1000)
                logger.debug(f"Dismissed overlay: {sel}")
                time.sleep(0.5)
        except Exception:
            pass


def _find_reg_input(page):
    """Find the registration plate input field."""
    # Prioritize selectors from the actual homepage HTML structure
    valuation_selectors = [
        ".home-valuations-filters input.vrm-lookup__input",
        ".home-valuations-filters .vrm-lookup__input",
        "input.vrm-lookup__input",
    ]
    for sel in valuation_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=500):
                logger.debug(f"Found vrm input: {sel}")
                return el
        except Exception:
            pass

    # Fallback to generic selectors
    selectors = [
        "input[placeholder*='reg' i]", "input[placeholder*='plate' i]",
        "input[placeholder*='Enter reg' i]", "input[type='text']",
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=500):
                logger.debug(f"Found reg input (fallback): {sel}")
                return el
        except Exception:
            pass
    return None


def _submit_valuation_form(page) -> bool:
    """Click the form submit button on the valuation form."""
    # Prioritize selectors from the actual homepage HTML structure
    valuation_selectors = [
        ".home-valuations-filters button.vrm-lookup__button",
        ".vrm-lookup__button",
        "button.vrm-lookup__button",
    ]
    for sel in valuation_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=500):
                btn.click(timeout=3000)
                logger.debug(f"Clicked valuation submit: {sel}")
                return True
        except Exception:
            pass

    # Fallback to generic selectors
    selectors = [
        "button[type='submit']", "input[type='submit']",
        "button:has-text('Value my car')", "button:has-text('Get valuation')",
        "button:has-text('Value this car')", "button:has-text('Value')",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=500):
                btn.click(timeout=3000)
                logger.debug(f"Clicked submit: {sel}")
                return True
        except Exception:
            pass
    try:
        page.keyboard.press("Enter")
        return True
    except Exception:
        return False


def _handle_confirmation_page(page) -> bool:
    """
    Select a valuation purpose radio and navigate past the confirmation page.
    The continue link is below the fold — must scroll to it before interacting.
    """

    # Step 1: Wait for page to fully load, then select the first valuationPurpose radio button
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
        page.wait_for_timeout(1000)  # Allow JS to render radio buttons
        radios = page.locator("input[name='valuationPurpose']")
        if radios.count() > 0:
            radios.nth(0).check()
            logger.info("Selected valuationPurpose radio option 0")
        else:
            logger.debug("No valuationPurpose radio buttons found (will use href fallback)")
    except Exception as e:
        logger.debug(f"Could not select radio: {e}")

    # Step 2: Scroll the confirmation link into the viewport
    try:
        link = page.locator("#valuation-confirmation-link")
        link.wait_for(state="attached", timeout=5000)
        link.scroll_into_view_if_needed()
        page.wait_for_timeout(500)  # let viewport settle
        logger.info("Scrolled #valuation-confirmation-link into view")
    except Exception as e:
        logger.warning(f"Could not scroll to confirmation link: {e}")

    # Step 3: Extract href and navigate directly (most reliable)
    try:
        href = page.locator("#valuation-confirmation-link").get_attribute("href")
        if href:
            if href.startswith("/"):
                href = "https://www.parkers.co.uk" + href
            logger.info(f"Navigating to: {href}")
            page.goto(href, wait_until="domcontentloaded", timeout=30000)
            return True
    except Exception as e:
        logger.warning(f"Could not extract href from confirmation link: {e}")

    # Step 4: Fallback — click the link
    try:
        page.locator("#valuation-confirmation-link").click()
        page.wait_for_load_state("domcontentloaded", timeout=30000)
        logger.info("Clicked confirmation link (fallback)")
        return True
    except Exception as e:
        logger.warning(f"Could not click confirmation link: {e}")

    return False


def _vehicle_picker_present(page) -> bool:
    """Check if a vehicle selection dropdown is shown post-submit."""
    for sel in [
        "select[name*='vehicle' i]", "select[name*='derivative' i]",
        "[class*='vehicle-picker']", "[class*='vehicle-select']",
    ]:
        try:
            if page.locator(sel).first.is_visible(timeout=500):
                return True
        except Exception:
            pass
    return False


def _select_first_vehicle(page):
    """Select the first option in the vehicle picker."""
    try:
        sel = page.locator("select").first
        if sel.is_visible(timeout=1000):
            sel.select_option(index=1)
            time.sleep(1)
            for btn_sel in ["button[type='submit']", "button:has-text('Continue')", "button:has-text('Select')"]:
                try:
                    btn = page.locator(btn_sel).first
                    if btn.is_visible(timeout=500):
                        btn.click()
                        return
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"Vehicle picker error: {e}")


def _dismiss_email_gate(page):
    """Skip any email capture gate."""
    for sel in [
        "button:has-text('Skip')", "button:has-text('No thanks')",
        "button:has-text('Continue without')", "a:has-text('Skip')",
        "[class*='skip']", "[class*='no-thanks']", "button[aria-label*='close' i]",
    ]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1000):
                btn.click(timeout=2000)
                logger.debug(f"Dismissed email gate: {sel}")
                return
        except Exception:
            pass


def _save_screenshot(page, path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        page.screenshot(path=path, full_page=False)
        logger.info(f"Screenshot saved: {path}")
    except Exception as e:
        logger.warning(f"Screenshot failed: {e}")
