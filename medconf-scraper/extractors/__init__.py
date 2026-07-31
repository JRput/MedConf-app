# extractors/__init__.py
"""
Per-source detail-page extractors.

Each source (RCGP, RCSEng, RSM, future sources) gets its own extractor module
that knows the HTML structure of that source's event detail pages. A registry
maps source_id (or source_name) to the matching extractor.

Architecture:
- Listing-page extraction (browser.get_event_cards) is GENERIC across sources.
- Detail-page extraction is PER-SOURCE because event detail pages have
  highly varied markup for pricing, venue, dates, etc.
- If no extractor is registered for a source, the FallbackExtractor uses the
  generic LLM-only extraction path (the previous default behaviour).

To onboard a new source:
1. Inspect a few of its event detail pages.
2. Create extractors/<source_slug>.py with a class implementing extract_detail().
3. Register it in EXTRACTOR_REGISTRY below.
"""

from typing import Dict, Any, Optional

from .base import BaseExtractor
from .fallback import FallbackExtractor
from .rsm import RSMExtractor
from .rcseng import RCSEngExtractor
from .rcgp import RCGPExtractor
from .rcp import RCPExtractor
from .rcseng_courses import RCSEngCoursesExtractor
from .rcem import RCEMExtractor
from .rcog import RCOGExtractor
from .rcr import RCRAIConferenceExtractor, RCREventsPortalExtractor
from .bopa import BOPAExtractor
from .btog import BTOGExtractor
from .asco import ASCOAnnualExtractor, ASCOMeetingsExtractor
from .esmo import ESMOExtractor
from .aacr import AACRExtractor
from .estro import ESTROExtractor
from .sabcs import SABCSExtractor
from .esgo import ESGOCongressExtractor, ESGOCoursesExtractor
from .sitc import SITCExtractor

# source_id → extractor class
# IDs come from the scraper_sources table (see Supabase).
EXTRACTOR_REGISTRY: Dict[int, type[BaseExtractor]] = {
    1: RCGPExtractor,                   # Royal College of General Practitioners
    2: RCSEngExtractor,                 # Royal College of Surgeons of England
    3: RSMExtractor,                    # Royal Society of Medicine
    4: RCPExtractor,                    # Royal College of Physicians
    5: RCSEngCoursesExtractor,          # RCSEng Surgical Courses (event_type='course')
    6: RCEMExtractor,                   # RCEM events calendar (live)
    7: RCEMExtractor,                   # RCEM on-demand catch-up (is_on_demand=TRUE)
    8: RCEMExtractor,                   # RCEM Annual Conference 2027 (flagship subsite)
    9: RCOGExtractor,                   # RCOG events & courses (eventsair.com detail pages)
    10: RCOGExtractor,                  # RCOG World Congress 2027 (USD pricing, KL)
    11: RCRAIConferenceExtractor,       # RCR Global AI Conference 2026 (flagship subsite)
    12: RCREventsPortalExtractor,       # RCR events portal (Salesforce LWC, shadow DOM)
    13: BOPAExtractor,                  # British Oncology Pharmacy Association (Tribe Events API)
    14: BTOGExtractor,                  # British Thoracic Oncology Group (WordPress /events/ future section)
    15: ASCOAnnualExtractor,            # American Society of Clinical Oncology — Annual Meeting flagship
    16: ASCOMeetingsExtractor,          # ASCO Meetings-Education (Breakthrough Singapore + future satellites)
    17: ESMOExtractor,                  # European Society for Medical Oncology — meeting calendar (Nuxt SPA)
    18: AACRExtractor,                  # American Association for Cancer Research — meetings & workshops calendar (WordPress, 5-page pagination)
    19: ESTROExtractor,                 # European Society for Radiotherapy and Oncology — congresses (server-rendered, 2 events)
    20: SABCSExtractor,                 # San Antonio Breast Cancer Symposium — flagship WordPress (USD tables, /key-dates)
    21: ESGOCongressExtractor,          # ESGO Annual Congress (congress.esgo.org, EUR HTML tables)
    22: ESGOCoursesExtractor,           # ESGO courses listing (esgo.org/esgo-courses, BEM cards)
    23: SITCExtractor,                  # SITC 41st Annual Meeting 2026 (Wix flagship; 2026 pricing behind JS role picker → deferred to remediator)
}


def get_extractor(source: Dict[str, Any]) -> BaseExtractor:
    """
    Return the registered extractor for a source, or the fallback if none.

    `source` is the row from scraper_sources (must include 'id').
    """
    cls = EXTRACTOR_REGISTRY.get(source["id"], FallbackExtractor)
    return cls(source)


__all__ = ["get_extractor", "BaseExtractor", "FallbackExtractor", "RSMExtractor"]
