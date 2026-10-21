"""BSG (British Society of Gastroenterology) events: Kentico site with Blazor-prerendered cards, plain HTTP listing.

`bsg.org.uk/events` is a Blazor component, but the server prerenders the cards into the HTML, so no browser is needed
for the first page. Page 2 is only reachable as `/events?page=2&start=<YYYY-MM-DD>` (the link the Blazor pager itself
navigates to); without `start` the server answers with the unfiltered archive (100 events, mostly past). Phase A walks
`?page=N&start=<today>` until the pager's "Showing X to Y of T results" total is reached.

Cards carry title, "dd-mm-yyyy @ hh:mm - dd-mm-yyyy @ hh:mm" and a location string, but no category; the event type
comes from the title (webinar / course / training / meeting / conference...). Event pages carry the same header, a rich-text
body and a "Registration fees" block written as `label:` then `£amount (notes)` lines (member / non-member / virtual).
Members-only refunds and the "register with your membership email" notes are kept out of tier labels.
"""
import html as _html
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from logger import logger

from .http_fetch import fetch_html
from .tribe_events import clip_venue, html_to_lines, sane_venue
from .wordpress_generic import WordPressGenericExtractor, classify_event_type

# UK city / county -> nation or region (local copy: BSG is not on the EMS platform). Unlisted cities fall back to "United Kingdom".
_UK_PLACES = {
    "london": "London", "manchester": "North West England", "liverpool": "North West England", "leeds": "Yorkshire and the Humber",
    "sheffield": "Yorkshire and the Humber", "york": "Yorkshire and the Humber", "newcastle": "North East England",
    "birmingham": "West Midlands", "coventry": "West Midlands", "bristol": "South West England", "exeter": "South West England",
    "cardiff": "Wales", "swansea": "Wales", "edinburgh": "Scotland", "glasgow": "Scotland", "aberdeen": "Scotland",
    "dundee": "Scotland", "belfast": "Northern Ireland", "cambridge": "East of England", "norwich": "East of England",
    "oxford": "South East England", "brighton": "South East England", "leicester": "East Midlands", "nottingham": "East Midlands",
    "derby": "East Midlands", "southampton": "South East England",
}

_ROOT = "https://www.bsg.org.uk"
_LISTING = _ROOT + "/events"
_CARD_RE = re.compile(r'(?is)<a\s+href="(/events/[^"#?]+)"[^>]*>\s*<div class="card.*?</a>')
_DATES_RE = re.compile(r"(\d{2})-(\d{2})-(\d{4})\s*@\s*(\d{2}):(\d{2})(?:\s*-\s*(\d{2})-(\d{2})-(\d{4})\s*@\s*(\d{2}):(\d{2}))?")
_TOTAL_RE = re.compile(r"Showing\s+\d+\s+to\s+\d+\s+of\s+(\d+)\s+results", re.I)
_POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}$")
_VENUE_WORD_RE = re.compile(r"(?i)\b(hotel|inn|centre|center|house|hall|college|hospital|university|institute|conference|suite|arena|stadium|voco|hilton|marriott|campus|school|trust)\b")
_ONLINE_RE = re.compile(r"^(?:online|virtual|webinar|zoom|teams|remote|livestream|tbc|tba)\b", re.I)
_AMOUNT_ONLY_RE = re.compile(r"^([£€$])\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\b")
_SYM = {"£": "GBP", "€": "EUR", "$": "USD"}
_FEE_HEAD_RE = re.compile(r"(?i)^(?:(?:registration|course|event|delegate)\s+)?(?:fees?|pricing|prices|ticket prices?|costs?)\s*:?$|^registrations?\s*:?$")
_DESC_SKIP_RE = re.compile(r"(?i)^(?:programme|registration|on behalf|if you|please|delegate|not a bsg|the bsg is committed|you can register|you must|nurse,|sold out)|^[^.]{0,40}\bnot yet open\b|cookie|code of conduct")
_NOTE_RE = re.compile(r"(?i)^(?:if you|please|not a bsg member|on behalf|delegate information|group bookings|cancellation|nurse,|you must|invoices|payments by)")


def _iso(d: str, m: str, y: str) -> Optional[str]:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def parse_dates(text: str) -> Optional[Dict[str, Optional[str]]]:
    m = _DATES_RE.search(text or "")
    if not m:
        return None
    start = _iso(m.group(1), m.group(2), m.group(3))
    end = _iso(m.group(6), m.group(7), m.group(8)) if m.group(6) else start
    if not start:
        return None
    return {"start": start, "end": end if end and end >= start else start, "time": f"{m.group(4)}:{m.group(5)}"}


