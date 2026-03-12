from __future__ import annotations
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional, List

from scrapers.nationwide.models import NationwideResult
from bs4 import BeautifulSoup
from playwright.async_api import Page, TimeoutError as PWTimeout, async_playwright

logger = logging.getLogger(__name__)

# ── ListenToTaxman Models ──────────────────────────────────────────────────
SalaryPeriod = Literal["year", "month", "4weeks", "2weeks", "week", "day", "hour"]
PensionType  = Literal["£", "%"]
StudentLoan  = Literal["No", "Plan 1", "Plan 2", "Plan 4", "Postgraduate"]
AgeGroup     = Literal["under 65", "65-74", "75 and over"]
Region       = Literal["UK", "Scotland"]

@dataclass
class TaxConfig:
    salary:         int          = 2200
    salary_period:  SalaryPeriod = "month"
    tax_year:       str          = "2025/26"
    region:         Region       = "UK"
    age:            AgeGroup     = "under 65"
    student_loan:   StudentLoan  = "No"
    pension_amount: float        = 0
    pension_type:   PensionType  = "£"
    allowances:     float        = 0
    tax_code:       str          = ""
    married:        bool         = False
    blind:          bool         = False
    no_ni:          bool         = False

@dataclass
class PayslipRow:
    label:   str
    percent: str = ""
    yearly:  str = ""
    monthly: str = ""
    weekly:  str = ""

@dataclass
class TaxResult:
    config:          dict
    scraped_at:      str
    url:             str
    payslip:         list[dict]    = field(default_factory=list)
    summary:         dict          = field(default_factory=dict)
    screenshot_path: Optional[str] = None
    error:           Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and bool(self.payslip)

    def to_dict(self) -> dict:
        return asdict(self)

# ── Council Tax Models ──────────────────────────────────────────────────────
@dataclass
class PropertyRecord:
    address:        str
    band:           str
    annual_amount:  float = 0.0
    monthly_amount: float = 0.0
    postcode:       str = ""

@dataclass
class CouncilTaxResult:
    postcode:    str
    scraped_at:  str
    properties:  list[dict] = field(default_factory=list)
    screenshot_path: Optional[str] = None
    error:       Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and len(self.properties) > 0

    def to_dict(self) -> dict:
        return asdict(self)

# ── Parkers Models ──────────────────────────────────────────────────────────
@dataclass
class ValuationPrices:
    private_low:   str = ""
    private_high:  str = ""
    dealer_low:    str = ""
    dealer_high:   str = ""

@dataclass
class ParkersResult:
    config:          dict
    scraped_at:      str
    reg_plate:       str    = ""
    make:            str    = ""
    model:           str    = ""
    year:            str    = ""
    prices:          ValuationPrices = field(default_factory=ValuationPrices)
    screenshot_path: Optional[str] = None
    error:           Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and (self.prices.private_low != "" or self.prices.dealer_low != "")

    def to_dict(self) -> dict:
        return asdict(self)

