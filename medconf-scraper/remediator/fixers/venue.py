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
        return h, "heuristic_prefix"

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


def fix_city(
    row: dict,
    page_text: str,
    llm_call: Callable[[str], Optional[str]],
) -> Tuple[Optional[str], Optional[str]]:
    if not page_text:
        return None, None
    # Heuristic: look for a known UK city in the body
    for city in _UK_CITIES:
        if re.search(rf"\b{re.escape(city)}\b", page_text):
            return city, "heuristic_known_city"

    # Postcode → city via prefix lookup
    m = _UK_POSTCODE_RE.search(page_text)
    if m:
        pc = m.group(1).upper()
        area = re.match(r"^([A-Z]{1,2})", pc)
        if area:
            mapping = {
                "SE": "London", "SW": "London", "NW": "London", "N": "London",
                "E": "London", "W": "London", "WC": "London", "EC": "London",
                "B": "Birmingham", "M": "Manchester", "L": "Liverpool",
                "LS": "Leeds", "S": "Sheffield", "BS": "Bristol",
                "SO": "Southampton",
            }
            city = mapping.get(area.group(1))
            if city:
                return city, "heuristic_postcode_prefix"

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
