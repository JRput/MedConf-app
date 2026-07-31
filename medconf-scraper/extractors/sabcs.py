"""San Antonio Breast Cancer Symposium — flagship extractor.

Single-event flagship on a WordPress subsite. Pattern mirrors AACR:
- `list_shells_override()` returns one shell (URL IS the event page)
- `extract_detail()` walks four sub-pages:
    /               — title, dates, venue, description (og:description)
    /key-dates/     — plain-text dated list ("July 13 : Abstract Submission Deadline")
    /registration-2/— 5 HTML tables in USD (In-Person, Virtual, Student, etc)
    /abstracts/     — backup abstract-status text

Composite pricing labels emit as
    "[Section] · [Registration Category] · [Timeframe]"
so the frontend's tabbed PricingTable groups Regular/Member/UT-Health/etc
by section, and Early/Advance/Late as the sub-filter within each.
"""

import re
import html as _html
import httpx
from datetime import date
from typing import Dict, Any, Optional, Callable, List, Tuple
from playwright.sync_api import Page

from .base import BaseExtractor
from logger import logger


HOMEPAGE = "https://sabcs.org/"
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
        logger.debug(f"SABCS fetch failed for {url}: {e}")
    return None


def _parse_us_date(text: str, default_year: int) -> Optional[str]:
    """Parse "July 13" (year inferred), "July 13, 2026", or "December 8-11, 2026"."""
    if not text:
        return None
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2})(?:-\d{1,2})?,?\s*(\d{4})?", text)
    if not m:
        return None
    mon = _MONTHS.get(m.group(1).lower())
    if not mon:
        return None
    day = int(m.group(2))
    year = int(m.group(3)) if m.group(3) else default_year
    return f"{year:04d}-{mon:02d}-{day:02d}"


def _extract_event_dates(homepage_text: str) -> Tuple[Optional[str], Optional[str]]:
    """Homepage carries "December 8–11, 2026" → returns (2026-12-08, 2026-12-11)."""
    m = re.search(
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+"
        r"(\d{1,2})\s*[–\-]\s*(\d{1,2}),\s*(\d{4})",
        homepage_text,
    )
    if m:
        mon = _MONTHS.get(m.group(1).lower())
        d1, d2, year = int(m.group(2)), int(m.group(3)), int(m.group(4))
        if mon:
            return (
                f"{year:04d}-{mon:02d}-{d1:02d}",
                f"{year:04d}-{mon:02d}-{d2:02d}",
            )
    return None, None