# ── Unified Scraper Engine ──────────────────────────────────────────────────
class ScraperEngine:
    """
    Unified engine for all scraping modules.
    Initialize once with global config, then call specific scrapers.
    """
    def __init__(
        self,
        headless: bool = True,
        output_dir: str | Path = "output",
        timeout_ms: int = 20_000,
    ):
        self.headless = headless
        self.output_dir = Path("static/screenshots")
        self.timeout_ms = timeout_ms
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Internal state for Playwright
        self._pw = None
        self._browser = None

    async def _start_browser(self):
        if not self._pw:
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
        return self._browser

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._pw = None
        self._browser = None

    # ── ListenToTaxman Implementation (Ported) ───────────────────────────────
    async def scrape_taxman(
        self,
        config: TaxConfig = None,
        screenshot: bool = False,
    ) -> TaxResult:
        if config is None:
            config = TaxConfig()

        browser = await self._start_browser()
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        url = "https://www.listentotaxman.com"
        
        result = TaxResult(
            config=asdict(config),
            scraped_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            url=url,
        )

        try:
            logger.info(f"Loading {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=40_000)
            
            # --- Wait for Form ---
            await page.wait_for_load_state("domcontentloaded", timeout=self.timeout_ms)
            await page.wait_for_timeout(1500)
            
            # --- Fill Form ---
            # Tax year
            await page.select_option('select[name="yr"]', label=config.tax_year)
            # Region
            await page.select_option('select[name="region"]', label=config.region)
            # Checkboxes
            if await page.is_checked('input[name="married"]') != config.married: await page.click('input[name="married"]')
            if await page.is_checked('input[name="blind"]') != config.blind: await page.click('input[name="blind"]')
            if await page.is_checked('input[name="exNI"]') != config.no_ni: await page.click('input[name="exNI"]')
            # Student loan
            await page.select_option('select[name="plan"]', label=config.student_loan)
            # Age
            await page.select_option('select[name="age"]', label=config.age)
            # Allowances
            await page.fill('input[name="add"]', str(int(config.allowances)) if config.allowances else "0")
            # Pension
            await page.select_option('#pension-prepend', label=config.pension_type)
            await page.fill('input[name="pension"]', str(config.pension_amount))
            # Salary
            await page.fill('input[name="ingr"]', str(config.salary))
            await page.select_option('select[name="time"]', label=config.salary_period)

            # --- Submit ---
            await page.evaluate("() => { const b = document.querySelector('#calculate'); if(b){ b.disabled=false; b.removeAttribute('disabled'); b.click(); }}")
            
            # --- Wait for Results ---
            try:
                await page.wait_for_selector('#row-gross-pay', timeout=20_000)
                await page.wait_for_timeout(2000) # Give it a moment to stabilize
            except:
                pass
            
            # --- Parse ---
            html = await page.content()
            soup = BeautifulSoup(html, "lxml")
            
            table = None
            for tbl in soup.find_all("table"):
                if "Net Wage" in tbl.get_text() or "Gross Pay" in tbl.get_text():
                    table = tbl
                    break
            
            rows = []
            if table:
                for tr in table.find_all("tr"):
                    cells = tr.find_all(["td", "th"])
                    if len(cells) >= 2:
                        texts = [c.get_text(" ", strip=True) for c in cells]
                        rows.append(PayslipRow(
                            label=texts[0],
                            percent=texts[1] if len(texts) > 1 else "",
                            yearly=texts[2] if len(texts) > 2 else "",
                            monthly=texts[3] if len(texts) > 3 else "",
                            weekly=texts[4] if len(texts) > 4 else "",
                        ))
            
            result.payslip = [asdict(r) for r in rows]
            result.summary = {r.label: asdict(r) for r in rows if r.label}

            if screenshot:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"taxman_{config.salary}_{ts}.png"
                filepath = self.output_dir / filename
                await page.screenshot(path=str(filepath), full_page=True)
                result.screenshot_path = f"/static/screenshots/{filename}"

        except Exception as e:
            logger.error(f"Scrape failed: {e}")
            result.error = str(e)
        finally:
            await context.close()

        return result

    # ── Council Tax Implementation (Ported) ──────────────────────────────────
    async def scrape_counciltax(self, postcode: str) -> CouncilTaxResult:
        postcode = postcode.strip().upper()
        browser = await self._start_browser()
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        url = "https://www.mycounciltax.org.uk/content/index"
        
        result = CouncilTaxResult(
            postcode=postcode,
            scraped_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

        try:
            logger.info(f"Navigating to {url}")
            await page.goto(url, wait_until="commit", timeout=45_000)
            await page.wait_for_selector("input[name='postcode']", timeout=30_000)
            
            # Fill and Submit
            await page.fill("input[name='postcode']", postcode)
            await page.click("input[name='search'], input[type='submit'], button[type='submit']")
            
            # Wait for Results
            try:
                await page.wait_for_selector("table tr td", timeout=30_000)
            except:
                pass # Try parsing anyway
                
            html = await page.content()
            soup = BeautifulSoup(html, "lxml")
            
            # Parsing Logic (Ported from parser.py)
            properties = []
            rows = soup.select("table tr")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 2: continue
                
                address = cells[0].get_text(strip=True)
                band = cells[1].get_text(strip=True)[:1].upper()
                annual_tax_str = cells[2].get_text(strip=True) if len(cells) >= 3 else "0"
                
                # Clean amount
                amount_str = annual_tax_str.replace("£", "").replace(",", "").strip()
                try:
                    amount = float(amount_str)
                except:
                    amount = 0.0
                
                properties.append(PropertyRecord(
                    address=address,
                    band=band,
                    annual_amount=amount,
                    monthly_amount=round(amount / 12, 2) if amount else 0.0,
                    postcode=postcode
                ))
            
            result.properties = [asdict(p) for p in properties]
            
            # Take screenshot of results
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"council_{postcode}_{ts}.png"
            filepath = self.output_dir / filename
            await page.screenshot(path=str(filepath), full_page=True)
            result.screenshot_path = f"/static/screenshots/{filename}"
            
            if not properties:
                # Check for error message on page
                error_el = soup.select_one(".error, .alert, [class*='error']")
                if error_el:
                    result.error = error_el.get_text(strip=True)
                else:
                    result.error = "No properties found for this postcode."

        except Exception as e:
            logger.error(f"Council tax scrape failed: {e}")
            result.error = str(e)
        finally:
            await context.close()

        return result

    # ── Parkers Implementation (Ported) ──────────────────────────────────────
    async def scrape_parkers(self, plate: str) -> ParkersResult:
        plate = plate.strip().upper().replace(" ", "")
        browser = await self._start_browser()
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900}
        )
        page = await context.new_page()
        url = "https://www.parkers.co.uk/"
        
        result = ParkersResult(
            config={"plate": plate},
            scraped_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            reg_plate=plate,
        )

        try:
            logger.info(f"Navigating to Parkers: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=40_000)
            await page.wait_for_timeout(2000)
            
            # Dismiss initial cookie banner
            await self._parkers_dismiss_overlays(page)
            
            # Click valuations tab
            try:
                tab = page.locator("a[data-tabs-target='valuations']")
                if await tab.is_visible(timeout=5000):
                    await tab.click()
                    await page.wait_for_timeout(1000)
            except: pass

            # Find and fill reg input
            reg_input = await self._parkers_find_reg_input(page)
            if not reg_input:
                raise RuntimeError("Could not find registration input field")
            
            await reg_input.click()
            await reg_input.fill(plate)
            await page.wait_for_timeout(500)
            
            # Submit
            if not await self._parkers_submit(page):
                raise RuntimeError("Could not submit valuation form")
            
            await page.wait_for_timeout(3000)
            await self._parkers_dismiss_overlays(page)
            
            # Handle confirmation page
            if "/confirm/" in page.url:
                await self._parkers_handle_confirm(page)
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
                await page.wait_for_timeout(2000)
            
            # Handle select-valuation page
            if "select-a-valuation" in page.url:
                await self._parkers_handle_select_valuation(page)
            
            # Handle vehicle picker
            if await self._parkers_picker_present(page):
                await self._parkers_select_first_vehicle(page)
                await page.wait_for_timeout(3000)

            # Final dismissals
            await self._parkers_dismiss_email_gate(page)
            
            # Wait for results
            try:
                await page.wait_for_selector("[class*='valuation'], [class*='price']", timeout=15000)
            except: pass
            
            html = await page.content()
            soup = BeautifulSoup(html, "lxml")
            
            # Parse prices
            prices = ValuationPrices()
            price_boxes = soup.find_all("div", class_="valuation-price-box__container")
            for box in price_boxes:
                name_elem = box.find("div", class_="valuation-price-box__price-name")
                price_elem = box.find("div", class_="valuation-price-box__price")
                if not name_elem or not price_elem: continue
                
                name = name_elem.get_text(strip=True).lower()
                price_text = price_elem.get_text(strip=True)
                vals = re.findall(r'£[\d,]+', price_text)
                
                if "private" in name:
                    prices.private_low = vals[0] if len(vals) > 0 else ""
                    prices.private_high = vals[1] if len(vals) > 1 else ""
                elif "dealer" in name or "forecourt" in name:
                    prices.dealer_low = vals[0] if len(vals) > 0 else ""
                    prices.dealer_high = vals[1] if len(vals) > 1 else ""
            
            result.prices = prices
            
            # Parse vehicle details
            details_span = soup.select_one(".valuation-free-page__container__header-row--vehicle, .valuation-option-box__header-row--vehicle")
            if details_span:
                txt = details_span.get_text(strip=True)
                parts = txt.split()
                if len(parts) >= 1: result.make = parts[0]
                if len(parts) >= 2: result.model = parts[1]
                if len(parts) >= 3: result.year = parts[-1]

            # Screenshot
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"parkers_{plate}_{ts}.png"
            filepath = self.output_dir / filename
            await page.screenshot(path=str(filepath), full_page=True)
            result.screenshot_path = f"/static/screenshots/{filename}"

        except Exception as e:
            logger.error(f"Parkers scrape failed: {e}")
            result.error = str(e)
        finally:
            await context.close()
        
        return result

    async def scrape_nationwide(self, postcode: str = "") -> NationwideResult:
        postcode = postcode.strip().upper()
        browser = await self._start_browser()
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
        )
        page = await context.new_page()

        result = NationwideResult(
            scraped_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            postcode=postcode,
        )

        try:
            logger.info(f"Navigating to Nationwide HPI")
            await page.goto("https://www.nationwide.co.uk/house-price-index", wait_until="commit", timeout=45_000)

            # Dismiss cookie banner
            try:
                await page.wait_for_selector("#onetrust-accept-btn-handler", timeout=5000)
                await page.click("#onetrust-accept-btn-handler")
                await page.wait_for_timeout(1000)
            except Exception:
                pass

            try:
                await page.wait_for_load_state("networkidle", timeout=30_000)
            except Exception:
                pass

            await page.wait_for_timeout(2000)

            # Postcode lookup
            if postcode:
                try:
                    await page.wait_for_selector("input[type='text'], input[placeholder*='postcode' i]", timeout=10_000)
                    await page.fill("input[type='text'], input[placeholder*='postcode' i]", postcode)
                    await page.wait_for_timeout(500)
                    await page.click("button[type='submit'], input[type='submit'], button:has-text('Search')")
                    try:
                        await page.wait_for_load_state("networkidle", timeout=15_000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(2000)
                except Exception as e:
                    logger.warning(f"Postcode form failed: {e}")

            html = await page.content()
            soup = BeautifulSoup(html, "lxml")
            full_text = soup.get_text(separator=" ")

            # Parse avg price
            price_match = re.search(r'£[\d,]+', full_text)
            if price_match:
                result.avg_price = price_match.group(0)

            # Parse changes
            changes = re.findall(r'[+\-]?\d+\.?\d*%', full_text)
            if len(changes) >= 1:
                result.monthly_change = changes[0]
            if len(changes) >= 2:
                result.annual_change = changes[1]

            # Parse report date
            date_match = re.search(
                r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}',
                full_text
            )
            if date_match:
                result.report_date = date_match.group(0)

            # Parse local price if postcode was used
            if postcode:
                prices = re.findall(r'£[\d,]+', full_text)
                if len(prices) >= 2:
                    result.local_avg_price = prices[-1]

            if not result.avg_price:
                result.error = "No price data found — check debug/nationwide_last.html"

            # Screenshot
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"nationwide_{postcode or 'headline'}_{ts}.png"
            filepath = self.output_dir / filename
            await page.screenshot(path=str(filepath), full_page=True)
            result.screenshot_path = f"/static/screenshots/{filename}"

        except Exception as e:
            logger.error(f"Nationwide scrape failed: {e}")
            result.error = str(e)
        finally:
            await context.close()

        return result

    # ── Parkers Helpers ──────────────────────────────────────────────────────
    async def _parkers_dismiss_overlays(self, page: Page):
        selectors = ["#onetrust-accept-btn-handler", ".cc-btn.cc-accept", "button.bm-close-btn", "[class*='close']"]
        for sel in selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=500):
                    await btn.click()
                    await page.wait_for_timeout(500)
            except: pass

    async def _parkers_find_reg_input(self, page: Page):
        for sel in ["input.vrm-lookup__input", "input[placeholder*='reg' i]", "input[name='vrm']"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=500): return el
            except: pass
        return None

    async def _parkers_submit(self, page: Page) -> bool:
        for sel in ["button.vrm-lookup__button", "button:has-text('Value my car')", "button[type='submit']"]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=500):
                    await btn.click()
                    return True
            except: pass
        return False

    async def _parkers_handle_confirm(self, page: Page):
        try:
            radios = page.locator("input[name='valuationPurpose']")
            if await radios.count() > 0:
                await radios.nth(0).check()
            
            link = page.locator("#valuation-confirmation-link")
            await link.scroll_into_view_if_needed()
            href = await link.get_attribute("href")
            if href:
                target = "https://www.parkers.co.uk" + href if href.startswith("/") else href
                await page.goto(target, wait_until="domcontentloaded")
            else:
                await link.click()
        except: pass

    async def _parkers_handle_select_valuation(self, page: Page):
        try:
            btn = page.locator("a.valuation-primer-page__option__cta__link--free").first
            href = await btn.get_attribute("href")
            if href:
                target = "https://www.parkers.co.uk" + href if href.startswith("/") else href
                await page.goto(target, wait_until="domcontentloaded")
            else:
                await btn.click()
        except:
            derived = page.url.replace("/select-a-valuation/", "/free-valuation/")
            await page.goto(derived, wait_until="domcontentloaded")

    async def _parkers_picker_present(self, page: Page) -> bool:
        try:
            return await page.locator("select[name*='derivative' i]").first.is_visible(timeout=500)
        except: return False

    async def _parkers_select_first_vehicle(self, page: Page):
        try:
            sel = page.locator("select").first
            await sel.select_option(index=1)
            await page.wait_for_timeout(1000)
            await page.click("button[type='submit'], button:has-text('Continue')")
        except: pass

    async def _parkers_dismiss_email_gate(self, page: Page):
        for sel in ["button:has-text('Skip')", "button:has-text('No thanks')", "a:has-text('Skip')"]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1000):
                    await btn.click()
            except: pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.stop()
