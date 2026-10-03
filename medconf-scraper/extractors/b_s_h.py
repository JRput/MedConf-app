# extractors/b_s_h.py
"""British Society for Haematology (BSH) — events listing + detail extractor.

Source 58. Umbraco site, SERVER-rendered (the recon note about React was wrong
for these pages). One un-paginated listing page holds every upcoming event in
two sections ("BSH Events" and "External events"), ~25 cards:

  <div class="page-grid-item"><a href="/education/conference-and-events/events/<slug>">
     <p class="page-grid-item__name">Title</p></a>
     <span class="page-grid-item__caption">October 9, London</span>   <- NO YEAR

Detail pages:
  - intro text with optional "Date: / Time: / Venue:" lines (free text, formats vary)
  - BSH-run events: "Event Availability" -> <ul class="price"> blocks, one per
    attendee category (<li class="header">Consultants</li>, then
    "£80.00 (BSH members)" / "£160.00 (non members)" or "£0.00 per Attendee").
  - external events: no fees (organiser's own registration link); the page also
    carries a timeline card with the full date incl. year
    (events-timeline-dark__events__event__date).
  - "Event places remaining: N" (0 => sold out).

Gotchas:
  - The listing caption has no year, so the year comes from (in order) the
    timeline card, an explicit year in the Date line / intro, the fee-block
    date, and finally "next occurrence on/after today".
  - The date under each fee block is NOT the event date (it is the pricing /
    registration cut-off) so it is only ever used as a year hint.
  - The IMG webinar series is one page listing several dated sessions
    ("14 October - Topic - Delivered by ...") with no years: emitted as one
    event_type='course' parent with upcoming `sessions`.
  - No CPD figures are published on event pages -> cpd_points None.
"""

import html as html_lib
import json
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from playwright.sync_api import Page

from logger import logger
from .base import BaseExtractor
from .http_fetch import fetch_html
from .specialty_classifier import classify_specialty

BASE_URL = "https://b-s-h.org.uk"
LISTING_URL = f"{BASE_URL}/education/conference-and-events/events"

MONTHS = {
    m: i + 1 for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"])
}
_MONTH_RE = "(" + "|".join(MONTHS) + ")"
_ORD = r"(?:st|nd|rd|th)?"

# "October 5-6" / "October 9th 2026" / "November26-27" / "November 24, 2026"
_MONTH_FIRST = re.compile(
    rf"\b{_MONTH_RE}\s*(\d{{1,2}}){_ORD}(?:\s*[-–]\s*(\d{{1,2}}){_ORD})?(?:\s*,?\s*(20\d\d))?",
    re.I)
# "19 January 2027" / "19–20 October 2026" / "5, November" / "11 November"
_DAY_FIRST = re.compile(
    rf"\b(\d{{1,2}}){_ORD}(?:\s*[-–]\s*(\d{{1,2}}){_ORD})?\s*,?\s*{_MONTH_RE}\b(?:\s*,?\s*(20\d\d))?",
    re.I)

# Cities that show up in BSH captions -> region / country.
_REGION = {
    "london": "London", "manchester": "North West England",
    "durham": "North East England", "newcastle": "North East England",
    "glasgow": "Scotland", "edinburgh": "Scotland", "cardiff": "Wales",
    "birmingham": "West Midlands", "leeds": "Yorkshire and the Humber",
    "bristol": "South West England", "oxford": "South East England",
    "cambridge": "East of England", "dublin": "Ireland",
    "philadelphia": "USA",
}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(s or "")).strip()


def _strip_tags(fragment: str) -> str:
    fragment = re.sub(r"(?is)<(script|style).*?</\1>", " ", fragment)
    fragment = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|ul|ol)>", "\n", fragment)
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html_lib.unescape(text).replace("​", "").replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _mk_date(y: int, mo: int, d: int) -> Optional[date]:
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def parse_span(text: str, year_hint: Optional[int] = None,
               today: Optional[date] = None) -> Tuple[Optional[date], Optional[date], bool]:
    """Parse the first date or date range in `text`.

    Returns (start, end, year_was_explicit). With no explicit year, `year_hint`
    is used, else the next occurrence on/after today (-3 days tolerance).
    """
    today = today or date.today()
    best = None
    for rx, order in ((_MONTH_FIRST, "m"), (_DAY_FIRST, "d")):
        m = rx.search(text or "")
        if m and (best is None or m.start() < best[0].start()):
            best = (m, order)
    if not best:
        return None, None, False
    m, order = best
    if order == "m":
        mo, d1, d2, yr = m.group(1), m.group(2), m.group(3), m.group(4)
    else:
        d1, d2, mo, yr = m.group(1), m.group(2), m.group(3), m.group(4)
    mon = MONTHS[mo.lower()]
    d1 = int(d1)
    d2 = int(d2) if d2 else None
    explicit = bool(yr)
    if yr:
        year = int(yr)
    elif year_hint:
        year = year_hint
    else:
        year = today.year
        probe = _mk_date(year, mon, d1)
        if probe and (today - probe).days > 3:
            year += 1
    s = _mk_date(year, mon, d1)
    e = _mk_date(year, mon, d2) if d2 and d2 >= d1 else None
    return s, e, explicit


