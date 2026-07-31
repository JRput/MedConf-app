"""European Society of Gynaecological Oncology — Congress + Courses.

Two extractor classes, both feed into the same source-onboarding flow:
- ESGOCongressExtractor (source 21) — congress.esgo.org flagship subsite
- ESGOCoursesExtractor (source 22) — esgo.org/esgo-courses listing

Congress subsite is server-rendered WordPress with EUR HTML tables and
a keydates-deadlines sub-page. Courses page uses BEM cards (.courses__box)
with ~38 courses; each has its own detail page under /courses/<slug>/.
"""

import re
import html as _html
import httpx
from datetime import date
from typing import Dict, Any, Optional, Callable, List, Tuple
from playwright.sync_api import Page

from .base import BaseExtractor
from logger import logger


CONGRESS_HOMEPAGE = "https://congress.esgo.org/"
COURSES_LISTING = "https://www.esgo.org/esgo-courses/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
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
        logger.debug(f"ESGO fetch failed for {url}: {e}")
    return None


def _parse_month_day_year(text: str) -> Optional[str]:
    """"October 30, 2026" → 2026-10-30. "Dec 17, 2026" also works."""
    if not text:
        return None
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", text)
    if not m:
        return None
    mon = _MONTHS.get(m.group(1).lower())
    if not mon:
        mon = _MONTHS.get(m.group(1).lower()[:3] + "uary" if m.group(1).lower().startswith(("jan", "feb")) else "")
    if not mon:
        return None
    return f"{int(m.group(3)):04d}-{mon:02d}-{int(m.group(2)):02d}"


def _extract_dates_from_h2(html: str) -> Tuple[Optional[str], Optional[str]]:
    """H2 like "February 25 - 27, 2027" → (2027-02-25, 2027-02-27)."""
    m = re.search(
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+"
        r"(\d{1,2})\s*[–\-]\s*(\d{1,2}),\s*(\d{4})",
        html,
    )
    if m:
        mon = _MONTHS.get(m.group(1).lower())
        d1, d2, year = int(m.group(2)), int(m.group(3)), int(m.group(4))
        if mon:
            return f"{year:04d}-{mon:02d}-{d1:02d}", f"{year:04d}-{mon:02d}-{d2:02d}"
    return None, None


def _parse_congress_key_dates(html: str) -> Dict[str, Any]:
    """Congress key-dates page format:
        "September 1, 2026 Abstract submission and registration opens"
        "October 30, 2026 Abstract submission deadline"
        "January 15, 2027 Late-breaking abstract (LBA) submission deadline"
    Each date is followed by 1-2 lines of label.
    """
    out: Dict[str, Any] = {}
    txt = _clean(html)
    # Match "MONTH DAY, YEAR <label up to next date>"
    dates = list(re.finditer(
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+"
        r"(\d{1,2}),\s*(\d{4})",
        txt,
    ))
    for i, m in enumerate(dates):
        # Label = text from end of this date to start of next date
        end = m.end()
        start_next = dates[i + 1].start() if i + 1 < len(dates) else min(end + 200, len(txt))
        label = txt[end:start_next].strip().lower()
        mon = _MONTHS[m.group(1).lower()]
        iso = f"{int(m.group(3)):04d}-{mon:02d}-{int(m.group(2)):02d}"
        # Assign to fields based on label content
        if "abstract" in label and "deadline" in label and "late" not in label and "changes" not in label:
            out.setdefault("abstract_deadline", iso)
        elif "late-breaking" in label and "deadline" in label:
            out.setdefault("late_breaking_deadline", iso)
        elif "registration opens" in label or "abstract submission and registration opens" in label:
            out.setdefault("registration_opens", iso)
        elif "abstract submission and registration open" in label:
            out.setdefault("registration_opens", iso)
    return out


# ---------------------------------------------------------------------------
# Pricing tables — congress /attend/registration/
# ---------------------------------------------------------------------------

def _extract_eur_price(cell: str) -> Optional[float]:
    m = re.search(r"([0-9]+(?:[,.][0-9]{3})*(?:[.][0-9]+)?)\s*€", cell)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _section_heading_before(html_slice: str) -> Optional[str]:
    """Find the last H2/H3 in html_slice — used to name each pricing
    table (ESGO uses headings like "ESGO Member" / "Non-Member")."""
    matches = list(re.finditer(
        r"<h[23][^>]*>(.*?)</h[23]>",
        html_slice, re.DOTALL | re.I,
    ))
    if not matches:
        return None
    return _clean(matches[-1].group(1))


