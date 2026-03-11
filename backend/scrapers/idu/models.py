from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class IDUConfig:
    """Input configuration for a single IDU search."""
    forename: str
    middlename: str = ""
    surname: str | None = None
    dd: str = ""
    mm: str = ""
    yyyy: str = ""
    gender: str = ""
    house: str = ""
    street: str = ""
    town: str = ""
    postcode: str = ""
    reference: str = ""
    email: str = ""
    email2: str = ""
    mobile: str = ""
    mobile2: str = ""
    landline: str = ""
    landline2: str = ""


@dataclass
class SummaryItem:
    """One item in the summary table."""
    category: str
    label: str
    status: str


@dataclass
class PEPEntry:
    """Representation of a single PEP/sanctions match."""
    match_score: str = ""
    name: str = ""
    aliases: List[str] = field(default_factory=list)
    last_updated: str = ""
    addresses: List[str] = field(default_factory=list)
    country: str = ""
    position: str = ""
    reason: str = ""


@dataclass
class IDUResult:
    """Complete result for one search."""
    config: Dict
    scraped_at: str
    search_id: str = ""
    verdict: str = ""
    score: str = ""
    date_of_search: str = ""
    summary_items: List[SummaryItem] = field(default_factory=list)
    address_detail: Dict = field(default_factory=dict)
    credit_active: Dict = field(default_factory=dict)
    dob_verification: Dict = field(default_factory=dict)
    mortality: Dict = field(default_factory=dict)
    gone_away: Dict = field(default_factory=dict)
    pep_entries: List[PEPEntry] = field(default_factory=list)
    sanction_result: str = ""
    ccj: Dict = field(default_factory=dict)
    insolvency: Dict = field(default_factory=dict)
    company_director: Dict = field(default_factory=dict)
    search_activity: Dict = field(default_factory=dict)
    address_links: List[Dict] = field(default_factory=list)
    property_detail: Dict = field(default_factory=dict)
    screenshot_path: Optional[str] = None
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """True when no error and verdict has been set."""
        return (self.error is None) and (self.verdict != "")

    def to_dict(self) -> Dict:
        """Return a JSON-serializable dict of the result."""
        try:
            return asdict(self)
        except Exception:
            logger.exception("Failed to convert IDUResult to dict")
            return {}

    def to_json(self, indent: int = 2) -> str:
        """Return pretty JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
