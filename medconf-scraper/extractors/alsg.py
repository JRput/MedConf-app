# extractors/alsg.py
"""
Advanced Life Support Group (ALSG) — Courses extractor.

ALSG's main site (alsg.org) is a Moodle VLE requiring login; the public
course-dates catalogue lives on a separate plain server-rendered PHP page:

    https://www.alsg.org/coursedates/courseview.php?coursetype=<TYPE>

There are 14 known course types (confirmed via the <select id="coursetype">
dropdown on that page — no course landing page or sitemap exists, so we
hardcode the list and loop it):

    APEx, APLS 2 Day, APLS Recertification, ATLS, CPRR, CYP APEx, HMIMMS,
    HMIMMS Team Provider, MIMMS 2 Day, MIMMS Team Provider, mMOET, NAPSTaR,
    PLS, POET

Each coursetype page IS the detail page — there's no separate per-course
subpage. The whole session table (dates, location, centre/venue, apply
link, phone, notes/fee) renders server-side in one plain HTML <table>
under a "Start date / End date / Location / Centre/Venue / Apply Here /
Telephone / Notes" header row. One course type = ONE parent `conferences`
row (event_type='course') + one `course_sessions` row per table row.

Verified quirks (probed live, 2026-08-15):
  - No page has a real per-course <h1> — the page's only <h1> is the site
    logo/banner ("Course Dates and Venues"), identical across all 14
    course-type pages. So conference_name comes from a small static
    TYPE -> full-name map (built from the recon notes + well-established
    public course-name conventions), NOT from an h1 per the usual rule —
    documented deviation, see COURSE_TYPE_NAMES below.
  - No CPD point/accreditation text anywhere on any of the 14 pages —
    cpd_points/cpd_accredited are always left null/False (never fabricated).
  - No Overview/About prose anywhere on the page — pricing_tables.py's
    heading-based table parser doesn't apply either (fees are inline free
    text inside the Notes <td>, not a labelled fee table). Fees are
    regex-parsed from the Notes cell text per row instead.
  - "Apply Here" cells are either a mailto: link (regional NHS Trust
    contact), a real external booking URL (private training providers),
    or occasionally a bare URL/email as plain text.
  - Only ~7/61 rows on APLS 2 Day publish a GBP fee inline; most leave it
    to the organiser to quote on contact. Sessions without a discoverable
    £ figure simply get no pricing tier — never fabricated.
  - All courses are face-to-face; no online/virtual course type exists
    (verified: no "virtual"/"e-learning"/"webinar"/"remote" text on any
    of the 14 pages) — event_format is always 'in_person'.
"""

import re
import urllib.parse
from datetime import date, datetime
from typing import Dict, Any, Optional, Callable, List, Tuple

from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from logger import logger


BASE_LISTING_URL = "https://www.alsg.org/coursedates/courseview.php?coursetype="

# The 14 known course types, taken verbatim from the <select id="coursetype">
# dropdown (probed live). No PHTLS course exists on this source (ATLS instead).
COURSE_TYPES: List[str] = [
    "APEx", "APLS 2 Day", "APLS Recertification", "ATLS", "CPRR",
    "CYP APEx", "HMIMMS", "HMIMMS Team Provider", "MIMMS 2 Day",
    "MIMMS Team Provider", "mMOET", "NAPSTaR", "PLS", "POET",
]

# Full-name expansions used ONLY where we're confident of the public,
# well-established course name (several confirmed directly in recon.json's
# expected_found list). Where we're not confident of an acronym expansion
# (APEx, CPRR, NAPSTaR, POET) we deliberately keep the bare code rather
# than guess wrong — see module docstring.
COURSE_TYPE_NAMES: Dict[str, str] = {
    "APEx": "APEx Course",
    "APLS 2 Day": "Advanced Paediatric Life Support (APLS) — 2 Day Course",
    "APLS Recertification": "Advanced Paediatric Life Support (APLS) Recertification",
    "ATLS": "Advanced Trauma Life Support (ATLS)",
    "CPRR": "CPRR Course",
    "CYP APEx": "Children and Young People (CYP) APEx Course",
    "HMIMMS": "Hospital Major Incident Medical Management and Support (HMIMMS)",
    "HMIMMS Team Provider": "Hospital Major Incident Medical Management and Support (HMIMMS) — Team Provider",
    "MIMMS 2 Day": "Major Incident Medical Management and Support (MIMMS) — 2 Day Course",
    "MIMMS Team Provider": "Major Incident Medical Management and Support (MIMMS) — Team Provider",
    "mMOET": "Managing Obstetric Emergencies and Trauma (mMOET)",
    "NAPSTaR": "NAPSTaR Course",
    "PLS": "Paediatric Life Support (PLS)",
    "POET": "POET Course",
}

