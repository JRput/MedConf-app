"""
Association of Surgeons of Great Britain and Ireland (ASGBI) — extractor.

Main site (asgbi.org.uk) is a static Webflow build; server-side HTML already
carries every field we need on the LISTING pages themselves — title, date
range, venue and city are all printed in plain divs on the card, no JS
render required. There are TWO relevant listing pages, both server-rendered
the same way:

    https://www.asgbi.org.uk/event-type/asgbi-congress   — flagship Congress
    https://www.asgbi.org.uk/event-type/egs-symposium     — EGS Symposium
        (Emergency General Surgery), a real one-day event series with its
        own dated cards — recon only checked the Congress page, but this
        sibling listing carries genuine upcoming events too, so both are
        scraped here.

Each page's real content lives in `.grid-of-2 .w-dyn-item .event-wrapper`
cards (there are also several unused/duplicate Webflow CMS-collection
templates on the page marked `w-condition-invisible` — e.g. `.event-list-of-6`
tables and a `._4-seasons-series` block — which must be ignored; only the
`.grid-of-2` card list is the one Webflow actually renders):

    <h2 class="name-2">ASGBI International Surgical Congress 2027</h2>
    ...<div class="details-text first-date">21 May 2027</div>
       <div class="details-text second-date">23 May 2027</div>
    ...<div class="flex-down">
         <div class="details-text">Manchester Central</div>   <- venue
         <div class="details-text">Manchester </div>          <- city
       </div>
    ...<div class="button-wrapper-2">
         <a href="https://events.asgbi.org.uk/asgbievents/modules/263011/html"
            target="_blank" class="button-6 rb w-button">Learn More</a>
       </div>

The venue/city pair is reliably [venue, city] in that order — confirmed on
both listings (Congress: "Manchester Central"/"Manchester", "ICC Wales"/
"Newport"; EGS: "Royal College of Surgeons of England"/"London", "tbc"/
"Leeds"). "tbc" (any case) means venue not yet announced -> venue_name=None.

Registration links go to `events.asgbi.org.uk`, an Angular SPA event portal
(noindex, empty-body, JS-required per recon) — there is nothing further to
scrape there, so we don't rely on `extract_detail`'s `page` navigation at
all: every field is captured up-front in `list_shells_override()` and
`extract_detail()` just reads it back off the shell dict. Some future
editions publish a `Learn More` button that is itself Webflow-hidden
(`w-condition-invisible`, e.g. the 2028 Congress at time of writing) because
that year's registration page doesn't exist yet — the href in that case
falls back to the generic `events.asgbi.org.uk` homepage. We keep the event
(hard rule: "cope with editions where registration isn't live yet") and use
whatever href Webflow prints, since it's still a legitimate outbound link
for the user.

The page also carries one static "About the ASGBI International Surgical
Congress" / "About the ASGBI Emergency General Surgery Symposium" rich-text
block (same text for every year of that event type) which we reuse as the
soft-field source text for description/specialty — it's genuine
organiser-written copy, not fabricated, just not per-edition.
"""

from __future__ import annotations

import re
import html as html_lib
from datetime import date, datetime
from typing import Dict, Any, Optional, Callable, List

from .base import BaseExtractor
from .http_fetch import fetch_html
from .specialty_classifier import classify_specialty
from logger import logger


CONGRESS_URL = "https://www.asgbi.org.uk/event-type/asgbi-congress"
EGS_URL = "https://www.asgbi.org.uk/event-type/egs-symposium"

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_UK_REGIONS = {
    "manchester": "North West England",
    "newport": "Wales",
    "cardiff": "Wales",
    "london": "London",
    "leeds": "Yorkshire and the Humber",
    "birmingham": "West Midlands",
    "edinburgh": "Scotland",
    "glasgow": "Scotland",
    "bristol": "South West England",
    "liverpool": "North West England",
}

CARD_MARKER = 'role="listitem" class="w-dyn-item"'
GRID_START = "grid-of-2 w-dyn-items"
GRID_END = 'class="_60pc"'


