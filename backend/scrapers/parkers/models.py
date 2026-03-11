from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, Literal
import json

InputMethod = Literal["registration", "dropdown"]

@dataclass
class ParkersConfig:
    """
    Input config for one Parkers valuation.
    Use EITHER reg_plate OR all of make/range/model/year — not both.
    """
    # Browser settings
    headless:    bool = True   # Run browser in headless mode

    # Path A — registration plate
    reg_plate:   str = ""   # e.g. "AB12CDE" — spaces stripped automatically

    # Path B — dropdown selection
    make:        str = ""   # e.g. "Ford"
    range_name:  str = ""   # e.g. "Focus"  (named range_name to avoid 'range' builtin)
    model:       str = ""   # e.g. "1.0 EcoBoost 125 ST-Line"
    year:        str = ""   # e.g. "2019"

    # Optional reference for batch tracking
    reference:   str = ""

    @property
    def input_method(self) -> InputMethod:
        return "registration" if self.reg_plate else "dropdown"

    def validate(self) -> None:
        """Raise ValueError if neither reg nor full dropdown set is provided."""
        if not self.reg_plate and not all([self.make, self.range_name, self.model, self.year]):
            raise ValueError(
                "Provide either reg_plate OR all of make/range_name/model/year"
            )

@dataclass
class ValuationPrices:
    """Price range from free Parkers valuation."""
    private_low:   str = ""   # e.g. "£2,995"
    private_high:  str = ""   # e.g. "£4,185"
    dealer_low:    str = ""   # e.g. "£4,890"
    dealer_high:   str = ""   # e.g. "£5,790"

@dataclass
class ParkersResult:
    """
    Full result for one Parkers valuation.
    Always returned — check .success before consuming .prices.
    Backend-ready: call .to_dict() or .to_json().
    """
    config:          dict
    scraped_at:      str
    input_method:    str    = ""
    make:            str    = ""
    range_name:      str    = ""
    model:           str    = ""
    year:            str    = ""
    reg_plate:       str    = ""
    fuel_type:       str    = ""
    transmission:    str    = ""
    prices:          ValuationPrices = field(default_factory=ValuationPrices)
    mileage_assumption: str = "10,000 miles/year (standard)"
    spec_assumption: str    = "Standard factory equipment"
    result_url:      str    = ""
    screenshot_path: Optional[str] = None
    error:           Optional[str] = None

    @property
    def success(self) -> bool:
        return (
            self.error is None and
            bool(self.prices.private_low or self.prices.dealer_low)
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
