"""Shared family base for sources on the Eventfolio ("EMS") event-calendar platform (Preside CMS, Pixl8).

The platform is recognisable by `<article class="eventfolio-calendar-event">` cards, a "Show more events" button and detail pages
with an `.event-header-post-meta` block (`.event-date`, `.event-time`, `.event-venue` x2, `.event-pricing`), a Booking widget
(`.event-widget-body`) and a body in `.event-detail-entry`. The button calls a public JSON endpoint,
`<root>/ems/eventCalendar/ajaxResults/?offset=N&sort=date&order=asc&page_size=P`, returning
`{"resultCount", "moreResults", "results": "<article ...>"}`; Phase A walks it with `fetch_html` (httpx first, real browser as the
fallback) and only falls back to the first server-rendered cards if the endpoint fails. Booking pages (`/ems-event-booking-page.html`,
`/learning/booking.html`) sit behind a login, so fees are only the header pricing line, the Booking widget, or a "course fees" block.

Flow
  list_shells_override : card -> shell (title, dates, venue string, type badge, CPD, teaser); on-demand / cancelled cards skipped via
                         `skip_card`; duplicates (same title + start date under two URLs) dropped; `extra_shells` hook for events that
                         are not calendar cards.
  extract_detail       : header + widget + body -> dates, time, city/venue/region, fee tiers, organiser_url for external rows, CPD,
                         description, specialty; `extra_detail` hook for per-site enrichment. A URL that redirects to an ordinary CMS page
                         (no Eventfolio header) goes through `_plain_page_detail`.

Subclasses are constants (ROOT, CALENDAR_PATH, SOCIETY, DEFAULT_SPECIALTY, PREFER_DEFAULT_SPECIALTY) plus optional hooks
(`skip_card`, `extra_shells`, `event_type_for`, `specialty_for`, `extra_detail`, `synthetic_detail`).
Used by: boa.py (British Orthopaedic Association), ics.py (Intensive Care Society).
"""
import html as _html
import json
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import money

from logger import logger

from .http_fetch import fetch_html
from .specialty_classifier import classify_specialty
from .tribe_events import clip_venue, html_to_lines, sane_venue
from .wordpress_generic import WordPressGenericExtractor, _COUNTRIES, split_location

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_MON_RE = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_ARTICLE_RE = re.compile(r"(?is)<article\b.*?</article>")
_TAG_RE = re.compile(r"<[^>]+>")
# symbol / prefix code ("£", "S$", "EUR") + number text; read by `money.parse_amount`
# (bare "$" = USD, "S$"/"A$" recognised, "1.500,00" EU decimals).
_AMOUNT = r"([£€$]|[A-Za-z]{1,3}\$|[A-Z]{3}(?=\s?\d))\s*([0-9][0-9.,']*[0-9]|[0-9])"


def _amt(sym: str, num: str) -> Optional[Tuple[float, str]]:
    """(amount, ISO currency) for a matched symbol + number, or None (unstated currency, range)."""
    m = money.parse_amount(f"{sym}{num}")
    return (m.amount, m.currency) if m and m.currency and m.high is None else None
_COOKIE_JUNK_RE = re.compile(r"\{\{\s*cookieConsents\s*\}\}|please accept\s*cookies", re.I)
_SOLD_OUT_RE = re.compile(r"\b(?:sold out|fully booked|event full|no places (?:left|remaining))\b", re.I)
_ONLINE_RE = re.compile(r"^(?:online|virtual|webinar|zoom|teams|remote|livestream)\b", re.I)
_POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}$")
_VENUE_WORD_RE = re.compile(r"(?i)\b(hospital|centre|center|college|hotel|hall|university|institute|museum|campus|school|olympia|building|house|suite|venue|arena|trust)\b")
_ON_DEMAND_RE = re.compile(r"\b(?:on[\s-]?demand|digital access only|box ?set|recordings? only)\b", re.I)
_CANCELLED_RE = re.compile(r"\b(?:cancell?ed|postponed)\b", re.I)
_HEADING_RE = re.compile(r"^[A-Z][A-Z &/-]{7,}\s+[A-Z][a-z]")           # "ELIGIBILITY Previous attendance ..." is a heading run into its text
_PROMO_RE = re.compile(r"(?i)^(?:please note|note:|who should attend|booking)|\bdiscount\b|\bdiscount code\b|\bpromo(?:tion)?\b|use code|with code|\bcoupon\b|^[^.]{0,60}\bfees?\s*:|^(?:contact|address|email|tel(?:ephone)?)\s*:")

