"""
Association of Coloproctology of Great Britain and Ireland (ACPGBI) — extractor.

Site (acpgbi.org.uk) is a custom ASP.NET CMS ("lmsitestarterduke"), not
WordPress despite the .org.uk look — server-rendered, no JS required for
either listing or detail pages.

Listing is a YEAR-scoped community events calendar at:

    https://www.acpgbi.org.uk/events            (defaults to the current year,
                                                   from today forward)
    https://www.acpgbi.org.uk/events/date/<YYYY> (any specific year)

There is no `?page=N` pagination within a year — each year is one page with
every remaining event for that year in `<div class="date_row">` cards:

    <div class="date_row col-xs-12 alternate_row">
      <div class="row">
        <div class="col-sm-4">26 Sep 2026</div>                         <- date
        <div class="col-sm-4"><a href="/events/1742/slug">Title</a></div> <- title+url
        <div class="col-sm-4">Venue, Address</div>                       <- location (blank for webinars)
      </div>
    </div>

Because events run YEARS ahead (the 2027 ACPGBI Annual Meeting is only
visible via `/events/date/2027`, not on the default `/events` page),
`list_shells_override()` walks forward year by year from the current year
until a year page carries no event links, capped at 6 years as a safety
stop.

Date-cell formats observed (day/month names, en-dash `&ndash;` ranges):
    "26 Sep 2026"                              -- single day, no time
    "24 Sep 2026 10:27AM"                      -- single day + time
    "2 Oct 2026 8:30AM &ndash; 4:00PM"         -- single day, time range
    "23 &ndash; 25 Sep 2026"                   -- multi-day, same month
    "29 Sep &ndash; 15 Dec 2026"               -- multi-day, cross-month
    "19 Oct 9:00AM &ndash; 20 Oct 5:00PM 2026" -- multi-day, cross-day, with
                                                   times and a trailing shared year
All are handled by `_parse_date_cell()`.

IMPORTANT — this is an aggregator-style community calendar, not a pure
ACPGBI listing. Recon and manual review both confirm predatory/third-party
conference-mill events get submitted alongside genuine ACPGBI/coloproctology
events (e.g. "25th Global Summit on Nursing Education and Practice",
"3rd International Conference on Preventive Medicine and Advanced
Healthcare", "16th World Gastroenterology, IBD, Hepatology Conference &
Exhibition"). These all share a distinctive naming pattern — an ordinal
number followed by "International"/"Global"/"World" — that genuine
ACPGBI/colorectal-surgery events never use. `_is_junk_title()` filters on
that pattern. It's a heuristic, not a whitelist, so it may need occasional
review (see `concerns` in the build JSON).

Detail pages carry the real date/location text again plus body copy, a
"Book online for this event" / "Further details about this event" button
(internal `/book` sub-page OR an external ticketing site, `target="_blank"`)
inside a `.booking_prompts` div, and free-text fee mentions ("No
registration fee", "Free to all") — there are NO markup-based fee tables
anywhere on this site (confirmed across 10 detail pages spot-checked), so
`parse_pricing_tables()` is tried as a backstop but is expected to return
`[]` on every event; a plain-text "no fee" / "free" match produces one
GBP £0 tier per the "free" rule (never invent an actual amount). A handful
of course pages mention CPD points awarded by a partner college in plain
text ("This course has been awarded 16 CPD points by RCSEd") — captured by
regex, no markup hook needed.
"""

from __future__ import annotations

import re
import html as html_lib
from datetime import date, datetime
from typing import Dict, Any, Optional, Callable, List, Tuple
from urllib.parse import urljoin

from playwright.sync_api import Page

from .base import BaseExtractor
from .http_fetch import fetch_html
from .specialty_classifier import classify_specialty
from .abstract_classifier import extract_abstract_info
from .pricing_tables import parse_pricing_tables
from logger import logger


BASE_URL = "https://www.acpgbi.org.uk"
LISTING_URL_TMPL = BASE_URL + "/events/date/{year}"
MAX_FUTURE_YEARS = 6  # safety stop if the site ever stops returning empty years

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

UK_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)

