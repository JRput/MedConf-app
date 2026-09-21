# extractors/rcpe.py
"""
Royal College of Physicians of Edinburgh (RCPE) — detail-page extractor.

Drupal site (server-rendered, plain HTML — no JS framework needed for
either listing or detail). Listing lives at

    https://www.rcpe.ac.uk/events?page=0..2   (~12 items/page, 3 pages seen)

rendered as Drupal Views rows:

    <div class="views-row">
      <a class="node node--type-event node--view-mode-teaser
                card-event-teaser" href="/events/<slug>">
        ...type icon (Conferences & Symposia / External Events / ...)...
        <h3 class="card-event-teaser__title"><span>Title</span></h3>
        <details class="card-event-teaser__more-detail">
          <div class="card-event-teaser__more-detail-content">
            <div class="icon-detail-item">…icon--calendar…Fri 25 Sep 2026</div>
            <div class="icon-detail-item">…icon--clock…09:25 - 17:00</div>
            <div class="icon-detail-item online">…icon--monitor…Online</div>
            <div class="icon-detail-item">…icon--map-pin…Venue, City</div>
            <div class="icon-detail-item"><img cpd-lozenge…/> + 6</div>
          </div>
        </details>
      </a>
    </div>

Detail pages repeat that exact "icon-detail-item" block TWICE (once in a
mobile-only `.event-information` copy, once in the desktop sidebar copy) —
harmless to parse both since the content is identical; a dict keyed by
field just gets the same value written twice.

Below the hero there's a tabbed content area: `#overview`, `#programme`,
`#fees`, occasionally `#live-links` (Evening Medical Updates), then
`#further-information`. All tab panes are server-rendered plain HTML (no
JS needed to read hidden tabs) with stable, non-nested `<div id="...">`
wrappers, so a "capture up to the next `<div id=`" slice reliably isolates
one tab's content.

Fees tables are always plain `<label> | £NNN` two-column tables — no need
for the shared pricing_tables.py heading-detection helper (which requires
an <h2-4> fee heading; RCPE's "Fees" label is a tab link, not a heading,
so that helper would find 0 tiers here). We parse the `#fees` tab's own
table(s) directly instead.

Sold-out events replace the "Book now" button with:
    <div class="event-notification-text ...">Fully Booked</div>

Event categories seen (tag-lozenge text): "Conferences & Symposia",
"External Events" (third-party societies renting an RCPE-branded page,
often via Eventbrite), "Evening Medical Updates" (block-booking parent —
each individual EMU date is ALSO its own separate listing row/detail page,
so the parent isn't turned into a course+sessions row here — it's just
another single-date conference row), "College Meetings & Ceremonies"
(MRCP(UK) Diploma Ceremonies — real scheduled/bookable events with dates
and venues, kept rather than filtered as junk; flagged in concerns since
they carry no CPD value).
"""

import re
import html as _htmlmod
import json as _json
from datetime import date
from typing import Dict, Any, Optional, Callable, List, Tuple
from playwright.sync_api import Page

from .base import BaseExtractor
from .http_fetch import fetch_html
from .specialty_classifier import classify_specialty
from .abstract_classifier import extract_abstract_info
from logger import logger


LISTING_URL = "https://www.rcpe.ac.uk/events"
BASE_URL = "https://www.rcpe.ac.uk"
MAX_PAGES = 6  # recon observed exactly 3 (?page=0..2); generous ceiling in case more get added

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_RE = (
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)"
)

UK_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)

# RCPE's own building — appears with no city/comma in the venue text.
_KNOWN_VENUES = {
    "royal college of physicians of edinburgh": ("Royal College of Physicians of Edinburgh", "Edinburgh", "Scotland"),
}

