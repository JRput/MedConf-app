# extractors/rcem.py
"""
Royal College of Emergency Medicine (RCEM) extractor.

One module covers three RCEM sources because they all share the same
WordPress/Elementor markup conventions:

  - source 6: events-calendar (live upcoming events; face-to-face + virtual)
  - source 7: on-demand catch-up (recorded past events users can register to
              watch until an access deadline — sets is_on_demand=True)
  - source 8: Annual Conference 2027 (a single multi-page subsite)

What's the same across all three:
  - <h1> is the event title.
  - The first one or two <strong> elements at the top of the article carry the
    key headline info using " | " as a separator, e.g.
      "Friday 19 June 2026 | Centre For Learning Anatomical Sciences, Southampton"
      "Face-to-face event | RCEM accredited for 7-CPD points"
    For on-demand it becomes "Available until 24 June 2026 | RCEM accredited..."
  - Pricing lives in a single <table> with 2-column rows (label, £price).
  - Booking links target surveymonkey.com or www.rcem-events.uk.

What differs:
  - Path /face-to-face-events/* → in-person; /virtual-events/* → online.
  - Path /on-demand/* → online + is_on_demand=True; start_date is the
    "Available until" deadline, on_demand_original_date is the live session date.
  - The annual conference uses a sub-tree of pages (/annual-conference-2027/,
    /annual-conference-2027/registration-and-fees/, …) and is treated as a
    single shell whose detail extraction harvests across the sub-pages.
"""

import json
import re
from datetime import datetime
from typing import Dict, Any, Optional, Callable, List, Tuple

from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from .abstract_classifier import extract_abstract_info
from logger import logger


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

# DD/MM/YYYY format on listings, "19 June 2026" on detail headers.
_DDMMYYYY_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_TEXTUAL_DATE_RE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b")
_TEXTUAL_RANGE_RE = re.compile(
    r"\b(\d{1,2})(?:\s+[A-Za-z]+)?\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b"
)
_CPD_RE = re.compile(r"(\d+)\s*[-–]?\s*CPD\s*points?", re.I)