_UK_REGIONS = {
    "london": "London",
    "manchester": "North West England",
    "liverpool": "North West England",
    "leeds": "Yorkshire and the Humber",
    "sheffield": "Yorkshire and the Humber",
    "york": "Yorkshire and the Humber",
    "birmingham": "West Midlands",
    "coventry": "West Midlands",
    "bristol": "South West England",
    "exeter": "South West England",
    "plymouth": "South West England",
    "cambridge": "East of England",
    "norwich": "East of England",
    "oxford": "South East England",
    "brighton": "South East England",
    "southampton": "South East England",
    "reading": "South East England",
    "slough": "South East England",
    "newcastle": "North East England",
    "sunderland": "North East England",
    "edinburgh": "Scotland",
    "glasgow": "Scotland",
    "aberdeen": "Scotland",
    "dundee": "Scotland",
    "alloa": "Scotland",
    "stirling": "Scotland",
    "cardiff": "Wales",
    "swansea": "Wales",
    "belfast": "Northern Ireland",
    "dublin": "Republic of Ireland",
}

# English/Welsh ceremonial counties (plus home-nation names) that sometimes
# appear as the LAST comma-segment of a venue address (ahead of the
# postcode) where the actual town/city is the segment before it — e.g.
# "..., Slough, Berkshire, SL1 4TQ" -> city is "Slough", not "Berkshire";
# "..., Dundee, Scotland" -> city is "Dundee", not "Scotland".
_UK_COUNTIES = {
    "berkshire", "buckinghamshire", "cambridgeshire", "cheshire", "cornwall",
    "cumbria", "derbyshire", "devon", "dorset", "durham", "essex",
    "gloucestershire", "hampshire", "herefordshire", "hertfordshire", "kent",
    "lancashire", "leicestershire", "lincolnshire", "merseyside", "norfolk",
    "northamptonshire", "northumberland", "nottinghamshire", "oxfordshire",
    "shropshire", "somerset", "staffordshire", "suffolk", "surrey",
    "sussex", "east sussex", "west sussex", "tyne and wear", "warwickshire",
    "wiltshire", "worcestershire", "yorkshire", "west yorkshire",
    "north yorkshire", "south yorkshire", "east yorkshire",
    "greater manchester", "west midlands",
    "scotland", "wales", "england", "northern ireland",
    "united kingdom", "uk", "great britain", "republic of ireland", "ireland",
}

# Non-UK countries that occasionally show up as the trailing segment of an
# overseas event's address (ACPGBI's calendar includes a few affiliated
# international society meetings, e.g. CSSANZ in Australia).
_COUNTRIES = {
    "australia", "new zealand", "usa", "united states", "united states of america",
    "canada", "south africa", "india", "singapore", "hong kong", "china",
    "japan", "france", "germany", "spain", "italy", "netherlands",
    "united arab emirates", "uae", "portugal", "switzerland",
}

# Known UK city/town names (reuses the region lookup's keys) used to pull a
# recognisable city out of a longer trailing segment like "King's College
# London" -> "London".
def _canonicalize_city(candidate: Optional[str]) -> Optional[str]:
    if not candidate:
        return candidate
    low = candidate.lower()
    if low in _UK_REGIONS:
        return candidate
    for key in _UK_REGIONS:
        if re.search(rf"\b{re.escape(key)}\b", low):
            return key.title()
    return candidate

# "(ordinal) International/Global/World ... Conference/Congress/Summit" is
# the distinctive naming pattern of the third-party conference-mill
# listings that get submitted to this aggregator calendar alongside genuine
# ACPGBI/colorectal events (ordinal is common but not universal — e.g.
# "World Congress on Nursing and Health Care" has none).
_JUNK_TITLE_RE = re.compile(
    r"^(?:\d+(?:st|nd|rd|th)\s+)?(?:international|global|world)\b"
    r".{0,60}?\b(?:conference|congress|summit)\b",
    re.I,
)

_FREE_RE = re.compile(
    r"\bno registration fee\b|\bfree to all\b|\bfree event\b|\bthis (?:webinar|event) is free\b",
    re.I,
)

_CPD_POINTS_RE = re.compile(r"\bawarded\s+(\d+)\s+CPD\s+points\b", re.I)
_CPD_MENTION_RE = re.compile(r"\bCPD\b", re.I)

