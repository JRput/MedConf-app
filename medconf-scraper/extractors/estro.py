"""European Society for Radiotherapy and Oncology — congresses extractor.

Listing strategy:
  ESTRO's /Congresses page is server-rendered HTML with a small number of
  events (2 as of 2026-07). Each event is a `<li>` block with:
    <h2 class="title"><a href="/Congresses/SLUG">TITLE</a></h2>
    <time datetime="P?D">START - END</time>
    <div class="location">CITY, COUNTRY</div>
    <div class="summary">...registration status snippet...</div>

Detail strategy:
  The event's own page is single-page; every field lives inline:
    - "Important deadlines Abstract submission deadline : 11 March 2026"
    - "Venue Singapore Expo 1 Expo Drive, Singapore 486150"
    - Introduction paragraph for description
  ESTRO 2027 also lists a late-breaking abstract window
  ("17-31 March 2027") which we skip in favour of the regular deadline.

  Pricing (fee table) is published as a JPG image at
  /getattachment/.../FEE-*.jpg for some events. We do NOT vision-parse
  that here — the remediator's Tier-2 pricing explorer handles it.
"""

import re
import html as _html
import httpx
from datetime import date
from typing import Dict, Any, Optional, Callable, List, Tuple
from playwright.sync_api import Page

from .base import BaseExtractor
from logger import logger


LISTING_URL = "https://www.estro.org/Congresses"
BASE_HOST = "https://www.estro.org"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def _clean(html_or_text: str) -> str:
    if not html_or_text:
        return ""
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html_or_text, flags=re.DOTALL | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = _html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _fetch(url: str, timeout: float = 25) -> Optional[str]:
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": USER_AGENT}) as c:
            r = c.get(url)
            if r.status_code == 200:
                return r.text
    except Exception as e:
        logger.debug(f"ESTRO fetch failed for {url}: {e}")
    return None


def _parse_uk_date(text: str) -> Optional[str]:
    """"28 August 2026" → "2026-08-28". Also handles "1 January 2027"."""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text)
    if not m:
        return None
    d = int(m.group(1))
    mon = _MONTHS.get(m.group(2).lower())
    y = int(m.group(3))
    if not mon:
        return None
    return f"{y:04d}-{mon:02d}-{d:02d}"


def _parse_date_range(text: str) -> Tuple[Optional[str], Optional[str]]:
    """"28 August 2026 - 30 August 2026" → (2026-08-28, 2026-08-30)"""
    parts = re.split(r"\s*[-–—]\s*", text)
    if len(parts) == 2:
        return _parse_uk_date(parts[0]), _parse_uk_date(parts[1])
    d = _parse_uk_date(text)
    return d, d


def _walk_listing() -> List[Dict[str, Any]]:
    html = _fetch(LISTING_URL)
    if not html:
        return []
    shells: List[Dict[str, Any]] = []
    # Each congress is an <li> with a title/time/location trio
    lis = re.findall(r"<li[^>]*>(.*?)</li>", html, re.DOTALL)
    for li in lis:
        title_m = re.search(
            r'<h2[^>]*class="title"[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>',
            li, re.DOTALL,
        )
        if not title_m:
            continue
        href = title_m.group(1)
        if not href.startswith("/Congresses/"):
            continue
        title = _clean(title_m.group(2))

        time_m = re.search(r"<time[^>]*>(.*?)</time>", li, re.DOTALL)
        date_txt = _clean(time_m.group(1)) if time_m else ""

        loc_m = re.search(r'<div[^>]+class="location"[^>]*>([^<]+)</div>', li)
        loc_txt = _clean(loc_m.group(1)) if loc_m else ""

        summary_m = re.search(r'<div[^>]+class="summary"[^>]*>(.*?)</div>\s*</address>', li, re.DOTALL)
        summary_txt = _clean(summary_m.group(1)) if summary_m else ""

        shells.append({
            "title": title,
            "booking_url": BASE_HOST + href,
            "source_url": BASE_HOST + href,
            "date_raw": date_txt,
            "location_raw": loc_txt,
            "summary_raw": summary_txt,
        })
    return shells


def _parse_city_country(loc: str) -> Tuple[Optional[str], Optional[str]]:
    """"Singapore, Singapore" → ("Singapore", "Singapore")
       "Milan, Italy"         → ("Milan", "Italy")
    """
    if not loc:
        return None, None
    parts = [p.strip() for p in loc.split(",")]
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return parts[0], None