# Short, conservative descriptions — factual about what the page itself
# shows (regional/international providers running the same standard ALSG
# course), never claiming CPD points or accreditation details not on the
# page.
COURSE_TYPE_DESC: Dict[str, str] = {
    "APEx": "An ALSG-run APEx course, delivered by regional and international training centres on multiple scheduled dates.",
    "APLS 2 Day": "Advanced Paediatric Life Support (APLS) is ALSG's standard 2-day course in the emergency care of acutely ill and injured children, run by NHS trusts and approved training centres across the UK and abroad.",
    "APLS Recertification": "A 1-day face-to-face recertification course for clinicians who have already completed a full APLS course within the past 4 years.",
    "ATLS": "Advanced Trauma Life Support (ATLS) is a 2-day face-to-face course in the systematic initial assessment and management of the severely injured patient.",
    "CPRR": "An ALSG-run CPRR course, delivered by regional and international training centres on multiple scheduled dates.",
    "CYP APEx": "The paediatric (Children and Young People) version of ALSG's APEx course, delivered by regional training centres.",
    "HMIMMS": "Hospital Major Incident Medical Management and Support (HMIMMS) trains hospital staff to manage a major incident from the receiving hospital's perspective.",
    "HMIMMS Team Provider": "The Team Provider variant of ALSG's Hospital MIMMS (HMIMMS) course.",
    "MIMMS 2 Day": "Major Incident Medical Management and Support (MIMMS) is a 2-day course covering the medical response to major incidents at the scene.",
    "MIMMS Team Provider": "The Team Provider variant of ALSG's Major Incident Medical Management and Support (MIMMS) course.",
    "mMOET": "Managing Obstetric Emergencies and Trauma (mMOET) trains multidisciplinary teams in the management of obstetric emergencies and maternal trauma.",
    "NAPSTaR": "An ALSG-run NAPSTaR course, delivered by regional and international training centres on multiple scheduled dates.",
    "PLS": "Paediatric Life Support (PLS) is a shorter ALSG course covering the recognition and initial management of the seriously ill child.",
    "POET": "An ALSG-run POET course, delivered by regional and international training centres on multiple scheduled dates.",
}

_MONTHLESS_DATE_RE = re.compile(r"^\s*(\d{2})-(\d{2})-(\d{4})\s*$")

_COUNTRY_TOKENS = {
    "gb", "uk", "united kingdom", "england", "scotland", "wales",
    "northern ireland", "ireland", "republic of ireland",
}

UK_POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", re.I)

_UK_REGIONS: Dict[str, str] = {
    "london": "London",
    "manchester": "North West England", "liverpool": "North West England",
    "warrington": "North West England", "preston": "North West England",
    "chester": "North West England", "bolton": "North West England",
    "leeds": "Yorkshire and the Humber", "sheffield": "Yorkshire and the Humber",
    "york": "Yorkshire and the Humber", "doncaster": "Yorkshire and the Humber",
    "hull": "Yorkshire and the Humber",
    "newcastle": "North East England", "middlesbrough": "North East England",
    "sunderland": "North East England", "durham": "North East England",
    "birmingham": "West Midlands", "coventry": "West Midlands",
    "wolverhampton": "West Midlands", "stoke": "West Midlands",
    "cannock": "West Midlands",
    "bristol": "South West England", "exeter": "South West England",
    "plymouth": "South West England", "bath": "South West England",
    "cardiff": "Wales", "swansea": "Wales", "newport": "Wales",
    "merthyr tydfil": "Wales", "penarth": "Wales", "llandough": "Wales",
    "edinburgh": "Scotland", "glasgow": "Scotland", "aberdeen": "Scotland",
    "dundee": "Scotland", "inverness": "Scotland",
    "belfast": "Northern Ireland",
    "cambridge": "East of England", "norwich": "East of England",
    "ipswich": "East of England", "luton": "East of England",
    "norfolk": "East of England", "peterborough": "East of England",
    "oxford": "South East England", "brighton": "South East England",
    "reading": "South East England", "southampton": "South East England",
    "portsmouth": "South East England", "gatwick": "South East England",
    "high wycombe": "South East England", "epsom": "South East England",
    "surrey": "South East England", "farnborough": "South East England",
    "farnbrough": "South East England", "poole": "South East England",
    "kettering": "East Midlands", "leicester": "East Midlands",
    "nottingham": "East Midlands", "derby": "East Midlands",
    "northampton": "East Midlands", "chesterfield": "East Midlands",
}


class ALSGExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing override — one shell per coursetype page (no sitemap/API
    # exists; the 14 types are hardcoded from a live probe of the
    # <select id="coursetype"> dropdown).
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        shells: List[Dict[str, Any]] = []
        for course_type in COURSE_TYPES:
            url = BASE_LISTING_URL + urllib.parse.quote(course_type)
            shells.append({
                "title": COURSE_TYPE_NAMES.get(course_type, f"{course_type} Course"),
                "booking_url": url,
                "is_sold_out": False,
                "start_date": None,
                "start_time": None,
                "location_hint": None,
                "description_hint": None,
                "category": "Course",
                "page_index": 1,
                # extra key consumed by extract_detail — the raw dropdown
                # value, needed to look up the name/description maps
                # without re-parsing it back out of the URL.
                "_course_type": course_type,
            })
        logger.info(f"ALSG: {len(shells)} course-type pages queued")
        return shells

    # ------------------------------------------------------------------ #
    # Detail extraction — the coursetype page IS the detail page.
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        course_type = shell.get("_course_type") or self._course_type_from_url(shell.get("booking_url") or "")
        course_name = COURSE_TYPE_NAMES.get(course_type, f"{course_type} Course" if course_type else shell.get("title"))

        sessions = self._extract_sessions(page)

        today_iso = date.today().isoformat()
        upcoming = [s for s in sessions if s["start_date"] and s["start_date"] >= today_iso]
        upcoming.sort(key=lambda s: s["start_date"])

        parent_start = upcoming[0]["start_date"] if upcoming else None
        parent_end = (upcoming[0].get("end_date") or parent_start) if upcoming else None

        parent_venue = self._uniform([s["venue_name"] for s in upcoming if s.get("venue_name")])
        parent_city = self._uniform([s["city"] for s in upcoming if s.get("city")])
        parent_region = self._uniform([s["region"] for s in upcoming if s.get("region")])

        description = COURSE_TYPE_DESC.get(course_type)
        specialty = classify_specialty(course_name, description)

        return {
            "conference_name": course_name,
            "event_type": "course",
            "description": description,
            "specialty": specialty,
            "start_date": parent_start,
            "end_date": parent_end,
            "venue_name": parent_venue,
            "city": parent_city,
            "region": parent_region,
            "event_format": "in_person",
            "cpd_points": None,
            "cpd_accredited": False,
            "is_sold_out": False,
            "abstract_open": False,
            "abstract_deadline": None,
            # Only upcoming sessions are emitted — per source-specific
            # instructions for this onboarding, past rows are filtered
            # rather than kept (unlike rcseng_courses, which keeps all
            # sessions and filters only for the parent-field computation).
            "sessions": upcoming,
            "pricing_tiers": self._build_pricing_tiers(upcoming),
        }

    # ------------------------------------------------------------------ #
    # Session table parsing
    # ------------------------------------------------------------------ #
    def _extract_sessions(self, page: Page) -> List[Dict[str, Any]]:
        try:
            raw_rows = page.evaluate(r"""() => {
                const tables = Array.from(document.querySelectorAll('table.auto-style3'));
                let target = null;
                for (const t of tables) {
                    const firstRow = t.querySelector('tr');
                    if (firstRow && /start date/i.test(firstRow.textContent)) { target = t; break; }
                }
                if (!target) return [];
                const trs = Array.from(target.querySelectorAll('tr')).slice(1);
                return trs.map((tr, idx) => {
                    const tds = Array.from(tr.querySelectorAll('td'));
                    const cell = i => tds[i] ? (tds[i].textContent || '').trim() : '';
                    const applyTd = tds[4];
                    const a = applyTd ? applyTd.querySelector('a') : null;
                    return {
                        idx: idx,
                        start: cell(0),
                        end: cell(1),
                        location: cell(2),
                        centre: cell(3),
                        apply_text: cell(4),
                        apply_href: a ? a.getAttribute('href') : null,
                        phone: cell(5),
                        notes: cell(6),
                    };
                });
            }""") or []
        except Exception as e:
            logger.warning(f"ALSG: session table probe failed: {e}")
            return []

        sessions: List[Dict[str, Any]] = []
        for raw in raw_rows:
            start_date = self._parse_ddmmyyyy(raw.get("start"))
            if not start_date:
                continue  # unusable without a start date
            end_date = self._parse_ddmmyyyy(raw.get("end")) or start_date

            venue, city, region = self._parse_location(raw.get("location") or "", raw.get("centre") or "")

            notes_text = (raw.get("notes") or "").strip()
            price = self.parse_gbp(notes_text)

            booking_url = self._clean_apply_url(raw.get("apply_href"), raw.get("apply_text"))
            availability = self._infer_availability(notes_text)

            sessions.append({
                "_idx": raw.get("idx", 0),
                "start_date": start_date,
                "end_date": end_date if end_date != start_date else None,
                "start_time": None,
                "duration_text": self._format_duration_text(start_date, end_date),
                "availability_status": availability,
                "spots_left": None,
                "booking_url": booking_url,
                "venue_name": venue,
                "city": city,
                "region": region,
                "notes": notes_text or None,
                "_price_gbp": price,
            })

        return sessions

    # ------------------------------------------------------------------ #
    # Pricing — one "Course fee" tier per session that publishes a GBP
    # figure. Not every row has one (organiser quotes on contact) — no
    # fallback price is invented for those. pricing_tables.py's shared
    # heading-based table parser doesn't apply here: there's no separate
    # fee table/heading, just free text inside each row's Notes cell.
    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_pricing_tiers(sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        tiers: List[Dict[str, Any]] = []
        for s in sessions:
            price = s.get("_price_gbp")
            if price is None:
                continue
            tiers.append({
                "tier_label": "Course fee",
                "price_gbp": price,
                "is_early_bird": False,
                "early_bird_deadline": None,
                "_session_idx": s["_idx"],
            })
        return tiers

    # ------------------------------------------------------------------ #
    # Availability — ALSG rows almost never carry an explicit status; err
    # towards 'unknown' rather than assuming 'available' per the playbook.
    # ------------------------------------------------------------------ #
    @staticmethod
    def _infer_availability(notes_text: str) -> str:
        t = notes_text.lower()
        if re.search(r"\bsold out\b|\bfully booked\b|\bno places\b|\bfull\s*$", t):
            return "sold_out"
        if re.search(r"\bwaiting list\b|\bcurrently full\b|\blimited places\b|\bfew places\b", t):
            return "limited"
        return "unknown"

    # ------------------------------------------------------------------ #
    # Booking URL cleanup — strip the malformed trailing
    # `?Subject=...target=" _top"=""` artefact ALSG's markup leaves on
    # mailto hrefs (target attribute got concatenated into the query
    # string by the source's own template).
    # ------------------------------------------------------------------ #
    @staticmethod
    def _clean_apply_url(href: Optional[str], text: Optional[str]) -> Optional[str]:
        if href:
            href = href.strip()
            if href.startswith("mailto:"):
                # keep mailto + Subject=..., drop everything from "target" on
                href = re.split(r"\s+target=", href)[0]
                return href or None
            if href.startswith("http"):
                return href
        # Some rows show a bare URL/email as plain text with no <a> at all
        if text:
            t = text.strip()
            m = re.search(r"https?://\S+", t)
            if m:
                return m.group(0)
            m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", t)
            if m:
                return f"mailto:{m.group(0)}"
        return None

    # ------------------------------------------------------------------ #
    # Location parsing — Location + Centre/Venue columns, wildly
    # inconsistent formatting across ~15 independent regional providers.
    # ------------------------------------------------------------------ #
    @classmethod
    def _parse_location(cls, location_text: str, centre_text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        location_text = location_text.strip()
        centre_text = centre_text.strip()

        venue = centre_text or None
        parts = [p.strip() for p in location_text.split(",") if p.strip()]

        # Drop postcode-only and country-only chunks before picking city/venue.
        useful = [p for p in parts if not UK_POSTCODE_RE.match(p) and p.lower() not in _COUNTRY_TOKENS]

        if not venue and len(useful) > 1:
            venue = useful[0][:200]

        if useful:
            city = useful[-1][:80]
        elif parts:
            city = parts[-1][:80]
        else:
            city = None

        region = cls._infer_uk_region(city) if city else None
        return venue, city, region

    @classmethod
    def _infer_uk_region(cls, city: Optional[str]) -> Optional[str]:
        c = (city or "").lower()
        for key, val in _UK_REGIONS.items():
            if key in c:
                return val
        return None

    # ------------------------------------------------------------------ #
    # Utilities
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_ddmmyyyy(text: Optional[str]) -> Optional[str]:
        if not text:
            return None
        m = _MONTHLESS_DATE_RE.match(text.strip())
        if not m:
            return None
        dd, mm, yyyy = m.groups()
        try:
            return f"{int(yyyy):04d}-{int(mm):02d}-{int(dd):02d}"
        except ValueError:
            return None

    @staticmethod
    def _format_duration_text(start_iso: str, end_iso: Optional[str]) -> Optional[str]:
        try:
            s = datetime.strptime(start_iso, "%Y-%m-%d").date()
            if end_iso and end_iso != start_iso:
                e = datetime.strptime(end_iso, "%Y-%m-%d").date()
                days = (e - s).days + 1
                return f"{days} days"
            return "1 day"
        except Exception:
            return None

    @staticmethod
    def _uniform(values: List[Optional[str]]) -> Optional[str]:
        cleaned = [v for v in values if v]
        if not cleaned:
            return None
        unique = set(v.strip().lower() for v in cleaned)
        return cleaned[0] if len(unique) == 1 else None

    @staticmethod
    def _course_type_from_url(url: str) -> Optional[str]:
        try:
            q = urllib.parse.urlparse(url).query
            params = urllib.parse.parse_qs(q)
            vals = params.get("coursetype")
            return urllib.parse.unquote(vals[0]) if vals else None
        except Exception:
            return None
