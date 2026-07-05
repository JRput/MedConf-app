"""American Society of Clinical Oncology — extractors.

Two source variants share this module:
- ASCOAnnualExtractor (source 15): the /annual-meeting flagship subsite.
  Currently shows 2027 Save the Date content. One conference row.
- ASCOMeetingsExtractor (source 16): the /meetings-education/meetings
  listing, which points at ASCO's other satellite/co-sponsored meetings
  (Best of ASCO, IASLC Lung Cancer, Head & Neck Symposium, etc).

Both share helpers (date parsing, image extraction, description trim).
"""

import re
import html as _html
from datetime import date
from typing import Dict, Any, Optional, Callable, List

import httpx
from playwright.sync_api import Page

from .base import BaseExtractor
from logger import logger


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)

_MONTHS_FULL = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}
_MONTHS_ANY = dict(_MONTHS_FULL)
for k, v in list(_MONTHS_FULL.items()):
    _MONTHS_ANY[k[:3]] = v
_MONTHS_ANY["sept"] = 9


def _parse_us_date_range(text: str) -> tuple:
    """Parse 'June 4 - 8, 2027' or 'June 4-8, 2027' → (start_iso, end_iso).
    Handles 'June 4, 2027' single-day too."""
    # "Month Day1 - Day2, Year"
    m = re.search(
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2})\s*[-–]\s*(\d{1,2}),?\s+(\d{4})",
        text, re.I,
    )
    if m:
        mon = _MONTHS_FULL[m.group(1).lower()]
        d1, d2, y = int(m.group(2)), int(m.group(3)), int(m.group(4))
        return f"{y:04d}-{mon:02d}-{d1:02d}", f"{y:04d}-{mon:02d}-{d2:02d}"
    # Single day
    m = re.search(
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
        text, re.I,
    )
    if m:
        mon = _MONTHS_FULL[m.group(1).lower()]
        d, y = int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mon:02d}-{d:02d}", f"{y:04d}-{mon:02d}-{d:02d}"
    return None, None


def _strip_and_normalise(raw_html: str) -> str:
    txt = re.sub(r"<[^>]+>", " ", raw_html)
    txt = _html.unescape(txt)  # unescape BEFORE normalise (BTOG lesson)
    txt = re.sub(r"\s+", " ", txt)
    return txt


def _extract_og_image(html: str) -> Optional[str]:
    m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html, re.I)
    return m.group(1) if m else None


def _is_real_asco_page(raw_html: str) -> bool:
    """ASCO's CDN returns HTTP 200 with 'Oops! Page Not Found' for
    URLs that don't exist yet (like /annual-meeting/register when
    registration hasn't opened). Detect this so we skip the placeholder.
    """
    return "Oops! Page Not Found" not in raw_html and "Page Not Found" not in raw_html[:2000]


def _fetch_asco_subpage(base_url: str, suffix: str, timeout: float = 25) -> Optional[str]:
    """Fetch an ASCO sub-page. Returns raw HTML if the page is real,
    None if it's a 'Page Not Found' placeholder or fetch failed."""
    url = base_url.rstrip("/") + "/" + suffix.lstrip("/")
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": USER_AGENT}) as c:
            r = c.get(url)
            if r.status_code != 200:
                return None
            if not _is_real_asco_page(r.text):
                return None
            return r.text
    except Exception as e:
        logger.warning(f"ASCO sub-page fetch failed for {url}: {e}")
        return None