# Words that mark a bare, comma-less location string as a venue name rather
# than a place/city (e.g. "Prague Congress Centre" with no city given).
_VENUE_KEYWORD_RE = re.compile(
    r"\b(?:centre|center|hotel|theatre|theater|hospital|university|college|"
    r"hall|building|campus|institute|academy|conference)\b", re.I
)


def _clean_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _to_24h(time_str: str) -> Optional[str]:
    time_str = time_str.strip().upper().replace(" ", "")
    try:
        return datetime.strptime(time_str, "%I:%M%p").strftime("%H:%M")
    except ValueError:
        return None


def _parse_date_cell(raw: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse a listing/detail date cell into (start_date, end_date, start_time),
    all ISO/HH:MM strings or None. Handles the five shapes documented above."""
    text = html_lib.unescape(raw or "").replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None, None, None

    day = r"(\d{1,2})"
    mon = r"([A-Za-z]{3,})"
    year = r"(\d{4})"
    time_ = r"(\d{1,2}:\d{2}\s*[AP]M)"

    def mk(d: str, m: str, y: str) -> Optional[date]:
        mo = _MONTHS.get(m.lower()[:3])
        if not mo:
            return None
        try:
            return date(int(y), mo, int(d))
        except ValueError:
            return None

    # 1. Cross-day with times, shared trailing year:
    #    "19 Oct 9:00AM - 20 Oct 5:00PM 2026"
    m = re.match(rf"^{day}\s+{mon}\s+{time_}\s*-\s*{day}\s+{mon}\s+{time_}\s+{year}$", text, re.I)
    if m:
        d1, m1, t1, d2, m2, t2, y = m.groups()
        sd, ed = mk(d1, m1, y), mk(d2, m2, y)
        return (sd.isoformat() if sd else None, ed.isoformat() if ed else None, _to_24h(t1))

    # 2. Cross-month multi-day: "29 Sep - 15 Dec 2026"
    m = re.match(rf"^{day}\s+{mon}\s*-\s*{day}\s+{mon}\s+{year}$", text, re.I)
    if m:
        d1, m1, d2, m2, y = m.groups()
        sd, ed = mk(d1, m1, y), mk(d2, m2, y)
        return (sd.isoformat() if sd else None, ed.isoformat() if ed else None, None)

    # 3. Same-month multi-day: "23 - 25 Sep 2026"
    m = re.match(rf"^{day}\s*-\s*{day}\s+{mon}\s+{year}$", text, re.I)
    if m:
        d1, d2, mth, y = m.groups()
        sd, ed = mk(d1, mth, y), mk(d2, mth, y)
        return (sd.isoformat() if sd else None, ed.isoformat() if ed else None, None)

    # 4. Single day, time range: "2 Oct 2026 8:30AM - 4:00PM"
    m = re.match(rf"^{day}\s+{mon}\s+{year}\s+{time_}\s*-\s*{time_}$", text, re.I)
    if m:
        d1, mth, y, t1, t2 = m.groups()
        sd = mk(d1, mth, y)
        return (sd.isoformat() if sd else None, sd.isoformat() if sd else None, _to_24h(t1))

    # 5. Single day + single time: "24 Sep 2026 10:27AM"
    m = re.match(rf"^{day}\s+{mon}\s+{year}\s+{time_}$", text, re.I)
    if m:
        d1, mth, y, t1 = m.groups()
        sd = mk(d1, mth, y)
        return (sd.isoformat() if sd else None, sd.isoformat() if sd else None, _to_24h(t1))

    # 6. Plain single day: "26 Sep 2026"
    m = re.match(rf"^{day}\s+{mon}\s+{year}$", text, re.I)
    if m:
        d1, mth, y = m.groups()
        sd = mk(d1, mth, y)
        return (sd.isoformat() if sd else None, sd.isoformat() if sd else None, None)

    logger.warning(f"ACPGBI: unparsed date cell '{text}'")
    return None, None, None


def _infer_region(city: Optional[str]) -> Optional[str]:
    if not city:
        return None
    low = city.lower()
    for key, region in _UK_REGIONS.items():
        if key in low:
            return region
    return None


def _split_venue_city(location_raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Split a free-text 'Venue, Address, City, Postcode' string into
    (venue_name, city). Best-effort — this site has no consistent
    venue/city separator, so we take the first comma-segment as venue and
    the segment before a trailing UK postcode (or the last segment) as
    city."""
    if not location_raw:
        return None, None
    loc = location_raw.strip()
    if loc.lower() in ("online", "online event", "n/a", "tbc", "tba"):
        return None, None
    parts = [p.strip() for p in loc.split(",") if p.strip()]
    if not parts:
        return None, None
    if len(parts) == 1:
        # No comma at all — just a bare name. If it reads like a venue
        # ("... Congress Centre", "... Hotel"), it's a venue with no known
        # city; otherwise treat it as a plain place name (city).
        if _VENUE_KEYWORD_RE.search(parts[0]):
            return parts[0], None
        return None, _canonicalize_city(parts[0])
    venue = parts[0]
    # Drop a trailing standalone UK postcode segment before picking "city"
    tail = parts[1:]
    tail = [p for p in tail if not UK_POSTCODE_RE.fullmatch(p.strip())]
    tail = [p for p in tail if p.lower() not in ("uk", "united kingdom")]
    # Strip any inline postcode off the last segment ("London SW3 6JJ" -> "London")
    if tail:
        tail[-1] = UK_POSTCODE_RE.sub("", tail[-1]).strip().rstrip(",").strip()
        tail = [p for p in tail if p]
    # Walk backwards over the tail, skipping ceremonial counties, home
    # nations, and non-UK countries ("..., Slough, Berkshire" ->
    # "Slough"; "Cairns, QLD, Australia" -> skip "Australia", then also
    # skip the bare 2-4 letter state/county code "QLD" -> "Cairns").
    city = None
    for seg in reversed(tail):
        low = seg.lower()
        if low in _UK_COUNTIES or low in _COUNTRIES:
            continue
        if re.fullmatch(r"[A-Z]{2,4}", seg):  # e.g. "QLD", "NSW" state codes
            continue
        city = seg
        break
    if city is None and venue:
        # Every tail segment was a county/country/state-code noise word —
        # the address had no distinct venue name, just "Place, Region,
        # Country" (seen on overseas affiliate events, e.g. "Cairns, QLD,
        # Australia"). The first segment is the actual place, not a venue.
        city, venue = venue, None
    return venue, _canonicalize_city(city)


def _is_junk_title(title: str) -> bool:
    # 2026-09-26: filter disabled on user decision — every event the
    # calendar lists is wanted, third-party ones included. Pattern kept
    # above in case that decision is revisited.
    return False


def _extract_body(detail_html: str) -> str:
    """Isolate the real event copy from the fixed nav/menu chrome that
    surrounds it on every page (which otherwise produces false-positive
    keyword matches — e.g. the nav always links to 'Course Accreditation
    and CPD Approval', which would make every event look CPD-accredited if
    matched against the whole page text).

    The genuine per-event copy always lives inside the `id="event"` tab
    pane, ending right before the `<div class="clearer">` that precedes
    the "Organised by:" block — a stable structural marker regardless of
    whether the event has a venue/Directions link or not."""
    marker_idx = detail_html.find('id="event"')
    if marker_idx < 0:
        return ""
    # Skip past the REST of the opening <div ... id="event"> tag itself —
    # find() only lands on the `id="event"` attribute text, still mid-tag,
    # not on real content. Slicing from there (a past bug) leaked the tag's
    # trailing `>` and the next tag's leading `<div ` as literal text into
    # the "body", because a truncated tag fragment like `<div ` doesn't
    # match the `<[^>]+>` strip regex in `_clean_text()`.
    tag_end = detail_html.find(">", marker_idx)
    if tag_end < 0:
        return ""
    start = tag_end + 1
    end = detail_html.find('<div class="clearer">', start)
    chunk = detail_html[start:end] if end > start else detail_html[start:start + 6000]
    return _clean_text(chunk)


def _parse_listing(html: str) -> List[Dict[str, Any]]:
    shells: List[Dict[str, Any]] = []
    today_iso = date.today().isoformat()

    for chunk in html.split('<div class="date_row')[1:]:
        # Each of the (up to) 3 "col-sm-4" cells: date / title-link / location.
        cells = re.findall(r'col-sm-4">(.*?)</div>', chunk, re.S)
        if len(cells) < 2:
            continue
        date_cell = _clean_text(cells[0])
        link_m = re.search(r'href="(/events/\d+/[^"]+)">([^<]+)</a>', cells[1])
        if not link_m:
            continue
        href, title = link_m.group(1), html_lib.unescape(link_m.group(2)).strip()
        location_raw = _clean_text(cells[2]) if len(cells) > 2 else ""

        if _is_junk_title(title):
            continue

        start_date, end_date, start_time = _parse_date_cell(date_cell)
        if not start_date:
            continue
        if end_date and end_date < today_iso:
            continue  # fully past

        booking_url = urljoin(BASE_URL, href)
        venue_name, city = _split_venue_city(location_raw)

        shells.append({
            "title": title,
            "booking_url": booking_url,
            "start_date": start_date,
            "end_date": end_date,
            "start_time": start_time,
            "venue_name": venue_name,
            "city": city,
        })

    return shells


class ACPGBIExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing phase — year-scoped calendar, no in-year pagination. Walk
    # forward year by year (starting at the current year) until a year
    # comes back with zero event links.
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        browser = getattr(self, "browser", None)
        shells: List[Dict[str, Any]] = []
        seen_urls = set()
        start_year = date.today().year

        for offset in range(MAX_FUTURE_YEARS):
            year = start_year + offset
            url = LISTING_URL_TMPL.format(year=year)
            html = fetch_html(url, browser=browser)
            if not html:
                logger.warning(f"ACPGBI: listing fetch failed for {year}")
                continue
            year_shells = _parse_listing(html)
            new = [s for s in year_shells if s["booking_url"] not in seen_urls]
            for s in new:
                seen_urls.add(s["booking_url"])
            shells.extend(new)
            if not year_shells:
                # Empty year -> assume nothing further out is populated either.
                break

        logger.info(f"ACPGBI: {len(shells)} upcoming shells across years {start_year}-{start_year + offset}")
        return shells

    # ------------------------------------------------------------------ #
    # Detail phase
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        url = shell.get("booking_url") or ""
        detail_html = fetch_html(url, browser=getattr(self, "browser", None), loaded_page=page) if url else None
        if not detail_html:
            try:
                detail_html = page.content()
            except Exception:
                detail_html = None
        if not detail_html:
            logger.warning(f"ACPGBI: no detail HTML for {url}")
            return result

        page_text = _clean_text(detail_html)
        body = _extract_body(detail_html)

        # Date/time — detail page repeats the same "module_article_metadata"
        # cell, occasionally more precise than the listing shell (a listing
        # date cell can get clipped for very long cross-year ranges).
        meta_cells = re.findall(r'<p class="module_article_metadata">\s*(.*?)\s*</p>', detail_html, re.S)
        if meta_cells:
            sd, ed, st = _parse_date_cell(_clean_text(meta_cells[0]))
            if sd:
                result["start_date"] = sd
                result["end_date"] = ed
            if st:
                result["start_time"] = st

        # Venue / city / region / event_format
        location_raw = _clean_text(meta_cells[1]) if len(meta_cells) > 1 else ""
        is_online_marker = location_raw.lower() in ("online", "online event")
        if location_raw and not is_online_marker:
            venue_name, city = _split_venue_city(location_raw)
            result["venue_name"] = venue_name or shell.get("venue_name")
            result["city"] = city or shell.get("city")
            result["region"] = _infer_region(result.get("city"))
            result["event_format"] = "in_person"
        elif is_online_marker:
            result["event_format"] = "online"
            result["venue_name"] = None
            result["city"] = None
            result["region"] = None
        else:
            # No location cell at all — either a genuine webinar (detected
            # via body text), or one of a handful of multi-venue courses
            # whose per-day venues are only in the body copy, not the
            # metadata cell. This site is overwhelmingly physical events,
            # so absent an explicit online/webinar signal we assume
            # in-person with an unknown venue rather than leaving format
            # null (a stronger guess than no signal at all, worth revisiting
            # if it misfires on a real online event with no "webinar" wording).
            is_webinar = "webinar" in body.lower()
            result["event_format"] = "online" if is_webinar else "in_person"
            result["venue_name"] = None
            result["region"] = None
            if is_webinar:
                result["city"] = None

        # Pricing — no markup fee tables observed anywhere on this site;
        # try the shared parser as a backstop, then fall back to the
        # plain-text "no fee" / "free" phrasing rule.
        tiers = parse_pricing_tables(detail_html, default_currency="GBP")
        if not tiers and _FREE_RE.search(body):
            tiers = [{"label": "Registration", "price_gbp": 0.0, "currency": "GBP"}]
        result["pricing_tiers"] = tiers

        # CPD — only ever seen as free-text "awarded N CPD points by <body>".
        # Scoped to the event's own copy, not the full page: the nav on
        # EVERY page links to "Course Accreditation and CPD Approval",
        # which would otherwise make every event look CPD-mentioned.
        cpd_m = _CPD_POINTS_RE.search(body)
        if cpd_m:
            result["cpd_points"] = int(cpd_m.group(1))
            result["cpd_accredited"] = True
        else:
            result["cpd_points"] = None
            result["cpd_accredited"] = bool(_CPD_MENTION_RE.search(body))

        # event_type — course/workshop keywords in the title, else conference.
        title = shell.get("title") or ""
        title_low = title.lower()
        if re.search(r"\bcourse\b|\btraining\b", title_low):
            result["event_type"] = "course"
        elif re.search(r"\bworkshop\b|\bwebinar\b|\bstudy day\b", title_low):
            result["event_type"] = "workshop"
        else:
            result["event_type"] = "conference"

        # is_sold_out — no explicit sold-out markup seen; only text signal.
        # Deliberately excludes "waiting list" — observed used for a
        # sub-component (e.g. a hands-on course slot) selling out while the
        # main event is still open, which would be a false positive.
        result["is_sold_out"] = bool(re.search(r"\bsold out\b|\bfully booked\b", body, re.I))

        # Abstract open/deadline — deterministic classifier over the event's
        # own copy.
        abstract_open, abstract_deadline = extract_abstract_info(body)
        result["abstract_open"] = abstract_open
        result["abstract_deadline"] = abstract_deadline.isoformat() if abstract_deadline else None

        # Soft fields: description + specialty.
        result.update(self._extract_soft_fields(body, title, llm_call))

        return result

    # ------------------------------------------------------------------ #
    def _extract_soft_fields(
        self, body: str, title: str, llm_call: Callable[[str], Optional[str]]
    ) -> Dict[str, Any]:
        # Deterministic backstop first: first real sentence-like chunk of
        # body copy (nav/metadata boilerplate already stripped by the caller).
        fallback_description = (body[:400].strip() or None) if body else None

        specialty = classify_specialty(title, fallback_description)
        description = fallback_description

        if llm_call and body:
            prompt = (
                "You are extracting structured data from a UK medical conference "
                "listing page. Given the page text below, return STRICT JSON only "
                '(no markdown) with keys "description" (a neutral 1-2 sentence '
                'summary of what the event is, in your own words, or null) and '
                '"specialty" (the single most relevant medical/surgical specialty, '
                'e.g. "Colorectal Surgery", "General Surgery", "Gastroenterology", '
                'or null if unclear).\n\n'
                f"Title: {title}\n\nPage text:\n{body[:3000]}"
            )
            raw = llm_call(prompt)
            if raw:
                try:
                    import json
                    m = re.search(r"\{.*\}", raw, re.S)
                    data = json.loads(m.group(0) if m else raw)
                    if data.get("description"):
                        description = str(data["description"]).strip()
                    if data.get("specialty"):
                        specialty = str(data["specialty"]).strip()
                except Exception as e:
                    logger.warning(f"ACPGBI: LLM soft-field parse failed: {e}")

        return {
            "description": description,
            "specialty": specialty or classify_specialty(title, fallback_description),
        }
