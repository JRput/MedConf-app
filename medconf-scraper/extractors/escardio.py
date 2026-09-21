"""European Society of Cardiology — congress calendar extractor.

Source 36. Server-rendered corporate CMS (not WordPress). The congress
listing (`/events/congresses/`) renders every congress — past AND future —
as static `.event-card` blocks in one page; there's no `?page=N` pagination.
We filter to upcoming ourselves by parsing each card's date range.

Detail pages are gold for deterministic extraction: every congress page
carries a set of `<meta name="esc-*">` tags (esc-title, esc-description,
esc-start-time, esc-end-time, esc-locations, esc-communities, esc-topics)
that give us title/description/dates/city/country/society/specialty
without any regex-on-prose guessing. Format (in_person/hybrid/online) comes
from a `<span class="badge ...">Onsite|Hybrid|Virtual</span>` badge that
sits right under the date block. Abstract deadlines come from
`.deadline-card` blocks with clean `<span class="start">ISO-DATE</span>`
+ `<span class="title">Label</span>` pairs.

Pricing lives on a same-society `/registration/` sub-page (own URL per
congress, not always published for congresses far out) as a genuinely
structured `<table class="pricing-table-content">`: `head-row` gives the
timeframe column labels (Early/Late/Onsite), `group-row` gives the
category (Non Members / <Society> Members / …), and `fee-row` gives the
actual line item + one price per timeframe column. We fetch that page
per-event and parse it directly rather than via the generic
`pricing_tables` helper, falling back to the generic helper only if our
structured parser finds nothing (some smaller/regional congresses may not
share this exact table markup).

Venue name (the actual building, e.g. "Allianz MiCO - Gate 4") is not on
the main page or the registration page — it shows up on a
`/helpful-information/` sub-page under a "The Congress Venue" heading, so
we fetch that too, best-effort (many congresses this far out haven't
published a venue yet — null is correct and self-heals next run).
"""

from __future__ import annotations
import json
import re
import html as _html
from datetime import date, datetime
from typing import Dict, Any, Optional, Callable, List
from urllib.parse import urljoin

from playwright.sync_api import Page

from .base import BaseExtractor
from .http_fetch import fetch_html
from .pricing_tables import parse_pricing_tables
from .specialty_classifier import classify_specialty
from logger import logger


LISTING_URL = "https://www.escardio.org/events/congresses/"

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _clean(html_fragment: str) -> str:
    if not html_fragment:
        return ""
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html_fragment,
                flags=re.DOTALL | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = _html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def _parse_card_date(text: str) -> Optional[str]:
    """"12 Nov 2026" -> "2026-11-12"."""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", text)
    if not m:
        return None
    mon = _MONTHS.get(m.group(2).lower()[:3])
    if not mon:
        return None
    return f"{int(m.group(3)):04d}-{mon:02d}-{int(m.group(1)):02d}"


def _parse_meta_date(raw: Optional[str]) -> Optional[str]:
    """esc-start-time / esc-end-time: "2026-12-03 08:00:00.000" -> "2026-12-03"."""
    if not raw:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw.strip())
    return m.group(0) if m else None