def _extract_asco_pricing(sub_html: str) -> List[dict]:
    """ASCO uses USD tiers. Common formats:
      Member — $850    Non-member — $1,200
      Early bird — Member $850
      Registration Type       Early    Standard   Late
      Member                  $850     $1050      $1250
    """
    tiers: List[dict] = []
    seen: set = set()
    txt = re.sub(r"<[^>]+>", " ", sub_html)
    txt = _html.unescape(txt); txt = re.sub(r"\s+", " ", txt)

    # Detect column headers if a table has Early / Regular / Late structure
    hdr = re.search(
        r"(Early(?:\s+(?:bird|registration))?)"
        r".{0,150}?"
        r"(Regular\s+registration|Standard\s+registration|Advance\s+registration)"
        r".{0,150}?"
        r"(Late\s+registration|Onsite\s+registration)?",
        txt, re.I,
    )
    col_labels = None
    if hdr:
        col_labels = [g for g in hdr.groups() if g]

    # Row labels — common ASCO categories
    row_label_re = re.compile(
        r"(ASCO\s+Member(?:\s+in\s+Training)?|"
        r"Non-?member(?:\s+Physician)?|Non\s+Member|"
        r"Physician\s+Member|Allied\s+Health\s+Professional|"
        r"Patient\s+Advocate|Trainee|Student|Resident|"
        r"Industry|Press|Media|"
        r"Standard\s+registration|Early\s+registration|Late\s+registration)",
        re.I,
    )
    price_re = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
    max_prices = len(col_labels) if col_labels else 4

    for lm in row_label_re.finditer(txt):
        label = re.sub(r"\s+", " ", lm.group(1)).strip()
        window = txt[lm.end(): lm.end() + 300]
        raw_prices = price_re.findall(window)
        if not raw_prices:
            continue
        prices: List[float] = []
        for p in raw_prices[:max_prices]:
            try:
                prices.append(float(p.replace(",", "")))
            except ValueError:
                pass
        if not prices:
            continue
        for idx, price in enumerate(prices):
            if not (50 <= price <= 20000):
                continue
            if col_labels and idx < len(col_labels):
                full_label = f"{label} — {col_labels[idx]}"
            else:
                full_label = label
            full_label = full_label.strip()[:200]
            key = (full_label.lower(), price)
            if key in seen:
                continue
            seen.add(key)
            tiers.append({
                "tier_label": full_label, "price_gbp": price,
                "currency": "USD",
                "is_early_bird": "early" in full_label.lower(),
                "early_bird_deadline": None,
            })
    return tiers


def _extract_asco_abstract_deadline(sub_html: str) -> Optional[str]:
    """ASCO uses dates like 'February 6, 2027' or 'Feb 6, 2027'."""
    txt = re.sub(r"<[^>]+>", " ", sub_html)
    txt = _html.unescape(txt); txt = re.sub(r"\s+", " ", txt)
    m = re.search(
        r"(?i)(?:abstract\s+submission\s+(?:deadline|closes?|due)|"
        r"submission\s+deadline|deadline\s+for\s+abstracts?)"
        r"[^A-Za-z0-9]{1,40}"
        r"("
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
        r"\s+\d{1,2},?\s+\d{4})",
        txt,
    )
    if not m:
        return None
    return _parse_us_date_single(m.group(1))


def _parse_us_date_single(s: str) -> Optional[str]:
    """Parse 'February 6, 2027' → '2027-02-06'."""
    dm = re.match(r"(\w+)\s+(\d{1,2}),?\s+(\d{4})", s)
    if not dm:
        return None
    mon_name = dm.group(1).lower()
    mon = _MONTHS_ANY.get(mon_name) or _MONTHS_ANY.get(mon_name[:3])
    if not mon:
        return None
    d, y = int(dm.group(2)), int(dm.group(3))
    return f"{y:04d}-{mon:02d}-{d:02d}"


def _extract_asco_abstract_opens(sub_html_or_main: str) -> Optional[str]:
    """Look for 'Abstract submission opens' patterns.
    Returns the raw date string (for display in a note) if found.
    """
    txt = re.sub(r"<[^>]+>", " ", sub_html_or_main)
    txt = _html.unescape(txt); txt = re.sub(r"\s+", " ", txt)
    m = re.search(
        r"(?i)abstract\s+submission\s+(?:opens?|begin|starts?|will\s+open|"
        r"is\s+open|available)\s*(?:on|from)?\s*"
        r"("
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
        r"\s+\d{1,2},?\s+\d{4})",
        txt,
    )
    if m:
        return m.group(1)
    # Also match "will open in <Month YYYY>"
    m = re.search(
        r"(?i)abstract\s+submission[^.]{0,60}?(?:will\s+open|opens?)\s+"
        r"(?:in\s+)?"
        r"("
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{4})",
        txt,
    )
    if m:
        return m.group(1)
    return None


