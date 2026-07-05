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
    dm = re.match(
        r"(\w+)\s+(\d{1,2}),?\s+(\d{4})",
        m.group(1),
    )
    if not dm:
        return None
    mon_name = dm.group(1).lower()
    mon = _MONTHS_ANY.get(mon_name) or _MONTHS_ANY.get(mon_name[:3])
    if not mon:
        return None
    d, y = int(dm.group(2)), int(dm.group(3))
    return f"{y:04d}-{mon:02d}-{d:02d}"


class ASCOMeetingsExtractor(BaseExtractor):
    """Source 16: ASCO Meetings-Education listing.

    The /meetings-education/meetings page lists several ASCO event types.
    Most are ongoing licensing programs (ASCO Direct, Best of ASCO) with
    no specific dates OR external co-sponsored meetings (IASLC lung
    cancer, SNO CNS metastases, AACR methods workshop) hosted on partner
    sites. The ONE self-hosted single event from this listing is:
      - ASCO Breakthrough — annual Asia meeting (Singapore for 2027)

    This extractor returns Breakthrough as one row. If ASCO adds more
    self-hosted single events later, add them to the shells list.
    """

    _EVENT_URLS = [
        {
            "title": "ASCO Breakthrough",
            "url": "https://www.asco.org/breakthrough",
        },
    ]

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        return [{
            "title": e["title"],
            "booking_url": e["url"],
            "source_url": e["url"],
        } for e in self._EVENT_URLS]

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
            out["conference_name"] = f"{year} ASCO Breakthrough"
        else:
            out["conference_name"] = "ASCO Breakthrough"

        # Location — Breakthrough rotates Asian cities; check known ones
        for city in ("Singapore", "Bangkok", "Kuala Lumpur", "Hong Kong",
                      "Tokyo", "Yokohama", "Seoul", "Taipei"):
            if city in txt:
                out["city"] = city
                break

        # Format: hybrid if "& online" or virtual mention
        low = txt.lower()
        if re.search(r"(?:&|and)\s+online", low) or "hybrid" in low:
            out["event_format"] = "hybrid"
        elif "virtual" in low or "online only" in low:
            out["event_format"] = "online"
        else:
            out["event_format"] = "in_person"

        out["event_type"] = "conference"
        out["is_flagship"] = True  # ASCO's flagship Asian meeting
        out["specialty"] = "Oncology"
        out["society"] = "ASCO"

        # Description — must mention "Breakthrough" AND be about the event
        target_tokens = ("breakthrough", "asia")
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
                if any(bad in dl for bad in ("cookie", "javascript",
                                              "annual meeting")):
                    continue
                if dl.startswith(("couldn", "did", "want", "why", "how", "what")):
                    continue
                candidates.append(d)
        if candidates:
            candidates.sort(key=len, reverse=True)
            out["description"] = candidates[0]

        # Fetch sub-pages for pricing, abstracts, venue
        for suffix in ("attend/register", "attend/registration",
                        "registration", "register"):
            reg_html = _fetch_asco_subpage(url, suffix)
            if reg_html:
                tiers = _extract_asco_pricing(reg_html)
                if tiers:
                    out["pricing_tiers"] = tiers
                    break

        for suffix in ("abstracts", "program/abstracts",
                        "attend/abstract-submissions"):
            abs_html = _fetch_asco_subpage(url, suffix)
            if abs_html:
                deadline = _extract_asco_abstract_deadline(abs_html)
                if deadline:
                    out["abstract_deadline"] = deadline
                    out["abstract_open"] = deadline >= date.today().isoformat()
                    break

        # Venue: often stated as "Marina Bay Sands, Singapore" on Breakthrough
        if "venue_name" not in out:
            venue_m = re.search(
                r"(?:held\s+at|will\s+take\s+place\s+at|at\s+the)\s+"
                r"([A-Z][A-Za-z0-9 .,'&-]{5,80})",
                txt,
            )
            if venue_m:
                v = venue_m.group(1)
                for stop in (" in ", " from ", " on ", " where ", " and ",
                              " which ", ",", ". ", " Subscribe",
                              " Register", " Learn", " View", " Meeting"):
                    idx = v.find(stop)
                    if idx > 4:
                        v = v[:idx]
                        break
                v = v.strip().rstrip(",.-;:")
                if 4 < len(v) < 100:
                    out["venue_name"] = v

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

        # Abstracts sub-page — for abstract submission deadline
        for suffix in ("abstracts", "program/abstracts",
                        "attend/abstract-submissions",
                        "abstracts-and-presentations"):
            abs_html = _fetch_asco_subpage(url, suffix)
            if abs_html:
                deadline = _extract_asco_abstract_deadline(abs_html)
                if deadline:
                    out["abstract_deadline"] = deadline
                    out["abstract_open"] = deadline >= date.today().isoformat()
                    break

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