def _parse_meta_time(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    m = re.search(r"(\d{2}):(\d{2}):\d{2}", raw)
    return f"{m.group(1)}:{m.group(2)}" if m else None


def _meta_content(html_doc: str, name: str) -> Optional[str]:
    m = re.search(
        rf'<meta\s+name="{re.escape(name)}"\s+content="([^"]*)"', html_doc, re.I,
    )
    if not m:
        return None
    return _html.unescape(m.group(1)).strip() or None


def _meta_json(html_doc: str, name: str) -> Optional[Any]:
    raw = _meta_content(html_doc, name)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _extract_event_format(html_doc: str) -> Optional[str]:
    m = re.search(
        r'class="badge[^"]*"[^>]*>\s*(Onsite|Hybrid|Virtual)\s*<', html_doc, re.I,
    )
    if not m:
        return None
    return {"onsite": "in_person", "hybrid": "hybrid", "virtual": "online"}[
        m.group(1).lower()
    ]


def _extract_cpd(html_doc: str) -> Dict[str, Any]:
    """"...for a maximum of 29 European CME Credits (ECMEC(R)s)"."""
    out: Dict[str, Any] = {}
    txt = _clean(html_doc)
    m = re.search(
        r"maximum of\s+(\d+(?:\.\d+)?)\s+(?:European\s+)?CME\s+Credits",
        txt, re.I,
    )
    if m:
        try:
            out["cpd_points"] = float(m.group(1))
            out["cpd_accredited"] = True
        except ValueError:
            pass
    return out


def _extract_abstract_deadline(html_doc: str) -> Dict[str, Any]:
    """Deadline cards: <span class="start">ISO</span> ... <span class="title">Label</span>."""
    out: Dict[str, Any] = {}
    today = date.today().isoformat()
    for m in re.finditer(
        r'<span class="start">(\d{4}-\d{2}-\d{2})</span>.*?'
        r'<span class="title">([^<]*)</span>',
        html_doc, re.DOTALL,
    ):
        iso, label = m.group(1), _html.unescape(m.group(2)).strip().lower()
        if "abstract" not in label:
            continue
        if "late-breaking" in label or "late breaking" in label:
            continue
        out["abstract_deadline"] = iso
        out["abstract_open"] = iso >= today
        break
    return out


def _extract_description(html_doc: str) -> Optional[str]:
    """esc-description meta first (curated 1-2 sentence blurb), then the
    "About the Congress" section's first real paragraph, then og:description."""
    desc = _meta_content(html_doc, "esc-description")
    if desc and 30 <= len(desc) <= 700:
        return desc

    m = re.search(r'id="about-the-congress"|About the Congress', html_doc, re.I)
    if m:
        section = html_doc[m.end(): m.end() + 4000]
        stop = re.search(r"important-deadlines|class=\"badge", section)
        if stop:
            section = section[:stop.start()]
        txt = _clean(section)
        # Drop the sub-heading tagline, keep the first real sentence-shaped run
        for para in re.split(r"(?<=[.!?])\s{2,}|\n{2,}", txt):
            para = para.strip()
            if 80 <= len(para) <= 700 and "cookie" not in para.lower():
                return para
        if 80 <= len(txt) <= 700:
            return txt[:700]

    og = re.search(
        r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', html_doc, re.I,
    )
    if og:
        d = _html.unescape(og.group(1)).strip()
        if 30 <= len(d) <= 700:
            return d
    return None


def _extract_venue_from_helpful_info(html_doc: str) -> Optional[str]:
    """"The Congress Venue Allianz MiCO - Gate 4 Viale Lodovico Scarampo
    20148 Milano, Italy" -> "Allianz MiCO - Gate". Street addresses run
    straight into the venue name with no punctuation to split on, so we
    cut at the first standalone number (street number / postcode) and
    accept losing a trailing house-style number (e.g. "Gate 4") as the
    safer failure mode over swallowing the whole address. If that leaves
    something implausibly long, the address didn't have an early number
    to anchor on — bail out to None (null self-heals; a wrong guess doesn't)."""
    txt = _clean(html_doc)
    m = re.search(
        r"(?:The\s+)?Congress\s+Venue\s+(.+?)(?=\s+(?:Plan\s+[Aa]head|"
        r"See\s+on\s+the\s+map|Transport\s*:))",
        txt,
    )
    if not m:
        return None
    raw = m.group(1)
    digit_m = re.search(r"\s\d", raw)
    candidate = raw[:digit_m.start()] if digit_m else raw
    candidate = candidate.strip().rstrip(",.-;:")
    if candidate and 3 < len(candidate) <= 90:
        return candidate
    return None


# ---------------------------------------------------------------------------
# Registration-page pricing table
# ---------------------------------------------------------------------------

def _parse_registration_pricing(html_doc: str) -> List[Dict[str, Any]]:
    """Parse ESC's `.pricing-table-content` tables: a `head-row` gives the
    timeframe column labels, `group-row` rows give the category, and
    `fee-row` rows give one price per timeframe column."""
    tiers: List[Dict[str, Any]] = []
    seen: set = set()

    for table_m in re.finditer(
        r'<table class="pricing-table-content">(.*?)</table>', html_doc, re.DOTALL,
    ):
        table_html = table_m.group(1)
        col_labels: List[str] = []
        current_group = "Registration"
        for row_m in re.finditer(r'<tr class="pricing-row ([^"]*)"(.*?)</tr>',
                                   table_html, re.DOTALL):
            classes, row_html = row_m.group(1), row_m.group(2)
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL)
            if "head-row" in classes:
                col_labels = [
                    re.sub(r"\s*Until\s+.*$", "", _clean(c), flags=re.I).strip()
                    for c in cells[1:]
                ]
                continue
            if "group-row" in classes:
                title_m = re.search(r'title-text">([^<]*)<', row_html)
                if title_m:
                    current_group = _html.unescape(title_m.group(1)).strip()
                continue
            if "fee-row" not in classes:
                continue
            title_m = re.search(r'title-text">([^<]*)<', row_html)
            fee_label = _html.unescape(title_m.group(1)).strip() if title_m else ""
            if not fee_label:
                continue
            price_cells = [_clean(c) for c in cells[1:]]
            for idx, cell in enumerate(price_cells):
                price = None
                pm = re.search(r"([\d,]+(?:\.\d{1,2})?)", cell.replace("€", "€"))
                if pm:
                    try:
                        price = float(pm.group(1).replace(",", ""))
                    except ValueError:
                        price = None
                if price is None or not (1 <= price <= 50000):
                    continue
                timeframe = col_labels[idx] if idx < len(col_labels) else f"Column {idx+1}"
                category = current_group
                if fee_label and fee_label != category:
                    category = f"{category} - {fee_label}"
                label = f"Registration · {category} · {timeframe}"[:200]
                key = (label.lower(), price)
                if key in seen:
                    continue
                seen.add(key)
                tiers.append({
                    "tier_label": label,
                    "price_gbp": price,
                    "currency": "EUR",
                    "is_early_bird": "early" in timeframe.lower(),
                    "early_bird_deadline": None,
                })
    return tiers


