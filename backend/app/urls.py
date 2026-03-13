from fastapi import APIRouter, Query
from app.auth.router import router as auth_router
from app.core.router import router as core_router
from app.scrapers.service import run_tax_scraper, run_counciltax_scraper, run_parkers_scraper, run_nationwide_scraper

api_router = APIRouter()

# Include existing routers
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(core_router, prefix="/core", tags=["core"])

# Scraper Endpoints
@api_router.get("/scrapers/taxman", tags=["scrapers"])
async def get_tax_valuation(
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
    Get a tax valuation by providing salary and various tax configuration parameters.
    """
    return await run_tax_scraper(
        salary=salary,
        period=period,
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

@api_router.get("/scrapers/counciltax", tags=["scrapers"])
async def get_council_tax(postcode: str):
    """
    Get council tax bands and amounts for a given postcode.
    """
    return await run_counciltax_scraper(postcode=postcode)

@api_router.get("/scrapers/parkers", tags=["scrapers"])
async def get_car_valuation(plate: str):
    """
    Get car valuation from Parkers by registration plate.
    """
    return await run_parkers_scraper(plate=plate)

@api_router.get("/scrapers/nationwide", tags=["scrapers"])
async def get_house_price_index(
    region: str = "Greater London",
    postcode: str = "",
    property_value: int = 0,
    from_year: int = 0,
    from_quarter: int = 1,
    to_year: int = 0,
    to_quarter: int = 1
):
    """
    Get Nationwide House Price Index valuation change for a property.
    """
    return await run_nationwide_scraper(
        region=region,
        postcode=postcode,
        property_value=property_value,
        from_year=from_year,
        from_quarter=from_quarter,
        to_year=to_year,
        to_quarter=to_quarter
    )