def _parse_congress_pricing(html: str) -> List[Dict[str, Any]]:
    """Parse the 4 pricing tables on /attend/registration/.
    Table shape:
        Row 0: Registration types | Early-bird | Standard | Onsite
        Row N: <role name> | 550 € | 700 € | 950 €
    Add-ons table (2nd-to-last) has "TBC" / "free" cells — skip.
    Bank-details table (last) has no prices — skipped naturally.
    """
    tiers: List[Dict[str, Any]] = []
    pos = 0
    section_default = "Registration"
    while pos < len(html):
        m = re.search(r"<table[^>]*>(.*?)</table>", html[pos:], re.DOTALL)
        if not m:
            break
        table_html = m.group(1)
        # Name = last H2/H3 before this table
        section = _section_heading_before(html[:pos + m.start()]) or section_default

        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL)
        col_labels: List[str] = []
        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL)
            if not cells:
                continue
            cell_texts = [_clean(c) for c in cells]
            first = cell_texts[0]
            if not first:
                continue
            # Header row: no €, contains "Registration types" or explicit rate labels
            if not col_labels and (
                "registration types" in first.lower()
                or all("€" not in c for c in cell_texts)
            ):
                col_labels = [
                    re.sub(r"\s*(until|from)\s+.*$", "", c, flags=re.I).strip() or f"Col {j+1}"
                    for j, c in enumerate(cell_texts[1:])
                ]
                # Skip if truly all empty or non-price-related header
                if any(col_labels) and not first.strip().lower().startswith(("account", "bank")):
                    continue
                col_labels = []
                continue
            # Data row
            category = re.sub(r"\s*\(\d+\)\s*$", "", first).strip()  # drop "(1)" footnote refs
            if not category or len(category) < 2:
                continue
            for idx, cell in enumerate(cell_texts[1:]):
                price = _extract_eur_price(cell)
                if price is None:
                    continue
                col = col_labels[idx] if idx < len(col_labels) else f"Timeframe {idx+1}"
                label = f"{section} · {category} · {col}"[:120]
                tiers.append({
                    "tier_label": label,
                    "price_gbp": price,
                    "currency": "EUR",
                    "is_early_bird": "early" in col.lower(),
                    "early_bird_deadline": None,
                })
        pos += m.end()
    return tiers


# ---------------------------------------------------------------------------
# Congress extractor (source 21)
# ---------------------------------------------------------------------------

class ESGOCongressExtractor(BaseExtractor):
    """Source 21: ESGO Annual Congress (congress.esgo.org)."""

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        return [{
            "title": "ESGO Congress",
            "booking_url": CONGRESS_HOMEPAGE,
            "source_url": CONGRESS_HOMEPAGE,
        }]

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "society": "ESGO",
            "specialty": "Gynaecological Oncology",
            "event_type": "conference",
            "is_flagship": True,
            "event_format": "in_person",
        }

        home = _fetch(CONGRESS_HOMEPAGE)
        if not home:
            logger.warning("ESGO congress: homepage fetch failed")
            return out
        home_text = _clean(home)

        # Title from H1
        h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", home, re.DOTALL)
        if h1_m:
            out["conference_name"] = _clean(h1_m.group(1))

        # Dates from H2 ("February 25 - 27, 2027")
        start, end = _extract_dates_from_h2(home_text)
        if start:
            out["start_date"] = start
        if end and end != start:
            out["end_date"] = end

        # City / region from H2 immediately after dates
        # H2 pattern: "London, United Kingdom"
        city_m = re.search(
            r"<h2[^>]*>\s*([A-Z][A-Za-z]+),\s+([A-Z][A-Za-z ]+)\s*</h2>",
            home,
        )
        if city_m:
            out["city"] = city_m.group(1).strip()
            out["region"] = city_m.group(2).strip()

        # Description from og:description or the "Join the ESGO..." H2
        og = re.search(
            r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"',
            home, re.I,
        )
        if og:
            desc = _html.unescape(og.group(1)).strip()
            if 50 <= len(desc) <= 700:
                out["description"] = desc
        if "description" not in out:
            m = re.search(r"<h2[^>]*>\s*(Join the ESGO[^<]{20,400})\s*</h2>", home)
            if m:
                out["description"] = _clean(m.group(1))[:700]

        # Key dates for abstract deadline
        kd = _fetch("https://congress.esgo.org/congress-info/keydates-deadlines/")
        if kd:
            k = _parse_congress_key_dates(kd)
            today = date.today().isoformat()
            deadline = k.get("abstract_deadline")
            if deadline:
                out["abstract_deadline"] = deadline
                out["abstract_open"] = deadline >= today

        # Pricing from /attend/registration/
        reg = _fetch("https://congress.esgo.org/attend/registration/")
        if reg:
            tiers = _parse_congress_pricing(reg)
            if tiers:
                out["pricing_tiers"] = tiers[:80]

        return out


# ---------------------------------------------------------------------------
# ESGO Courses extractor (source 22)
# ---------------------------------------------------------------------------