class ASCOMeetingsExtractor(BaseExtractor):
    """Source 16: ASCO Meetings-Education listing.

    ASCO hosts 4 self-published event pages (short paths on asco.org):
      - /breakthrough  -> ASCO Breakthrough (Asia annual meeting)
      - /gi            -> ASCO Gastrointestinal Cancers Symposium
      - /gu            -> ASCO Genitourinary Cancers Symposium
      - /quality       -> ASCO Quality Care Symposium

    (Also on the listing but excluded: ongoing licensed programs like
    /meetings-education/meetings/asco-direct and /best-of-asco, and
    externally co-sponsored partner meetings like IASLC | ASCO Lung
    Cancer, SNO/ASCO CNS Metastases, AACR/ASCO Methods Workshop and
    Multidisciplinary Head & Neck Symposium.)
    """

    _EVENT_URLS = [
        {
            "title": "ASCO Breakthrough",
            "url": "https://www.asco.org/breakthrough",
            "desc_tokens": ("breakthrough", "asia"),
            "candidate_cities": ("Singapore", "Bangkok", "Kuala Lumpur",
                                  "Hong Kong", "Tokyo", "Yokohama",
                                  "Seoul", "Taipei"),
        },
        {
            "title": "ASCO Gastrointestinal Cancers Symposium",
            "url": "https://www.asco.org/gi",
            "desc_tokens": ("gastrointestinal", "gi cancers"),
            "candidate_cities": ("San Francisco",),
        },
        {
            "title": "ASCO Genitourinary Cancers Symposium",
            "url": "https://www.asco.org/gu",
            "desc_tokens": ("genitourinary", "gu cancers"),
            "candidate_cities": ("San Francisco",),
        },
        {
            "title": "ASCO Quality Care Symposium",
            "url": "https://www.asco.org/quality",
            "desc_tokens": ("quality care", "quality, safety"),
            "candidate_cities": ("Boston",),
        },
    ]

    # Discovery — scan the /meetings-education/meetings page for any
    # short-path URLs like /gi, /gu, /breakthrough, /quality that link
    # to standalone event subsites. This catches new symposia when ASCO
    # adds them (they've historically added ~1 new event per year).
    _LISTING_URL = "https://www.asco.org/meetings-education/meetings"

    # Short paths on asco.org that ARE real event pages, but excluded
    # because they're not single-event pages
    _EXCLUDED_SHORT_PATHS = {
        "search", "contact-us", "abstracts", "posters", "slides", "videos",
        "guidelines", "journals", "annual-meeting",  # separate source
        "asco-licensing-opportunities", "meetings-education",
    }

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        # Start with the hardcoded curated list — these are known-good
        # entries with proper metadata (candidate_cities, desc_tokens).
        # Then auto-discover any additional short-path event URLs on the
        # listing page — if ASCO adds "ASCO Breast Cancer Symposium" at
        # /breast, we'll pick it up on the next scrape.
        curated_by_url = {e["url"]: e for e in self._EVENT_URLS}
        discovered_urls: set = set()
        try:
            with httpx.Client(timeout=25, follow_redirects=True,
                              headers={"User-Agent": USER_AGENT}) as c:
                r = c.get(self._LISTING_URL)
                raw = r.text
            # Find /<short-path> hrefs where short-path is 2-30 chars,
            # single segment, no /meetings-education/ prefix
            for m in re.finditer(
                r'href=["\'](/[a-z][a-z0-9\-]{1,29}|'
                r'https://www\.asco\.org/[a-z][a-z0-9\-]{1,29})["\']',
                raw,
            ):
                url = m.group(1)
                if url.startswith("/"):
                    url = "https://www.asco.org" + url
                url = url.rstrip("/")
                slug = url.rsplit("/", 1)[-1]
                if slug in self._EXCLUDED_SHORT_PATHS:
                    continue
                discovered_urls.add(url)
        except Exception as e:
            logger.warning(f"ASCO listing discovery failed: {e}")

        # Warn if we found any URLs that AREN'T in our curated list —
        # they may be new events we need to add metadata for.
        for url in sorted(discovered_urls):
            if url not in curated_by_url:
                logger.warning(
                    f"ASCO: discovered short-path URL not in curated list: "
                    f"{url} — verify if this is a new event and add to "
                    f"_EVENT_URLS if so"
                )

        return [{
            "title": e["title"],
            "booking_url": e["url"],
            "source_url": e["url"],
            "_meta": e,
        } for e in self._EVENT_URLS]

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        url = shell.get("source_url") or shell.get("booking_url") or ""
        meta = shell.get("_meta") or {}
        title_hint = meta.get("title") or shell.get("title") or ""
        desc_tokens = meta.get("desc_tokens") or (title_hint.lower(),)
        candidate_cities = meta.get("candidate_cities") or ()

        out: Dict[str, Any] = {}
        try:
            with httpx.Client(timeout=30, follow_redirects=True,
                              headers={"User-Agent": USER_AGENT}) as c:
                r = c.get(url)
                r.raise_for_status()
                raw = r.text
        except Exception as e:
            logger.warning(f"ASCO meetings sub-fetch failed: {e}")
            return out

        txt = _strip_and_normalise(raw)

        # Dates + year prefix
        start, end = _parse_us_date_range(txt)
        if start:
            out["start_date"] = start
            if end and end != start:
                out["end_date"] = end
            year = start[:4]
            out["conference_name"] = f"{year} {title_hint}"
        else:
            out["conference_name"] = title_hint

        # Location — try known candidate cities for this event first
        for city in candidate_cities:
            if city in txt:
                out["city"] = city
                break

        # Venue detection — ASCO uses "location_on Venue Name | City"
        # or "at Moscone West" or "Hynes Convention Center, Boston"
        venue_m = re.search(
            r"location_on\s+([A-Z][A-Za-z0-9 .,'&-]{4,80}?)\s*\|",
            txt,
        )
        if venue_m:
            out["venue_name"] = venue_m.group(1).strip()
        else:
            # Fallback — "Hynes Convention Center, Boston, MA & Online"
            for city in candidate_cities:
                venue_m = re.search(
                    rf"([A-Z][A-Za-z0-9 .,'&-]{{4,80}}?),\s+{re.escape(city)}\b",
                    txt,
                )
                if venue_m:
                    out["venue_name"] = venue_m.group(1).strip()
                    break

        # Format detection
        low = txt.lower()
        if re.search(r"(?:&|and)\s+online", low) or "hybrid" in low:
            out["event_format"] = "hybrid"
        elif "virtual" in low or "online only" in low:
            out["event_format"] = "online"
        else:
            out["event_format"] = "in_person"

        out["event_type"] = "conference"
        out["is_flagship"] = True
        out["specialty"] = "Oncology"
        out["society"] = "ASCO"

        # Description — must mention title-specific tokens
        candidates: List[str] = []
        for tag in ("h1", "h2", "p"):
            for m in re.finditer(rf"<{tag}[^>]*>(.*?)</{tag}>", raw, re.I | re.S):
                d = _html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))
                d = re.sub(r"\s+", " ", d).strip()
                if not (50 <= len(d) <= 700):
                    continue
                dl = d.lower()
                if not any(t in dl for t in desc_tokens):
                    continue
                if any(bad in dl for bad in ("cookie", "javascript")):
                    continue
                if dl.startswith(("couldn", "did", "want", "why", "how", "what")):
                    continue
                candidates.append(d)
        if candidates:
            candidates.sort(key=len, reverse=True)
            out["description"] = candidates[0]

        # Abstract opening date (when future) — check main page first
        # then abstracts sub-page
        opens_raw = _extract_asco_abstract_opens(txt)
        deadline: Optional[str] = None
        for suffix in ("abstracts", "program/abstracts",
                        "attend/abstract-submissions",
                        "abstracts-and-presentations"):
            abs_html = _fetch_asco_subpage(url, suffix)
            if abs_html:
                if not deadline:
                    deadline = _extract_asco_abstract_deadline(abs_html)
                if not opens_raw:
                    opens_raw = _extract_asco_abstract_opens(abs_html)
                if deadline and opens_raw:
                    break

        today = date.today().isoformat()
        if deadline:
            out["abstract_deadline"] = deadline
            out["abstract_open"] = deadline >= today
            if opens_raw:
                # Only add opening note if opening date is in the future
                # relative to today
                opens_iso = _parse_us_date_single(opens_raw) or ""
                if opens_iso and opens_iso > today:
                    out["abstract_deadline_note"] = f"Opens {opens_raw}"
        elif opens_raw:
            opens_iso = _parse_us_date_single(opens_raw)
            # Some pages say "Abstract submission will open in October 2026"
            # (month + year, no day). If we can't parse to a full ISO date,
            # still surface it as a note so users see when submissions open.
            out["abstract_deadline_note"] = f"Abstract submission opens {opens_raw}"
            out["abstract_open"] = False

        # Registration sub-page for USD pricing tiers
        for suffix in ("attend/register", "attend/registration",
                        "registration", "register"):
            reg_html = _fetch_asco_subpage(url, suffix)
            if reg_html:
                tiers = _extract_asco_pricing(reg_html)
                if tiers:
                    out["pricing_tiers"] = tiers
                    break

        return out


