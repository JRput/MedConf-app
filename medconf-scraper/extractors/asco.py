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

        # No pricing / abstracts published this far in advance — they'll be
        # remediated in later months when ASCO posts the info.
        return out