_COURSE_CARD_RE = re.compile(
    r'<div[^>]+class="[^"]*courses__(?:box|content)[^"]*"[^>]*>(.*?)</(?:article|div)>\s*(?=<div[^>]+class="[^"]*courses__(?:box|content)|<footer|<!-- /courses)',
    re.DOTALL | re.I,
)


def _parse_uk_date(text: str) -> Optional[str]:
    """"22.06.2026" (DD.MM.YYYY) → "2026-06-22"."""
    if not text:
        return None
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    if not m:
        return None
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"


def _parse_uk_date_range(text: str) -> Tuple[Optional[str], Optional[str]]:
    """"22.06.2026 - 23.06.2026" → (2026-06-22, 2026-06-23)."""
    parts = re.split(r"\s*-\s*", text)
    if len(parts) == 2:
        return _parse_uk_date(parts[0]), _parse_uk_date(parts[1])
    d = _parse_uk_date(text)
    return d, d


def _walk_courses_listing() -> List[Dict[str, Any]]:
    html = _fetch(COURSES_LISTING)
    if not html:
        return []
    # Each course anchor lives inside .courses__box; extract by anchor first, dedup by href
    anchor_re = re.compile(
        r'<h3[^>]*>\s*<a\s+href="([^"]+/courses/[^"?#]+)"[^>]*>([^<]+)</a>',
        re.I,
    )
    seen: set = set()
    shells: List[Dict[str, Any]] = []
    for m in anchor_re.finditer(html):
        href = m.group(1)
        if href in seen:
            continue
        seen.add(href)
        title = _html.unescape(m.group(2)).strip()
        # Look up date + address in the 800 chars AFTER the anchor
        tail = html[m.end():m.end() + 1500]
        date_m = re.search(r"<time[^>]*>(.*?)</time>", tail, re.DOTALL)
        addr_m = re.search(r"<address[^>]*>(.*?)</address>", tail, re.DOTALL)
        strip_m = re.search(
            r'<div[^>]+class="[^"]*courses__strip[^"]*"[^>]*>(.*?)</div>',
            tail, re.DOTALL,
        )
        date_txt = _clean(date_m.group(1)) if date_m else ""
        addr_txt = _clean(addr_m.group(1)) if addr_m else ""
        status = _clean(strip_m.group(1)) if strip_m else ""
        shells.append({
            "title": title,
            "booking_url": href,
            "source_url": href,
            "date_raw": date_txt,
            "address_raw": addr_txt,
            "status_raw": status,
        })
    return shells


def _classify_course_status(status_raw: str) -> Tuple[Optional[bool], Optional[str]]:
    """"Applications closed" / "SOLD OUT!" / "Registration closed" →
    (is_sold_out True) for closed; None for open/available."""
    s = (status_raw or "").lower()
    if "sold out" in s or "applications closed" in s or "registration closed" in s:
        return True, status_raw
    return None, status_raw or None


def _parse_city_country(addr: str) -> Tuple[Optional[str], Optional[str]]:
    if not addr:
        return None, None
    parts = [p.strip() for p in addr.split(",")]
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return parts[0], None


# --------------------------------------------------------------------------
# ESGO course pricing parser
#
# ESGO course detail pages carry inline HTML pricing tables in three
# format variants (found across the 3 upcoming courses):
#   Variant A (European):  "1 200,00" (space thousand, comma decimal)
#   Variant B (US-ish):    "550.00"   (no thousand, dot decimal)
#   Variant C (mixed):     "1.500 EUR" (dot thousand, no decimals, EUR suffix)
# All are EUR. Number without currency symbol → default to EUR.
# --------------------------------------------------------------------------


def _parse_esgo_number(raw: str) -> Optional[float]:
    """Accept "1 200,00", "550.00", "1.500 EUR", "50" — return float."""
    if not raw:
        return None
    s = raw.strip()
    # Strip "EUR" / "€" and whitespace
    s = re.sub(r"\s*(?:EUR|€|£|\$)\s*$", "", s, flags=re.I).strip()
    # Detect thousand separator: if there's a period AND >1 digits after it,
    # treat period as decimal; otherwise as thousand separator.
    if "," in s and "." in s:
        # Both present — assume US style (1,200.50)
        s = s.replace(",", "")
    elif "," in s:
        # European decimal (1 200,00 or 1200,50)
        s = s.replace(" ", "").replace(",", ".")
    elif re.match(r"^\d{1,3}(?:\.\d{3})+$", s):
        # 1.500 (European thousand-sep, no decimal)
        s = s.replace(".", "")
    else:
        s = s.replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return None


_FEE_HEADING_TOKENS = (
    "registration fee", "course package fee", "regular rate",
    "course fee", "pricing", "fees", "registration"
)


