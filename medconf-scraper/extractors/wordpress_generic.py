"""Family base for ordinary WordPress event archives (Wave 2c).

For sites that are NOT on The Events Calendar (Tribe) but publish a plain
`/events/` or `/event/` archive of cards, each linking to its own detail page.
A site is onboarded with a ~15-line subclass:

    class FooExtractor(WordPressGenericExtractor):
        LISTING_URL = "https://www.foo.org/events/"
        SOCIETY = "FOO"
        DEFAULT_SPECIALTY = "Cardiology"
        DEFAULT_CURRENCY = "GBP"
        # only when the defaults miss:
        #   EVENT_LINK_RE    regex on the URL *path* of a card link
        #   CARD_SPLIT_RE    regex that opens each card (default: slice between links)
        #   PAGINATION       'auto' | 'path' (/page/N/) | 'paged' (?paged=N) | 'page' (?page=N)

Listing (Phase A): walk the archive page by page (rel="next" link, else the
configured URL style), cut the HTML into one chunk per event link, read title
/ date range / venue line / category from the chunk. Dedupe by URL, upcoming
only, cancelled dropped. Every request goes through `http_fetch.fetch_html`.

Detail (Phase B), all deterministic, in this order of trust:
  JSON-LD `Event`  ->  header line near the title  ->  listing card values.
  Fees: JSON-LD offers -> `<table>` fee tables (pricing_tables) -> heading +
  `label / amount` lines -> a lone amount under a fee heading -> "free".
  Description = first real paragraph; specialty = title classifier, then the
  subclass default, then (only if both miss) one small LLM call.

Platform-agnostic by construction: nothing here assumes WordPress markup, so
Drupal/Joomla archives with card-per-event markup also work with constants.
"""

import html as _html
import json
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Page

from .base import BaseExtractor
from .http_fetch import fetch_html
from .pricing_tables import parse_pricing_tables
from .specialty_classifier import classify_specialty
from .tribe_events import clip_venue, html_to_lines, parse_fee_lines, pick_description
from logger import logger

# ── dates ───────────────────────────────────────────────────────────────────

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
           "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_M = (r"(?<![A-Za-z])(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
      r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)(?![A-Za-z])")
_D = r"\d{1,2}(?:st|nd|rd|th)?"
_SEP = r"\s*(?:-|\u2013|\u2014|to|until|till)\s*"
_W = r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?,?\s+)?"
_Y = r"\d{4}"
_DATE_RE = re.compile("|".join([
    # 28 October[,] 2026 - 29 October[,] 2026
    rf"(?P<r1>{_W}(?P<r1d1>{_D})\s+(?P<r1m1>{_M})\.?,?\s+(?P<r1y1>{_Y}){_SEP}{_W}(?P<r1d2>{_D})\s+(?P<r1m2>{_M})\.?,?\s+(?P<r1y2>{_Y}))",
    # 30 Sep - 2 Oct[,] 2026
    rf"(?P<r2>{_W}(?P<r2d1>{_D})\s+(?P<r2m1>{_M})\.?{_SEP}{_W}(?P<r2d2>{_D})\s+(?P<r2m2>{_M})\.?,?\s+(?P<r2y>{_Y}))",
    # 2-4 November[,] 2026
    rf"(?P<r3>{_W}(?P<r3d1>{_D}){_SEP}{_W}(?P<r3d2>{_D})\s+(?P<r3m>{_M})\.?,?\s+(?P<r3y>{_Y}))",
    # October 17 - 20, 2026 | Oct 17 - Nov 2, 2026 | December 30, 2026 - January 2, 2027
    rf"(?P<r4>(?P<r4m1>{_M})\.?\s+(?P<r4d1>{_D})(?:,?\s+(?P<r4y1>{_Y}))?{_SEP}(?:(?P<r4m2>{_M})\.?\s+)?(?P<r4d2>{_D}),?\s+(?P<r4y2>{_Y}))",
    # 3 December 2026
    rf"(?P<s1>{_W}(?P<s1d>{_D})\s+(?P<s1m>{_M})\.?,?\s+(?P<s1y>{_Y}))",
    # September 25, 2026
    rf"(?P<s2>(?P<s2m>{_M})\.?\s+(?P<s2d>{_D}),?\s+(?P<s2y>{_Y}))",
    # Tuesday 10 November  (no year: resolved from the weekday)
    rf"(?P<w>(?P<wwd>Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?,?\s+(?P<wd1>{_D})\s+(?P<wm1>{_M})\.?(?:{_SEP}(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?,?\s+)?(?P<wd2>{_D})\s+(?P<wm2>{_M})\.?)?(?!\s*,?\s*\d{{4}}))",
    # 12/10/2026 (UK day-first; swapped when the middle number cannot be a month)
    r"(?P<n1>(?P<n1a>\d{1,2})[/.](?P<n1b>\d{1,2})[/.](?P<n1y>\d{4}))",
    # 2026-10-12
    r"(?P<iso>(?P<isoy>\d{4})-(?P<isom>\d{2})-(?P<isod>\d{2}))",
]), re.I)
_PUBLISHED_BEFORE_RE = re.compile(r"(?:posted|published|updated|modified|written|created|deadline|closes?|until|by)\s*(?:on|:)?\s*$", re.I)


def _num(s: str) -> int:
    return int(re.match(r"\d+", s).group(0))


def _mon(s: str) -> int:
    return _MONTHS[s[:3].lower()]


def _iso(y: int, m: int, d: int) -> Optional[str]:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _year_from_weekday(wd: str, day: int, month: int, today: date) -> Optional[int]:
    """Year (last, this or next) in which day/month falls on weekday `wd`; the one
    nearest to today wins, so an unresolvable-looking past date still comes back past."""
    best = None
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            d = date(y, month, day)
        except ValueError:
            continue
        if d.weekday() == _WEEKDAYS.index(wd[:3].lower()):
            gap = abs((d - today).days)
            if best is None or gap < best[0]:
                best = (gap, y)
    return best[1] if best else None