def parse_cards(html: str) -> List[Dict[str, Any]]:
    """Cards of the first `#events-results` block. Pure."""
    i = html.find('id="events-results"')
    seg = html[i:] if i >= 0 else html
    out: List[Dict[str, Any]] = []
    for m in _CARD_RE.finditer(seg):
        card = m.group(0)
        title_m = re.search(r'(?is)<span class="d-block[^"]*fw-semibold[^"]*">(.*?)</span>', card)
        dates = parse_dates(re.sub(r"<[^>]+>", " ", card))
        loc_m = re.search(r'(?is)#icon-location"></use></svg></span>(.*?)</span>', card)
        title = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", title_m.group(1)))).strip() if title_m else ""
        venue = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", loc_m.group(1)))).strip() if loc_m else ""
        if title and dates:
            out.append({"url": _ROOT + m.group(1), "title": title, "dates": dates, "venue": venue})
    return out


def place_from_raw(raw: Optional[str]) -> Dict[str, Any]:
    """'Hilton Leeds City, Neville Street, LS1 4BR' / 'Europa Hotel Belfast' / 'Birmingham' / 'Online' -> venue, city, region, format."""
    raw = re.sub(r"\s+", " ", raw or "").strip(" ,")
    out: Dict[str, Any] = {}
    if not raw:
        return out
    if _ONLINE_RE.match(raw):
        if not re.match(r"(?i)^(?:tbc|tba)", raw):
            out["event_format"] = "online"
        return out
    parts = [re.sub(r"\s+[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}$", "", p.strip()) for p in raw.split(",")]
    parts = [p for p in parts if p and not _POSTCODE_RE.match(p)]
    if not parts:
        return out
    low = raw.lower()
    city = next((c.title() for c in sorted(_UK_PLACES, key=len, reverse=True) if re.search(rf"\b{re.escape(c)}\b", low)), None)
    venue = parts[0] if (len(parts) > 1 or _VENUE_WORD_RE.search(parts[0])) else None
    if venue and re.match(r"^\d", venue):
        venue = None
    if not city and len(parts) > 1:
        city = parts[-1]
    elif not city and not venue:
        city = parts[0]
    out["event_format"] = "in_person"
    if venue:
        venue = sane_venue(venue)
        if venue:
            out["venue_name"] = clip_venue(venue)
    if city:
        out["city"] = city
        out["region"] = _UK_PLACES.get(city.lower(), "United Kingdom")
    return out


def _tier(label: str, amount: float, cur: str, section: Optional[str] = None) -> Dict[str, Any]:
    label = re.sub(r"\s+", " ", label).strip(" :-")
    parts = [p.strip() for p in re.split(r"\s+-\s+", label) if p.strip()]
    if section:
        parts.insert(0, re.sub(r"\s+", " ", section).strip(" :-"))
    return {"tier_label": " \u00b7 ".join(parts)[:120], "price_gbp": amount, "currency": cur, "is_early_bird": False, "early_bird_deadline": None}


