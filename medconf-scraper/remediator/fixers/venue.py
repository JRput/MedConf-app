"""Venue / city fixer.

Strategy:
  1. Heuristic: look for "Venue:" / "Location:" / "Address:" / "held at"
     prefixes, postcode patterns, known UK city names
  2. LLM: ask for the venue text with strict "return null if not visible"
  3. Validate: not a nav phrase, length 5-200, must contain a letter
"""

from __future__ import annotations
import re
from typing import Callable, Optional, Tuple

_NAV_PHRASES = {
    "register", "login", "log in", "sign up", "menu", "search", "cookies",
    "privacy", "terms", "contact", "back to", "skip to", "newsletter",
    "members", "membership", "exams", "training",
}

_UK_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)

_UK_CITIES = {
    "London", "Manchester", "Liverpool", "Leeds", "Sheffield", "Newcastle",
    "Birmingham", "Bristol", "Exeter", "Plymouth", "Southampton", "Brighton",
    "Oxford", "Cambridge", "Cardiff", "Edinburgh", "Glasgow", "Belfast",
    "Hull", "Bradford", "Lancashire", "York", "Norwich", "Portsmouth",
    "Sutton Coldfield", "Pembury", "Tunbridge Wells", "Maidstone",
    "Chorley", "Reading", "Kettering", "Thame", "Pune",
}

_VENUE_PREFIXES = (
    r"venue\s*[:\|]",
    r"location\s*[:\|]",
    r"address\s*[:\|]",
    r"held\s+at\b",
    r"taking\s+place\s+at\b",
    r"hosted\s+at\b",
)


def _looks_like_venue(s: str) -> bool:
    s_low = s.lower().strip()
    if not s or len(s) < 5 or len(s) > 200:
        return False
    if not any(c.isalpha() for c in s):
        return False
    if any(p in s_low for p in _NAV_PHRASES):
        return False
    return True


def _heuristic_venue(page_text: str) -> Optional[str]:
    """Find a venue chunk via the standard "Venue | X" / "Location: X" patterns."""
    for pat in _VENUE_PREFIXES:
        m = re.search(pat + r"\s*([^\n\r]{5,200})", page_text, re.I)
        if m:
            candidate = m.group(1).strip(" .,;")
            if _looks_like_venue(candidate):
                return candidate
    return None


def _html_place(row: dict) -> Optional[dict]:
    """Venue / city evidence in the row's already-fetched page HTML (JSON-LD,
    Google-Maps embed, address block...). No network; site chrome excluded."""
    html = row.get("_page_html")
    if not html:
        return None
    try:
        from ..explorer import extract_place_from_html
        return extract_place_from_html(html, row.get("source_url") or "")
    except Exception:  # noqa: BLE001 - a parser bug must not sink the fixer
        return None


def fix_venue(
    row: dict,
    page_text: str,
    llm_call: Callable[[str], Optional[str]],
) -> Tuple[Optional[str], Optional[str]]:
    if not page_text:
        return None, None

    # Heuristic first
    h = _heuristic_venue(page_text)
    if h:
        from extractors.tribe_events import sane_venue
        h = sane_venue(h)                 # never a footer / address blob (CROI, Euroanaesthesia 2026-10-14)
        if h:
            return h, "heuristic_prefix"

    place = _html_place(row)
    if place and place.get("venue_name"):
        return place["venue_name"], f"html_{place['method']}"

    # LLM with strict prompt
    title = row.get("conference_name") or ""
    prompt = f"""You are reading a medical event detail page. What is the VENUE?

EVENT TITLE: {title}

PAGE TEXT (excerpt):
{page_text[:3000]}

Respond with ONLY the venue text (e.g. "Royal College of Physicians, London"
or "Pembury Hospital Education Centre"). If the venue is NOT explicitly stated
on the page, respond with the single word: null

Do not invent. Do not return navigation menu items. If unsure, return null."""

    raw = llm_call(prompt)
    if not raw or raw.strip().lower() in ("null", "none", "n/a", "unknown"):
        return None, None
    candidate = raw.strip().strip("`\"'").strip()
    if not _looks_like_venue(candidate):
        return None, None
    return candidate, "llm_strict"


_PREFIX_RE = re.compile("|".join(_VENUE_PREFIXES), re.I)
_PREFIX_WINDOW = 160
_POSTCODE_AREA_CITY = {
    "SE": "London", "SW": "London", "NW": "London", "N": "London",
    "E": "London", "W": "London", "WC": "London", "EC": "London",
    "B": "Birmingham", "M": "Manchester", "L": "Liverpool",
    "LS": "Leeds", "BS": "Bristol", "SO": "Southampton",
    # "S" deliberately absent: it also covers Barnsley, Rotherham, Doncaster.
}


def _city_in(text: str) -> Optional[str]:
    """Earliest whole-word _UK_CITIES match in text; longest name wins a tie."""
    best = None  # (start, -len, city)
    for city in _UK_CITIES:
        m = re.search(rf"\b{re.escape(city)}\b", text)
        if m:
            key = (m.start(), -len(city), city)
            if best is None or key < best:
                best = key
    return best[2] if best else None


def _prefix_windows(page_text: str) -> list:
    """The 160 characters following each Venue:/Location:/Address:/held at match.

    Footer zone = the last 15 % of page_text when len(page_text) > 4000;
    windows starting there are ignored (college addresses sit in footers).
    """
    footer_start = len(page_text) * 0.85 if len(page_text) > 4000 else None
    out = []
    for m in _PREFIX_RE.finditer(page_text):
        if footer_start is not None and m.start() >= footer_start:
            continue
        out.append(page_text[m.end():m.end() + _PREFIX_WINDOW])
    return out


def fix_city(
    row: dict,
    page_text: str,
    llm_call: Callable[[str], Optional[str]],
) -> Tuple[Optional[str], Optional[str]]:
    if row.get("event_format") == "online":
        return None, None                      # a webinar has no city
    if not page_text:
        return None, None

    # 1. Known city inside the stored venue name
    c = _city_in(row.get("venue_name") or "")
    if c:
        return c, "heuristic_city_in_venue"

    # 2. Known city right after a location prefix (never a bare word match:
    #    EANM "Reading Mask" widget, college footer addresses - 2026-10-30)
    windows = _prefix_windows(page_text)
    for w in windows:
        c = _city_in(w)
        if c:
            return c, "heuristic_city_after_prefix"

    # 3. Postcode prefix, only for a postcode inside one of those windows
    for w in windows:
        m = _UK_POSTCODE_RE.search(w)
        if m:
            area = re.match(r"^([A-Z]{1,2})", m.group(1).upper())
            city = _POSTCODE_AREA_CITY.get(area.group(1)) if area else None
            if city:
                return city, "heuristic_postcode_prefix"

    place = _html_place(row)
    if place and place.get("city"):
        return place["city"], f"html_{place['method']}"

    # LLM
    prompt = f"""From this event page, extract the CITY only (no street address).

PAGE TEXT (excerpt):
{page_text[:2500]}

Respond with ONLY the city name (e.g. "London", "Cambridge"). If not stated, respond: null"""
    raw = llm_call(prompt)
    if not raw or raw.strip().lower() in ("null", "none", "n/a", "unknown"):
        return None, None
    candidate = raw.strip().strip("`\"'").strip()
    if len(candidate) < 2 or len(candidate) > 60 or not candidate[0].isalpha():
        return None, None
    return candidate, "llm_strict"