class ESCExtractor(BaseExtractor):
    """Source 36: ESC congress calendar (escardio.org)."""

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html_doc = fetch_html(LISTING_URL, browser=getattr(self, "browser", None))
        if not html_doc:
            logger.warning("ESC listing: fetch failed")
            return None

        today = date.today().isoformat()
        shells: List[Dict[str, Any]] = []
        seen: set = set()

        for block in html_doc.split('class="card event-card')[1:]:
            href_m = re.search(r'href="([^"]+)"', block)
            title_m = re.search(r'card-title[^>]*>([^<]+)<', block)
            if not href_m or not title_m:
                continue
            href = href_m.group(1)
            if href in seen:
                continue
            if "/past-congresses/" in href:
                continue
            title = _html.unescape(title_m.group(1)).strip()

            venue_m = re.search(
                r'congress-venue.*?<h5[^>]*>\s*([^<]+?)\s*</h5>', block, re.DOTALL,
            )
            venue_raw = venue_m.group(1).strip() if venue_m else None

            date_m = re.search(
                r'congress-date.*?<p[^>]*>(.*?)</p>', block, re.DOTALL,
            )
            date_text = _clean(date_m.group(1)) if date_m else ""
            dates_found = re.findall(r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}", date_text)
            start_iso = _parse_card_date(dates_found[0]) if dates_found else None
            end_iso = (
                _parse_card_date(dates_found[-1]) if len(dates_found) > 1
                else start_iso
            )

            # Skip anything that has already ended (covers non-past-congresses
            # URLs whose current edition has already happened, e.g. the plain
            # "esc-congress" page keeps its finished-2026 content until the
            # society publishes the 2027 edition under its own path).
            if end_iso and end_iso < today:
                continue
            if not end_iso and start_iso and start_iso < today:
                continue

            desc_m = re.search(r'card-text[^>]*>([^<]+)<', block)
            description_hint = _html.unescape(desc_m.group(1)).strip() if desc_m else None

            seen.add(href)
            shells.append({
                "title": title,
                "booking_url": href,
                "source_url": href,
                "start_date": start_iso,
                "end_date": end_iso if end_iso != start_iso else None,
                "venue_raw": venue_raw,
                "description_hint": description_hint,
            })

        total_cards = html_doc.count('class="card event-card')
        logger.info(f"ESC: {len(shells)} upcoming congresses (of {total_cards} total cards)")
        return shells if shells else None

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        url = shell.get("source_url") or shell.get("booking_url") or ""
        out: Dict[str, Any] = {"event_type": "conference"}

        html_doc = ""
        try:
            html_doc = page.content()
        except Exception as e:
            logger.warning(f"ESC: page.content() failed for {url}: {e}")
        if not html_doc:
            html_doc = fetch_html(url, browser=getattr(self, "browser", None),
                                   loaded_page=page) or ""
        if not html_doc:
            logger.warning(f"ESC: no HTML for {url}; returning shell-only fields")
            if shell.get("start_date"):
                out["start_date"] = shell["start_date"]
            if shell.get("end_date"):
                out["end_date"] = shell["end_date"]
            return out

        # --- Title ---
        title_val = _meta_content(html_doc, "esc-title") or shell.get("title")
        if title_val:
            out["conference_name"] = title_val

        # --- Dates (meta authoritative, shell card as fallback) ---
        start_date = _parse_meta_date(_meta_content(html_doc, "esc-start-time")) \
            or shell.get("start_date")
        end_date = _parse_meta_date(_meta_content(html_doc, "esc-end-time")) \
            or shell.get("end_date")
        if start_date:
            out["start_date"] = start_date
        if end_date:
            out["end_date"] = end_date
        start_time = _parse_meta_time(_meta_content(html_doc, "esc-start-time"))
        if start_time:
            out["start_time"] = start_time

        # --- City / region ---
        locations = _meta_json(html_doc, "esc-locations")
        if isinstance(locations, list) and locations:
            loc = locations[0]
            city = (loc.get("city") or "").strip()
            country = (loc.get("country") or "").strip()
            if city:
                out["city"] = city
            if country:
                out["region"] = country

        # --- Format ---
        fmt = _extract_event_format(html_doc)
        if fmt:
            out["event_format"] = fmt
        elif "city" in out:
            out["event_format"] = "in_person"

        # --- Society / specialty ---
        communities = _meta_json(html_doc, "esc-communities")
        if isinstance(communities, list) and communities:
            name = communities[0].get("name") or ""
            out["society"] = re.sub(r"\s*\([A-Z]+\)\s*$", "", name).strip() or "European Society of Cardiology"
        else:
            out["society"] = "European Society of Cardiology"

        topics = _meta_json(html_doc, "esc-topics")
        specialty = None
        if isinstance(topics, list) and topics:
            specialty = topics[0]
        if not specialty:
            specialty = classify_specialty(title_val or "", _clean(html_doc)[:3000])
        out["specialty"] = specialty or "Cardiology"

        # --- CPD ---
        out.update(_extract_cpd(html_doc))

        # --- Abstract deadline ---
        out.update(_extract_abstract_deadline(html_doc))

        # --- Description ---
        desc = _extract_description(html_doc) or shell.get("description_hint")
        if desc:
            out["description"] = desc

        # --- Registration sub-page: pricing + booking_url ---
        reg_url = urljoin(url.rstrip("/") + "/", "registration/")
        reg_html = fetch_html(reg_url, browser=getattr(self, "browser", None))
        if reg_html:
            out["booking_url"] = reg_url
            tiers = _parse_registration_pricing(reg_html)
            if not tiers:
                tiers = parse_pricing_tables(reg_html, default_currency="EUR")
            if tiers:
                out["pricing_tiers"] = tiers[:80]

        # --- Venue: helpful-information sub-page (best-effort, often TBC) ---
        info_url = urljoin(url.rstrip("/") + "/", "helpful-information/")
        info_html = fetch_html(info_url, browser=getattr(self, "browser", None))
        if info_html:
            venue = _extract_venue_from_helpful_info(info_html)
            if venue:
                out["venue_name"] = venue

        return out