def _extract_venue(txt: str) -> Optional[str]:
    """From detail-page prose. Common form:
       'Venue Singapore Expo 1 Expo Drive, Singapore 486150 Max Atria Entrance'
       'Venue Allianz MiCo Gate 2 Viale Eginardo 20149 Milano Italy Important Notice'

    Grab the first noun-phrase after 'Venue' up to a distinctive stop word.
    """
    m = re.search(
        r"Venue\s+([A-Z][A-Za-z0-9\s\-'\.&]{2,60}?)(?=\s+(?:\d|Gate|Expo Drive|Level|Floor|Viale|Via|Rue|Strasse|Str\.|Piazza|Boulevard|Blvd|Convention|,))",
        txt,
    )
    if m:
        return m.group(1).strip()
    m = re.search(r"Venue\s+([A-Z][A-Za-z0-9\s\-'\.&]{3,80})", txt)
    if m:
        return m.group(1).strip().split(",")[0]
    return None


def _extract_abstract_deadline_raw(txt: str) -> Optional[str]:
    """Match 'Abstract submission deadline : 11 March 2026' and variants.
    Prefer 'Regular abstract' over 'Late-breaking abstract' when both exist.
    """
    # Prefer regular
    m = re.search(
        r"(?i)Regular\s+abstract\s+submission\s+deadline\s*:?\s*"
        r"(\d{1,2}\s+[A-Za-z]+\s+20\d{2})",
        txt,
    )
    if m:
        return m.group(1)
    m = re.search(
        r"(?i)Abstract\s+submission\s+deadline\s*:?\s*"
        r"(\d{1,2}\s+[A-Za-z]+\s+20\d{2})",
        txt,
    )
    if m:
        return m.group(1)
    return None


def _extract_description(txt: str) -> Optional[str]:
    """Pull an intro paragraph before 'Congress Co-Chairs' / 'Important deadlines'.

    Detail pages open with an intro like 'On behalf of the Steering
    Committee ...' or 'We are pleased to invite you to Milan for ESTRO
    2027 ...'. Grab everything from the first meaningful sentence up to
    the boilerplate stopper.
    """
    # Find the "Welcome Letter" / intro paragraph. Detail pages use these
    # openings (all lowercased for match): 'it is our pleasure',
    # 'it is with great pleasure', 'we are pleased to invite', 'on behalf of',
    # 'welcome to', 'welcome letter'. Pick the EARLIEST hit.
    start_markers = [
        "it is with great pleasure",
        "it is our pleasure",
        "we are pleased to invite",
        "we are looking forward",
        "on behalf of",
        "welcome letter",
        "welcome to",
        "join us",
    ]
    lo = txt.lower()
    start = -1
    for marker in start_markers:
        idx = lo.find(marker)
        if idx > 0 and (start == -1 or idx < start):
            start = idx
    if start < 0:
        return None
    # Stop at first substantial section heading
    stops = [
        "congress co-chairs",
        "important deadlines",
        "scientific committee",
        "steering committee",
        "read more",
    ]
    end = len(txt)
    for st in stops:
        idx = lo.find(st, start)
        if idx > 0 and idx < end:
            end = idx
    desc = txt[start:end].strip()
    # Trim to 700 chars
    if len(desc) > 700:
        desc = desc[:697].rstrip() + "..."
    return desc if len(desc) >= 60 else None


def _classify_specialty(title: str) -> str:
    t = title.lower()
    if "head and neck" in t or "hnc" in t or "ichno" in t:
        return "Head & Neck Oncology"
    if "physics" in t:
        return "Radiation Physics"
    return "Radiation Oncology"


class ESTROExtractor(BaseExtractor):
    """Source 19: ESTRO congresses (server-rendered custom CMS)."""

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        shells = _walk_listing()
        if not shells:
            logger.warning("ESTRO: 0 shells from listing")
            return None
        logger.info(f"ESTRO: {len(shells)} congresses on listing")
        return shells

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        url = shell.get("source_url") or ""
        title = shell.get("title") or ""

        # 1. Society, specialty
        out["society"] = "ESTRO"
        out["specialty"] = _classify_specialty(title)

        # 2. Event type
        out["event_type"] = "conference"

        # 3. Dates from listing time tag
        start, end = _parse_date_range(shell.get("date_raw", ""))
        if start:
            out["start_date"] = start
        if end and end != start:
            out["end_date"] = end

        # 4. City / region
        city, country = _parse_city_country(shell.get("location_raw", ""))
        if city:
            out["city"] = city
        if country:
            out["region"] = country
        out["event_format"] = "in_person"

        # 5. Flagship — both congresses are ESTRO's main events
        out["is_flagship"] = True

        # 6. Fetch detail page for description, venue, abstract deadline
        detail_html = _fetch(url)
        if detail_html:
            txt = _clean(detail_html)

            venue = _extract_venue(txt)
            if venue:
                out["venue_name"] = venue

            desc = _extract_description(txt)
            if desc:
                out["description"] = desc

            deadline_raw = _extract_abstract_deadline_raw(txt)
            today = date.today().isoformat()
            if deadline_raw:
                deadline_iso = _parse_uk_date(deadline_raw)
                if deadline_iso:
                    out["abstract_deadline"] = deadline_iso
                    out["abstract_open"] = deadline_iso >= today

        return out
