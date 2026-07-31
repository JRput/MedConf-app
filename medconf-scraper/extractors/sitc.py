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

        # 6. Pricing — the /2026/attendee-resources/registration page
        # is Wix-hydrated: httpx sees zero prices, but after client-side
        # render the DOM exposes the full USD ladder as plain text like
        # "Member $815 Save $270 Non-member $1,085". Use the passed
        # Playwright page to fetch + parse.
        try:
            tiers = _extract_pricing_via_playwright(page)
            if tiers:
                out["pricing_tiers"] = tiers[:80]
        except Exception as e:
            logger.warning(f"SITC: pricing extraction via Playwright failed: {e}")

        return out


# ---------------------------------------------------------------------------
# Pricing extraction (Wix-hydrated Playwright required)
# ---------------------------------------------------------------------------

_PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")


def _parse_registration_body_text(body_text: str) -> List[Dict[str, Any]]:
    """Parse SITC's registration page body.innerText which arranges tiers
    as a sequence of blocks like:

        Friday, Saturday & Sunday · Nov. 6-8
        CURRENT RATE
        EARLY
        Ends Aug. 24
        Member
        $815
        Save $270
        Non-member
        $1,085
        REGULAR
        Ends Oct. 30
        Member
        $1,015
        ...

    Emit one tier per (section × band × role) with composite label
    "[Section] · [Role] · [Band]".
    """
    tiers: List[Dict[str, Any]] = []
    lines = [ln.strip() for ln in body_text.splitlines() if ln.strip()]

    _BANDS = {"EARLY", "REGULAR", "ONSITE", "VIRTUAL", "CURRENT RATE"}
    section: Optional[str] = None
    band: Optional[str] = None
    band_deadline: Optional[str] = None

    i = 0
    while i < len(lines):
        line = lines[i]
        # Section header — line containing "·" and a month name
        if "·" in line and re.search(
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", line
        ) and "$" not in line:
            section = line.strip()
            i += 1
            continue
        # Band header
        if line.upper() in _BANDS:
            band = line.upper()
            band_deadline = None
            # Next line often "Ends Aug. 24" or "Starts Oct. 31"
            if i + 1 < len(lines) and re.match(
                r"(?i)(Ends|Starts|Open\s+through)\s+", lines[i + 1]
            ):
                band_deadline = lines[i + 1]
                i += 1
            i += 1
            continue
        # Role line: "Member" or "Non-member" followed by a price line
        if line in ("Member", "Non-member") and i + 1 < len(lines):
            price_m = _PRICE_RE.match(lines[i + 1])
            if price_m and section and band:
                price = float(price_m.group(1).replace(",", ""))
                # Skip "Save $X" (discount amounts)
                role = line
                # Skip if a "Save $" line — we only want the base price
                if band == "CURRENT RATE":
                    band_label = "Current Rate"
                else:
                    band_label = band.title()
                label = f"{section} · {role} · {band_label}"
                # Trim overly long labels
                label = label[:120]
                tiers.append({
                    "tier_label": label,
                    "price_gbp": price,
                    "currency": "USD",
                    "is_early_bird": band in ("EARLY", "CURRENT RATE"),
                    "early_bird_deadline": None,
                })
                i += 2
                continue
        i += 1
    # Dedupe by (label, price)
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for t in tiers:
        key = (t["tier_label"], t["price_gbp"])
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def _extract_pricing_via_playwright(page: Page) -> List[Dict[str, Any]]:
    """Load the SITC registration page in the existing Playwright browser,
    wait for Wix hydration, then parse the body text."""
    url = "https://www.sitcancer.org/2026/attendee-resources/registration"
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    # Wix takes ~5-8s to hydrate pricing widgets
    page.wait_for_timeout(8000)
    body = page.evaluate("document.body.innerText")
    if not body or "$" not in body:
        logger.warning("SITC: registration page has no $ after hydration")
        return []
    return _parse_registration_body_text(body)