class RCEMExtractor(BaseExtractor):

    # Constants distinguishing the three RCEM sources by their integer id in
    # scraper_sources. Bound at runtime in __init__ via self.source_id.
    EVENTS_CALENDAR_ID = 6
    ON_DEMAND_ID = 7
    ANNUAL_CONFERENCE_ID = 8

    # The annual-conference subsite is treated as ONE event whose detail page
    # concatenates these sibling slugs to recover registration / abstracts /
    # programme info.
    ANNUAL_CONFERENCE_SUBPAGES = [
        "",                              # the homepage itself
        "registration-and-fees/",
        "call-for-talks/",
        "key-themes/",
    ]

    # ------------------------------------------------------------------ #
    # Listing override — anchor harvest beats Elementor card walking
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        """Return the shell list for whichever RCEM source this is.

        The RCEM site uses Elementor loop-grids that don't expose clean card
        elements to the standard DOM walker, but the detail-page anchors are
        rendered server-side. We grab the listing HTML over plain HTTP and
        regex out URLs matching the expected slug pattern — no headless
        browser needed at the listing step. The annual conference is a
        special-case singleton with one shell.
        """
        import httpx

        if self.source_id == self.ANNUAL_CONFERENCE_ID:
            return [{
                "title": "Annual Conference 2027",
                "booking_url": "https://rcem.ac.uk/annual-conference-2027/",
                "category": "conference",
            }]

        listing_url = self.source["base_url"]
        if self.source_id == self.EVENTS_CALENDAR_ID:
            link_re = re.compile(
                r'href="(https://rcem\.ac\.uk/(?:face-to-face-events|virtual-events)/[a-z0-9-]+/)"'
            )
        elif self.source_id == self.ON_DEMAND_ID:
            link_re = re.compile(r'href="(https://rcem\.ac\.uk/on-demand/[a-z0-9-]+/)"')
        else:
            return None

        try:
            with httpx.Client(timeout=30.0, follow_redirects=True,
                              headers={"User-Agent": "Mozilla/5.0 (MedConf scraper)"}) as client:
                resp = client.get(listing_url)
                resp.raise_for_status()
                html = resp.text
        except Exception as e:
            logger.warning(f"RCEM source {self.source_id}: listing fetch failed: {e}")
            return None

        seen: set = set()
        shells: List[Dict[str, Any]] = []
        for m in link_re.finditer(html):
            href = m.group(1)
            # Skip the catch-up index page itself if it ever matches
            if href.rstrip("/").endswith("catch-up-with-on-demand-events"):
                continue
            if href in seen:
                continue
            seen.add(href)
            slug = href.rstrip("/").rsplit("/", 1)[-1]
            title = slug.replace("-", " ").strip().title()
            category = "workshop" if self.source_id == self.ON_DEMAND_ID else None
            shells.append({
                "title": title,
                "booking_url": href,
                "category": category,
            })
        logger.info(f"RCEM source {self.source_id}: harvested {len(shells)} listing shells")
        return shells

    # ------------------------------------------------------------------ #
    # Detail extraction
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        if self.source_id == self.ANNUAL_CONFERENCE_ID:
            return self._extract_annual_conference(page, shell, llm_call)

        is_on_demand = self.source_id == self.ON_DEMAND_ID

        # Title — H1 wins over the listing-anchor text which can be a button label
        h1 = (page.evaluate("() => (document.querySelector('h1')||{}).textContent || ''") or "").strip()
        result: Dict[str, Any] = {}
        if h1:
            result["conference_name"] = h1

        # Concatenate the first 2 headline strongs and split into pipe-pieces.
        # RCEM detail pages publish key info ("date | venue | format | cpd")
        # split inconsistently across one or two <strong> elements. Treating
        # them as a single pipe-separated list and classifying each piece
        # robustly handles every layout we've seen.
        headline = self._collect_headline_strongs(page)
        joined = " | ".join(headline[:2]) if headline else ""
        pieces = [p.strip() for p in joined.split("|") if p.strip()]
        classified = self._classify_headline_pieces(pieces)
        line1 = headline[0] if headline else ""
        line2 = headline[1] if len(headline) > 1 else ""

        # ---- Dates --------------------------------------------------------
        start_date, end_date, original_date = self._extract_dates(
            classified.get("date_piece") or line1, line2, page, is_on_demand
        )
        if start_date:
            result["start_date"] = start_date
        if end_date:
            result["end_date"] = end_date
        if is_on_demand:
            result["is_on_demand"] = True
            if original_date:
                result["on_demand_original_date"] = original_date

        # ---- Venue / format -----------------------------------------------
        venue_info = self._venue_and_format_from_classified(
            classified, shell.get("booking_url") or ""
        )
        result.update(venue_info)

        # On-demand events are always recordings → online format
        if is_on_demand:
            result["event_format"] = "online"
            result["venue_name"] = None
            result["city"] = None
            result["region"] = None

        # ---- CPD -----------------------------------------------------------
        cpd_points, cpd_accredited = self._extract_cpd(
            classified.get("cpd_piece") or (line1 + " " + line2), page
        )
        result["cpd_points"] = cpd_points
        result["cpd_accredited"] = cpd_accredited

        # ---- Pricing -------------------------------------------------------
        result["pricing_tiers"] = self._extract_pricing(page)

        # ---- Booking URL ---------------------------------------------------
        booking = self._extract_booking_url(page)
        if booking:
            result["booking_url"] = booking
        result["organiser_url"] = shell.get("booking_url")  # the rcem.ac.uk page

        # ---- Event type ----------------------------------------------------
        # On-demand → workshop unless the title screams "conference" / "boxset"
        # (the Annual Conference 2026 Boxset is genuinely a conference recording)
        if is_on_demand:
            title_l = (h1 or shell.get("title") or "").lower()
            if re.search(r"\b(annual conference|congress|symposium|boxset|conference)\b", title_l):
                result["event_type"] = "conference"
            else:
                result["event_type"] = "workshop"
        # Otherwise leave event_type unset — the merge layer's title heuristic
        # handles it, so a "Cadaver airway course" becomes course automatically.

        # ---- Abstracts (only relevant for live events) ---------------------
        if not is_on_demand:
            page_text = page.evaluate("() => document.body.textContent || ''")
            is_open, deadline = extract_abstract_info(page_text)
            result["abstract_open"] = is_open
            result["abstract_deadline"] = deadline.isoformat() if deadline else None

        # ---- Description + specialty (LLM + heuristic fallback) ------------
        result.update(self._extract_soft_fields(page, shell, llm_call))

        return result

    # ------------------------------------------------------------------ #
    # Annual Conference 2027 — multi-page subsite extraction
    # ------------------------------------------------------------------ #
    def _extract_annual_conference(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        # Walk the known sub-pages, concatenating their text.
        from browser import BrowserController  # late import
        base = "https://rcem.ac.uk/annual-conference-2027/"
        combined_text_parts: List[str] = []
        pricing_tiers: List[Dict[str, Any]] = []
        early_bird_deadlines: List[str] = []

        for sub in self.ANNUAL_CONFERENCE_SUBPAGES:
            url = base + sub
            try:
                if sub:
                    page.goto(url, timeout=15000, wait_until="domcontentloaded")
                    page.wait_for_timeout(1200)
                # Strip nav/header/footer so the LLM and the description
                # fallback see only the article body — otherwise the
                # WordPress nav strings leak into the description.
                body = page.evaluate(r"""() => {
                    const main = document.querySelector('article, main, .elementor-location-single, .entry-content') || document.body;
                    const clone = main.cloneNode(true);
                    clone.querySelectorAll('nav, footer, script, style, noscript, header, .menu, .elementor-nav-menu, .elementor-icon-list-items').forEach(n => n.remove());
                    return (clone.textContent || '').replace(/\s+/g, ' ').trim();
                }""") or ""
                combined_text_parts.append(body)
                # Harvest any tables of pricing on this page
                pricing_tiers.extend(self._extract_pricing(page))
                # Look for early bird deadlines mentioned in this page
                ebd = self._find_early_bird_deadlines(body)
                early_bird_deadlines.extend(ebd)
            except Exception as e:
                logger.warning(f"RCEM annual conf sub-page {url} failed: {e}")

        combined_text = "\n\n".join(combined_text_parts)

        # Dedupe pricing
        seen = set()
        pricing: List[Dict[str, Any]] = []
        for t in pricing_tiers:
            key = (t["tier_label"], t["price_gbp"])
            if key in seen:
                continue
            seen.add(key)
            pricing.append(t)

        # Annual Conference 2027 publishes its full registration rates only
        # in a downloadable PDF, so we encode them here verbatim. Source:
        # RCEM-Annual-Conference-Registration-Rates-2027.pdf (provided
        # 2026-06-14). Three time-banded tiers, plus abstract presenter +
        # LMIC rates that don't expire.
        result: Dict[str, Any] = {
            "conference_name": "RCEM Annual Conference 2027",
            "start_date": "2027-04-13",
            "end_date": "2027-04-15",
            "venue_name": "Manchester Central",
            "city": "Manchester",
            "region": "North West England",
            "event_format": "hybrid",
            "event_type": "conference",
            "is_flagship": True,
            "cpd_accredited": True,
            "cpd_points": self._first_int_or_none(_CPD_RE.search(combined_text)),
            "booking_url": "https://www.rcem-events.uk/rcem/438/register?externalLogin=1",
            "organiser_url": "https://rcem.ac.uk/annual-conference-2027/",
            "pricing_tiers": self._annual_conference_2027_pricing(),
            # RCEM accepts abstracts via a SurveyMonkey form with no
            # published deadline. The "open with no date" case is driven
            # by abstract_deadline_note (curator-set), not by guessing the
            # open flag here — we leave it false so the heuristic doesn't
            # produce stale UI if the note is ever cleared.
            "abstract_open": True,
            "abstract_deadline": None,
            "abstract_deadline_note": "see event page for details",
        }

        # LLM-driven soft fields
        result.update(self._extract_soft_fields(page, {"title": result["conference_name"]}, llm_call,
                                                pre_text=combined_text[:5000]))
        # The RCEM Annual Conference is an Emergency Medicine event by
        # definition, regardless of how the LLM/heuristic classify it.
        result["specialty"] = "Emergency Medicine"
        return result

    # ------------------------------------------------------------------ #
    # Helpers — DOM probes
    # ------------------------------------------------------------------ #
    def _collect_headline_strongs(self, page: Page) -> List[str]:
        """Return the first few <strong> elements as cleaned single-line strings.

        RCEM detail pages put the date/venue/format/CPD into the first 1-2
        <strong> elements at the top of the article. We collect the first six
        and let the date/venue/format/CPD parsers pick what they recognise.
        """
        try:
            return page.evaluate(r"""() => {
                return [...document.querySelectorAll('article strong, .elementor-widget-container strong, .entry-content strong')]
                    .map(e => (e.textContent || '').replace(/\s+/g, ' ').trim())
                    .filter(t => t.length > 5)
                    .slice(0, 6);
            }""") or []
        except Exception as e:
            logger.warning(f"RCEM headline strongs failed: {e}")
            return []

    def _extract_dates(
        self,
        line1: str,
        line2: str,
        page: Page,
        is_on_demand: bool,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Returns (start_date_iso, end_date_iso, original_date_iso).

        For live events the start/end are from line1's "Friday 19 June 2026 | …"
        prefix. For on-demand the line is "Available until 24 June 2026 | …"
        so start_date = the deadline. original_date comes from the listing-page
        DD/MM/YYYY display when we can recover it (we don't yet — that gets
        wired through the shell from get_event_cards_paginated when the source
        has a structured card; for now we just leave original_date None and
        let the description carry it).
        """
        combined = line1 + " " + line2

        # Range "29 June - 2 July 2026" or "4 - 5 June 2026"
        m = _TEXTUAL_RANGE_RE.search(combined)
        if m:
            d1, d2, month, year = m.group(1), m.group(2), m.group(3), m.group(4)
            # Cross-month form: "29 June - 2 July 2026" — _TEXTUAL_RANGE_RE
            # only matches the trailing month, so we need a cross-month re-check
            cross = re.search(
                r"\b(\d{1,2})\s+([A-Za-z]+)\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b",
                combined,
            )
            if cross:
                d1, mon1, d2, mon2, year = cross.group(1), cross.group(2), cross.group(3), cross.group(4), cross.group(5)
                start = self._iso(year, mon1, d1)
                end = self._iso(year, mon2, d2)
                return start, end, None
            start = self._iso(year, month, d1)
            end = self._iso(year, month, d2)
            return start, end, None

        # Single textual date "19 June 2026" (also handles "Available until 24 June 2026")
        m = _TEXTUAL_DATE_RE.search(combined)
        if m:
            iso = self._iso(m.group(3), m.group(2), m.group(1))
            return iso, None, None

        # Year-less form "Thursday 9 July" — assume current year, but roll to
        # next year if that date is already in the past.
        m = re.search(r"\b(\d{1,2})\s+([A-Za-z]+)\b", combined)
        if m:
            from datetime import date
            today = date.today()
            iso = self._iso(str(today.year), m.group(2), m.group(1))
            if iso and iso < today.isoformat():
                iso = self._iso(str(today.year + 1), m.group(2), m.group(1))
            if iso:
                return iso, None, None

        # Fall back to body text
        try:
            body = page.evaluate("() => document.body.innerText || ''")
        except Exception:
            body = ""
        m = _TEXTUAL_DATE_RE.search(body)
        if m:
            iso = self._iso(m.group(3), m.group(2), m.group(1))
            return iso, None, None

        return None, None, None

    # ------------------------------------------------------------------ #
    # Classify pipe-separated headline pieces into date/format/venue/cpd
    # ------------------------------------------------------------------ #
    _UK_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)

    def _classify_headline_pieces(self, pieces: List[str]) -> Dict[str, Optional[str]]:
        """Each piece is one of: date, format ("Face-to-face event" etc),
        CPD ("RCEM accredited for N-CPD points"), or venue (a comma-separated
        address). Multiple venue pieces are joined together."""
        out: Dict[str, Optional[str]] = {
            "date_piece": None,
            "format_piece": None,
            "cpd_piece": None,
            "venue_piece": None,
        }
        venue_parts: List[str] = []
        for p in pieces:
            pl = p.lower()
            # Format keywords
            if re.match(r"^(face[- ]to[- ]face|virtual|online|hybrid|webinar)\b", pl):
                if not out["format_piece"]:
                    out["format_piece"] = p
                continue
            # CPD
            if "cpd" in pl and ("accredited" in pl or "points" in pl):
                if not out["cpd_piece"]:
                    out["cpd_piece"] = p
                continue
            # Date — has a month name or DD/MM/YYYY pattern. "Available until X"
            # also lands here for on-demand pages.
            if (
                _TEXTUAL_DATE_RE.search(p)
                or _TEXTUAL_RANGE_RE.search(p)
                or _DDMMYYYY_RE.search(p)
                or re.match(r"^(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", pl)
                or "available until" in pl
            ):
                if not out["date_piece"]:
                    out["date_piece"] = p
                    continue
            # Anything else is venue/address content
            venue_parts.append(p)
        if venue_parts:
            out["venue_piece"] = ", ".join(venue_parts)
        return out

    def _venue_and_format_from_classified(
        self, classified: Dict[str, Optional[str]], shell_url: str,
    ) -> Dict[str, Any]:
        out: Dict[str, Any] = {}

        # ---- Format -------------------------------------------------------
        fmt_piece = (classified.get("format_piece") or "").lower()
        if "virtual" in fmt_piece or "online" in fmt_piece or "webinar" in fmt_piece:
            out["event_format"] = "online"
        elif "face-to-face" in fmt_piece or "face to face" in fmt_piece or "in person" in fmt_piece:
            out["event_format"] = "in_person"
        elif "hybrid" in fmt_piece:
            out["event_format"] = "hybrid"
        # URL-path fallback (most reliable for live events): if the source
        # URL begins with /virtual-events/, the event is online.
        if "event_format" not in out and shell_url:
            if "/virtual-events/" in shell_url:
                out["event_format"] = "online"
            elif "/face-to-face-events/" in shell_url:
                out["event_format"] = "in_person"

        # Online events get no venue/city even if the page coincidentally has one
        if out.get("event_format") == "online":
            out["venue_name"] = None
            out["city"] = None
            out["region"] = None
            return out

        # ---- Venue / city / region ---------------------------------------
        venue_text = (classified.get("venue_piece") or "").strip()
        if not venue_text:
            return out

        # Strip "View directions to the venue." and similar trailing junk
        venue_text = re.sub(r"\.\s*View directions[^.]*\.?", "", venue_text, flags=re.I).strip(" ,.")

        # Remove postcode but remember it
        postcode = None
        m = self._UK_POSTCODE_RE.search(venue_text)
        if m:
            postcode = m.group(1)
            venue_text = self._UK_POSTCODE_RE.sub("", venue_text).strip(" ,.")

        # Look for a known UK city anywhere in the venue text
        city = None
        region = None
        for key, val in self._UK_REGIONS.items():
            if re.search(rf"\b{re.escape(key)}\b", venue_text, re.I):
                city = key.title()
                region = val
                break

        if not city and postcode:
            # Postcode area → coarse region inference; leave city null rather
            # than misreport "SE1 1EU" as a city.
            region = region or self._region_from_postcode(postcode)

        # Venue name = everything before the city token (if a known city
        # was found), else the full cleaned string. Cap to 200 chars.
        venue_name = venue_text
        if city:
            cut = re.split(rf"\b{re.escape(city)}\b", venue_text, flags=re.I)[0].strip(" ,.")
            venue_name = cut or venue_text
        out["venue_name"] = venue_name[:200] if venue_name else None
        out["city"] = city
        out["region"] = region or self._infer_uk_region(city)
        return out

    @staticmethod
    def _region_from_postcode(postcode: str) -> Optional[str]:
        area = re.match(r"^([A-Z]{1,2})", postcode.upper())
        if not area:
            return None
        prefix = area.group(1)
        # Crude lookup — only the prefixes the RCEM-listed venues use
        return {
            "SE": "London", "SW": "London", "NW": "London", "N": "London",
            "E": "London", "W": "London", "WC": "London", "EC": "London",
            "SO": "South East England",
            "M": "North West England", "L": "North West England",
            "B": "West Midlands",
            "LS": "Yorkshire and the Humber",
        }.get(prefix)

    def _extract_venue_and_format(self, line1: str, line2: str, page: Page) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        # Format from the SECOND <strong> like "Face-to-face event | RCEM …"
        l2_l = line2.lower()
        if "virtual" in l2_l or "online" in l2_l or "webinar" in l2_l:
            out["event_format"] = "online"
            return out
        if "face-to-face" in l2_l or "in person" in l2_l:
            out["event_format"] = "in_person"
        elif "hybrid" in l2_l:
            out["event_format"] = "hybrid"

        # Venue from line1: "Friday 19 June 2026 | <venue text>"
        if "|" in line1:
            after = line1.split("|", 1)[1].strip()
            if after:
                # Split off city from the end — naive: last comma-token
                bits = [b.strip() for b in re.split(r"[,]", after) if b.strip()]
                if bits:
                    if len(bits) >= 2:
                        venue = ", ".join(bits[:-1])[:200]
                        city = bits[-1][:80]
                    else:
                        venue = bits[0][:200]
                        city = None
                    out["venue_name"] = venue
                    if city:
                        out["city"] = city
                        out["region"] = self._infer_uk_region(city)

        # Format fallback from URL/path is set by the merge layer (the shell's
        # booking_url path already encodes face-to-face vs virtual).
        if "event_format" not in out:
            # Default to in_person when we got a venue, else leave unset
            if out.get("venue_name"):
                out["event_format"] = "in_person"
        return out

    _UK_REGIONS = {
        "london": "London",
        "manchester": "North West England",
        "liverpool": "North West England",
        "leeds": "Yorkshire and the Humber",
        "sheffield": "Yorkshire and the Humber",
        "york": "Yorkshire and the Humber",
        "newcastle": "North East England",
        "birmingham": "West Midlands",
        "bristol": "South West England",
        "exeter": "South West England",
        "plymouth": "South West England",
        "southampton": "South East England",
        "brighton": "South East England",
        "oxford": "South East England",
        "cardiff": "Wales",
        "swansea": "Wales",
        "edinburgh": "Scotland",
        "glasgow": "Scotland",
        "belfast": "Northern Ireland",
        "cambridge": "East of England",
        "norwich": "East of England",
        "leicester": "East Midlands",
        "nottingham": "East Midlands",
    }

    def _infer_uk_region(self, city: Optional[str]) -> Optional[str]:
        if not city:
            return None
        cl = city.lower()
        for key, val in self._UK_REGIONS.items():
            if key in cl:
                return val
        return None

    def _extract_cpd(self, headline_text: str, page: Page) -> Tuple[Optional[int], bool]:
        m = _CPD_RE.search(headline_text)
        if m:
            return int(m.group(1)), True
        try:
            body = page.evaluate("() => document.body.innerText || ''")
        except Exception:
            body = ""
        m = _CPD_RE.search(body)
        if m:
            return int(m.group(1)), True
        if re.search(r"\bCPD[ -]?accredited\b|\bRCEM accredited\b", body, re.I):
            return None, True
        return None, False

    def _extract_pricing(self, page: Page) -> List[Dict[str, Any]]:
        """Parse pricing from the first table on the page.

        RCEM detail pages render a single table where each row has a label
        cell and a £-price cell. The label often contains "Member" / "Non-member"
        / "student / retired" qualifiers.
        """
        try:
            rows = page.evaluate(r"""() => {
                const out = [];
                document.querySelectorAll('table tr').forEach(tr => {
                    const cells = [...tr.querySelectorAll('td, th')]
                        .map(c => (c.textContent || '').replace(/\s+/g, ' ').trim())
                        .filter(t => t.length > 0);
                    if (cells.length >= 2) out.push(cells);
                });
                return out;
            }""") or []
        except Exception as e:
            logger.warning(f"RCEM pricing extraction failed: {e}")
            return []

        tiers: List[Dict[str, Any]] = []
        for cells in rows:
            # Find the cell containing £ and the cell(s) that don't
            price_cell = None
            label_parts = []
            for c in cells:
                if "£" in c and price_cell is None:
                    price_cell = c
                else:
                    label_parts.append(c)
            if not price_cell:
                continue
            price = self.parse_gbp(price_cell)
            if price is None:
                continue
            label = " ".join(label_parts).strip()[:120] or "Standard"
            tiers.append({
                "tier_label": label,
                "price_gbp": price,
                "is_early_bird": "early" in label.lower(),
                "early_bird_deadline": None,
            })
        return tiers

    def _extract_booking_url(self, page: Page) -> Optional[str]:
        """RCEM uses surveymonkey forms and rcem-events.uk for live registration."""
        try:
            href = page.evaluate(r"""() => {
                const a = document.querySelector(
                    'a[href*="surveymonkey.com"], a[href*="rcem-events.uk"], a[href*="zoom.us"]'
                );
                return a ? a.href : null;
            }""")
            return href
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Annual Conference 2027 pricing — full PDF tier list, encoded here
    # because the rates aren't published on any HTML page we can scrape.
    # Source: RCEM-Annual-Conference-Registration-Rates-2027.pdf (2026-06-14).
    # Re-emitted on every scrape so the delete-and-reinsert pricing flow
    # in scraper.py doesn't wipe them.
    # ------------------------------------------------------------------ #
    _AC2027_GRADES = [
        ("Associate specialist / consultant",
            # super EB F2F member, super EB F2F non-member, super EB virtual member, super EB virtual non-member
            #   each as [1d, 2d, 3d]
            [300, 495, 705], [550, 745, 955], [256, 420, 600], [506, 670, 850],
            # EB F2F member, F2F non-member, virtual member, virtual non-member
            [340, 560, 790], [590, 810, 1040], [288, 473, 675], [538, 723, 925],
            # standard F2F member, F2F non-member, virtual member, virtual non-member
            [375, 620, 880], [625, 870, 1130], [320, 525, 750], [570, 775, 1000]),
        ("Trainee / SAS doctor / ACP / nurse / AHP",
            [270, 450, 630], [520, 700, 880], [232, 380, 536], [482, 630, 786],
            [305, 505, 710], [555, 755, 960], [261, 428, 603], [511, 678, 853],
            [340, 560, 790], [590, 810, 1040], [290, 475, 670], [540, 725, 920]),
        ("Student / foundation doctor / retired",
            [90, 150, 210], [340, 400, 460], [80, 124, 180], [330, 374, 430],
            [105, 165, 240], [355, 415, 490], [90, 140, 203], [340, 390, 453],
            [115, 185, 264], [365, 435, 514], [100, 155, 225], [350, 405, 475]),
    ]

    def _annual_conference_2027_pricing(self) -> List[Dict[str, Any]]:
        tiers: List[Dict[str, Any]] = []
        SUPER_EB_DL = "2026-09-30"
        EB_DL = "2027-01-04"

        def add_band(band_label: str, prices_by_section, early: bool, deadline: Optional[str]):
            # prices_by_section is 4 lists: [F2F member, F2F non, virtual member, virtual non]
            f2f_mem, f2f_non, virt_mem, virt_non = prices_by_section
            for fmt_label, mem_prices, non_prices in (
                ("Face-to-face", f2f_mem, f2f_non),
                ("Virtual", virt_mem, virt_non),
            ):
                for status, prices in (("Member", mem_prices), ("Non-member", non_prices)):
                    for n_days, price in enumerate(prices, start=1):
                        suffix = f"{n_days} day" if n_days == 1 else f"{n_days} days"
                        tiers.append({
                            "tier_label": f"{band_label} · {fmt_label} · {status} · {{grade}} · {suffix}",
                            "price_gbp": float(price),
                            "is_early_bird": early,
                            "early_bird_deadline": deadline,
                        })

        for grade in self._AC2027_GRADES:
            grade_label = grade[0]
            super_prices = grade[1:5]   # F2F mem, F2F non, virt mem, virt non
            eb_prices = grade[5:9]
            std_prices = grade[9:13]

            before = len(tiers)
            add_band("Super early bird", super_prices, True, SUPER_EB_DL)
            add_band("Early bird", eb_prices, True, EB_DL)
            add_band("Standard (from 5 Jan 2027)", std_prices, False, None)
            # Replace {grade} placeholder for the tiers we just added
            for t in tiers[before:]:
                t["tier_label"] = t["tier_label"].replace("{grade}", grade_label)

        # Abstract presenter — F2F only, matches Super EB F2F rates per PDF.
        # No expiry: applies once an abstract is accepted.
        abstract_grades = [
            ("Associate specialist / consultant", [300, 495, 705], [550, 745, 955]),
            ("Trainee / SAS doctor / ACP / nurse / AHP", [270, 450, 630], [520, 700, 880]),
            ("Student / foundation doctor / retired", [90, 150, 210], [340, 400, 460]),
        ]
        for grade_label, mem_p, non_p in abstract_grades:
            for status, prices in (("Member", mem_p), ("Non-member", non_p)):
                for n_days, price in enumerate(prices, start=1):
                    suffix = f"{n_days} day" if n_days == 1 else f"{n_days} days"
                    tiers.append({
                        "tier_label": f"Abstract presenter · Face-to-face · {status} · {grade_label} · {suffix}",
                        "price_gbp": float(price),
                        "is_early_bird": False,
                        "early_bird_deadline": None,
                    })

        # LMIC member rates — F2F + Virtual columns.
        lmic_rates = [
            ("Member, all grades except student / retired",
                # F2F 1/2/3 day, Virtual 1/2/3 day
                [55, 110, 165], [40, 80, 120]),
            ("Member student / retired",
                [35, 70, 105], [20, 40, 60]),
        ]
        for grade_label, f2f_prices, virt_prices in lmic_rates:
            for fmt_label, prices in (("Face-to-face", f2f_prices), ("Virtual", virt_prices)):
                for n_days, price in enumerate(prices, start=1):
                    suffix = f"{n_days} day" if n_days == 1 else f"{n_days} days"
                    tiers.append({
                        "tier_label": f"LMIC member · {fmt_label} · {grade_label} · {suffix}",
                        "price_gbp": float(price),
                        "is_early_bird": False,
                        "early_bird_deadline": None,
                    })

        return tiers

    # ------------------------------------------------------------------ #
    # Annual-conference helpers
    # ------------------------------------------------------------------ #
    def _find_early_bird_deadlines(self, body: str) -> List[str]:
        out = []
        for m in re.finditer(r"early bird[^.]*?(\d{1,2}\s+\w+\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})", body, re.I):
            iso = self._parse_textual_date(m.group(1)) or self._parse_ddmmyyyy(m.group(1))
            if iso:
                out.append(iso)
        return out

    def _parse_textual_date(self, text: str) -> Optional[str]:
        m = _TEXTUAL_DATE_RE.search(text)
        if not m:
            return None
        return self._iso(m.group(3), m.group(2), m.group(1))

    def _parse_ddmmyyyy(self, text: str) -> Optional[str]:
        m = _DDMMYYYY_RE.search(text)
        if not m:
            return None
        try:
            return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
        except ValueError:
            return None

    @staticmethod
    def _iso(year: str, month_name: str, day: str) -> Optional[str]:
        key = month_name.lower()
        mon = _MONTHS.get(key) or _MONTHS.get(key[:3])
        if not mon:
            return None
        try:
            return f"{int(year):04d}-{mon:02d}-{int(day):02d}"
        except ValueError:
            return None

    @staticmethod
    def _first_int_or_none(m) -> Optional[int]:
        if not m:
            return None
        try:
            return int(m.group(1))
        except (ValueError, IndexError):
            return None

    # ------------------------------------------------------------------ #
    # Soft fields — description + specialty via LLM + heuristic backstop
    # ------------------------------------------------------------------ #
    def _extract_soft_fields(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
        pre_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        if pre_text is None:
            text = page.evaluate(r"""() => {
                const main = document.querySelector('article, main, .elementor') || document.body;
                const clone = main.cloneNode(true);
                clone.querySelectorAll('nav, footer, script, style, noscript, header, .menu').forEach(n => n.remove());
                return clone.textContent.replace(/\s+/g, ' ').trim();
            }""")[:5000]
        else:
            text = pre_text

        title = shell.get("title") or ""
        prompt = f"""You are summarising a single medical event detail page. Extract ONLY two fields.

EVENT TITLE: {title}

PAGE BODY:
{text}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the page text" or null,
  "specialty": "primary clinical/topic area (e.g. Emergency Medicine, Paediatric Emergency Medicine, Toxicology, Trauma)" or null
}}"""

        result: Dict[str, Any] = {}
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
                parsed = json.loads(raw)
                result = {
                    "description": parsed.get("description"),
                    "specialty": parsed.get("specialty"),
                }
            except json.JSONDecodeError as e:
                logger.warning(f"RCEM soft-fields JSON parse failed: {e}; raw[:200]={raw[:200]!r}")

        # Heuristic specialty fallback — RCEM is an emergency-medicine college,
        # so when nothing else matches we default to Emergency Medicine.
        if not result.get("specialty"):
            heuristic = classify_specialty(title, text)
            result["specialty"] = heuristic or "Emergency Medicine"

        if not result.get("description") and text:
            chunk = text[:320].rstrip()
            cut = chunk.rfind(". ")
            if cut > 100:
                chunk = chunk[: cut + 1]
            else:
                chunk = chunk + "…"
            result["description"] = chunk

        return result
