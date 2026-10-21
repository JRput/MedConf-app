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
from .ersnet import ErsnetExtractor
from .bsge import BsgeExtractor
from .bcis import BcisExtractor
from .fdi import FdiExtractor
from .ecco_ibd import EccoIbdExtractor
from .easl import EaslExtractor
from .bapras import BaprasExtractor
from .esicm import EsicmExtractor
from .apm import ApmExtractor
from .era import EraExtractor
from .eusem import EusemExtractor
from .dermamedical import DermamedicalExtractor
from .biasp import BiaspExtractor
from .bia import BiaExtractor
from .sam import SamExtractor
from .aaos import AaosExtractor
from .theultrasoundsite import TheUltrasoundSiteExtractor
from .endocrine import EndocrineExtractor
from .arrs import ArrsExtractor
from .bsccp import BsccpExtractor
from .crf import CrfExtractor
from .eadv import EadvExtractor
from .ataccgroup import AtaccExtractor
from .interfaceaesthetics import InterfaceAestheticsExtractor
from .bdiap import BdiapExtractor
from .esaic import EsaicExtractor
from .euretina import EuretinaExtractor
from .aasld import AasldExtractor
from .bess import BessExtractor
from .ukio import UkioExtractor
from .ddw import DdwExtractor
from .ectrims import EctrimsExtractor
from .efort import EfortExtractor
from .eaps_kenes import EapsExtractor
from .espid import EspidExtractor
from .pas_meeting import PasExtractor
from .acog import AcogExtractor
from .escmid import EscmidExtractor
from .croi import CroiExtractor
from .myesr import MyesrExtractor
from .ccrlondon import CcrLondonExtractor
from .nhsconfedexpo import NhsConfedExpoExtractor
from .viveevent import ViveExtractor
from .aaic import AaicExtractor
from .aao import AaoExtractor
from .acc import AccExtractor
from .asahq import AsahqExtractor
from .asn_online import AsnOnlineExtractor
from .auanet import AuanetExtractor
from .baaps import BaapsExtractor
from .boa import BoaExtractor
from .bofas import BofasExtractor
from .bpna import BpnaExtractor
from .bsg import BsgExtractor
from .chestnet import ChestnetExtractor
from .ean import EanExtractor
from .escrs import EscrsExtractor
from .ics import IcsExtractor
from .rsna import RsnaExtractor
from .ueg import UegExtractor
from .bapm import BapmExtractor
from .bmfms import BmfmsExtractor
from .brit_thoracic import BritThoracicExtractor
from .bsir import BsirExtractor
from .rheumatology import RheumatologyExtractor
from .sbns import SbnsExtractor
from .associationofbreastsurgery import AssociationOfBreastSurgeryExtractor
from .basl import BASLExtractor
from .baus import BAUSExtractor
from .bbts import BBTSExtractor
from .bssh import BSSHExtractor
from .his import HISExtractor
from .vascularsociety import VascularSocietyExtractor

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
    60: ErsnetExtractor,                     # 60: European Respiratory Society - WordPress generic family (constants only)
    61: BsgeExtractor,                       # 61: British Society for Gynaecological Endoscopy - WordPress generic family (constants only)
    62: BcisExtractor,                       # 62: British Cardiovascular Intervention Society - WordPress generic family (constants only)
    63: FdiExtractor,                        # 63: FDI World Dental Federation - family extractor on Drupal archive (constants only)
    64: EccoIbdExtractor,                    # 64: ECCO - family extractor on Joomla calendar (constants only)
    65: EaslExtractor,                       # 65: EASL (European Association for the Study of the Liver) events: WordPress family subclass + bespoke venue/course/organiser_url handling
    66: BaprasExtractor,                     # 66: BAPRAS events: Sitefinity listing via WordPress family base; bespoke prose fee/location parser and organiser_url
    67: EsicmExtractor,                      # 67: ESICM events: 'Next events' grid only; bespoke header (city/venue) and fee-grid parsing
    68: ApmExtractor,                        # 68: APM events: MEC list skin parsed with divider year; ticket block fees; JSON-LD offers ignored
    69: EraExtractor,                        # 69: ERA events: multi-source shells (endorsed events, Congress, Education Meetings, CME courses); external sites left to the explorer
    70: EusemExtractor,                      # 70: European Society for Emergency Medicine - Joomla course articles, home-menu walk (family subclass + listing override)
    71: DermamedicalExtractor,               # 71: Derma Medical UK aesthetic-medicine courses - WooCommerce variation JSON -> course + sessions (family subclass + override)
    72: BiaspExtractor,                      # 72: British and Irish Association of Stroke Physicians - single free-form events page, block parser (BaseExtractor, bespoke)
    73: BiaExtractor,                        # 73: British Infection Association - concrete5 event_list cards, family subclass + prose venue parsing
    74: SamExtractor,                        # 74: Society for Acute Medicine - Events Manager, three listing URLs unioned, per-page H1 + date line (family subclass + overrides)
    75: AaosExtractor,                       # 75: AAOS: 3 course category pages + future-meetings Annual Meetings; fees from same-site /registration/ sub-page (USD)
    76: TheUltrasoundSiteExtractor,          # 76: The Ultrasound Site: WooCommerce shop; one course row per two-day product, day-only products folded into fee tiers (GBP)
    77: EndocrineExtractor,                  # 77: Endocrine Society: hub CEU sentence + ENDO future meetings + Keystone joint meetings; Keystone fees from pricing page (USD)
    78: ArrsExtractor,                       # 78: ARRS: server-rendered events table; longitudinal rows grouped into parent courses with sessions; symposium/course fees from page tables (USD)
    79: BsccpExtractor,                      # 79: BSCCP: Craft CMS /events card list (page 1 only); Register button kept as organiser_url; trainee OSCE exam skipped
    80: CrfExtractor,                        # 80: CRF events calendar: one flat page of cards (dates/venue on the card) linking to each meeting's own site; fees read from the meeting's USD rate grid (family subclass, list_shells_override)
    81: EadvExtractor,                       # 81: EADV events calendar: flat page of partner-congress cards (complete shells, external booking URL) plus EADV's own Symposium/Congress from their page titles (family subclass, list_shells_override)
    82: AtaccExtractor,                      # 82: ATACC Group: WooCommerce product grid of dated trauma/critical-care courses -> one course parent per group (ATACC Course, ATACC Ireland) with sessions[] (family subclass)
    83: InterfaceAestheticsExtractor,        # 83: Interface Aesthetics (UK injectables training): /courses/ links -> course pages; one parent per course with sessions[] from the Upcoming Dates rows (family subclass)
    84: BdiapExtractor,                      # 84: BDIAP (pathology) future meetings: .aspx bullet list -> detail pages; venue from ./location.aspx, fees from ./registration.aspx tables (family subclass)
    85: EsaicExtractor,                      # 85: ESAIC - WP REST /wp-json/wp/v2/event (ACF dates/place); own events parsed from esaic.org pages, endorsed events from the API record, congress fee grids from the organiser registration page
    86: EuretinaExtractor,                   # 86: EURETINA - future-meetings table parsed from the rendered Elementor page (first schedule block, deduped); rows without a microsite link get a listing#slug URL
    87: AasldExtractor,                      # 87: AASLD - Drupal JSON:API /jsonapi/index/events (browser), plus The Liver Meeting microsite (/tlm-NN/home + /event-registration) which the index omits
    88: BessExtractor,                       # 88: BESS - CoBlocks events carousel read from the rendered listing; links to event pages, partner (ORUK) pages and WooCommerce product pages followed
    89: UkioExtractor,                       # 89: UKIO single-congress site (one upcoming edition) - single_congress family
    90: DdwExtractor,                        # 90: DDW single-congress site (one upcoming edition) - single_congress family
    91: EctrimsExtractor,                    # 91: ECTRIMS single-congress site (one upcoming edition) - single_congress family
    92: EfortExtractor,                      # 92: EFORT single-congress site (one upcoming edition) - single_congress family
    93: EapsExtractor,                       # 93: EAPS single-congress site (one upcoming edition) - single_congress family
    94: EspidExtractor,                      # 94: ESPID single-congress site (one upcoming edition) - single_congress family
    95: PasExtractor,                        # 95: PAS single-congress site (one upcoming edition) - single_congress family
    96: AcogExtractor,                       # 96: ACOG single-congress site (one upcoming edition) - single_congress family
    97: EscmidExtractor,                     # 97: ESCMID single-congress site (one upcoming edition) - single_congress family
    98: CroiExtractor,                       # 98: CROI single-congress site (one upcoming edition) - single_congress family
    99: MyesrExtractor,                      # 99: ESR single-congress site (one upcoming edition) - single_congress family
    100: CcrLondonExtractor,                  # 100: CCR London single-congress site (one upcoming edition) - single_congress family
    101: NhsConfedExpoExtractor,              # 101: NHS ConfedExpo single-congress site (one upcoming edition) - single_congress family
    102: ViveExtractor,                       # 102: ViVE single-congress site (one upcoming edition) - single_congress family
    103: EanExtractor,                        # 103: EAN single-congress site (one upcoming edition) - single_congress family
    104: AaicExtractor,                       # 104: AAIC single-congress site (one upcoming edition) - single_congress family
    105: AuanetExtractor,                     # 105: AUA single-congress site (one upcoming edition) - single_congress family
    106: AaoExtractor,                        # 106: AAO single-congress site (one upcoming edition) - single_congress family
    107: RsnaExtractor,                       # 107: RSNA single-congress site (one upcoming edition) - single_congress family
    108: ChestnetExtractor,                   # 108: CHEST single-congress site (one upcoming edition) - single_congress family
    109: BofasExtractor,                      # 109: BOFAS single-congress site (one upcoming edition) - single_congress family
    110: BpnaExtractor,                       # 110: BPNA single-congress site (one upcoming edition) - single_congress family
    111: AccExtractor,                        # 111: ACC single-congress site (one upcoming edition) - single_congress family
    112: AsnOnlineExtractor,                  # 112: ASN single-congress site (one upcoming edition) - single_congress family
    113: AsahqExtractor,                      # 113: ASA single-congress site (one upcoming edition) - single_congress family
    114: UegExtractor,                        # 114: UEG single-congress site (one upcoming edition) - single_congress family
    115: BaapsExtractor,                      # 115: BAAPS events calendar (bespoke, plastic/aesthetic-surgery events only)
    130: BsgExtractor,                        # 130: BSG events: Kentico/Blazor prerendered cards, walk ?page=N&start=<today> to the pager total; fees from the 'Registration fees' block; event type from title
    131: BoaExtractor,                        # 131: BOA event & course calendar: Eventfolio JSON endpoint via ems_calendar.EmsCalendarExtractor; third-party rows kept only if orthopaedic/surgical; 2027 Annual Congress from future-congresses page
    132: EscrsExtractor,                      # 132: ESCRS meetings & events: Umbraco event-search cards (plain HTTP), year-less dates resolved from URL/next occurrence, annual events enriched from the wintermeeting/congress microsites, Vision to Venture fees via members.escrs.org tickets
    133: IcsExtractor,                        # 133: Intensive Care Society events calendar: Eventfolio JSON endpoint via ems_calendar.EmsCalendarExtractor, SOA congress enriched from /events/soaNN.html, fee images left to the remediator
    116: BSSHExtractor,                       # 116: BSSH events: LightMedia year-view listing (current + 2 years), bespoke fee-matrix/prose/bookwhen fee parsing, 3-way event_type from row class
    117: VascularSocietyExtractor,            # 117: Vascular Society events: LightMedia current-year + calendar/date/<YYYY> listing; deposit/ticket/prose/external-hop fee parsing; ASM fee image read via vision
    118: BAUSExtractor,                       # 118: BAUS events: LightMedia ?view=year listing + sitemap fallback for next-year events (date routes 502), dates from add-to-calendar JSON, ticket-table fees
    119: HISExtractor,                        # 119: HIS events: Umbraco events-diary card list (+HISCON from conferences page), side-menu registration sub-page fees, two-hop FIS fees, event_type from URL section
    120: BBTSExtractor,                       # 120: BBTS events: Svelte-SSR news-style feed filtered to /events/bbts_events/, month archives, free-text date/venue parsing; sparse (2 upcoming)
    121: AssociationOfBreastSurgeryExtractor, # 121: ABS courses & events: Umbraco calendar cards (card date = last day, so details read in listing), registration sub-page fee grid, ABS Conference page + abstracts sub-page
    122: BASLExtractor,                       # 122: BASL events: ColdFusion single-page list (eid/999) with month headings and inline write-ups, fragment booking URLs, prose fee parsing
    124: BsirExtractor,                       # 124: BSIR (interventional radiology): crawl of /events/ series pages for the dated prose line; fees from the Register link (VITALS two-column page, ASM CIRSE grid)
    125: BmfmsExtractor,                      # 125: BMFMS (maternal & fetal medicine) events calendar: year-view date_row rows, current + next 2 year pages; fees on external organiser sites
    126: BritThoracicExtractor,               # 126: BTS (respiratory): short courses + Winter/Summer meetings + webinars + third-party courses; fees in a Fees block / booking-rates table
    127: RheumatologyExtractor,               # 127: BSR (rheumatology): DNN listings for conferences, courses, webinars; detail Date/Venue/CPD labels + Members/Non-members pricing tabs
    128: BapmExtractor,                       # 128: BAPM (perinatal medicine) meetings and events: teaser cards -> event pages; end date from Date line or intro duration; EventsAir fees for BAPM's own conference
    129: SbnsExtractor,                       # 129: SBNS (neurosurgery) event calendar: Eventfolio cards -> event pages; society meetings plus external courses; fee widget + organiser Book Now link
}


def get_extractor(source: Dict[str, Any]) -> BaseExtractor:
    """
    Return the registered extractor for a source, or the fallback if none.

    `source` is the row from scraper_sources (must include 'id').
    """
    cls = EXTRACTOR_REGISTRY.get(source["id"], FallbackExtractor)
    return cls(source)


__all__ = ["get_extractor", "BaseExtractor", "FallbackExtractor", "RSMExtractor"]