def _extract_venue_city(homepage_text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Homepage/registration pages mention "San Antonio, Texas" prominently.
    Convention centre name: "Henry B. Gonzalez Convention Center" for SABCS."""
    if "Henry B. Gonzalez" in homepage_text or "Convention Center" in homepage_text:
        venue = "Henry B. Gonzalez Convention Center"
    else:
        venue = None
    if "San Antonio" in homepage_text:
        return venue, "San Antonio", "Texas"
    return venue, None, None


# ---------------------------------------------------------------------------
# /key-dates/ parser — "April 1 : SABCS 2025 Presentations Available Online"
# ---------------------------------------------------------------------------

_KEY_DATE_RE = re.compile(
    r"([A-Za-z]+)\s+(\d{1,2})\s*:\s*([^\n]{5,120})"
)


def _parse_key_dates(html: str, event_year: int) -> Dict[str, Any]:
    """Extract abstract_deadline / late_breaking_deadline / registration_opens
    from the plain-text "April 1 : Label" pattern."""
    out: Dict[str, Any] = {}
    txt = _clean(html)
    for m in _KEY_DATE_RE.finditer(txt):
        mon_name = m.group(1).lower()
        if mon_name not in _MONTHS:
            continue
        day = int(m.group(2))
        label = m.group(3).strip()
        iso = f"{event_year:04d}-{_MONTHS[mon_name]:02d}-{day:02d}"
        ll = label.lower()
        if re.search(r"abstract\s+submission\s+deadline", ll) and "late" not in ll and "late-breaking" not in ll:
            out.setdefault("abstract_deadline", iso)
            out.setdefault("abstract_deadline_raw", label)
        elif re.search(r"late[\-\s]?breaking\s+abstract\s+submission\s+deadline", ll):
            out.setdefault("late_breaking_deadline", iso)
        elif re.search(r"abstract\s+submission\s+opens?", ll):
            out.setdefault("abstract_opens", label)
        elif re.search(r"early\s+registration\s+deadline", ll):
            out.setdefault("early_registration_deadline", iso)
    return out


# ---------------------------------------------------------------------------
# Pricing table parser
# ---------------------------------------------------------------------------

def _extract_dollar_price(text: str) -> Optional[float]:
    m = re.search(r"\$\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{2})?)", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _table_section_name(preceding_text: str) -> Optional[str]:
    """Find the H2/H3 immediately before a table — SABCS uses those as
    section names (In-Person Registration, Virtual Registration, etc)."""
    m = re.search(
        r"<h[23][^>]*>([^<]{5,80})</h[23]>[^<]*(?:<[^h][^>]*>[^<]*)*$",
        preceding_text[-2000:], re.DOTALL | re.I,
    )
    if m:
        cand = _html.unescape(m.group(1)).strip()
        # Filter out section titles that aren't pricing-related
        if any(k in cand.lower() for k in ("registration", "rates", "fees", "virtual", "hotel")) \
                and "hotel" not in cand.lower():
            return cand
    return None


def _parse_registration_tables(html: str) -> List[Dict[str, Any]]:
    """Parse the 5 pricing tables on /registration-2/. Each has:
      Row 1: header — "Registration Category | Early | Advance | Late"
      Data rows: "<Category> | $X | $Y | $Z"
    Emit one tier per (row × column) with composite label like
        "In-Person Registration · Regular Registration · Early Registration"
    """
    tiers: List[Dict[str, Any]] = []
    # Iterate tables with their preceding context so we can name them
    pos = 0
    while pos < len(html):
        m = re.search(r"<table[^>]*>(.*?)</table>", html[pos:], re.DOTALL)
        if not m:
            break
        table_html = m.group(1)
        section = _table_section_name(html[:pos + m.start()]) or "Registration"

        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL)
        col_labels: List[str] = []
        for i, row in enumerate(rows):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL)
            if not cells:
                continue
            cell_texts = [_clean(c) for c in cells]
            first = cell_texts[0]
            if not first:
                continue
            # Header row usually contains "Registration Category" or "$"-free cells
            if not col_labels and (
                "registration category" in first.lower()
                or all("$" not in c for c in cell_texts[1:])
            ):
                # Column labels — normalise "(7/16 to 9/25)" out of the header
                col_labels = [
                    re.sub(r"\s*\([^)]+\)", "", c).strip() or f"Col {j+1}"
                    for j, c in enumerate(cell_texts[1:])
                ]
                continue
            # Data row — one tier per priced column
            category = re.split(r"\s*\(", first)[0].strip()
            for idx, cell in enumerate(cell_texts[1:]):
                price = _extract_dollar_price(cell)
                if price is None:
                    continue
                col = (
                    col_labels[idx] if idx < len(col_labels)
                    else f"Timeframe {idx+1}"
                )
                # Compress "In-Person Early Registration" → "Early Registration"
                col = re.sub(r"^In-?Person\s+", "", col, flags=re.I)
                label = f"{section} · {category} · {col}"[:120]
                tiers.append({
                    "tier_label": label,
                    "price_gbp": price,
                    "currency": "USD",
                    "is_early_bird": "early" in col.lower(),
                    "early_bird_deadline": None,
                })
        pos += m.end()
    return tiers


class SABCSExtractor(BaseExtractor):
    """Source 20: San Antonio Breast Cancer Symposium — flagship WordPress site."""

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        return [{
            "title": "San Antonio Breast Cancer Symposium",
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
            "society": "SABCS",
            "specialty": "Oncology",  # Breast cancer specifically, but Oncology is the parent
            "event_type": "conference",
            "is_flagship": True,
            "event_format": "hybrid",  # SABCS runs in-person + virtual
        }

        home_html = _fetch(HOMEPAGE)
        if not home_html:
            logger.warning("SABCS: homepage fetch failed")
            return out
        home_text = _clean(home_html)

        # 1. Title from H1 (strip trademark symbol + trailing spaces)
        h1_m = re.search(r"<h1[^>]*>([^<]+)</h1>", home_html)
        if h1_m:
            title = _html.unescape(h1_m.group(1)).replace("®", "").strip()
            out["conference_name"] = re.sub(r"\s+", " ", title)

        # 2. Description from og:description
        og_m = re.search(
            r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"',
            home_html, re.I,
        )
        if og_m:
            desc = _html.unescape(og_m.group(1)).strip()
            if 50 <= len(desc) <= 700:
                out["description"] = desc

        # 3. Dates
        start, end = _extract_event_dates(home_text)
        if start:
            out["start_date"] = start
        if end and end != start:
            out["end_date"] = end
        event_year = int(start[:4]) if start else date.today().year

        # 4. Venue / city / region
        venue, city, region = _extract_venue_city(home_text)
        if venue:
            out["venue_name"] = venue
        if city:
            out["city"] = city
        if region:
            out["region"] = region

        # 5. Key dates for abstract deadlines
        kd_html = _fetch("https://sabcs.org/key-dates/")
        if kd_html:
            kd = _parse_key_dates(kd_html, event_year)
            today = date.today().isoformat()
            deadline = kd.get("abstract_deadline")
            if deadline:
                out["abstract_deadline"] = deadline
                out["abstract_open"] = deadline >= today
            elif kd.get("abstract_opens"):
                out["abstract_open"] = False
                out["abstract_deadline_note"] = f"Abstract submission opens {kd['abstract_opens']}"

        # 6. Pricing from /registration-2/
        reg_html = _fetch("https://sabcs.org/registration-2/")
        if reg_html:
            tiers = _parse_registration_tables(reg_html)
            if tiers:
                out["pricing_tiers"] = tiers[:60]  # cap generous but bounded

        return out