def parse_fees(lines: List[str], default_currency: str = "GBP") -> List[Dict[str, Any]]:
    """'Registration fees' block, in the three layouts BSG pages use:
    `In-person - BSG members:` / `£50.00 (...)`  |  `Members` / `: £50.00 (...)`  |  `Member: £150.00`.
    A lone heading line ahead of a label (`Full event ticket`) becomes the first part of the tier label. Pure."""
    start = next((i for i, l in enumerate(lines) if _FEE_HEAD_RE.match(l.strip())), None)
    if start is None:
        for ln in lines:                                           # "Course Fee: £1,750.00" on one line
            m = re.match(r"(?i)^(?:course|registration|event|delegate)?\s*fees?\s*:\s*([£€$])\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\b", ln.strip())
            if m:
                return [_tier("Standard", float(m.group(2).replace(",", "")), _SYM[m.group(1)])]
        return prose_fees(lines[:120], default_currency)
    tiers: List[Dict[str, Any]] = []
    seen = set()
    section: Optional[str] = None

    def add(label: str, amount: float, cur: str) -> None:
        t = _tier(label, amount, cur, section)
        key = (t["tier_label"].lower(), amount, cur)
        if key not in seen:
            seen.add(key)
            tiers.append(t)

    i = start + 1
    end = min(len(lines), start + 40)
    while i < end:
        ln = lines[i].strip()
        if re.match(r"(?i)^(?:programme|learning outcomes|delegate information|on behalf|not a bsg member|group bookings|cancellation|nurse,|you must)", ln):
            break
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        nxt2 = lines[i + 2].strip() if i + 2 < len(lines) else ""
        if _AMOUNT_ONLY_RE.match(ln) and i == start + 1:          # "Course Fee:" / "£1,750.00"
            am = _AMOUNT_ONLY_RE.match(ln)
            add("Standard", float(am.group(2).replace(",", "")), _SYM[am.group(1)])
            i += 1
            continue
        inline = re.match(r"^(.{2,80}?)\s*:\s*([£€$]\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?)", ln)
        if inline:
            am = _AMOUNT_ONLY_RE.match(inline.group(2))
            add(inline.group(1), float(am.group(2).replace(",", "")), _SYM[am.group(1)])
        elif ln.endswith(":") and _AMOUNT_ONLY_RE.match(nxt):
            am = _AMOUNT_ONLY_RE.match(nxt)
            add(ln[:-1], float(am.group(2).replace(",", "")), _SYM[am.group(1)])
            i += 1
        elif re.match(r"^:\s*[£€$]", nxt) and len(ln) <= 60 and not ln.startswith(":"):
            am = _AMOUNT_ONLY_RE.match(re.sub(r"^:\s*", "", nxt))
            add(ln, float(am.group(2).replace(",", "")), _SYM[am.group(1)])
            i += 1
        elif re.match(r"^:\s*[£€$]", nxt2) and len(ln) <= 60 and not ln.endswith(":") and not re.search(r"[£€$]", ln):
            section = ln                                           # "Full event ticket" above "Members" / ": £100.00"
        i += 1
    if tiers:
        return tiers
    return prose_fees(lines[max(0, start - 2):end], default_currency) or []


def prose_fees(lines: List[str], default_currency: str = "GBP") -> List[Dict[str, Any]]:
    """Fees written as a sentence: 'FREE to attend for BASL & BSG Trainee Members', 'The non-member rate ... is £75'. Pure."""
    tiers: List[Dict[str, Any]] = []
    for ln in lines:
        m = re.search(r"(?i)\b(?:is\s+)?free\s+(?:to attend\s+)?for\s+(everyone|[^.(,;]{3,70})", ln)
        if m:
            who = re.sub(r"(?i)\s+to attend$", "", m.group(1)).strip(" !.:")
            if who.lower().startswith("everyone"):
                tiers.append(_tier("Everyone", 0.0, default_currency))
            elif re.search(r"(?i)\bmembers?\b", who) and len(who.split()) <= 6:     # anything else is prose, not a fee category
                tiers.append(_tier(who, 0.0, default_currency))
        m = re.search(r"(?i)\b(non-?members?)\b[^£.]{0,50}?([£€$])\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", ln)
        if m:
            tiers.append(_tier("Non-members", float(m.group(3).replace(",", "")), _SYM[m.group(2)]))
    return tiers