def _parse_course_pricing_tables(html: str) -> List[Dict[str, Any]]:
    """Walk the detail-page HTML for pricing tables. Anchors on the last
    <h2>/<h3>/<h4> before a table containing (label + numeric price)
    rows. Default currency EUR (all ESGO courses price in EUR)."""
    tiers: List[Dict[str, Any]] = []
    # Iterate <table>...</table> blocks with preceding heading context
    for m in re.finditer(r"<table[^>]*>(.*?)</table>", html, re.DOTALL):
        table_html = m.group(1)
        # Find nearest H2/H3/H4 in the 2000 chars BEFORE this table
        head_slice = html[max(0, m.start() - 2000):m.start()]
        head_matches = list(re.finditer(
            r"<h[234][^>]*>(.*?)</h[234]>", head_slice, re.DOTALL | re.I,
        ))
        # Walk backwards through candidate headings to find the last one
        # that names a pricing section. CTA links ("You can register HERE")
        # sometimes render as H3s and shouldn't be used as tier prefixes.
        heading = ""
        for candidate in reversed(head_matches):
            c = _clean(candidate.group(1))
            if any(t in c.lower() for t in _FEE_HEADING_TOKENS):
                heading = c
                break
        # Skip tables that don't have a fee-section heading AND don't
        # advertise pricing in their own header row
        if not heading and not re.search(
            r"(?i)(registration\s+fees?|regular\s+rate|course\s+package)",
            table_html,
        ):
            continue
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL)
        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL)
            if len(cells) < 2:
                continue
            label = _clean(cells[0])
            price_cell = _clean(cells[-1])
            if not label:
                continue
            # Skip header row ("Registration Fees | Regular Rate (EUR)")
            if not re.search(r"\d", price_cell):
                continue
            price = _parse_esgo_number(price_cell)
            if price is None or price <= 0:
                continue
            # Compose "<Heading> · <Label>" so the frontend can group
            if heading:
                tier_label = f"{heading} · {label}"[:120]
            else:
                tier_label = label[:120]
            tiers.append({
                "tier_label": tier_label,
                "price_gbp": price,
                "currency": "EUR",
                "is_early_bird": False,
                "early_bird_deadline": None,
            })
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


class ESGOCoursesExtractor(BaseExtractor):
    """Source 22: ESGO course listing (BEM cards, ~38 courses)."""

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        shells = _walk_courses_listing()
        if not shells:
            logger.warning("ESGO courses: 0 shells from listing")
            return None
        # Filter to upcoming (end date today or later)
        today = date.today().isoformat()
        upcoming: List[Dict[str, Any]] = []
        for s in shells:
            _, end = _parse_uk_date_range(s.get("date_raw", ""))
            if end and end >= today:
                upcoming.append(s)
        logger.info(f"ESGO courses: {len(shells)} total, {len(upcoming)} upcoming")
        return upcoming

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "society": "ESGO",
            "specialty": "Gynaecological Oncology",
            "event_type": "course",
            "event_format": "in_person",  # updated below if title/address says otherwise
        }

        title = shell.get("title") or ""

        # Dates from card <time>
        start, end = _parse_uk_date_range(shell.get("date_raw", ""))
        if start:
            out["start_date"] = start
        if end and end != start:
            out["end_date"] = end

        # City/country from card <address>
        city, country = _parse_city_country(shell.get("address_raw", ""))
        if city and city.lower() not in ("online", "virtual", "webinar"):
            out["city"] = city
        else:
            out["event_format"] = "online"
        if country:
            out["region"] = country

        # Sold-out flag from ribbon
        sold_out, note = _classify_course_status(shell.get("status_raw", ""))
        if sold_out is True:
            out["is_sold_out"] = True

        # Detail page for a proper description + inline pricing table.
        # ESGO course pages carry an HTML pricing table inside the
        # "Registration" / "Course Package Fee" section with prices in
        # EUR — variants: "1 200,00" / "550.00" / "1.500 EUR" / "50".
        detail = _fetch(shell["booking_url"])
        if detail:
            og = re.search(
                r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"',
                detail, re.I,
            )
            if og:
                desc = _html.unescape(og.group(1)).strip()
                if 50 <= len(desc) <= 700:
                    out["description"] = desc
            # If og:desc missing/short, take the first substantial <p>
            if "description" not in out:
                for p in re.findall(r"<p[^>]*>(.*?)</p>", detail, re.DOTALL):
                    txt = _clean(p)
                    if 150 <= len(txt) <= 700 and "cookie" not in txt.lower():
                        out["description"] = txt
                        break

            # Pricing table (Registration section). Prefer the shared
            # helper (handles all number formats + currency detection);
            # keep _parse_course_pricing_tables as a fallback for parity
            # with the earlier version.
            from .pricing_tables import parse_pricing_tables
            tiers = parse_pricing_tables(detail, default_currency="EUR")
            if not tiers:
                tiers = _parse_course_pricing_tables(detail)
            if tiers:
                out["pricing_tiers"] = tiers[:30]

        return out