def _parse_date(text: str) -> Optional[date]:
    text = (text or "").strip()
    m = re.match(r"(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})", text)
    if not m:
        return None
    day, mon_text, year = m.groups()
    mon = _MONTHS.get(mon_text.lower()[:3])
    if not mon:
        return None
    try:
        return date(int(year), mon, int(day))
    except ValueError:
        return None


def _infer_region(city: Optional[str]) -> Optional[str]:
    if not city:
        return None
    c = city.lower()
    for key, region in _UK_REGIONS.items():
        if key in c:
            return region
    return None


def _extract_about_text(html: str, heading_prefix: str) -> str:
    """Pull the static 'About the ASGBI ...' rich-text block used as the
    soft-field source text for every edition of that event type."""
    m = re.search(
        rf'<h3>{re.escape(heading_prefix)}.*?</h3>(.*?)<h3>Industry</h3>',
        html, re.S,
    )
    if not m:
        return ""
    chunk = m.group(1)
    text = re.sub(r"<[^>]+>", " ", chunk)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()[:3000]


def _parse_listing(html: str, event_type_label: str) -> List[Dict[str, Any]]:
    """Extract event cards from a single ASGBI event-type listing page."""
    shells: List[Dict[str, Any]] = []

    start = html.find(GRID_START)
    end = html.find(GRID_END, start if start >= 0 else 0)
    if start < 0 or end < 0 or end <= start:
        logger.warning(f"ASGBI: couldn't locate grid-of-2 block for {event_type_label}")
        return shells
    grid_html = html[start:end]

    chunks = grid_html.split(CARD_MARKER)[1:]  # drop text before first card
    today = date.today()

    for chunk in chunks:
        title_m = re.search(r'<h2 class="name-2">([^<]+)</h2>', chunk)
        if not title_m:
            continue
        title = html_lib.unescape(title_m.group(1)).strip()

        first_m = re.search(r'class="details-text first-date">([^<]+)<', chunk)
        second_m = re.search(r'class="details-text second-date">([^<]+)<', chunk)
        start_date = _parse_date(first_m.group(1)) if first_m else None
        end_date = _parse_date(second_m.group(1)) if second_m else None

        if not start_date:
            logger.warning(f"ASGBI: no parseable date for '{title}', skipping")
            continue
        if start_date < today:
            continue  # past event

        loc_matches = re.findall(r'<div class="details-text">([^<]*)</div>', chunk)
        venue_raw = (loc_matches[0].strip() if len(loc_matches) > 0 else "") or None
        city_raw = (loc_matches[1].strip() if len(loc_matches) > 1 else "") or None
        if venue_raw and venue_raw.lower() in ("tbc", "tba"):
            venue_raw = None
        if city_raw and city_raw.lower() in ("tbc", "tba"):
            city_raw = None

        href_m = re.search(r'<a href="([^"]+)" target="_blank" class="button-6([^"]*)"', chunk)
        booking_url = href_m.group(1) if href_m else None
        registration_live = bool(href_m) and "w-condition-invisible" not in href_m.group(2)

        # booking_url is the scraper's dedupe key (conferences.source_url).
        # ASGBI points several editions at ONE portal module (EGS 2026 and
        # 2027 both → modules/175324) and unreleased ones at the homepage,
        # so key each edition with a #fragment — harmless for navigation.
        if booking_url:
            edition = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            if str(start_date.year) not in edition:
                edition = f"{edition}-{start_date.year}"
            booking_url = f"{booking_url.split('#')[0]}#{edition}"
        shells.append({
            "title": title,
            "booking_url": booking_url,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat() if end_date else start_date.isoformat(),
            "venue_name": venue_raw,
            "city": city_raw,
            "region": _infer_region(city_raw),
            "event_format": "in_person",
            "category": event_type_label,
            "is_sold_out": False,
            "registration_live": registration_live,
        })

    return shells


class ASGBIExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing phase — both event-type pages are static server-rendered
    # HTML; nothing here needs a browser, so fetch_html's httpx path
    # covers it (falls back to the shared browser only if bot-blocked).
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        browser = getattr(self, "browser", None)
        shells: List[Dict[str, Any]] = []

        congress_html = fetch_html(CONGRESS_URL, browser=browser)
        if congress_html:
            congress_shells = _parse_listing(congress_html, "conference")
            about = _extract_about_text(congress_html, "About the ASGBI International Surgical Congress")
            for s in congress_shells:
                s["_about_text"] = about
            shells.extend(congress_shells)
        else:
            logger.warning("ASGBI: congress listing fetch failed")

        egs_html = fetch_html(EGS_URL, browser=browser)
        if egs_html:
            egs_shells = _parse_listing(egs_html, "conference")
            about = _extract_about_text(egs_html, "About the ASGBI Emergency General Surgery Symposium")
            for s in egs_shells:
                s["_about_text"] = about
            shells.extend(egs_shells)
        else:
            logger.warning("ASGBI: EGS symposium listing fetch failed")

        logger.info(f"ASGBI: {len(shells)} upcoming shells across both listings")
        return shells  # may be [] — the caller copes with zero shells fine

    # ------------------------------------------------------------------ #
    # Detail phase — nothing further to scrape. Registration links go to
    # an Angular SPA event portal (noindex, empty-body, JS-required) with
    # no additional structured data, so every field was already captured
    # in the listing pass; just pass it through.
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        about_text = shell.get("_about_text") or ""

        result: Dict[str, Any] = {
            "conference_name": shell.get("title"),
            "start_date": shell.get("start_date"),
            "end_date": shell.get("end_date"),
            "venue_name": shell.get("venue_name"),
            "city": shell.get("city"),
            "region": shell.get("region"),
            "event_format": shell.get("event_format"),
            "event_type": "conference",
            "cpd_points": None,
            "cpd_accredited": False,
            "abstract_open": False,
            "abstract_deadline": None,
            "pricing_tiers": [],
        }

        # Registration not yet live for this edition — still a real,
        # dated event, just no working booking link beyond the portal
        # homepage. Leave organiser_url pointing at the ASGBI site itself
        # so the card always has SOME working outbound link.
        if not shell.get("registration_live"):
            result["organiser_url"] = "https://www.asgbi.org.uk"

        result.update(self._extract_soft_fields(shell.get("title"), about_text, llm_call))
        return result

    # ------------------------------------------------------------------ #
    # Description + specialty — LLM summary of the static "About" copy,
    # with a deterministic fallback for when the LLM call fails.
    # ------------------------------------------------------------------ #
    def _extract_soft_fields(
        self,
        title: Optional[str],
        about_text: str,
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        if about_text:
            prompt = f"""You are summarising a medical conference series' "About" copy. Extract ONLY two fields.

EVENT TITLE: {title}

ABOUT TEXT:
{about_text}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the text above" or null,
  "specialty": "primary clinical/topic area (e.g. General Surgery, Emergency General Surgery)" or null
}}"""
            raw = llm_call(prompt)
            if raw:
                raw = raw.strip()
                if raw.startswith("```"):
                    parts = raw.split("```")
                    if len(parts) >= 3:
                        raw = parts[1]
                        if raw.startswith("json"):
                            raw = raw[4:]
                        raw = raw.strip()
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    raw = m.group(0)
                try:
                    import json
                    parsed = json.loads(raw)
                    result["description"] = parsed.get("description")
                    result["specialty"] = parsed.get("specialty")
                except Exception as e:
                    logger.warning(f"ASGBI soft-fields JSON parse failed: {e}; raw[:200]={raw[:200]!r}")

        if not result.get("specialty"):
            result["specialty"] = classify_specialty(title, about_text) or "Surgery (General)"

        if not result.get("description") and about_text:
            sentences = re.split(r"(?<=[.!?])\s+", about_text)
            snippet = " ".join(sentences[:2]).strip()
            if len(snippet) > 40:
                result["description"] = snippet[:320]

        return result