_UK_REGIONS = {
    "edinburgh": "Scotland", "glasgow": "Scotland", "aberdeen": "Scotland", "dundee": "Scotland",
    "dunblane": "Scotland", "stirling": "Scotland", "inverness": "Scotland", "perth": "Scotland",
    "london": "London", "manchester": "North West England", "liverpool": "North West England",
    "leeds": "Yorkshire and the Humber", "sheffield": "Yorkshire and the Humber",
    "york": "Yorkshire and the Humber", "newcastle": "North East England",
    "birmingham": "West Midlands", "bristol": "South West England", "exeter": "South West England",
    "plymouth": "South West England", "cardiff": "Wales", "swansea": "Wales",
    "belfast": "Northern Ireland", "cambridge": "East of England", "norwich": "East of England",
    "oxford": "South East England", "brighton": "South East England", "leicester": "East Midlands",
    "nottingham": "East Midlands", "southampton": "South East England",
}


def _infer_uk_region(city: str) -> Optional[str]:
    c = (city or "").lower()
    for key, val in _UK_REGIONS.items():
        if key in c:
            return val
    return None


def _clean(html_frag: str) -> str:
    if not html_frag:
        return ""
    t = re.sub(r"<[^>]+>", " ", html_frag)
    t = _htmlmod.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


_ICON_DIV_RE = re.compile(r'<div class="icon-detail-item[^"]*">(.*?)</div>', re.DOTALL)


def _parse_icon_details(html_frag: str) -> Dict[str, Any]:
    """Reads the repeated 'icon-detail-item' blocks (listing cards AND
    detail-page hero, mobile+desktop copies) into a flat field dict.
    Safe to call on a whole page — the class is only used for these
    date/time/format/venue/CPD chips, nowhere else on the site."""
    out: Dict[str, Any] = {}
    for m in _ICON_DIV_RE.finditer(html_frag or ""):
        div_html = m.group(1)
        text = _clean(div_html)
        if not text:
            continue
        if "cpd-lozenge" in div_html:
            num_m = re.search(r"(\d+)", text)
            if num_m:
                out["cpd_points"] = int(num_m.group(1))
        elif "icon--calendar" in div_html:
            out.setdefault("date_text", text)
        elif "icon--clock" in div_html:
            out.setdefault("time_text", text)
        elif "icon--monitor" in div_html:
            out["online"] = True
        elif "icon--map-pin" in div_html:
            out.setdefault("venue_text", text)
    return out