# UK city / county -> nation or region. Cities not listed fall back to "United Kingdom".
_UK_PLACES = {
    "london": "London", "manchester": "North West England", "liverpool": "North West England", "leeds": "Yorkshire and the Humber",
    "sheffield": "Yorkshire and the Humber", "york": "Yorkshire and the Humber", "newcastle": "North East England",
    "birmingham": "West Midlands", "coventry": "West Midlands", "bristol": "South West England", "exeter": "South West England",
    "cardiff": "Wales", "swansea": "Wales", "edinburgh": "Scotland", "glasgow": "Scotland", "aberdeen": "Scotland",
    "dundee": "Scotland", "belfast": "Northern Ireland", "cambridge": "East of England", "norwich": "East of England",
    "oxford": "South East England", "brighton": "South East England", "berkshire": "South East England", "ascot": "South East England",
    "leicester": "East Midlands", "nottingham": "East Midlands", "derby": "East Midlands", "shropshire": "West Midlands",
    "oswestry": "West Midlands", "wrightington": "North West England", "southampton": "South East England",
}


def _clean(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(_TAG_RE.sub(" ", frag or ""))).replace("\xa0", " ").strip()


def _iso(y: int, m: int, d: int) -> Optional[str]:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def ems_dates(text: str) -> Optional[Tuple[str, str]]:
    """'22 October 2026' | '23 – 24 October 2026' | '30 August – 10 November 2026' | '14 September – 22 October 2027'. Pure."""
    t = re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()
    m = re.search(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s*({_MON_RE})?\s*(\d{{4}})?\s*(?:-|–|—|to)\s*(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MON_RE})\s+(\d{{4}})", t, re.I)
    if m:
        d1, m1, y1, d2, m2, y2 = m.groups()
        mon2 = _MONTHS[m2[:3].lower()]
        mon1 = _MONTHS[m1[:3].lower()] if m1 else mon2
        yr2 = int(y2)
        yr1 = int(y1) if y1 else (yr2 - 1 if mon1 > mon2 else yr2)
        a, b = _iso(yr1, mon1, int(d1)), _iso(yr2, mon2, int(d2))
        return (a, b) if a and b and b >= a else None
    m = re.search(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MON_RE})\s+(\d{{4}})", t, re.I)
    if m:
        a = _iso(int(m.group(3)), _MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
        return (a, a) if a else None
    return None


def ems_time(text: str) -> Optional[str]:
    """'9.30am – 5pm GMT' -> '09:30'; '12am - 11.59pm' -> None (all-day marker)."""
    m = re.search(r"(\d{1,2})(?:[.:](\d{2}))?\s*(am|pm)?", text or "", re.I)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if not ap and not m.group(2):
        return None
    if h == 0 and mi == 0:
        return None
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None


def parse_ems_articles(fragment: str) -> List[Dict[str, Any]]:
    """One dict per `<article class="eventfolio-calendar-event">` card. Pure."""
    out: List[Dict[str, Any]] = []
    for art in _ARTICLE_RE.findall(fragment or ""):
        tm = re.search(r'(?is)<h4[^>]*class="[^"]*article-title[^"]*"[^>]*>\s*<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', art)
        if not tm:
            continue
        date_m = re.search(r'(?is)class="[^"]*article-date[^"]*"[^>]*>(.*?)</div>', art)
        cpd_m = re.search(r'(?is)class="[^"]*article-cpd[^"]*"[^>]*>(.*?)</div>', art)
        teaser_m = re.search(r'(?is)class="article-teaser"[^>]*>(.*?)</div>', art)
        cpd = None
        if cpd_m:
            n = re.search(r"(\d+(?:\.\d+)?)", _clean(cpd_m.group(1)))
            cpd = float(n.group(1)) if n else None
        out.append({
            "url": _html.unescape(tm.group(1)).strip(),
            "title": _clean(tm.group(2)),
            "dates": ems_dates(_clean(date_m.group(1)) if date_m else ""),
            "badges": [_clean(x) for x in re.findall(r'(?is)class="badge event-badge"[^>]*>(.*?)</span>', art)],
            "type": next((_clean(x) for x in re.findall(r'(?is)class="badge event-type-badge"[^>]*>(.*?)</span>', art)), ""),
            "venue": next((_clean(x) for x in re.findall(r'(?is)class="event-venue"[^>]*>(.*?)</span>', art)), ""),
            "cpd": cpd,
            "teaser": _clean(teaser_m.group(1)) if teaser_m else "",
        })
    return out


def ems_event_type(title: str, category: str, days: int = 0) -> str:
    """3-way type (PLAYBOOK): workshop words win, then course/programme/skills/masterclass in the title, then a span of
    two weeks or more (a multi-week programme), then conference words, then the card category."""
    t, c = (title or "").lower(), (category or "").lower()
    if re.search(r"\b(workshops?|webinars?|seminars?|study days?|bitesize)\b", t):
        return "workshop"
    if re.search(r"\b(courses?|programmes?|skills|masterclass(?:es)?|bootcamp|cadaver\w*|casting|certificate)\b", t) or days >= 14:
        return "course"
    if re.search(r"\b(conference|congress|symposium|meeting|summit|forum|annual)\b", t):
        return "conference"
    if re.search(r"casting|training", c):
        return "course"
    if re.search(r"webinar|study day|assessment|workshop", c):
        return "workshop"
    return "conference"


def ems_fee_tiers(lines: List[str], default_currency: str = "GBP") -> List[Dict[str, Any]]:
    """Fee rows as the Eventfolio pages write them:
    'ICS members - £215' | 'UK & IE Candidates - £4,250.00' | '£30 for non-members' | 'Free for ICS members'. Pure."""
    tiers: List[Dict[str, Any]] = []
    seen = set()

    def add(label: str, amount: float, cur: str) -> None:
        label = re.sub(r"\s+", " ", label).strip(" :-– ")
        label = re.sub(r"(?i)^(?:fee|fees|price|pricing|cost)\s*[:\-]?\s*", "", label).strip(" :-–") or "Standard"
        key = (label.lower(), amount, cur)
        if key in seen or len(label) > 90:
            return
        seen.add(key)
        tiers.append({"tier_label": f"Registration · {label}", "price_gbp": amount, "currency": cur,
                      "is_early_bird": False, "early_bird_deadline": None})

    for ln in lines:
        ln = ln.strip()
        m = re.match(rf"^(?P<label>[^£€$]{{2,80}}?)\s*(?:-|–|:)\s*(?:approx\.?\s*)?{_AMOUNT}\s*(?:\(.*\))?\s*(?:\+\s*VAT)?\.?$", ln)
        if m and _amt(m.group(2), m.group(3)):
            add(m.group("label"), *_amt(m.group(2), m.group(3)))
            continue
        m = re.match(rf"^{_AMOUNT}\s+(?:for|per)\s+(?P<label>.{{2,60}})$", ln, re.I)
        if m and _amt(m.group(1), m.group(2)):
            add(m.group("label"), *_amt(m.group(1), m.group(2)))
            continue
        m = re.match(r"^free\s+(?:for|to)\s+(?P<label>.{2,60})$", ln, re.I)
        if m:
            add(m.group("label"), 0.0, default_currency)
            continue
    return tiers


def ems_prose_fees(text: str, default_currency: str = "GBP") -> List[Dict[str, Any]]:
    """Fees written as one sentence: 'A discounted course fee of £200 is available only for BOA members. (£300 for non-BOA members)'. Pure."""
    tiers: List[Dict[str, Any]] = []
    t = re.sub(r"\s+", " ", text or "")
    pats = (rf"fee of {_AMOUNT}\s+is available\s+(?:only\s+)?(?:for|to)\s+([^.(]{{3,40}}?)\s*(?:[.(]|$)", rf"\(\s*{_AMOUNT}\s+for\s+([^)]{{3,40}})\)")
    for pat in pats:
        m = re.search(pat, t, re.I)
        a = _amt(m.group(1), m.group(2)) if m else None
        if a:
            label = m.group(3).strip(" .")
            tiers.append({"tier_label": f"Registration \u00b7 {label}", "price_gbp": a[0], "currency": a[1],
                          "is_early_bird": False, "early_bird_deadline": None})
    return tiers if len(tiers) else []


def _split_widget_lines(widget_html: str) -> List[str]:
    return [l for l in html_to_lines(re.sub(r"(?is)<a\b[^>]*class=\"btn\".*?</a>", " ", widget_html or "")) if l.lower() != "booking"]


class EmsCalendarExtractor(WordPressGenericExtractor):
    """Base for Eventfolio calendars. Subclasses set ROOT, CALENDAR_PATH, SOCIETY and the specialty defaults."""

    ROOT: str = ""
    CALENDAR_PATH: str = ""
    PAGE_SIZE: int = 50
    MAX_LOOPS: int = 8
    REQUEST_GAP_S: float = 1.0
    DEFAULT_CURRENCY = "GBP"
    ON_DEMAND_TYPES = re.compile(r"^on[\s-]?demand$", re.I)

    # ---- hooks ---------------------------------------------------------------------------------
    def skip_card(self, card: Dict[str, Any]) -> bool:
        return bool(self.ON_DEMAND_TYPES.match(card.get("type") or "") or _ON_DEMAND_RE.search(card.get("title") or "")
                    or _CANCELLED_RE.search(card.get("title") or ""))

    def extra_shells(self) -> List[Dict[str, Any]]:
        return []

    @staticmethod
    def _span_days(shell: Dict[str, Any]) -> int:
        try:
            return (date.fromisoformat(shell["end_date"]) - date.fromisoformat(shell["start_date"])).days
        except (KeyError, ValueError):
            return 0

    def event_type_for(self, title: str, category: str, days: int = 0) -> str:
        return ems_event_type(title, category, days)

    # ---- listing -------------------------------------------------------------------------------
    @staticmethod
    def _json_from_body(body: Optional[str]) -> Optional[Dict[str, Any]]:
        if not body:
            return None
        text = body.strip()
        if not text.startswith("{"):                       # the browser fallback wraps JSON in <pre>
            text = _html.unescape(_TAG_RE.sub("", text)).strip()
            i = text.find("{")
            text = text[i:] if i >= 0 else ""
        try:
            d = json.loads(text)
            return d if isinstance(d, dict) and "results" in d else None
        except ValueError:
            return None

    def _ajax_page(self, offset: int) -> Optional[Dict[str, Any]]:
        url = f"{self.ROOT}/ems/eventCalendar/ajaxResults/?&offset={offset}&sort=date&order=asc&page_size={self.PAGE_SIZE}"
        browser = getattr(self, "browser", None)
        for attempt in range(3):
            d = self._json_from_body(fetch_html(url, browser=browser, headers={"Accept": "application/json"}, expect_selector="body"))
            if d is not None:
                return d
            time.sleep(2 * (attempt + 1))
        return None

    def _cards(self) -> List[Dict[str, Any]]:
        cards: List[Dict[str, Any]] = []
        offset, total = 0, None
        for _ in range(self.MAX_LOOPS):
            d = self._ajax_page(offset)
            if d is None:
                break
            got = parse_ems_articles(d.get("results") or "")
            try:
                total = int(d.get("resultCount")) if d.get("resultCount") is not None else total
            except (TypeError, ValueError):
                pass
            cards.extend(got)
            if not got or not d.get("moreResults") or (total is not None and len(cards) >= total):
                break
            offset += self.PAGE_SIZE
            time.sleep(self.REQUEST_GAP_S)
        if not cards and total == 0:
            self.verified_empty = f"{self.SOCIETY} calendar JSON endpoint answered 200 with resultCount 0"
        if not cards and total is None:                     # endpoint unreachable: the 10-21 server-rendered cards are better than nothing
            html = fetch_html(self.ROOT + self.CALENDAR_PATH, browser=getattr(self, "browser", None))
            cards = parse_ems_articles(html or "")
            if cards:
                logger.warning(f"{self.SOCIETY}: JSON endpoint failed, using {len(cards)} server-rendered cards (may be partial)")
        return cards

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today()
        shells: List[Dict[str, Any]] = []
        seen_url, seen_key = set(), set()
        for c in self._cards():
            if not c["title"] or not c["dates"] or self.skip_card(c):
                continue
            start, end = c["dates"]
            if end < today.isoformat() or (date.fromisoformat(start) - today).days > self.MAX_FUTURE_DAYS:
                continue
            url = c["url"].split("#")[0]
            key = (re.sub(r"\W+", "", c["title"].lower()), start)          # BOA lists some events twice under two URLs
            if url in seen_url or key in seen_key:
                continue
            seen_url.add(url)
            seen_key.add(key)
            shells.append({"title": c["title"], "booking_url": url, "source_url": url, "start_date": start, "end_date": end,
                           "start_time": None, "venue_raw": c["venue"] or None, "category": c["type"] or None,
                           "badges": c["badges"], "cpd_points_listing": c["cpd"], "teaser": c["teaser"]})
        for s in self.extra_shells():
            if s["booking_url"] not in seen_url:
                shells.append(s)
        logger.info(f"{self.SOCIETY}: {len(shells)} upcoming shells")
        return shells or None

    # ---- detail --------------------------------------------------------------------------------
    @staticmethod
    def _block(html: str, cls: str) -> str:
        m = re.search(rf'(?is)<(div|span|section|aside)\b[^>]*class="[^"]*\b{cls}\b[^"]*"[^>]*>(.*?)</\1>', html)
        return m.group(2) if m else ""

    def place_from_spans(self, spans: List[str], fallback_raw: Optional[str]) -> Dict[str, Any]:
        """(city/area, venue name) spans from the header; the listing's single venue string when the header has none."""
        spans = [re.sub(r"\s+", " ", s).strip(" ,") for s in spans if s and s.strip(" ,")]
        if not spans and fallback_raw:
            spans = [fallback_raw.strip()]
        spans = [s for s in spans if not _POSTCODE_RE.match(s)]
        out: Dict[str, Any] = {}
        if not spans:
            return out
        if _ONLINE_RE.match(spans[0]):
            out["event_format"] = "online"
            return out
        city = venue = country = None
        if len(spans) >= 2:
            head = [p.strip() for p in spans[0].split(",") if p.strip() and not _POSTCODE_RE.match(p.strip())]
            if head and head[-1] in ("UK", "United Kingdom", "England", "Scotland", "Wales", "Northern Ireland"):
                head.pop()
            elif len(head) >= 2 and head[-1] in ("Spain", "France", "Germany", "Italy", "Ireland", "Malaysia", "Greece", "Portugal"):
                country = head.pop()
            city, venue = (head[-1] if head else None), spans[1]
        else:
            parts = [p.strip() for p in spans[0].split(",") if p.strip() and not _POSTCODE_RE.match(p.strip())]
            if parts and (parts[-1] in _COUNTRIES or parts[-1] in ("UK", "United Kingdom")):
                country = "United Kingdom" if parts[-1] in ("UK", "United Kingdom") else parts.pop()
                if country == "United Kingdom":
                    parts.pop()
            if len(parts) == 1:
                if _VENUE_WORD_RE.search(parts[0]):
                    venue = parts[0]                        # "The Robert Jones & Agnes Hunt Orthopaedic Hospital": a venue, not a city
                else:
                    city = parts[0]
            elif parts:
                city = parts[-1]
                head = ", ".join(parts[:-1])
                venue = head if _VENUE_WORD_RE.search(head) else None
        out["event_format"] = "in_person"
        if city:
            out["city"] = city
            region = _UK_PLACES.get(city.lower().split(" (")[0])
            out["region"] = region or (country if self._abroad(city, country) else "United Kingdom")
        if country and not out.get("region"):
            out["region"] = country
        if venue:
            venue = sane_venue(venue)
            if venue:
                out["venue_name"] = clip_venue(venue)
        if not out.get("region") and not city and out.get("venue_name"):
            out["region"] = None
        return out

    @staticmethod
    def _abroad(city: str, country: Optional[str]) -> bool:
        return bool(country and country not in ("UK", "United Kingdom", "England", "Scotland", "Wales", "Northern Ireland"))

    def _description(self, intro: str, entry_html: str, shell: Dict[str, Any]) -> Optional[str]:
        cands = [_clean(intro)] if intro else []
        cands += [_clean(p) for p in re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", entry_html or "")]
        cands.append(shell.get("teaser") or "")
        for c in cands:
            c = _COOKIE_JUNK_RE.sub("", c).strip()
            if len(c) >= 60 and re.search(r"[.!?](\s|$)", c) and not _PROMO_RE.search(c) and not _HEADING_RE.match(c):
                return c[:600]
        for c in cands:                                      # short but real one-liners ("Welcome to ... SOA27!")
            c = _COOKIE_JUNK_RE.sub("", c).strip()
            if len(c) >= 30 and not _PROMO_RE.search(c) and not _HEADING_RE.match(c):
                return c[:600]
        return None

    def specialty_for(self, title: str, description: Optional[str], llm_call: Callable[[str], Optional[str]]) -> Optional[str]:
        if self.PREFER_DEFAULT_SPECIALTY and self.DEFAULT_SPECIALTY:
            return self.DEFAULT_SPECIALTY
        return classify_specialty(title) or classify_specialty(title, description) or self.DEFAULT_SPECIALTY

    def extra_detail(self, html: str, shell: Dict[str, Any], out: Dict[str, Any]) -> None:
        """Per-site hook, called last with the detail HTML."""

    def extract_detail(self, page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        html = page.content() if page is not None else ""
        if shell.get("has_page") is False:                   # synthetic shell (no page of its own)
            return self.synthetic_detail(shell, llm_call)
        if html and "event-header-post-meta" not in html:     # a listing URL can redirect to an ordinary CMS course page (BOA Ortho Update)
            return self._plain_page_detail(html, shell, llm_call)
        out: Dict[str, Any] = {"society": self.SOCIETY}
        title = shell["title"]
        out["event_type"] = self.event_type_for(title, shell.get("category") or "", self._span_days(shell))

        header = self._block(html, "event-header-post-meta")
        d = ems_dates(_clean(self._block(header, "event-date"))) or (shell["start_date"], shell["end_date"])
        out["start_date"], out["end_date"] = d
        st = ems_time(_clean(self._block(header, "event-time")))
        if st:
            out["start_time"] = st

        spans = [_clean(x) for x in re.findall(r'(?is)<span class="event-venue"[^>]*>(.*?)</span>', header)]
        out.update(self.place_from_spans(spans, shell.get("venue_raw")))

        # fees: header pricing line + booking widget + a "course fees" block in the body
        widget = self._block(html, "event-widget-body")
        entry = self._block(html, "event-detail-entry")
        lines = _split_widget_lines(widget)
        pricing_span = _clean(self._block(header, "event-pricing"))
        tiers = ems_fee_tiers(([pricing_span] if pricing_span else []) + lines, self.DEFAULT_CURRENCY)
        if not tiers:
            elines = html_to_lines(entry)
            for i, ln in enumerate(elines):
                if re.match(r"(?i)^(?:[\w&+ ]{0,40}\s)?(?:fees?|pricing|prices|cost)\s*:?$", ln):
                    tiers = ems_fee_tiers(elines[i + 1:i + 9], self.DEFAULT_CURRENCY)
                    if tiers:
                        break
        if not tiers and ("Free" in (shell.get("badges") or []) or any(re.fullmatch(r"(?i)free", l) for l in lines)):
            tiers = [{"tier_label": "Registration · Free", "price_gbp": 0.0, "currency": self.DEFAULT_CURRENCY,
                      "is_early_bird": False, "early_bird_deadline": None}]
        out["pricing_tiers"] = tiers

        # booking link: external organiser pages get kept for the fee explorer
        bm = re.search(r'(?is)class="event-booking-btn"[^>]*>\s*<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html)
        if bm:
            href = _html.unescape(bm.group(1)).strip()
            if urlparse(href).netloc and urlparse(href).netloc.lower().lstrip("www.") != urlparse(self.ROOT).netloc.lower().lstrip("www."):
                out["organiser_url"] = href

        body_text = " ".join(html_to_lines(header + " " + widget))
        if _SOLD_OUT_RE.search(body_text):
            out["is_sold_out"] = True

        cm = re.search(r"(\d+(?:\.\d+)?)\s*(?:external\s+)?CPD\b", _clean(entry), re.I)
        cpd = float(cm.group(1)) if cm and 0.5 <= float(cm.group(1)) <= 100 else shell.get("cpd_points_listing")
        if cpd:
            out["cpd_points"], out["cpd_accredited"] = cpd, True

        intro = self._block(html, "page-banner-content-intro")
        desc = self._description(intro, entry, shell)
        if desc:
            out["description"] = desc
        if out["event_type"] == "conference" and desc and not re.search(r"(?i)conference|congress|symposium|meeting|summit|forum|annual", title):
            first = desc[:200].lower()                       # "This course aims to ..." on a card titled "Plastering Techniques ..."
            if re.search(r"\b(?:this|a|an|the)\s+(?:\w+\s+){0,6}(?:course|masterclass)\b", first):
                out["event_type"] = "course"
            elif re.search(r"\b(?:this|a|an|the)\s+(?:\w+\s+){0,6}(?:workshop|webinar|seminar|study day)\b", first):
                out["event_type"] = "workshop"
        spec = self.specialty_for(title, desc, llm_call)
        if spec:
            out["specialty"] = spec
        self.extra_detail(html, shell, out)
        return out

    def synthetic_detail(self, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        return {}

    def _plain_page_detail(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        m = re.search(r'(?is)<section\b[^>]*class="[^"]*main-section[^"]*"[^>]*>(.*?)</section>', html) or re.search(r"(?is)<main\b.*?</main>", html)
        body = m.group(0) if m else html
        lines = html_to_lines(re.sub(r"(?is)<(script|style|svg|nav|footer)\b.*?</\1>", " ", body))
        text = " ".join(lines)
        out: Dict[str, Any] = {"society": self.SOCIETY, "start_date": shell["start_date"], "end_date": shell["end_date"],
                               "event_type": self.event_type_for(shell["title"], shell.get("category") or "", self._span_days(shell))}
        loc = None
        for i, ln in enumerate(lines):
            lm = re.match(r"(?i)^(?:location|venue)\s*:\s*(.+)$", ln)
            if lm:
                loc = lm.group(1)
                break
            if re.match(r"(?i)^(?:location|venue)\s*:?$", ln) and i + 1 < len(lines):
                loc = lines[i + 1]
                break
        v, c, k = split_location(loc or shell.get("venue_raw"))
        if v:
            out["venue_name"] = sane_venue(v)
        if c:
            out["city"] = c
            out["region"] = _UK_PLACES.get(c.lower()) or k or "United Kingdom"
        if v or c:
            out["event_format"] = "in_person"
        elif shell.get("venue_raw") and _ONLINE_RE.match(shell["venue_raw"]):
            out["event_format"] = "online"
        elif shell.get("venue_raw"):
            out.update(self.place_from_spans([shell["venue_raw"]], None))
        cm = re.search(r"(\d+(?:\.\d+)?)\s*(?:external\s+)?CPD\b", text, re.I)
        cpd = float(cm.group(1)) if cm and 0.5 <= float(cm.group(1)) <= 100 else shell.get("cpd_points_listing")
        if cpd:
            out["cpd_points"], out["cpd_accredited"] = cpd, True
        out["pricing_tiers"] = ems_fee_tiers(lines, self.DEFAULT_CURRENCY) or ems_prose_fees(text, self.DEFAULT_CURRENCY)
        desc = self._description("", body, shell)
        if desc:
            out["description"] = desc
        spec = self.specialty_for(shell["title"], desc, llm_call)
        if spec:
            out["specialty"] = spec
        return out
