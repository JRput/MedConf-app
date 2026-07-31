"""Society for Immunotherapy of Cancer — SITC 2026 (41st Annual Meeting).

Server-rendered Wix flagship subsite at sitcancer.org/2026/*. Uses
abbreviated month format ("Nov. 4–8, 2026"), pricing is behind a JS
role picker for 2026 (2025 exposes plain-text $ ladder). We extract
what's stable now and let the remediator's Tier-2 explorer fill
pricing once 2026 rates go live.
"""

import re
import html as _html
import httpx
from datetime import date
from typing import Dict, Any, Optional, Callable, List, Tuple
from playwright.sync_api import Page

from .base import BaseExtractor
from logger import logger


HOMEPAGE = "https://www.sitcancer.org/2026/home"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _clean(html: str) -> str:
    if not html:
        return ""
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.DOTALL | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = _html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def _fetch(url: str, timeout: float = 25) -> Optional[str]:
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": USER_AGENT}) as c:
            r = c.get(url)
            if r.status_code == 200:
                return r.text
    except Exception as e:
        logger.debug(f"SITC fetch failed for {url}: {e}")
    return None


def _extract_event_dates(text: str) -> Tuple[Optional[str], Optional[str]]:
    """SITC uses abbreviated month: "Nov. 4–8, 2026". Also handle full."""
    m = re.search(
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December|"
        r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+"
        r"(\d{1,2})\s*[–\-]\s*(\d{1,2}),?\s+(\d{4})",
        text,
    )
    if m:
        mon = _MONTHS.get(m.group(1).lower())
        d1, d2, year = int(m.group(2)), int(m.group(3)), int(m.group(4))
        if mon:
            return f"{year:04d}-{mon:02d}-{d1:02d}", f"{year:04d}-{mon:02d}-{d2:02d}"
    return None, None


def _parse_us_date(s: str) -> Optional[str]:
    """"April 22, 2026" or "Jun 25, 2026" → ISO."""
    if not s:
        return None
    m = re.search(r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if not m:
        return None
    mon = _MONTHS.get(m.group(1).lower())
    if not mon:
        return None
    return f"{int(m.group(3)):04d}-{mon:02d}-{int(m.group(2)):02d}"


def _parse_abstract_dates(html: str) -> Dict[str, Any]:
    """/2026/abstracts/abstract-dates page. Look for:
       "Abstract Submission April 22, 2026–June 25, 2026"  → open + deadline
       "Late-Breaking Abstract - Clinical Only (LBA) Submission July 15, 2026"
    """
    txt = _clean(html)
    out: Dict[str, Any] = {}
    # Submission window: "Abstract Submission <date>–<date>"
    m = re.search(
        r"Abstract\s+Submission\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})\s*[–\-]\s*"
        r"([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        txt, re.I,
    )
    if m:
        opens = _parse_us_date(m.group(1))
        closes = _parse_us_date(m.group(2))
        if opens:
            out["abstract_opens_iso"] = opens
        if closes:
            out["abstract_deadline"] = closes
    # Late-breaking
    m = re.search(
        r"Late[\-\s]?Breaking\s+Abstract[^.]{0,120}"
        r"([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        txt, re.I,
    )
    if m:
        lba = _parse_us_date(m.group(1))
        if lba:
            out["late_breaking_deadline"] = lba
    return out


class SITCExtractor(BaseExtractor):
    """Source 23: SITC 41st Annual Meeting flagship."""

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        return [{
            "title": "SITC 41st Annual Meeting",
            "booking_url": HOMEPAGE,
            "source_url": HOMEPAGE,
        }]

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "society": "SITC",
            "specialty": "Oncology",  # immunotherapy of cancer
            "event_type": "conference",
            "is_flagship": True,
            "event_format": "in_person",
        }

        home = _fetch(HOMEPAGE)
        if not home:
            logger.warning("SITC: homepage fetch failed")
            return out
        home_text = _clean(home)

        # 1. Title — clean "Home - SITC 2026" → "SITC 41st Annual Meeting"
        # Prefer the "41st Anniversary Annual Meeting" phrasing if present
        if "41st" in home_text and "Annual Meeting" in home_text:
            out["conference_name"] = "SITC 41st Annual Meeting 2026"
        else:
            out["conference_name"] = shell["title"]

        # 2. Event dates ("Nov. 4-8, 2026")
        start, end = _extract_event_dates(home_text)
        if start:
            out["start_date"] = start
        if end and end != start:
            out["end_date"] = end

        # 3. Venue / city — Phoenix Convention Center, Phoenix AZ
        if "Phoenix Convention Center" in home_text:
            out["venue_name"] = "Phoenix Convention Center"
        if "Phoenix" in home_text:
            out["city"] = "Phoenix"
            out["region"] = "Arizona"

        # 4. Description — grab the "Why Attend SITC 2026?" paragraph
        desc_m = re.search(
            r"Why\s+Attend\s+SITC\s+2026\??\s*([^\n]{100,700}?)(?:Find\s+out\s+what\s+SITC|The\s+Society\s+for)",
            home_text, re.I,
        )
        if desc_m:
            out["description"] = desc_m.group(1).strip()
        else:
            # Fallback: og:description
            og = re.search(
                r'<meta[^>]+(?:property|name)="og:description"[^>]+content="([^"]+)"',
                home, re.I,
            )
            if og:
                d = _html.unescape(og.group(1)).strip()
                if 50 <= len(d) <= 700:
                    out["description"] = d

        # 5. Abstract dates from /2026/abstracts/abstract-dates
        ad = _fetch("https://www.sitcancer.org/2026/abstracts/abstract-dates")
        if ad:
            k = _parse_abstract_dates(ad)
            today = date.today().isoformat()
            deadline = k.get("abstract_deadline")
            if deadline:
                out["abstract_deadline"] = deadline
                opens_iso = k.get("abstract_opens_iso")
                if opens_iso and opens_iso > today:
                    out["abstract_open"] = False
                    out["abstract_deadline_note"] = f"Opens {opens_iso}"
                else:
                    out["abstract_open"] = deadline >= today

        # 6. Pricing: NOT extracted here — 2026 rates are behind a
        # JS role picker. The remediator's Tier-2 explorer will pick
        # them up once they're published in plain-text form (as 2025
        # was). Leave pricing_tiers empty; the frontend shows "Pricing
        # information not yet available."

        return out