class ASCOAnnualExtractor(BaseExtractor):
    """Source 15: ASCO Annual Meeting flagship subsite.

    The /annual-meeting page shows one row: whichever ASCO Annual Meeting
    is upcoming (currently 2027). No listing walk — the URL itself IS the
    event's page.
    """

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        # Return exactly one shell — the event page itself
        return [{
            "title": "ASCO Annual Meeting",
            "booking_url": "https://www.asco.org/annual-meeting",
            "source_url": "https://www.asco.org/annual-meeting",
        }]

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        url = shell.get("source_url") or shell.get("booking_url") or ""
        out: Dict[str, Any] = {}
        try:
            with httpx.Client(timeout=30, follow_redirects=True,
                              headers={"User-Agent": USER_AGENT}) as c:
                r = c.get(url)
                r.raise_for_status()
                raw = r.text
        except Exception as e:
            logger.warning(f"ASCO Annual fetch failed: {e}")
            return out

        txt = _strip_and_normalise(raw)

        # Dates + implied year in the conference name
        start, end = _parse_us_date_range(txt)
        if start:
            out["start_date"] = start
            if end and end != start:
                out["end_date"] = end
            year_from_date = start[:4]
            out["conference_name"] = f"{year_from_date} ASCO Annual Meeting"
        else:
            out["conference_name"] = "ASCO Annual Meeting"

        # Location detection — anchor to "McCormick Place, Chicago, IL"-shape
        # or "location_on" material icon marker used on the page.
        # First check for known ASCO venues + city combos
        venue_city_m = re.search(
            r"(?:location_on|Location[:\s]+)\s*"
            r"([A-Z][A-Za-z .'&-]{4,80}?),\s+"
            r"(Chicago|Boston|Atlanta|San Francisco|New York|Orlando|Washington|Los Angeles)"
            r",?\s*[A-Z]{0,2}",
            txt,
        )
        if venue_city_m:
            out["venue_name"] = venue_city_m.group(1).strip()
            out["city"] = venue_city_m.group(2).strip()
        else:
            # Try "Chicago" bare mention
            for c in ("Chicago", "Boston", "San Francisco", "Orlando"):
                if c in txt:
                    out["city"] = c
                    break

        # Format — hybrid if "& Online" or "and Online"
        low = txt.lower()
        if re.search(r"(?:&|and)\s+online", low) or "hybrid" in low:
            out["event_format"] = "hybrid"
        elif "virtual" in low or "online only" in low:
            out["event_format"] = "online"
        else:
            out["event_format"] = "in_person"

        out["event_type"] = "conference"
        out["is_flagship"] = True
        out["specialty"] = "Oncology"
        out["society"] = "ASCO"

        # Description — must be about THIS event (the Annual Meeting), not
        # about a different ASCO satellite event that happens to name-check
        # the Annual Meeting. Filters:
        #   1. mentions "annual meeting"
        #   2. does NOT mention other ASCO satellite events by name
        #   3. not an interrogative or clearly navigational
        target_tokens = ("annual meeting", "asco annual")
        # Other ASCO events that might appear in ambient descriptions.
        # If a candidate mentions any of these, it's about a different event.
        other_events = (
            "breakthrough", "quality care", "gastrointestinal",
            "genitourinary", "supportive care", "direct highlights",
            "best of asco", "aacr/asco", "sno/asco", "iaslc",
            "head & neck symposium", "cns metastases",
        )
        candidates: List[str] = []
        for tag in ("h1", "h2", "p"):
            for m in re.finditer(rf"<{tag}[^>]*>(.*?)</{tag}>", raw, re.I | re.S):
                d = _html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))
                d = re.sub(r"\s+", " ", d).strip()
                if not (50 <= len(d) <= 700):
                    continue
                dl = d.lower()
                if not any(t in dl for t in target_tokens):
                    continue
                if any(bad in dl for bad in ("cookie", "javascript")):
                    continue
                # Reject if mentions other ASCO satellite events
                if any(oe in dl for oe in other_events):
                    continue
                # Reject interrogative openings (they're often nav prompts)
                if dl.startswith(("couldn", "did", "want", "why", "how", "what")):
                    continue
                candidates.append(d)
        if candidates:
            # Prefer the longest surviving candidate
            candidates.sort(key=len, reverse=True)
            out["description"] = candidates[0]

        # Fetch known sub-pages when they exist (ASCO returns 200 with
        # "Oops! Page Not Found" for URLs that don't exist yet).
        # These auto-populate as ASCO publishes info closer to the meeting.
        #
        # Registration sub-page — for USD pricing tiers
        for suffix in ("attend/register", "attend/registration",
                        "registration", "register"):
            reg_html = _fetch_asco_subpage(url, suffix)
            if reg_html:
                tiers = _extract_asco_pricing(reg_html)
                if tiers:
                    out["pricing_tiers"] = tiers
                    break

        # Abstracts sub-page — deadline AND opening date
        opens_raw = _extract_asco_abstract_opens(txt)
        deadline: Optional[str] = None
        for suffix in ("abstracts", "program/abstracts",
                        "attend/abstract-submissions",
                        "abstracts-and-presentations"):
            abs_html = _fetch_asco_subpage(url, suffix)
            if abs_html:
                if not deadline:
                    deadline = _extract_asco_abstract_deadline(abs_html)
                if not opens_raw:
                    opens_raw = _extract_asco_abstract_opens(abs_html)
                if deadline and opens_raw:
                    break
        today = date.today().isoformat()
        if deadline:
            out["abstract_deadline"] = deadline
            out["abstract_open"] = deadline >= today
            if opens_raw:
                opens_iso = _parse_us_date_single(opens_raw) or ""
                if opens_iso and opens_iso > today:
                    out["abstract_deadline_note"] = f"Opens {opens_raw}"
        elif opens_raw:
            out["abstract_deadline_note"] = (
                f"Abstract submission opens {opens_raw}"
            )
            out["abstract_open"] = False

        # Venue sub-page — for detailed venue info if main page didn't
        # have "McCormick Place, Chicago" pattern
        if "venue_name" not in out:
            for suffix in ("venue", "attend/venue", "attend/hotels", "hotels"):
                v_html = _fetch_asco_subpage(url, suffix)
                if v_html:
                    v_txt = _strip_and_normalise(v_html)
                    # "held at the McCormick Place" or "McCormick Place, Chicago"
                    vm = re.search(
                        r"(?:held\s+at|will\s+take\s+place\s+at|hosted\s+at)"
                        r"\s+(?:the\s+)?"
                        r"([A-Z][A-Za-z0-9 .,'&-]{5,120})",
                        v_txt, re.I,
                    )
                    if vm:
                        v = vm.group(1)
                        for stop in (" in ", " from ", ",", " and ",
                                      " Chicago", " where "):
                            idx = v.find(stop)
                            if idx > 4:
                                v = v[:idx]
                                break
                        v = v.strip().rstrip(",.-;:")
                        if 4 < len(v) < 120:
                            out["venue_name"] = v
                            break
        return out
