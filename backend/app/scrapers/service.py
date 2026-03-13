from app.scrapers.base import ScraperEngine, TaxConfig
from scrapers.nationwide.models import NationwideQuery
from scrapers.nationwide.scraper import NationwideScraper
import asyncio

async def run_tax_scraper(
    salary: int, 
    period: str = "month", 
    tax_year: str = "2025/26",
    region: str = "UK",
    age: str = "under 65",
    student_loan: str = "No",
    pension_amount: float = 0,
    pension_type: str = "£",
    allowances: float = 0,
    tax_code: str = "",
    married: bool = False,
    blind: bool = False,
    no_ni: bool = False
):
    """
    Service function to bootstrap the tax scraping process.
    """
    async with ScraperEngine(headless=True) as engine:
        config = TaxConfig(
            salary=salary,
            salary_period=period,
            tax_year=tax_year,
            region=region,
            age=age,
            student_loan=student_loan,
            pension_amount=pension_amount,
            pension_type=pension_type,
            allowances=allowances,
            tax_code=tax_code,
            married=married,
            blind=blind,
            no_ni=no_ni
        )
        result = await engine.scrape_taxman(config, screenshot=True)
        return result.to_dict()

async def run_counciltax_scraper(postcode: str):
    """
    Service function to bootstrap the council tax scraping process.
    """
    async with ScraperEngine(headless=True) as engine:
        result = await engine.scrape_counciltax(postcode)
        return result.to_dict()

async def run_parkers_scraper(plate: str):
    """
    Service function to bootstrap the Parkers scraping process.
    """
    async with ScraperEngine(headless=True) as engine:
        result = await engine.scrape_parkers(plate)
        return result.to_dict()

async def run_nationwide_scraper(
    region: str = "Greater London",
    postcode: str = "",
    property_value: int = 0,
    from_year: int = 0,
    from_quarter: int = 1,
    to_year: int = 0,
    to_quarter: int = 1,
) -> dict:
    """
    Service function to bootstrap the Nationwide HPI scraping process.
    """
    query = NationwideQuery(
        region=region,
        postcode=postcode,
        property_value=property_value,
        from_year=from_year,
        from_quarter=from_quarter,
        to_year=to_year,
        to_quarter=to_quarter,
    )

    loop = asyncio.get_running_loop()

    def _run_sync():
        with NationwideScraper() as scraper:
            return scraper.scrape(query)

    result = await loop.run_in_executor(None, _run_sync)
    return result.to_dict()