def _parse_date_text(text: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """'Fri 25 Sep 2026' -> (iso, iso). 'Thu 1 - Fri 2 Oct 2026 | 2 Day Event'
    -> (iso_day1, iso_day2). Trailing '| N Day Event' markers are dropped."""
    if not text:
        return None, None
    text = text.split("|")[0].strip()

    range_m = re.search(
        r"(\d{1,2})(?:st|nd|rd|th)?\s*-\s*(?:\w{3,9}\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+"
        + _MONTH_RE + r"\s+(\d{4})",
        text, re.I,
    )
    if range_m:
        d1, d2, mon, year = range_m.groups()
        mon_num = _MONTHS.get(mon.lower()[:3] if mon.lower() != "sept" else "sept")
        mon_num = mon_num or _MONTHS.get(mon.lower()[:3])
        if mon_num:
            try:
                start = date(int(year), mon_num, int(d1))
                end = date(int(year), mon_num, int(d2))
                return start.isoformat(), end.isoformat()
            except ValueError:
                pass

    single_m = re.search(
        r"(\d{1,2})(?:st|nd|rd|th)?\s+" + _MONTH_RE + r"\s+(\d{4})", text, re.I,
    )
    if single_m:
        d, mon, year = single_m.groups()
        mon_num = _MONTHS.get(mon.lower()[:3])
        if mon_num:
            try:
                dt = date(int(year), mon_num, int(d))
                return dt.isoformat(), dt.isoformat()
            except ValueError:
                pass
    return None, None


def _parse_time_text(text: Optional[str]) -> Optional[str]:
    """'09:25 - 17:00' / 'Thu 10:25 - Fri 13:30' -> '09:25' (start time)."""
    if not text:
        return None
    m = re.search(r"\b(\d{1,2}:\d{2})\b", text)
    return m.group(1) if m else None


class RCPEExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing override — plain server-rendered Drupal Views markup, no
    # browser needed (recon: platform=static_html, js_required=false).
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        shells: List[Dict[str, Any]] = []
        seen_urls = set()
        browser = getattr(self, "browser", None)
        try:
            for page_num in range(MAX_PAGES):
                url = LISTING_URL if page_num == 0 else f"{LISTING_URL}?page={page_num}"
                html = fetch_html(url, browser=browser)
                if not html:
                    break
                rows = re.findall(
                    r'<div class="views-row">(.*?)(?=<div class="views-row"|<nav class="vsc-pager"|$)',
                    html, re.DOTALL,
                )
                if not rows:
                    break
                found_new = False
                for row_html in rows:
                    href_m = re.search(r'card-event-teaser"\s+href="\s*([^"]+)"', row_html)
                    title_m = re.search(
                        r'card-event-teaser__title">\s*<span[^>]*>([^<]+)</span>', row_html,
                    )
                    if not href_m or not title_m:
                        continue
                    href = href_m.group(1).strip()
                    booking_url = href if href.startswith("http") else BASE_URL + href
                    if booking_url in seen_urls:
                        continue
                    seen_urls.add(booking_url)
                    found_new = True
                    title = _clean(title_m.group(1))
                    type_m = re.search(r'tag-lozenge">\s*([^<]+)<', row_html)
                    event_type_hint = _clean(type_m.group(1)) if type_m else None
                    icons = _parse_icon_details(row_html)
                    start_date, end_date = _parse_date_text(icons.get("date_text"))
                    shells.append({
                        "title": title,
                        "booking_url": booking_url,
                        "start_date": start_date,
                        "end_date": end_date,
                        "start_time": _parse_time_text(icons.get("time_text")),
                        "is_sold_out": False,  # refined per-page in extract_detail
                        "event_type_hint": event_type_hint,
                        "page_index": page_num,
                    })
                # Stop once a page yields nothing new (avoids looping past
                # the last real page if MAX_PAGES overshoots the pager).
                if not found_new:
                    break
        except Exception as e:
            logger.warning(f"RCPE listing override failed: {e}")
            return None

        if not shells:
            logger.warning("RCPE listing override found 0 shells; falling back to DOM walker")
            return None

        logger.info(f"RCPE: {len(shells)} shells found across listing pages")
        return shells

    # ------------------------------------------------------------------ #
    # Detail page
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        try:
            html = page.content()
        except Exception as e:
            logger.warning(f"RCPE: page.content() failed, falling back to fetch_html: {e}")
            html = fetch_html(shell.get("booking_url", ""), loaded_page=page) or ""

        # Real title from the h1, never the listing shell text
        h1_m = re.search(r'<h1[^>]*>.*?<span[^>]*>([^<]+)</span>', html, re.DOTALL)
        result["conference_name"] = _clean(h1_m.group(1)) if h1_m else shell.get("title")

        # Event category (tag-lozenge) -> event_type
        type_m = re.search(r'event-information__type">\s*<div class="tag-lozenge">\s*([^<]+)<', html)
        category = _clean(type_m.group(1)) if type_m else None
        result["event_type"] = self._classify_event_type(category)

        # Dates / time / online / venue / CPD — from the icon-detail-item chips
        icons = _parse_icon_details(html)
        start_date, end_date = _parse_date_text(icons.get("date_text"))
        result["start_date"] = start_date or shell.get("start_date")
        result["end_date"] = end_date or shell.get("end_date") or result["start_date"]
        result["start_time"] = _parse_time_text(icons.get("time_text")) or shell.get("start_time")

        result.update(self._extract_venue(icons.get("venue_text"), bool(icons.get("online"))))

        cpd_points = icons.get("cpd_points")
        result["cpd_points"] = cpd_points
        result["cpd_accredited"] = bool(cpd_points) or bool(re.search(r"\bCPD\b", html))

        # Sold out — "Book now" button replaced with an event-notification-text
        notify_m = re.search(r'event-notification-text[^"]*">\s*([^<]+)<', html)
        result["is_sold_out"] = bool(
            notify_m and re.search(r"fully booked|sold out|waiting list", notify_m.group(1), re.I)
        )

        # Pricing (deterministic — the #fees tab's own plain-number tables)
        result["pricing_tiers"] = self._extract_pricing(html)

        # Abstracts — only bother parsing if the page actually mentions one
        # (RCPE's "College Meetings & Ceremonies" / EMU pages never do).
        plain_text = _clean(html)
        if re.search(r"abstract", plain_text, re.I):
            is_open, deadline = extract_abstract_info(plain_text)
            result["abstract_open"] = is_open
            result["abstract_deadline"] = deadline.isoformat() if deadline else None
        else:
            result["abstract_open"] = False
            result["abstract_deadline"] = None

        # Soft fields (LLM + deterministic fallback)
        result.update(self._extract_soft_fields(html, shell, llm_call))

        return result

    # ------------------------------------------------------------------ #
    # Event type classification
    # ------------------------------------------------------------------ #
    @staticmethod
    def _classify_event_type(category: Optional[str]) -> str:
        c = (category or "").lower()
        if "course" in c:
            return "course"
        if "workshop" in c:
            return "workshop"
        return "conference"

    # ------------------------------------------------------------------ #
    # Venue / city / region / format
    # ------------------------------------------------------------------ #
    def _extract_venue(self, venue_text: Optional[str], is_online: bool) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        text = (venue_text or "").strip()

        # The map-pin chip is sometimes the ONLY chip even for a hybrid
        # event — RCPE folds it into the venue text itself ("Hybrid: Online
        # and <venue>", "<venue> & Online") rather than also showing a
        # separate monitor icon. Detect that wording here too.
        text_mentions_online = bool(re.search(r"\bonline\b", text, re.I))
        is_online = is_online or text_mentions_online

        # Strip the "Hybrid:" / "Online and" framing so it doesn't pollute
        # the venue name / city parsing below.
        venue_only = re.sub(r"^\s*hybrid\s*:\s*", "", text, flags=re.I)
        venue_only = re.sub(r"\bonline\s+and\b", "", venue_only, flags=re.I)
        venue_only = re.sub(r"[&,]?\s*\bonline\b\s*$", "", venue_only, flags=re.I)
        venue_only = venue_only.strip(" ,-")

        if is_online and not venue_only:
            out["event_format"] = "online"
            out["venue_name"] = None
            out["city"] = None
            out["region"] = None
            return out

        if not venue_only:
            out["event_format"] = "online" if is_online else None
            return out

        # Known RCPE-branded venue (own building — no comma/city in the text)
        venue_name, city, region = None, None, None
        for key, (v, c, r) in _KNOWN_VENUES.items():
            if key in venue_only.lower():
                venue_name, city, region = v, c, r
                break

        if not venue_name:
            parts = [p.strip() for p in venue_only.split(",") if p.strip()]
            venue_name = venue_only
            if parts:
                candidate_city = UK_POSTCODE_RE.sub("", parts[-1]).strip(" ,")
                city = candidate_city or (parts[0] if len(parts) == 1 else None)
                # Prefer a recognised UK town/city name if one appears anywhere
                for known_city in _UK_REGIONS:
                    if re.search(rf"\b{re.escape(known_city)}\b", venue_only, re.I):
                        city = known_city.title()
                        break
            region = _infer_uk_region(city) if city else None

        out["event_format"] = "hybrid" if is_online else "in_person"
        out["venue_name"] = venue_name
        out["city"] = city
        out["region"] = region
        return out

    # ------------------------------------------------------------------ #
    # Pricing — plain <label>|£X tables inside the #fees tab
    # ------------------------------------------------------------------ #
    def _extract_pricing(self, html: str) -> List[Dict[str, Any]]:
        fees_m = re.search(r'<div id="fees"[^>]*>(.*?)<div id="', html, re.DOTALL)
        if not fees_m:
            # Last tab on the page (no further-information/live-links after it)
            fees_m = re.search(r'<div id="fees"[^>]*>(.*)$', html, re.DOTALL)
        fees_html = fees_m.group(1) if fees_m else ""
        if not fees_html:
            return []

        tiers: List[Dict[str, Any]] = []

        # Layout B: no table at all — plain prose (e.g. Diploma Ceremonies:
        # "The Ceremony ... will be free of charge ... a charge of £35 per
        # guest"). Catches simple single-fee/add-on mentions without
        # inventing anything beyond what the text says.
        if "<table" not in fees_html:
            plain = _clean(fees_html)
            for pm in re.finditer(r"charge of\s*£\s*([0-9]+(?:\.[0-9]{2})?)\s*per\s+(\w+)", plain, re.I):
                tiers.append({
                    "tier_label": pm.group(2).strip().title(),
                    "price_gbp": float(pm.group(1)),
                    "is_early_bird": False,
                    "early_bird_deadline": None,
                })
            if re.search(r"\bfree of charge\b", plain, re.I) and not any(
                t["price_gbp"] == 0.0 for t in tiers
            ):
                tiers.append({
                    "tier_label": "Standard",
                    "price_gbp": 0.0,
                    "is_early_bird": False,
                    "early_bird_deadline": None,
                })
            return tiers

        for table_m in re.finditer(r"<table[^>]*>(.*?)</table>", fees_html, re.DOTALL):
            table_html = table_m.group(1)
            for row_m in re.finditer(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL):
                cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_m.group(1), re.DOTALL)
                if len(cells) < 2:
                    continue
                label = _clean(cells[0])
                if not label:
                    continue
                price = None
                for cell_html in reversed(cells[1:]):
                    price = self.parse_gbp(_clean(cell_html))
                    if price is not None:
                        break
                if price is None:
                    continue
                if label.lower() in {"category", "type", "rate", "amount", "price", "cost", "fee"}:
                    continue
                tiers.append({
                    "tier_label": label[:120],
                    "price_gbp": price,
                    "is_early_bird": bool(re.search(r"early[- ]?bird", label, re.I)),
                    "early_bird_deadline": None,
                })

        # Dedupe (label, price) — desktop/mobile duplication doesn't apply
        # here (fees tab renders once), but guards against repeated rows.
        seen = set()
        deduped = []
        for t in tiers:
            key = (t["tier_label"], t["price_gbp"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(t)
        return deduped

    # ------------------------------------------------------------------ #
    # Description + specialty (LLM, small prompt, heuristic fallback)
    # ------------------------------------------------------------------ #
    def _extract_soft_fields(
        self,
        html: str,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        overview_m = re.search(r'<div id="overview"[^>]*>(.*?)<div id="', html, re.DOTALL)
        overview_html = overview_m.group(1) if overview_m else ""
        text = _clean(overview_html)[:3000]

        title = shell.get("title") or ""
        prompt = f"""You are summarising a single medical conference/event detail page. Extract ONLY two fields.

EVENT TITLE: {title}

PAGE BODY:
{text}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the page text" or null,
  "specialty": "primary clinical specialty (e.g. Cardiology, Infectious Disease, Respiratory)" or null
}}"""

        result: Dict[str, Any] = {}
        raw = llm_call(prompt)
        if raw:
            raw = raw.strip()
            if raw.startswith("```"):
                parts = raw.split("```")
                if len(parts) >= 3:
                    raw = parts[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                    raw = raw.strip()
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                raw = m.group(0)
            try:
                parsed = _json.loads(raw)
                result = {
                    "description": parsed.get("description"),
                    "specialty": parsed.get("specialty"),
                }
            except _json.JSONDecodeError as e:
                logger.warning(f"RCPE soft-fields JSON parse failed: {e}; raw[:200]={raw[:200]!r}")

        # Heuristic specialty backstop
        if not result.get("specialty"):
            heuristic = classify_specialty(title, text)
            if heuristic:
                result["specialty"] = heuristic

        # Description fallback — first clean chunk of the Overview text
        if not result.get("description") and text:
            if len(text) > 40:
                result["description"] = self._truncate_to_sentence(text, 320)

        return result

    @staticmethod
    def _truncate_to_sentence(text: str, max_chars: int = 320) -> str:
        text = text.strip()
        if len(text) <= max_chars:
            return text
        cut = text[:max_chars]
        candidates = [cut.rfind(p + " ") for p in (".", "!", "?")]
        last_end = max(candidates)
        if last_end > max_chars * 0.5:
            return cut[: last_end + 1].rstrip()
        return cut.rstrip() + "…"