def find_dates(text: str, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """All date mentions in `text`, in order: {start, end, pos, endpos, range}.
    Single dates have start == end. Dates introduced by "Posted on", "Updated",
    "Deadline" etc. are dropped (they are not the event date)."""
    out: List[Dict[str, Any]] = []
    today = today or date.today()
    for m in _DATE_RE.finditer(text or ""):
        g = m.groupdict()
        s = e = None
        if g["w"]:
            d1, m1 = _num(g["wd1"]), _mon(g["wm1"])
            y = _year_from_weekday(g["wwd"], d1, m1, today)
            if y:
                s = e = _iso(y, m1, d1)
                if g["wd2"]:
                    m2 = _mon(g["wm2"])
                    e = _iso(y + (1 if m2 < m1 else 0), m2, _num(g["wd2"])) or s
        elif g["r1"]:
            s = _iso(_num(g["r1y1"]), _mon(g["r1m1"]), _num(g["r1d1"]))
            e = _iso(_num(g["r1y2"]), _mon(g["r1m2"]), _num(g["r1d2"]))
        elif g["r2"]:
            y, m1, m2 = _num(g["r2y"]), _mon(g["r2m1"]), _mon(g["r2m2"])
            s = _iso(y - 1 if m1 > m2 else y, m1, _num(g["r2d1"]))
            e = _iso(y, m2, _num(g["r2d2"]))
        elif g["r3"]:
            y, mo = _num(g["r3y"]), _mon(g["r3m"])
            s, e = _iso(y, mo, _num(g["r3d1"])), _iso(y, mo, _num(g["r3d2"]))
        elif g["r4"]:
            y2 = _num(g["r4y2"])
            m1 = _mon(g["r4m1"])
            m2 = _mon(g["r4m2"]) if g["r4m2"] else m1
            y1 = _num(g["r4y1"]) if g["r4y1"] else (y2 - 1 if m1 > m2 else y2)
            s, e = _iso(y1, m1, _num(g["r4d1"])), _iso(y2, m2, _num(g["r4d2"]))
        elif g["s1"]:
            s = e = _iso(_num(g["s1y"]), _mon(g["s1m"]), _num(g["s1d"]))
        elif g["s2"]:
            s = e = _iso(_num(g["s2y"]), _mon(g["s2m"]), _num(g["s2d"]))
        elif g["n1"]:
            a, b, y = _num(g["n1a"]), _num(g["n1b"]), _num(g["n1y"])
            s = e = _iso(y, b, a) if b <= 12 else _iso(y, a, b)
        elif g["iso"]:
            s = e = _iso(_num(g["isoy"]), _num(g["isom"]), _num(g["isod"]))
        if not s or not e:
            continue
        if e < s:
            e = s
        if _PUBLISHED_BEFORE_RE.search(text[max(0, m.start() - 24):m.start()]):
            continue
        out.append({"start": s, "end": e, "pos": m.start(), "endpos": m.end(), "range": s != e})
    return out


def pick_event_dates(text: str, today: Optional[date] = None) -> Optional[Tuple[str, str]]:
    """(start, end) for a card / header block. A range form wins; two separate
    dates are a range only when the second is labelled "End"/"Ends"."""
    ds = find_dates(text, today)
    if not ds:
        return None
    first = ds[0]
    if first["range"] or len(ds) < 2:
        return first["start"], first["end"]
    second = ds[1]
    gap = text[first["endpos"]:second["pos"]]
    if re.search(r"\bend", gap, re.I) and second["start"] >= first["start"]:
        return first["start"], second["end"]
    return first["start"], first["end"]


_TIME_RE = re.compile(r"(?<![\d:/.])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])")


def find_start_time(text: str) -> Optional[str]:
    m = _TIME_RE.search(text or "")
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


# ── locations ───────────────────────────────────────────────────────────────

_COUNTRIES = set("""Albania Andorra Argentina Armenia Australia Austria Azerbaijan Belarus Belgium Bosnia Brazil Bulgaria Canada Chile China
Colombia Croatia Cyprus Czechia Denmark Egypt England Estonia Finland France Georgia Germany Greece Hungary Iceland India Indonesia
Iran Iraq Ireland Israel Italy Japan Jordan Kazakhstan Kenya Korea Kosovo Kuwait Latvia Lebanon Lithuania Luxembourg Malaysia Malta
Mexico Moldova Monaco Montenegro Morocco Nepal Netherlands Nigeria Norway Pakistan Peru Philippines Poland Portugal Qatar Romania
Russia Scotland Serbia Singapore Slovakia Slovenia Spain Sweden Switzerland Taiwan Thailand Tunisia Turkey Türkiye Ukraine Uruguay
Uzbekistan Venezuela Vietnam Wales Zimbabwe""".split()) | {
    "United Kingdom", "UK", "United States", "USA", "US", "United States of America", "South Africa", "Saudi Arabia", "New Zealand",
    "South Korea", "Hong Kong", "Sri Lanka", "United Arab Emirates", "UAE", "Czech Republic", "North Macedonia", "The Netherlands",
    "Northern Ireland", "Republic of Ireland", "Bosnia and Herzegovina", "Taiwan, China", "Costa Rica", "Puerto Rico"}
_VENUE_KW_RE = re.compile(
    r"\b(?:\w*klinik\w*|\w*krankenhaus|\w*spital|centre|center|hospital|infirmary|university|institute|college|hotel|hall|clinic|clinique|klinik|school|academy|museum|theatre|"
    r"theater|arena|campus|laboratory|library|congress|convention|suite|building|house|room|block|floor|church|palace|castle|"
    r"stadium|auditorium|pavilion|messe|palais|expo|royal|hilton|marriott|mercure|novotel|sheraton|hyatt|radisson|premier inn|holiday inn|ibis|"
    r"st\.?\s+\w+'s)\b", re.I)
_UK_COUNTIES = set("""Bedfordshire Berkshire Buckinghamshire Cambridgeshire Cheshire Cornwall Cumbria Derbyshire Devon Dorset Durham Essex
Gloucestershire Hampshire Herefordshire Hertfordshire Kent Lancashire Leicestershire Lincolnshire Merseyside Norfolk Northamptonshire
Northumberland Nottinghamshire Oxfordshire Rutland Shropshire Somerset Staffordshire Suffolk Surrey Sussex Warwickshire Wiltshire
Worcestershire Yorkshire""".split()) | {"East Sussex", "West Sussex", "North Yorkshire", "South Yorkshire", "West Yorkshire", "East Yorkshire",
    "West Midlands", "Greater London", "Greater Manchester", "Tyne and Wear", "Isle of Wight", "East Riding of Yorkshire"}
_POSTCODE_RE = re.compile(r"^(?:[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}|\d{4,6}(?:-\d{4})?|[A-Z]{2}\s?\d{4,5})$")
_ONLINE_ONLY_RE = re.compile(r"^(?:online|virtual|webinar|zoom|teams|on[\s-]?demand|livestream|remote|tba|tbc|tbd|to be (?:announced|confirmed))\b", re.I)


def split_location(raw: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Free-text location -> (venue_name, city, country). Conservative: a string
    of several bare place names ("Amsterdam, Athens, Copenhagen") is a multi-site
    course and yields nothing rather than a wrong venue."""
    if not raw:
        return None, None, None
    raw = re.sub(r"\s+", " ", _html.unescape(raw)).strip(" ,;|-\u2013.")
    if "|" in raw:                                   # "Lectures online | Practical | In-person | RCOG, London"
        raw = raw.split("|")[-1].strip(" ,;-\u2013.")
    raw = re.sub(r"\s[-\u2013]\s*(?=(?:%s)$)" % "|".join(sorted(map(re.escape, _COUNTRIES), key=len, reverse=True)), ", ", raw)
    if not raw or _ONLINE_ONLY_RE.match(raw):
        return None, None, None
    parts = [p.strip(" .") for p in raw.split(",") if p.strip(" .")]
    country = None
    if parts and parts[-1] in _COUNTRIES:
        country = parts.pop()
        if country == "UK":
            country = "United Kingdom"
        if country == "China" and parts and parts[-1] in ("Taiwan", "Hong Kong", "Macao", "Macao SAR"):
            country = parts.pop()                       # "..., Taiwan, China"
    parts = [re.sub(r"\s+[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}$", "", p) for p in parts]   # "London WC2A 3PE" -> London
    parts = [re.sub(r"^\d{5,6}\s+|\s+\d{5,6}$", "", p) for p in parts]                 # "69126 Heidelberg"
    parts = [p for p in parts if p and not _POSTCODE_RE.match(p)]
    parts = [re.sub(r"\s*\([^)]*$", "", p).strip() for p in parts]                        # dangling "(38-43 Lincoln's"
    parts = [p for p in parts if p]
    if not parts:
        return None, None, country
    if len(parts) >= 2 and parts[-1] in _UK_COUNTIES:     # "Guildford, Surrey": the county is the region, not the city
        county = parts.pop()
        country = f"{county}, {country}" if country else county
    kw = [bool(_VENUE_KW_RE.search(p)) for p in parts]
    if len(parts) == 1:
        return (parts[0], None, country) if (kw[0] or re.search(r"\d", parts[0])) else (None, parts[0], country)
    if any(kw) or any(re.match(r"\d", p) for p in parts):
        city = parts[-1] if not kw[-1] and not re.match(r"\d", parts[-1]) else None
        body = parts[:-1] if city else parts
        for i, p in enumerate(body):                  # drop the street address and anything after it
            if i > 0 and (re.match(r"\d", p) or re.search(r"\d\s*[a-z]?$|\b(?:strasse|stra\u00dfe|straat|street|st\.|road|rd|avenue|ave|rue|via|calle|platz|weg|lane|way)\b", p, re.I)):
                body = body[:i]
                break
        return ", ".join(body[:3]), city, country
    return None, None, country  # several bare place names: multi-site


# ── card parsing ────────────────────────────────────────────────────────────

_STRIP_BLOCKS_RE = re.compile(r"(?is)<(script|style|svg|noscript|nav|footer|aside|template)\b.*?</\1\s*>")
_COMMENT_RE = re.compile(r"(?s)<!--.*?-->")
_ANCHOR_RE = re.compile(r"(?is)<a\b([^>]*)>(.*?)</a\s*>")
_ATTR_RE = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_GENERIC_LINK_TEXT_RE = re.compile(
    r"^(?:read more|find out more|more info(?:rmation)?|learn more|view(?: event)?|details|register(?: now)?|book(?: now)?|"
    r"click here|see more|show congress|visit website|permalink.*)$", re.I)
_CHUNK_END_RE = re.compile(r'(?i)</main>|<footer\b|class="[^"]*pagination|facetwp-pager|class="[^"]*\bpager\b')
_HEADING_RE = re.compile(r"(?is)<h([1-6])\b[^>]*>(.*?)</h\1\s*>")
_CLASS_TITLE_RE = re.compile(r"""(?is)<(?:div|span|p|strong)\b[^>]*class=["'][^"']*\b(?:h[1-6]|[\w-]*title[\w-]*)\b[^"']*["'][^>]*>(.*?)</(?:div|span|p|strong)\s*>""")
_CLASS_VENUE_RE = re.compile(r"""(?is)<(?:div|span|p)\b[^>]*class=["'][^"']*\b(?:venue|location|address|eventaddress)\b[^"']*["'][^>]*>(.*?)</(?:div|span|p)\s*>""")
_CLASS_CAT_RE = re.compile(r"""(?is)<(?:div|span|p)\b[^>]*class=["'][^"']*\b(?:subheading|category|cat|event-type|type|tag)\b[^"']*["'][^>]*>(.*?)</(?:div|span|p)\s*>""")
_LABEL_VENUE_RE = re.compile(r"^(?:location|venue|where|address)\s*:\s*(.+)$", re.I)
_CANCELLED_RE = re.compile(r"\b(?:cancell?ed|postponed|sold out)\b", re.I)


def _attrs(s: str) -> Dict[str, str]:
    return {m.group(1).lower(): _html.unescape(m.group(2) if m.group(2) is not None else m.group(3) or "") for m in _ATTR_RE.finditer(s)}


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", " ".join(html_to_lines(fragment))).strip()


def default_event_link_re(listing_url: str) -> "re.Pattern[str]":
    path = urlparse(listing_url).path.rstrip("/")
    return re.compile(rf"^{re.escape(path)}/(?!page/)[^/?#]+/?$")


def classify_event_type(title: str, category: str = "") -> str:
    t = (title or "").lower()
    c = (category or "").lower()
    if re.search(r"\b(courses?|masterclass(?:es)?|master class(?:es)?|training|cadaver\w*|bootcamp|boot camp|programme part|certified)\b", t + " " + c):
        return "course"
    if re.search(r"\b(workshops?|webinars?|seminars?|study days?|bitesize|forums?|grand rounds|webcasts?)\b", t + " " + c):
        return "workshop"
    return "conference"


def parse_listing_cards(
    html: str,
    base_url: str,
    *,
    event_link_re: Optional["re.Pattern[str]"] = None,
    card_split_re: Optional["re.Pattern[str]"] = None,
    allow_external: bool = False,
) -> List[Dict[str, Any]]:
    """Listing HTML -> one shell per distinct event link, in page order.
    Pure (no network). Past/undated filtering is the caller's job."""
    html = _COMMENT_RE.sub("", _STRIP_BLOCKS_RE.sub(" ", html or ""))
    host = urlparse(base_url).netloc.lower().removeprefix("www.")
    link_re = event_link_re or default_event_link_re(base_url)

    def accept(href: str) -> Optional[str]:
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            return None
        u = urljoin(base_url, href).split("#")[0]
        p = urlparse(u)
        h = p.netloc.lower().removeprefix("www.")
        if not allow_external and h != host and not h.endswith("." + host):   # same site or a subdomain of it
            return None
        if not p.scheme.startswith("http"):
            return None
        return u if link_re.match(p.path) else None

    anchors: List[Tuple[int, str, Dict[str, str], str]] = []   # (pos, url, attrs, inner)
    for m in _ANCHOR_RE.finditer(html):
        a = _attrs(m.group(1))
        u = accept(a.get("href", ""))
        if u:
            anchors.append((m.start(), u, a, m.group(2)))

    chunks: List[Tuple[str, Dict[str, str], str, str]] = []     # (url, attrs, inner, chunk_html)
    if card_split_re is not None:
        starts = [m.start() for m in card_split_re.finditer(html)]
        for i, st in enumerate(starts):
            en = starts[i + 1] if i + 1 < len(starts) else min(len(html), st + 12000)
            seg = html[st:en]
            hit = next(((u, a, inner) for pos, u, a, inner in anchors if st <= pos < en), None)
            if hit:
                chunks.append((hit[0], hit[1], hit[2], seg))
    else:
        for i, (pos, u, a, inner) in enumerate(anchors):
            j = i + 1
            while j < len(anchors) and anchors[j][1] == u:
                j += 1
            en = anchors[j][0] if j < len(anchors) else min(len(html), pos + 9000)
            seg = html[pos:en]
            end_m = _CHUNK_END_RE.search(seg)
            if end_m:
                seg = seg[:end_m.start()]
            chunks.append((u, a, inner, seg))
        # An event URL can occur several times (menu entry, card title, "Find out more"):
        # keep the occurrence with a date, then a category/venue, then the most text.
        best: Dict[str, Tuple[Tuple[int, int, int], Tuple[str, Dict[str, str], str, str]]] = {}
        order: List[str] = []
        for ch in chunks:
            lines_ = html_to_lines(ch[3])
            txt = "\n".join(lines_)
            score = (1 if pick_event_dates(txt) else 0,
                     1 if (_CLASS_CAT_RE.search(ch[3]) or _CLASS_VENUE_RE.search(ch[3]) or _card_venue(ch[3], lines_)) else 0,
                     len(txt))
            if ch[0] not in best:
                order.append(ch[0])
            if ch[0] not in best or score > best[ch[0]][0]:
                best[ch[0]] = (score, ch)
        chunks = [best[u][1] for u in order]

    shells: List[Dict[str, Any]] = []
    seen_urls = set()
    for url, a, inner, seg in chunks:
        if url in seen_urls:
            continue
        seen_urls.add(url)
        title = _card_title(seg, a, inner)
        if not title:
            continue
        lines = html_to_lines(seg)
        text = "\n".join(lines)
        dates = pick_event_dates(text)
        cat_m = _CLASS_CAT_RE.search(seg)
        category = _text(cat_m.group(1)) if cat_m else None
        venue_raw = _card_venue(seg, lines)
        shells.append({
            "title": title,
            "booking_url": url,
            "source_url": url,
            "start_date": dates[0] if dates else None,
            "end_date": dates[1] if dates else None,
            "start_time": find_start_time(" ".join(l for l in lines if find_dates(l))) if dates else None,
            "venue_raw": venue_raw,
            "category": category or None,
        })
    return shells


def _card_title(seg: str, a: Dict[str, str], inner: str) -> Optional[str]:
    def ok(t: Optional[str]) -> Optional[str]:
        t = _text(t or "")
        t = re.sub(r"^(?:permanent link to|read more about|more about)\s*:?\s*", "", t, flags=re.I)
        return t if len(t) >= 3 and not _GENERIC_LINK_TEXT_RE.match(t) else None

    attr_title = ok(a.get("title")) or ok(a.get("aria-label"))
    cands = []
    hm = _HEADING_RE.search(seg)
    close = seg.lower().find("</a")
    if hm and close != -1 and hm.start() > close and ok(inner) and len(_text(inner)) <= 120:
        cands.append(ok(inner))                 # link text then a later section heading: the heading is not this card's
    if hm:
        cands.append(ok(hm.group(2)))
    cm = _CLASS_TITLE_RE.search(seg)
    if cm:
        cands.append(ok(cm.group(1)))
    cands += [attr_title, ok(inner)]
    title = next((c for c in cands if c), None)
    if title and attr_title and re.search(r"(?:\.\.\.|\u2026)$", title) and attr_title.lower().startswith(re.sub(r"(?:\.\.\.|\u2026)$", "", title).lower()):
        title = attr_title                      # theme truncated the heading; the title attribute is whole
    return title


def _card_venue(seg: str, lines: List[str]) -> Optional[str]:
    m = _CLASS_VENUE_RE.search(seg)
    if m:
        v = _text(m.group(1))
        v = re.sub(r"^(?:location|venue)\s*:?\s*", "", v, flags=re.I)
        if v:
            return v
    for i, ln in enumerate(lines):
        lm = _LABEL_VENUE_RE.match(ln)
        if lm:
            return lm.group(1).strip()
        if re.match(r"^(?:location|venue)\s*:?$", ln, re.I) and i + 1 < len(lines):
            return lines[i + 1].strip()
    return None


def next_page_url(html: str, current_url: str, page_no: int, style: str = "auto") -> Optional[str]:
    """URL of listing page `page_no + 1`: rel="next", else a "next" pagination
    anchor, else built from `style`."""
    h = re.sub(r"(?is)<(script|style)\b.*?</\1\s*>", " ", html or "")   # keep <nav>: that is where pagers live
    for rx in (r"""<link\b[^>]*rel=["']next["'][^>]*href=["']([^"']+)""",
               r"""<link\b[^>]*href=["']([^"']+)["'][^>]*rel=["']next["']""",
               r"""<a\b[^>]*rel=["']next["'][^>]*href=["']([^"']+)""",
               r"""<a\b[^>]*href=["']([^"']+)["'][^>]*rel=["']next["']""",
               r"""<[^>]+class=["'][^"']*(?:pagination-next|next page-numbers|pager__item--next)[^"']*["'][^>]*>\s*<a\b[^>]*href=["']([^"']+)""",
               r"""<a\b[^>]*class=["'][^"']*\bnext\b[^"']*["'][^>]*href=["']([^"']+)"""):
        m = re.search(rx, h, re.I)
        if m:
            u = urljoin(current_url, _html.unescape(m.group(1)))
            if u.split("#")[0] != current_url.split("#")[0]:
                return u
    if style == "auto":
        return None
    return build_page_url(current_url, page_no + 1, style)


def build_page_url(url: str, n: int, style: str) -> str:
    """Page-N URL for the three common archive styles."""
    p = urlparse(url)
    base = url.split("?")[0].split("#")[0]
    base = re.sub(r"/page/\d+/?$", "/", base)
    if style == "path":
        return f"{base.rstrip('/')}/page/{n}/"
    key = "paged" if style == "paged" else "page"
    q = re.sub(rf"(^|&){key}=\d+", "", p.query).strip("&")
    q = f"{q}&{key}={n}" if q else f"{key}={n}"
    return f"{base}?{q}"



# ── optional WordPress REST path ────────────────────────────────────────────

_REST_DATE_KEY_RE = re.compile(r"date|start|begin|from|end|finish|until|\bto\b", re.I)


def _as_iso(v: Any) -> Optional[str]:
    v = str(v or "").strip()
    if re.match(r"^\d{8}$", v):                       # ACF date picker: 20261103
        return _iso(int(v[:4]), int(v[4:6]), int(v[6:]))
    ds = find_dates(v)
    return ds[0]["start"] if ds else None


def rest_record_to_shell(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """WP REST record -> shell, ONLY when the record itself carries event dates in
    `acf`/`meta` (the core `date` field is the publish date and is never used)."""
    fields: Dict[str, Any] = {}
    for k in ("meta", "acf"):
        if isinstance(rec.get(k), dict):
            fields.update(rec[k])
    start = end = venue = None
    for k, v in fields.items():
        if isinstance(v, (str, int)) and _REST_DATE_KEY_RE.search(k):
            iso = _as_iso(v)
            if iso:
                if re.search(r"end|finish|until|to$", k, re.I):
                    end = end or iso
                else:
                    start = start or iso
        elif isinstance(v, str) and re.search(r"venue|location", k, re.I) and not venue:
            venue = v.strip() or None
    title = _text((rec.get("title") or {}).get("rendered", "")) if isinstance(rec.get("title"), dict) else ""
    url = rec.get("link") or ""
    if not (start and title and url):
        return None
    return {"title": title, "booking_url": url, "source_url": url, "start_date": start,
            "end_date": end if end and end >= start else start, "start_time": None,
            "venue_raw": venue, "category": None}

# ── JSON-LD ─────────────────────────────────────────────────────────────────

_LD_RE = re.compile(r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script\s*>')


def _walk_ld(node: Any):
    if isinstance(node, list):
        for x in node:
            yield from _walk_ld(x)
    elif isinstance(node, dict):
        yield node
        for k in ("@graph", "subEvent", "event"):
            if k in node:
                yield from _walk_ld(node[k])


def json_ld_events(html: str) -> List[Dict[str, Any]]:
    out = []
    for m in _LD_RE.finditer(html or ""):
        try:
            data = json.loads(_html.unescape(m.group(1)).strip())
        except ValueError:
            continue
        for node in _walk_ld(data):
            t = node.get("@type")
            ts = t if isinstance(t, list) else [t]
            if any(isinstance(x, str) and x.endswith("Event") for x in ts):
                out.append(node)
    return out


def tiers_from_offers(ev: Dict[str, Any], default_currency: str = "GBP") -> List[Dict[str, Any]]:
    offers = ev.get("offers")
    offers = [offers] if isinstance(offers, dict) else (offers or [])
    tiers, seen = [], set()
    for o in offers:
        if not isinstance(o, dict):
            continue
        raw = o.get("price", o.get("lowPrice"))
        try:
            amt = float(str(raw).replace(",", "").strip())
        except (TypeError, ValueError):
            continue
        cur = (o.get("priceCurrency") or default_currency).upper()
        name = _text(str(o.get("name") or o.get("category") or o.get("description") or "")) or ("Free" if amt == 0 else "Standard")
        label = f"Registration \u00b7 {name[:70]}"
        key = (label, amt, cur)
        if key in seen:
            continue
        seen.add(key)
        tiers.append({"tier_label": label, "price_gbp": amt, "currency": cur,
                      "is_early_bird": bool(re.search(r"early[\s-]?bird", name, re.I)), "early_bird_deadline": None})
    return tiers


def location_from_ld(ev: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str], bool]:
    """(venue, city, country, virtual_only) from a JSON-LD Event."""
    loc = ev.get("location")
    locs = loc if isinstance(loc, list) else [loc]
    venue = city = country = None
    virtual = False
    for l in locs:
        if isinstance(l, str):
            venue = venue or l.strip() or None
            continue
        if not isinstance(l, dict):
            continue
        if "VirtualLocation" in str(l.get("@type")):
            virtual = True
            continue
        name = (l.get("name") or "").strip()
        addr = l.get("address")
        if isinstance(addr, dict):
            city = city or (addr.get("addressLocality") or "").strip() or None
            c = addr.get("addressCountry")
            country = country or ((c.get("name") if isinstance(c, dict) else c) or "").strip() or None
        elif isinstance(addr, str) and not city:
            v, c2, k = split_location(addr)
            city, country = c2, k
        if name and not _ONLINE_ONLY_RE.match(name):
            venue = venue or name
    return venue, city, country, virtual and not (venue or city)


# ── fees ────────────────────────────────────────────────────────────────────

_AMOUNT_ONLY_RE = re.compile(r"^(?:from\s+)?(£|€|\$|GBP|EUR|USD|CHF)\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:\+\s*VAT)?\*?$", re.I)
_FEE_HEAD_RE = re.compile(r"^(?:registration fees?|course fees?|fees?|pricing|prices?|ticket prices?|cost|costs?)\s*:?$", re.I)
_HEAD_AMOUNT_RE = re.compile(r"^(fees?|prices?|cost|registration fees?|ticket price)\s*:?\s*(£|€|\$|GBP|EUR|USD|CHF)\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)\*?$", re.I)
_HEAD_RANGE_RE = re.compile(
    r"^(fees?|prices?|cost|registration fees?|ticket price)\s*:?\s*(£|€|\$|GBP|EUR|USD|CHF)\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:-|\u2013|to)\s*"
    r"(?:(?:£|€|\$|GBP|EUR|USD|CHF)\s?)?([0-9][0-9,]*(?:\.[0-9]{1,2})?)\*?$", re.I)
_FREE_LINE_RE = re.compile(r"^(?:registration\s+)?(?:fees?|cost|price|admission|entry)\s*:\s*(?:free|no charge)\b", re.I)
_FREE_RE = re.compile(r"\bfree (?:to attend|of charge|event|webinar|registration|entry)\b|\bno (?:charge|cost|fee)\b|\bfree\b\s*$", re.I)
_SYM = {"£": "GBP", "€": "EUR", "$": "USD"}


def dedupe_consecutive(lines: List[str]) -> List[str]:
    out: List[str] = []
    for l in lines:
        if not out or out[-1] != l:
            out.append(l)
    return out


def fee_tiers_from_lines(lines: List[str], default_currency: str = "GBP") -> List[Dict[str, Any]]:
    """`Heading` + `label / amount` rows; else `Heading` + lone amount; else free."""
    lines = dedupe_consecutive([l for l in lines if len(l) <= 200])
    tiers = parse_fee_lines(lines, default_currency=default_currency)
    if tiers:
        return tiers
    for ln in lines:                                  # "Fees: Free for ERS members and non-members"
        if _FREE_LINE_RE.match(ln):
            return [{"tier_label": "Fees \u00b7 Free", "price_gbp": 0.0, "currency": default_currency,
                     "is_early_bird": False, "early_bird_deadline": None}]
    for ln in lines:                                  # "Price £200-£350": the site gives a range, not labelled grades
        m = _HEAD_RANGE_RE.match(ln)
        if m:
            cur = _SYM.get(m.group(2), m.group(2).upper())
            lo, hi = float(m.group(3).replace(",", "")), float(m.group(4).replace(",", ""))
            head = m.group(1).title()
            rows = [(f"{head} \u00b7 Lowest rate", lo)] + ([(f"{head} \u00b7 Highest rate", hi)] if hi != lo else [])
            return [{"tier_label": lab, "price_gbp": amt, "currency": cur, "is_early_bird": False, "early_bird_deadline": None}
                    for lab, amt in rows]
    for ln in lines:                                  # "Price £950" on one line
        m = _HEAD_AMOUNT_RE.match(ln)
        if m:
            cur = _SYM.get(m.group(2), m.group(2).upper())
            return [{"tier_label": f"{m.group(1).title()} \u00b7 Standard", "price_gbp": float(m.group(3).replace(",", "")),
                     "currency": cur, "is_early_bird": False, "early_bird_deadline": None}]
    for i, ln in enumerate(lines):
        if not _FEE_HEAD_RE.match(ln):
            continue
        found = []
        for nxt in lines[i + 1:i + 4]:
            m = _AMOUNT_ONLY_RE.match(nxt)
            if m:
                cur = _SYM.get(m.group(1), m.group(1).upper())
                found.append({"tier_label": f"{ln.rstrip(':').title()} \u00b7 Standard", "price_gbp": float(m.group(2).replace(",", "")),
                              "currency": cur, "is_early_bird": False, "early_bird_deadline": None})
                break
        if found:
            return found
        if i + 1 < len(lines) and _FREE_RE.search(lines[i + 1]) and len(lines[i + 1]) < 60:
            return [{"tier_label": f"{ln.rstrip(':').title()} \u00b7 Free", "price_gbp": 0.0, "currency": default_currency,
                     "is_early_bird": False, "early_bird_deadline": None}]
    return []


# ── detail ──────────────────────────────────────────────────────────────────

_CPD_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:external\s+)?(?:CPD|CME|EBAP|CE)\s*(?:points?|credits?|hours?)"
    r"|(?:CPD|CME)\s*(?:points?|credits?)\s*[:=-]?\s*(\d+(?:\.\d+)?)", re.I)
_FMT_TOKEN_RE = re.compile(r"^(?:in[\s-]?person|online|virtual|hybrid|face[\s-]to[\s-]face|webinar|webcast|livestream)$", re.I)
_COOKIE_RE = re.compile(r"cookie|consent|remembering users|privacy|gdpr|browser|javascript|session storage|third[- ]party|"
                        r"\bCDN\b|network administrator|redirected to|click on continue|you must (?:log|sign)|please (?:log|sign)|log in|login", re.I)
_SOLD_OUT_RE = re.compile(r"\b(?:sold out|fully booked|event full|no places (?:left|remaining)|waiting list only)\b", re.I)
_DETAIL_CHROME_RE = re.compile(r"(?is)<(script|style|svg|noscript|nav|footer|aside|form|template)\b.*?</\1\s*>")


def _meta(html: str, name: str) -> Optional[str]:
    for rx in (rf"""<meta\b[^>]*(?:property|name)=["']{name}["'][^>]*content=["']([^"']*)""",
               rf"""<meta\b[^>]*content=["']([^"']*)["'][^>]*(?:property|name)=["']{name}["']"""):
        m = re.search(rx, html or "", re.I)
        if m:
            return _html.unescape(m.group(1)).strip() or None
    return None


def header_zone(lines: List[str], title: str, n: int = 30) -> List[str]:
    """Lines right after the title in the page body; the occurrence followed by a date wins."""
    tl = re.sub(r"\W+", "", (title or "").lower())
    head: List[str] = []
    for i, ln in enumerate(lines):
        if tl and re.sub(r"\W+", "", ln.lower()) == tl:
            head = lines[i + 1:i + 1 + n]
            if any(find_dates(h) for h in head[:8]):
                break
    if not any(find_dates(h) for h in head[:8]):          # title differs from the card (e.g. "- 19 NOVEMBER, 2026" suffix)
        for i, ln in enumerate(lines[:150]):
            if "|" in ln and find_dates(ln):
                return lines[i:i + n]
    return head


class WordPressGenericExtractor(BaseExtractor):
    LISTING_URL: str = ""
    SOCIETY: str = ""
    DEFAULT_SPECIALTY: Optional[str] = None
    PREFER_DEFAULT_SPECIALTY: bool = False
    DEFAULT_CURRENCY: str = "GBP"
    DEFAULT_EVENT_TYPE: Optional[str] = None     # force a type (else classified from title/category)
    EVENT_LINK_RE: Optional["re.Pattern[str]"] = None
    CARD_SPLIT_RE: Optional["re.Pattern[str]"] = None
    REST_POST_TYPE: Optional[str] = None         # e.g. 'events': use /wp-json/wp/v2/<type> when its records carry event dates
    EXTERNAL_LINKS: bool = False                 # cards link to other sites (calendar of third-party events)
    PAGINATION: str = "auto"                     # auto | path | paged | page
    MAX_PAGES: int = 12
    STOP_AFTER_EMPTY_PAGES: int = 2              # stop after N consecutive pages that add no upcoming event
    ONLINE_CATEGORY_RE: Optional["re.Pattern[str]"] = None   # cards of this category are online; their place line is not a venue
    REQUEST_GAP_S: float = 1.0
    MAX_FUTURE_DAYS: int = 1100                  # farther out = placeholder / on-demand e-learning date: skipped
    MAX_DETAIL_LOOKUPS: int = 30                 # cap on extra page loads for undated cards per run
    DATE_FROM_DETAIL: bool = True                # undated cards: read the date from the detail page, drop if none
    DETAIL_HEADER_LINES: int = 30                # lines after the title searched for date / venue

    # ---- hooks (override per site only if needed) -------------------------
    def skip_event(self, shell: Dict[str, Any]) -> bool:
        return False

    def venue_from_lines(self, lines: List[str], shell: Dict[str, Any]) -> Optional[str]:
        """Optional per-site hook: raw venue text found in the detail page lines (default none)."""
        return None

    def parse_listing(self, html: str, url: str) -> List[Dict[str, Any]]:
        return parse_listing_cards(html, url, event_link_re=self.EVENT_LINK_RE or default_event_link_re(self.LISTING_URL),
                                   card_split_re=self.CARD_SPLIT_RE, allow_external=self.EXTERNAL_LINKS)

    # ---- listing ----------------------------------------------------------
    def _fetch(self, url: str) -> Optional[str]:
        for attempt in range(3):
            body = fetch_html(url, browser=getattr(self, "browser", None))
            if body and len(body) > 500:
                return body
            logger.warning(f"{self.SOCIETY} listing fetch attempt {attempt + 1}/3 failed for {url}")
            time.sleep(2 * (attempt + 1))
        return None

    def _rest_shells(self) -> List[Dict[str, Any]]:
        root = re.match(r"https?://[^/]+", self.LISTING_URL).group(0)
        out: List[Dict[str, Any]] = []
        for pg in range(1, self.MAX_PAGES + 1):
            body = fetch_html(f"{root}/wp-json/wp/v2/{self.REST_POST_TYPE}?per_page=100&page={pg}&_fields=link,title,acf,meta",
                              browser=getattr(self, "browser", None), headers={"Accept": "application/json"})
            try:
                recs = json.loads(body or "[]")
            except ValueError:
                recs = []
            if not isinstance(recs, list) or not recs:
                break
            out += [sh for sh in (rest_record_to_shell(r) for r in recs if isinstance(r, dict)) if sh]
            if len(recs) < 100:
                break
            time.sleep(self.REQUEST_GAP_S)
        return out

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today().isoformat()
        if self.REST_POST_TYPE:
            rest = [r for r in self._rest_shells() if (r["end_date"] or r["start_date"]) >= today]
            if rest:
                logger.info(f"{self.SOCIETY} WP REST ({self.REST_POST_TYPE}): {len(rest)} shells")
                return rest
        url = self.LISTING_URL
        shells: List[Dict[str, Any]] = []
        seen_urls, seen_pages, seen_keys = set(), set(), set()
        lookups = 0
        empty_pages = 0
        for page_no in range(1, self.MAX_PAGES + 1):
            seen_pages.add(url)
            html = self._fetch(url)
            if html is None:
                if page_no == 1:
                    return None
                break
            cards = self.parse_listing(html, url)
            new = [c for c in cards if c["booking_url"] not in seen_urls]
            if not new:
                break
            before = len(shells)
            for c in new:
                seen_urls.add(c["booking_url"])
                if _CANCELLED_RE.search(c["title"]) or self.skip_event(c):
                    continue
                if c["start_date"] and (c["end_date"] or c["start_date"]) < today:
                    continue
                if not c["start_date"]:
                    if lookups >= self.MAX_DETAIL_LOOKUPS:
                        continue
                    lookups += 1
                    if not self._date_from_detail(c, today):
                        continue
                    if (c["end_date"] or c["start_date"]) < today:
                        continue
                key = (re.sub(r"\W+", "", c["title"].lower()), c["start_date"])
                if key in seen_keys:
                    continue
                if (date.fromisoformat(c["start_date"]) - date.today()).days > self.MAX_FUTURE_DAYS:
                    continue
                seen_keys.add(key)
                shells.append(c)
            empty_pages = empty_pages + 1 if len(shells) == before else 0
            if empty_pages >= self.STOP_AFTER_EMPTY_PAGES:
                break
            nxt = next_page_url(html, url, page_no, self.PAGINATION)
            if not nxt or nxt in seen_pages:
                break
            url = nxt
            time.sleep(self.REQUEST_GAP_S)
        logger.info(f"{self.SOCIETY} generic WP listing: {len(shells)} shells")
        return shells or None

    def _date_from_detail(self, c: Dict[str, Any], today: str) -> bool:
        """Undated listing card: fetch its page once and read the header-zone date.
        A page with no date ("More information coming soon") is dropped, not stored undated."""
        if not self.DATE_FROM_DETAIL:
            return False
        time.sleep(self.REQUEST_GAP_S)
        html = fetch_html(c["booking_url"], browser=getattr(self, "browser", None))
        if not html:
            return False
        lines = dedupe_consecutive(html_to_lines(_DETAIL_CHROME_RE.sub(" ", html)))
        ld = (json_ld_events(html) or [None])[0]
        if ld and re.match(r"\d{4}-\d{2}-\d{2}", ld.get("startDate") or ""):
            c["start_date"] = ld["startDate"][:10]
            c["end_date"] = (ld.get("endDate") or ld["startDate"])[:10]
            return True
        for h in header_zone(lines, c["title"]):
            d = pick_event_dates(h)
            if d:
                c["start_date"], c["end_date"] = d
                c["start_time"] = find_start_time(h)
                return True
        return False

    # ---- detail -----------------------------------------------------------
    def extract_detail(self, page: Page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        html = page.content() if page is not None else ""
        return self.detail_from_html(html, shell, llm_call)

    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {"society": self.SOCIETY}
        title = shell.get("title") or ""
        ld = (json_ld_events(html) or [None])[0]
        body_html = _DETAIL_CHROME_RE.sub(" ", html)
        lines = dedupe_consecutive(html_to_lines(body_html))
        text = " ".join(lines)
        category = shell.get("category") or ""

        out["event_type"] = self.DEFAULT_EVENT_TYPE or classify_event_type(title, category)

        head = header_zone(lines, title, self.DETAIL_HEADER_LINES)
        tl = re.sub(r"\W+", "", title.lower())
        head_dates_line = next((h for h in head if find_dates(h)), None)

        # dates
        start, end = shell.get("start_date"), shell.get("end_date")
        if ld and not start:
            s, e = (ld.get("startDate") or "")[:10], (ld.get("endDate") or "")[:10]
            if re.match(r"\d{4}-\d{2}-\d{2}$", s):
                start, end = s, (e if re.match(r"\d{4}-\d{2}-\d{2}$", e) else s)
        if head_dates_line:
            hd = pick_event_dates(head_dates_line)
            if hd and not start:
                start, end = hd
            elif hd and start == hd[0] and (not end or hd[1] > end):
                end = hd[1]                       # listing showed one day, header shows the range
        if start:
            out["start_date"] = start
            out["end_date"] = end or start
        st = find_start_time(head_dates_line or "") if head_dates_line else None
        if ld and not st and re.search(r"T\d{2}:\d{2}", ld.get("startDate") or ""):
            st = (ld["startDate"].split("T")[1])[:5]
        if st:
            out["start_time"] = st

        # location + format
        venue = city = country = None
        virtual = False
        online_cat = bool(self.ONLINE_CATEGORY_RE and self.ONLINE_CATEGORY_RE.search(category))
        if online_cat:
            shell = {**shell, "venue_raw": None}          # e.g. FDI "CE programme": the place line is the speaker's country
        if ld:
            venue, city, country, virtual = location_from_ld(ld)
        header_fmt = None
        if head_dates_line and "|" in head_dates_line:
            for part in [p.strip() for p in head_dates_line.split("|")]:
                if find_dates(part) or re.match(r"^(?:one|two|three|four|five)[\s-]day$", part, re.I) or not part or re.match(r"^\d{1,2}[:.]\d{2}", part):
                    continue
                if _FMT_TOKEN_RE.match(part):
                    header_fmt = part.lower()
                    continue
                if not (venue or city) and header_fmt not in ("online", "virtual", "webinar", "webcast", "livestream"):
                    v, c, k = split_location(part)
                    if v or (c and k) or (c and "," in part):      # a bare word is a topic tag, not a place
                        venue, city, country = v, c, k
        if not (venue or city):
            raw = shell.get("venue_raw")
            labelled = self._labelled_location(lines)
            for cand in (raw, labelled):
                if cand and _ONLINE_ONLY_RE.match(cand.strip()):
                    virtual = True
                    break
                v, c, k = split_location(cand)
                if v or c:
                    venue, city, country = v, c, k
                    break
        elif not venue and shell.get("venue_raw"):
            v, c, k = split_location(shell["venue_raw"])
            if c == city and v:
                venue = v
        if not venue:
            hv = self.venue_from_lines(lines, shell)
            if hv:
                v, c, k = split_location(hv)
                venue = v
                city, country = city or c, country or k
        venue = clip_venue(venue)
        probe = f"{title} {category} {' '.join(head[:6])}".lower()
        mode = str((ld or {}).get("eventAttendanceMode") or "")
        if online_cat:
            fmt = "online"
        elif "Mixed" in mode or "hybrid" in probe or header_fmt == "hybrid":
            fmt = "hybrid"
        elif "Online" in mode or header_fmt in ("online", "virtual", "webinar", "webcast", "livestream") or (virtual and not (venue or city)):
            fmt = "online"
        elif venue or city:
            fmt = "in_person"
        elif re.search(r"\b(webinar|webcast|zoom)\b", probe):
            fmt = "online"
        else:
            fmt = None
        if fmt:
            out["event_format"] = fmt
        if venue:
            out["venue_name"] = venue
        if city:
            out["city"] = city
        if country:
            out["region"] = country

        # fees
        tiers: List[Dict[str, Any]] = tiers_from_offers(ld, self.DEFAULT_CURRENCY) if ld else []
        if not tiers:
            tiers = parse_pricing_tables(body_html, default_currency=self.DEFAULT_CURRENCY)
        if not tiers:
            tiers = fee_tiers_from_lines(lines, self.DEFAULT_CURRENCY)
        if tiers:
            out["pricing_tiers"] = tiers
        if _SOLD_OUT_RE.search(text[:20000]):
            out["is_sold_out"] = True

        # CPD
        m = _CPD_RE.search(text)
        if m:
            try:
                out["cpd_points"] = float(m.group(1) or m.group(2))
                out["cpd_accredited"] = True
            except ValueError:
                pass

        # abstracts / call for papers: left to the merge step (PLAYBOOK pattern 7), which sees the page text and follows PDFs

        # description + specialty
        title_idx = [i for i, l in enumerate(lines) if tl and re.sub(r"\W+", "", l.lower()) == tl]
        body_lines = lines[title_idx[-1] + 1:] if title_idx else lines
        body_lines = [l for l in body_lines if not _COOKIE_RE.search(l)]
        desc = pick_description(body_lines, title) or (ld or {}).get("description") or None
        if not desc:
            md = _meta(html, "og:description") or _meta(html, "description")
            desc = md if md and len(md) >= 50 else None
        if desc:
            out["description"] = _html.unescape(re.sub(r"<[^>]+>", " ", desc)).strip()[:600]
        spec = None
        if self.PREFER_DEFAULT_SPECIALTY and self.DEFAULT_SPECIALTY:
            spec = self.DEFAULT_SPECIALTY
        else:
            spec = classify_specialty(title) or classify_specialty(title, out.get("description")) or self.DEFAULT_SPECIALTY
        if not spec and llm_call:
            try:
                resp = llm_call(
                    "Name the single medical specialty (1-3 words, e.g. Cardiology) this event is for. "
                    f"Reply with only the specialty or NONE.\nTitle: {title}\nText: {text[:1500]}")
                resp = (resp or "").strip().strip(".\"'")
                if resp and resp.upper() != "NONE" and len(resp) <= 40:
                    spec = resp
            except Exception:  # noqa: BLE001
                spec = None
        if spec:
            out["specialty"] = spec
        return out

    @staticmethod
    def _labelled_location(lines: List[str]) -> Optional[str]:
        for i, ln in enumerate(lines):
            m = _LABEL_VENUE_RE.match(ln)
            if m:
                return m.group(1).strip()
            if re.match(r"^(?:location|venue)\s*:?$", ln, re.I) and i + 1 < len(lines):
                nxt = lines[i + 1]
                if len(nxt) <= 160 and not re.match(r"^(?:price|website|name|email|phone)", nxt, re.I):
                    return nxt
        return None
