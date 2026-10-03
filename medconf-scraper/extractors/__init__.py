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
from .alsg import ALSGExtractor
from .rcpsg import RCPSGExtractor
from .rcpath import RCPathExtractor
from .rcpsych import RCPsychExtractor
from .rcsed import RCSEdExtractor
from .resus import ResusExtractor
from .rcpe import RCPEExtractor
from .rcpch import RCPCHExtractor
from .rcophth import RCOphthExtractor
from .fph import FPHExtractor
from .fom import FOMExtractor
from .fpm import FPMExtractor
from .escardio import ESCExtractor
from .acpgbi import ACPGBIExtractor
from .asgbi import ASGBIExtractor
from .cosrh import CoSRHExtractor
from .ficm import FICMExtractor
from .rcoa import RCoAExtractor
from .arvo import ARVOExtractor
from .iasociety import IASExtractor
from .mddus import MDDUSExtractor
from .themdu import MDUExtractor
from .baets import BaetsExtractor
from .aans import AansExtractor
from .aagl import AaglExtractor
from .esp_pathology import EspPathologyExtractor
from .uroweb import UrowebExtractor
from .eanm import EanmExtractor
from .sccm import SccmExtractor
from .advance_he import AdvanceHeExtractor
from .ifosworld import IfosworldExtractor
from .idweek import IdweekExtractor
from .isuog import IsuogExtractor
from .ihi import IhiExtractor
from .b_s_h import BSHExtractor
from .acep import AcepExtractor

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
    24: ALSGExtractor,                  # Advanced Life Support Group — 14 course-type PHP tables (course/sessions, httpx)
    25: RCPSGExtractor,                 # RCPSG Glasgow — Drupal /education catalogue (mixed, multi-session courses)
    26: RCPathExtractor,                # Royal College of Pathologists — Preside CMS single listing (mixed, upcoming/past div split)
    27: RCPsychExtractor,               # Royal College of Psychiatrists — one-page calendar (mixed, httpx UA workaround for CloudFront WAF)
    28: RCSEdExtractor,                 # RCSEd — services.rcsed.ac.uk catalogue ?page=1..5 (mixed)
    29: ResusExtractor,                 # Resuscitation Council UK — course hub + availability tables (course/sessions, no public fees)
    30: RCPEExtractor,                      # RCPE — Drupal /events listing, page_query pagination, deterministic icon-chip dates/venue/CPD + #fees tab pricing (bypasses pricing_tables.py's headin
    31: RCPCHExtractor,                     # RCPCH (Royal College of Paediatrics and Child Health) — events + courses/webinars, paginated static HTML, cs-/ev- shared field shape
    32: RCOphthExtractor,                   # RCOphth (32) — WordPress listing override (generic walker finds 0 cards) + plain WordPress detail pages, no anti-bot
    33: FPHExtractor,                       # FPH: custom CMS, page-query pagination (?pageSize=12&pageIndex=N), no fees ever published on-site (booking via members-portal login or off-site organi
    34: FOMExtractor,                       # FOM (Faculty of Occupational Medicine) — tiny 1-2 event listing, both externally-run, no pricing/venue on-site
    35: FPMExtractor,                       # FPM (Faculty of Pharmaceutical Medicine) events -- WordPress listing at /events/, mixed conference/course/workshop catalogue, 9 upcoming events at onb
    36: ESCExtractor,                       # European Society of Cardiology congress calendar - meta-tag driven detail pages + structured registration fee tables, EUR pricing.
    37: ACPGBIExtractor,                    # Coloproctology events aggregator calendar (ACPGBI); year-paginated (2026, 2027, ...), free-text fees/CPD (no markup tables), title-filtered to drop th
    38: ASGBIExtractor,                     # ASGBI — Webflow static cards: International Surgical Congress + EGS Symposium listings (fees behind JS portal, not scraped)
    39: CoSRHExtractor,                     # CoSRH (ex-FSRH) — iMIS Cloud SPA, browser-first listing, 4 fee-table shapes
    40: RCoAExtractor,                      # RCoA — INACTIVE: Cloudflare also blocks GitHub-runner IPs (works from home). Drupal, 0-indexed pager, fee JPGs
    41: FICMExtractor,                      # FICM — Drupal behind Cloudflare (browser profile rotation), 0-indexed pager, server-rendered tabs
    42: ARVOExtractor,                      # ARVO Annual Meeting — flagship microsite, single shell per year, USD pricing tables
    43: IASExtractor,                       # IAS flagship conferences (International AIDS Conference, IAS Conference on HIV Science, HIVR4P) - homepage mega-menu as listing, thin market
    44: MDDUSExtractor,                     # 44: MDDUSExtractor,  # MDDUS training & CPD (Interactive Zoom courses, page_query listing, date cross-check for CMS date bug)
    45: MDUExtractor,                       # MDU Learn & Develop — dated CPD courses (event_type='course', sessions[]) via the site's own search-widget JSON API; no /events page exists
    46: BaetsExtractor,                     # BAETS - Tribe Events API family
    47: AansExtractor,                      # AANS - Tribe Events API family
    48: AaglExtractor,                      # AAGL - Tribe Events API family
    49: EspPathologyExtractor,              # ESP - Tribe Events API family
    50: UrowebExtractor,                    # EAU Events (50) - Nuxt SPA, listing via site's own GraphQL (token captured in-browser), 55 upcoming live events, EUR/no fees publi
    51: EanmExtractor,                      # European Association of Nuclear Medicine - calendar of events via Stec REST API (EANM + third-party listings)
    52: SccmExtractor,                      # 52: SCCM — single calendar page (75 cards) + flagship Congress page; shells use #evt-hash identity URLs, real link returned as boo
    53: AdvanceHeExtractor,                 # Advance HE: UK HE leadership/teaching/governance events, WordPress query-loop listing (~111 upcoming), sparse detail pages with GB
    54: IfosworldExtractor,                 # IFOS ORL congress calendar - Tribe Events REST API, ~16 upcoming, USD fees when stated
    55: IdweekExtractor,                    # IDWeek annual meeting - flagship microsite, single shell per year, USD pricing table
    56: IsuogExtractor,                     # ISUOG — static events calendar (upcoming tab only), approved courses + education webinars/livestream courses, GBP fee tables
    57: IhiExtractor,                       # IHI — dated course/certification runs from /learn/courses cards + ConferenceEvent JSON-LD from /connect/events; USD
    58: BSHExtractor,                       # British Society for Haematology (events listing, server-rendered)
    59: AcepExtractor,                      # 59: ACEP — American College of Emergency Physicians event calendar (JSON API listing, USD, no fees published)
}


def get_extractor(source: Dict[str, Any]) -> BaseExtractor:
    """
    Return the registered extractor for a source, or the fallback if none.

    `source` is the row from scraper_sources (must include 'id').
    """
    cls = EXTRACTOR_REGISTRY.get(source["id"], FallbackExtractor)
    return cls(source)


__all__ = ["get_extractor", "BaseExtractor", "FallbackExtractor", "RSMExtractor"]