def _parse_time(text: str) -> Optional[str]:
    """First clock time in `text` as HH:MM (handles '9.00-17.00', '7.00-8.00 pm', '7pm')."""
    m = re.search(
        r"(\d{1,2})(?:[.:](\d{2}))?\s*(am|pm)?(?:\s*[-–to]+\s*(\d{1,2})(?:[.:](\d{2}))?\s*(am|pm)?)?",
        text or "", re.I)
    if not m:
        return None
    h = int(m.group(1))
    mi = int(m.group(2) or 0)
    suf = (m.group(3) or "").lower()
    end_suf = (m.group(6) or "").lower()
    end_h = int(m.group(4)) if m.group(4) else None
    if not suf and end_suf == "pm" and end_h is not None and h <= end_h and h < 12:
        suf = "pm"
    if suf == "pm" and h < 12:
        h += 12
    if suf == "am" and h == 12:
        h = 0
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


class BSHExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = None
        for attempt in range(3):
            html = fetch_html(LISTING_URL, browser=getattr(self, "browser", None))
            if html and "page-grid-item" in html:
                break
            time.sleep(2 * (attempt + 1))
        if not html or "page-grid-item" not in html:
            logger.warning("BSH: listing fetch failed, no shells")
            return None

        shells: List[Dict[str, Any]] = []
        seen = set()
        today = date.today()
        card_re = re.compile(
            r'<a href="(/education/conference-and-events/events/[^"?#]+)"[^>]*class="page-grid-item__item".*?'
            r'<p class="page-grid-item__name">(.*?)</p>.*?'
            r'<span class="page-grid-item__caption">(.*?)</span>', re.S)
        for m in card_re.finditer(html):
            url = urljoin(BASE_URL, m.group(1))
            title = _clean(m.group(2))
            caption = _clean(m.group(3))
            if url in seen or not title:
                continue
            seen.add(url)
            if re.search(r"cancel|postponed", title, re.I):
                continue
            start, end, _ = parse_span(caption, today=today)
            # Caption has no year: only trust it when it is not already past.
            # (A just-passed caption can be a running series; detail decides.)
            shells.append({
                "title": title,
                "booking_url": url,
                "start_date": start.isoformat() if start and start >= today else None,
                "caption": caption,
            })
        logger.info(f"BSH: {len(shells)} shells from listing")
        return shells

    # ------------------------------------------------------------------ #
    # Detail
    # ------------------------------------------------------------------ #
    def extract_detail(self, page: Page, shell: Dict[str, Any],
                       llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        html = page.content()
        url = shell.get("booking_url") or ""
        title = shell.get("title") or ""
        caption = shell.get("caption") or ""
        today = date.today()

        body_html = self._body_html(html)
        text = _strip_tags(body_html)
        lines = text.splitlines()
        cut = len(text)
        for marker in ("Event Availability", "To register for this event", "Event places remaining"):
            k = text.find(marker)
            if k >= 0:
                cut = min(cut, k)
        intro = text[:cut]

        prices, price_year = self._parse_fee_blocks(body_html)
        tiers = self._tiers(prices)

        # ---- location / format ------------------------------------------
        venue_raw = self._label_value(intro, r"Venue|Location")
        cap_loc = caption.split(",", 1)[1].strip() if "," in caption else ""
        online_signal = bool(
            re.search(r"\b(online|zoom|webinar|virtual|teams)\b", f"{venue_raw or ''} {cap_loc}", re.I))
        in_person_signal = (bool(venue_raw) and not re.search(r"\b(online|zoom|virtual|teams)\b", venue_raw, re.I)) \
            or (bool(cap_loc) and not re.search(r"online", cap_loc, re.I))
        if online_signal and in_person_signal:
            fmt = "hybrid"
        elif online_signal:
            fmt = "online"
        elif in_person_signal:
            fmt = "in_person"
        elif re.search(r"\bonline\b|webinar", f"{title} {intro[:400]}", re.I):
            fmt = "online"
        else:
            fmt = "in_person"
        if re.search(r"(?<!not )(?<!no )\bhybrid\b", intro, re.I) and not re.search(r"not\s+(?:be\s+)?hybrid", intro, re.I):
            fmt = "hybrid"

        city = None
        if fmt != "online" and cap_loc:
            city = cap_loc.strip(" ,") or None
        venue_name = None
        if venue_raw and fmt != "online" and not re.fullmatch(r"(?i)\s*(tba|tbc|online)\s*", venue_raw):
            venue_name = venue_raw[:200]
        region = _REGION.get((city or "").lower())

        # ---- dates / sessions -------------------------------------------
        sessions = self._series_sessions(lines, price_year, today) if self._looks_like_series(intro) else []
        event_type = None
        if sessions:
            start = date.fromisoformat(sessions[0]["start_date"])
            end = date.fromisoformat(sessions[-1]["start_date"])
            event_type = "course"
            for s in sessions:
                s.update({"venue_name": venue_name, "city": city, "region": region})
        else:
            start, end = self._resolve_dates(html, url, intro, caption, price_year, today)

        time_val = self._label_value(intro, r"Time")
        start_time = _parse_time(time_val) if time_val else None

        # ---- sold out ---------------------------------------------------
        sold_out = False
        pm = re.search(r"Event places remaining:\s*(\d+)", text)
        if pm and int(pm.group(1)) == 0:
            sold_out = True

        # ---- type ------------------------------------------------------
        if event_type is None:
            head = f"{title} {intro[:300]}"
            if re.search(r"\bworkshop\b", head, re.I):
                event_type = "workshop"
            elif re.search(r"\b(course|teaching session|taster day|education day)\b", head, re.I):
                event_type = "course"
            else:
                event_type = "conference"

        result: Dict[str, Any] = {
            "event_type": event_type,
            "start_date": start.isoformat() if start else None,
            "end_date": end.isoformat() if end and start and end > start else None,
            "start_time": start_time,
            "venue_name": venue_name,
            "city": city,
            "region": region,
            "event_format": fmt,
            "cpd_points": None,
            "cpd_accredited": False,
            "is_sold_out": sold_out,
            "pricing_tiers": tiers,
        }
        if sessions:
            result["sessions"] = sessions
        result.update(self._soft_fields(title, intro, llm_call))
        return result

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _body_html(html: str) -> str:
        a = html.find('class="page-content__copy"')
        if a < 0:
            a = html.find('class="page-body"')
        if a < 0:
            return html
        b = html.find('class="page-sidebar"', a)
        return html[a:b] if b > a else html[a:]

    @staticmethod
    def _label_value(intro: str, labels: str) -> Optional[str]:
        """Value of 'Label: value' (value on the same line or the next one)."""
        m = re.search(rf"(?im)^\s*(?:{labels})\s*:\s*(.*)$", intro)
        if not m:
            return None
        val = m.group(1).strip()
        if not val:
            rest = intro[m.end():].lstrip("\n").splitlines()
            val = rest[0].strip() if rest else ""
        return val or None

    def _resolve_dates(self, html: str, url: str, intro: str, caption: str,
                       year_hint: Optional[int], today: date) -> Tuple[Optional[date], Optional[date]]:
        # 1. timeline card for this very event (externals): full date with year
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        card_start = None
        for m in re.finditer(
                r'events__event__date">([^<]+)</div>(.*?)href="[^"]*/events/' + re.escape(slug) + r'"',
                html, re.S):
            if "events__event__date" in m.group(2):   # date belongs to an earlier card
                continue
            card_start, _, _ = parse_span(_clean(m.group(1)), today=today)
            break

        # 2. explicit date line in the intro ("Date: ...")
        line_val = self._label_value(intro, r"Date")
        line_s, line_e, line_explicit = (
            parse_span(line_val, year_hint, today) if line_val else (None, None, False))

        # 3. explicit "D–D Month YYYY" anywhere in the intro
        intro_s, intro_e, intro_explicit = parse_span(intro, None, today)
        if not intro_explicit:
            intro_s = intro_e = None

        # 4. caption (no year) + year hint
        cap_s, cap_e, _ = parse_span(caption, year_hint, today)

        if card_start:
            end = None
            if cap_e and cap_s and (cap_s.month, cap_s.day) == (card_start.month, card_start.day):
                end = _mk_date(card_start.year, card_start.month, cap_e.day)
            elif intro_e and intro_s and intro_s == card_start:
                end = intro_e
            return card_start, end
        if line_s and line_explicit:
            # The site occasionally mistypes the year ("Friday 22 January 2026"
            # for a 2027 Friday). Trust the weekday name when it disagrees.
            wd = re.search(r"\b(mon|tues|wednes|thurs|fri|satur|sun)day\b", line_val or "", re.I)
            if wd:
                want = ["mon", "tues", "wednes", "thurs", "fri", "satur", "sun"].index(wd.group(1).lower())
                if line_s.weekday() != want:
                    for dy in (1, -1):
                        alt = _mk_date(line_s.year + dy, line_s.month, line_s.day)
                        if alt and alt.weekday() == want:
                            shift = alt.year - line_s.year
                            line_s = alt
                            line_e = _mk_date(line_e.year + shift, line_e.month, line_e.day) if line_e else None
                            break
            return line_s, line_e
        if intro_s and cap_s and (cap_s.month, cap_s.day) == (intro_s.month, intro_s.day):
            return intro_s, intro_e or cap_e
        if cap_s:
            # same month/day as an un-yeared Date line? the caption wins on year logic
            return cap_s, cap_e
        if line_s:
            return line_s, line_e
        return intro_s, intro_e

    @staticmethod
    def _looks_like_series(intro: str) -> bool:
        return bool(re.search(r"\b(webinar series|bi-weekly|weekly)\b", intro, re.I))

    @staticmethod
    def _series_sessions(lines: List[str], year_hint: Optional[int], today: date) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        rx = re.compile(rf"^(\d{{1,2}}){_ORD}\s+{_MONTH_RE}\s*[-–:]\s*(.+)$", re.I)
        for ln in lines:
            m = rx.match(ln.strip())
            if not m:
                continue
            year = year_hint or today.year
            d = _mk_date(year, MONTHS[m.group(2).lower()], int(m.group(1)))
            if not d or d < today:
                continue
            out.append({
                "start_date": d.isoformat(), "end_date": None, "start_time": None,
                "duration_text": None, "availability_status": None, "spots_left": None,
                "booking_url": None, "venue_name": None, "city": None, "region": None,
                "notes": m.group(3).strip()[:300],
            })
        return out

    @staticmethod
    def _parse_fee_blocks(body_html: str) -> Tuple[List[Tuple[str, str, float]], Optional[int]]:
        """-> ([(category, qualifier, price)], year hint from the fee-block date)."""
        out: List[Tuple[str, str, float]] = []
        year = None
        for ul in re.findall(r'(?is)<ul class="price".*?</ul>', body_html):
            items = [_clean(re.sub(r"<[^>]+>", " ", li))
                     for li in re.findall(r"(?is)<li[^>]*>(.*?)</li>", ul)]
            if not items:
                continue
            header = items[0]
            for it in items[1:]:
                pm = re.match(r"£\s*([\d,]+(?:\.\d+)?)\s*(?:\((.*?)\)|(per attendee))?", it, re.I)
                if pm:
                    qual = (pm.group(2) or "").strip()
                    if not qual:
                        qual = "Standard"
                    elif re.fullmatch(r"(?i)non[- ]?members?", qual):
                        qual = "Non-members"
                    elif re.fullmatch(r"(?i)(bsh )?members?", qual):
                        qual = "BSH members"
                    out.append((header, qual, float(pm.group(1).replace(",", ""))))
                    continue
                ym = re.search(r"\b(20\d\d)\b", it)
                if ym and year is None:
                    year = int(ym.group(1))
        return out, year

    @staticmethod
    def _tiers(prices: List[Tuple[str, str, float]]) -> List[Dict[str, Any]]:
        tiers, seen = [], set()
        for cat, qual, price in prices:
            label = f"{cat} · {qual}"[:120]
            if (label, price) in seen:
                continue
            seen.add((label, price))
            tiers.append({
                "tier_label": label, "price_gbp": price, "currency": "GBP",
                "is_early_bird": False, "early_bird_deadline": None,
            })
        return tiers

    # ---- soft fields ----------------------------------------------------
    def _soft_fields(self, title: str, intro: str,
                     llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        prompt = f"""You are summarising one medical event page. Extract ONLY two fields.

EVENT TITLE: {title}

PAGE TEXT:
{intro[:2800]}

Respond with valid JSON only, no markdown:
{{"description": "concise 30-50 word summary using only the page text" or null,
  "specialty": "primary clinical area, e.g. Haematology, Transfusion Medicine, Oncology" or null}}"""
        raw = llm_call(prompt)
        if raw:
            m = re.search(r"\{.*\}", raw, re.S)
            if m:
                try:
                    parsed = json.loads(m.group(0))
                    out["description"] = parsed.get("description") or None
                    out["specialty"] = parsed.get("specialty") or None
                except Exception as e:
                    logger.warning(f"BSH soft-fields JSON parse failed: {e}")
        if not out.get("specialty"):
            out["specialty"] = classify_specialty(title, intro) or "Haematology"
        if not out.get("description"):
            out["description"] = self._first_paragraph(intro)
        return out

    @staticmethod
    def _first_paragraph(intro: str) -> Optional[str]:
        skip = re.compile(r"^(date|time|venue|location|register|email|programme|day \d)\b", re.I)
        for ln in intro.splitlines():
            ln = ln.strip()
            if len(ln) < 60 or skip.match(ln) or ln.startswith("http") or "[email" in ln:
                continue
            if len(ln) > 320:
                cut = ln[:320]
                dot = cut.rfind(". ")
                ln = cut[:dot + 1] if dot > 120 else cut.rstrip() + "…"
            return ln
        return None