class BsgExtractor(WordPressGenericExtractor):
    LISTING_URL = _LISTING
    SOCIETY = "British Society of Gastroenterology"
    DEFAULT_SPECIALTY = "Gastroenterology & Hepatology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"
    MAX_PAGES = 8

    def _page(self, n: int, today: str) -> Optional[str]:
        url = f"{_LISTING}?page={n}&start={today}"
        for attempt in range(3):
            html = fetch_html(url, browser=getattr(self, "browser", None), expect_selector="#events-results")
            if html and 'id="events-results"' in html:
                return html
            time.sleep(2 * (attempt + 1))
        return None

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today()
        cards: List[Dict[str, Any]] = []
        total: Optional[int] = None
        for n in range(1, self.MAX_PAGES + 1):
            html = self._page(n, today.isoformat())
            if html is None:
                break
            tm = _TOTAL_RE.search(re.sub(r"<[^>]+>", " ", html))
            if tm and total is None:
                total = int(tm.group(1))
            got = parse_cards(html)
            cards.extend(got)
            if not got or total is None or len(cards) >= total:
                break
            time.sleep(self.REQUEST_GAP_S)
        if total == 0 and not cards:
            self.verified_empty = "bsg.org.uk/events pager reports 0 upcoming results"
        shells: List[Dict[str, Any]] = []
        seen = set()
        for c in cards:
            d = c["dates"]
            if d["end"] < today.isoformat() or (date.fromisoformat(d["start"]) - today).days > self.MAX_FUTURE_DAYS:
                continue
            if c["url"] in seen or re.search(r"(?i)\b(?:cancell?ed|postponed)\b", c["title"]):
                continue
            seen.add(c["url"])
            shells.append({"title": c["title"], "booking_url": c["url"], "source_url": c["url"], "start_date": d["start"],
                           "end_date": d["end"], "start_time": d["time"] if d["time"] != "00:00" else None,
                           "venue_raw": c["venue"] or None, "category": None})
        if total is not None and len(cards) != total:
            logger.warning(f"BSG: pager says {total} results but {len(cards)} cards were read")
        logger.info(f"BSG: {len(shells)} upcoming shells (pager total {total})")
        return shells or None

    def extract_detail(self, page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        html = page.content() if page is not None else ""
        title = shell["title"]
        out: Dict[str, Any] = {"society": self.SOCIETY, "start_date": shell["start_date"], "end_date": shell["end_date"]}
        if shell.get("start_time"):
            out["start_time"] = shell["start_time"]
        out["event_type"] = self._event_type(title)

        head_dates = None
        rt = re.search(r'(?is)<div class="rich-text">(.*)', html)
        body_html = rt.group(1) if rt else html
        body_html = re.split(r"(?is)<footer\b", body_html)[0]
        # header venue: the second <p class="m-0"> in the cover block (first is the date line)
        header_ps = [re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", p))).strip() for p in re.findall(r'(?is)<p class="m-0">(.*?)</p>', html)]
        header_ps = [p for p in header_ps if p]
        for i, p in enumerate(header_ps):
            if _DATES_RE.search(p):
                head_dates = parse_dates(p)
                venue_raw = header_ps[i + 1] if i + 1 < len(header_ps) and not _DATES_RE.search(header_ps[i + 1]) else None
                break
        else:
            venue_raw = None
        if head_dates:
            out["start_date"], out["end_date"] = head_dates["start"], head_dates["end"]
        out.update(place_from_raw(venue_raw or shell.get("venue_raw")))
        if not out.get("event_format") and re.search(r"(?i)\b(?:webinar|question time)\b", title):
            out["event_format"] = "online"                     # webinar pages carry no location line at all

        lines = html_to_lines(body_html)
        tiers = parse_fees(lines, self.DEFAULT_CURRENCY)
        if not tiers and any(re.fullmatch(r"(?i)(?:this event is )?free(?: to attend| of charge)?\.?", l) for l in lines[:40]):
            tiers = [{"tier_label": "Registration · Free", "price_gbp": 0.0, "currency": self.DEFAULT_CURRENCY,
                      "is_early_bird": False, "early_bird_deadline": None}]
        out["pricing_tiers"] = tiers

        text = " ".join(lines)
        cm = (re.search(r"(\d+(?:\.\d+)?)\s*(?:external\s+)?CPD\s*(?:points?|credits?|hours?)", text, re.I)
              or re.search(r"CPD\s*(?:points?|credits?)\s*[:=-]?\s*(\d+(?:\.\d+)?)", text, re.I)
              or re.search(r"approved for (\d+(?:\.\d+)?)\s[^.]{0,60}?CPD", text, re.I))
        if cm and 0.5 <= float(cm.group(1)) <= 100:
            out["cpd_points"], out["cpd_accredited"] = float(cm.group(1)), True
        if re.search(r"(?i)\b(?:sold out|fully booked|event full)\b", text[:4000]):
            out["is_sold_out"] = True

        desc = None
        for t in lines:
            if len(t) >= 70 and re.search(r"[.!?](\s|$)", t) and not _DESC_SKIP_RE.search(t):
                desc = t
                break
        if desc:
            out["description"] = desc[:600]
        out["specialty"] = self.DEFAULT_SPECIALTY
        return out

    @staticmethod
    def _event_type(title: str) -> str:
        t = title.lower()
        if re.search(r"\b(?:webinar|question time|bitesize)\b", t):
            return "workshop"
        if re.search(r"\b(?:course|capsule reading|masterclass)\b", t):
            return "course"
        if re.search(r"\b(?:highlights|taster|introduction to|introduction day)\b", t):
            return "workshop"
        return classify_event_type(title, "")
