"""BMFMS (British Maternal & Fetal Medicine Society) events calendar: WordPress-family subclass, custom listing.

`bmfms.org.uk/professionals/events` is an ASP.NET page (lmsitestarterduke CMS), fully server-rendered. It shows ONE
YEAR at a time ("Events in 2026"), from today onwards, as `div.date_row` rows grouped under `div.month_row` headings:
a "Dates" cell ("21 Nov 8:30AM - 22 Nov 5:00PM 2026", "12 - 13 Nov 2026", "15 Oct 2026 5:30PM - 6:00PM"), a "Title" cell
linking to `/professionals/events/<id>/<slug>` and a "Location" cell (a venue, a city, or "Virtual / Online"). The year
pager links to `/professionals/events/date/<YYYY>/`, so Phase A reads the current view plus the next two year pages.
The `?page=` style pagination in the recon does not exist: filters are `?region=` / `?type=` only.

The calendar mixes BMFMS-organised meetings, RCOG events and "meetings of interest" run by other bodies (BICS, ISOM,
commercial course providers), so rows are third-party events and `booking_url` is the BMFMS detail page. The recurring
"BMFMS Webinar series" row reuses ONE detail URL for several dates; each date gets its own row via a `#<date>` fragment
(the page is the same, `source_url` stays unique).

Detail pages are thin: `span.meta_date` + a `<p>` place line under the h2, a free-text description, then external
"Book online for this event" and "Further details about this event" links (fees live on those organiser sites, never
on bmfms.org.uk), stored as `organiser_url` for the explorer to follow.
"""
import html as _html
import re
import time
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from playwright.sync_api import Page

from logger import logger

from .http_fetch import fetch_html
from .tribe_events import html_to_lines
from .wordpress_generic import (WordPressGenericExtractor, classify_event_type, clip_venue, pick_event_dates)

_ROOT = "https://www.bmfms.org.uk"
_PROMOTER_RE = re.compile(r"(?i)^\s*\d+(?:st|nd|rd|th)\s+(?:international|world|global)\b.*\b(?:conference|congress|summit)\b")   # conference-mill titles ("5th International Conference on ...")


_ROW_RE = re.compile(r'(?is)<div class="date_row\b.*?(?=<div class="date_row\b|<div class=.row.><div class=.col-xs-12.><div class=.month_row|</section>|<footer|$)')
_CELL_RE = re.compile(r'(?is)<div class="col-sm-4">(.*?)</div>')
_LINK_RE = re.compile(r'(?is)<a href="(/professionals/events/\d+/[^"#?]+)"[^>]*>(.*?)</a>')
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*([AP]M)", re.I)

_UK_CITIES = {
    "London": "England", "Birmingham": "England", "Manchester": "England", "Liverpool": "England", "Leeds": "England",
    "Sheffield": "England", "Bristol": "England", "Newcastle": "England", "Nottingham": "England", "Leicester": "England",
    "Oxford": "England", "Cambridge": "England", "Southampton": "England", "Harrogate": "England", "Northampton": "England",
    "St Albans": "England", "Preston": "England", "Coventry": "England", "Kettering": "England", "Windsor": "England",
    "Darlington": "England", "York": "England", "Brighton": "England", "Bath": "England", "Exeter": "England",
    "Cardiff": "Wales", "Swansea": "Wales", "Edinburgh": "Scotland", "Glasgow": "Scotland", "Aberdeen": "Scotland",
    "Dundee": "Scotland", "Belfast": "Northern Ireland",
}
_STREET_RE = re.compile(r"\b(?:road|street|lane|avenue|drive|close|way|place|square|terrace|row)\b", re.I)
_POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*(?:\d[A-Z]{2})?\b")


def uk_place(raw: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """'Wembley, London' / 'John Parker Lecture Theatre, ..., Blackshaw Road, London SW17 0QT' / 'Mercure Northampton'
    -> (venue, city, region). Only a known UK town counts as the city; the street and postcode are dropped."""
    if not raw:
        return None, None, None
    parts = [re.sub(r"\s+", " ", _POSTCODE_RE.sub("", p)).strip(" .-–") for p in re.split(r",|–|\|", raw)]
    parts = [p for p in parts if p and p.lower() not in ("uk", "united kingdom", "england", "scotland", "wales", "northern ireland")]
    city = None
    for p in reversed(parts):
        hit = next((c for c in _UK_CITIES if re.search(rf"\b{c}\b", p)), None)
        if hit:
            city = hit
            break
    venue_parts = [p for p in parts if not _STREET_RE.search(p) and p != city]
    venue = clip_venue(", ".join(venue_parts[:3])) if venue_parts else None
    return venue, city, _UK_CITIES.get(city) if city else None


def _txt(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag))).replace("\xa0", " ").strip()


def _start_time(text: str) -> Optional[str]:
    m = _TIME_RE.search(text or "")
    if not m:
        return None
    h = int(m.group(1)) % 12 + (12 if m.group(3).upper() == "PM" else 0)
    return f"{h:02d}:{m.group(2)}"


def parse_listing(html: str) -> List[Dict[str, Any]]:
    """Year/month listing HTML -> one dict per row (pure)."""
    out: List[Dict[str, Any]] = []
    for row in _ROW_RE.findall(html or ""):
        cells = _CELL_RE.findall(row)
        link = _LINK_RE.search(row)
        if len(cells) < 3 or not link:
            continue
        raw_date = _txt(cells[0])
        dates = pick_event_dates(_TIME_RE.sub(" ", raw_date))
        if not dates:
            continue
        out.append({"title": _txt(link.group(2)), "path": link.group(1), "start_date": dates[0], "end_date": dates[1],
                    "start_time": _start_time(raw_date), "venue_raw": _txt(cells[2]) or None})
    return out


class BmfmsExtractor(WordPressGenericExtractor):
    LISTING_URL = _ROOT + "/professionals/events"
    SOCIETY = "BMFMS"
    DEFAULT_SPECIALTY = "Obstetrics & Gynaecology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"
    YEARS_AHEAD = 2

    # ---- Phase A -----------------------------------------------------------
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today()
        urls = [self.LISTING_URL] + [f"{_ROOT}/professionals/events/date/{today.year + i}/" for i in range(1, self.YEARS_AHEAD + 1)]
        rows: List[Dict[str, Any]] = []
        got_any = False
        for i, url in enumerate(urls):
            html = self._fetch(url) if i == 0 else fetch_html(url, browser=getattr(self, "browser", None))
            if i == 0 and not html:
                return None
            if html:
                got_any = True
                rows += parse_listing(html)
            time.sleep(self.REQUEST_GAP_S)
        if not got_any:
            return None
        iso_today = today.isoformat()
        uses: Dict[str, int] = {}
        for r in rows:
            uses[r["path"]] = uses.get(r["path"], 0) + 1
        shells: List[Dict[str, Any]] = []
        seen_url, seen_key = set(), set()
        for r in rows:
            if (r["end_date"] or r["start_date"]) < iso_today:
                continue
            url = _ROOT + r["path"]
            if uses[r["path"]] > 1:
                url = f"{url}#{r['start_date']}"            # one page, several dates: keep source_url unique
            key = (re.sub(r"\W+", "", r["title"].lower()), r["start_date"])
            if url in seen_url or key in seen_key or re.search(r"(?i)cancel", r["title"]):
                continue
            if _PROMOTER_RE.search(r["title"]):
                logger.info(f"BMFMS: dropped promoter-style event: {r['title']}")
                continue
            seen_url.add(url)
            seen_key.add(key)
            shells.append({"title": r["title"], "booking_url": url, "source_url": url, "start_date": r["start_date"],
                           "end_date": r["end_date"], "start_time": r["start_time"], "venue_raw": r["venue_raw"], "category": None})
        logger.info(f"BMFMS: {len(shells)} upcoming shells from {len(rows)} calendar rows")
        return shells or None

    @staticmethod
    def _prose_fee(html: str) -> List[Dict[str, Any]]:
        """Thin pages state the fee in a sentence: "Tickets are £10, charged as a donation ..." or "free webinars for members"."""
        text = " ".join(html_to_lines(re.sub(r"(?is)<(script|style|nav|footer|header)\b.*?</\1\s*>", " ", html)))
        m = re.search(r"(?i)\b(?:tickets?|fees?|cost|price|registration)\b[^.\u00a3]{0,40}\u00a3\s?(\d[\d,]*(?:\.\d{2})?)", text)
        if m:
            return [{"tier_label": "Ticket \u00b7 Standard", "price_gbp": float(m.group(1).replace(",", "")), "currency": "GBP",
                     "is_early_bird": False, "early_bird_deadline": None}]
        m = re.search(r"(?i)\bfree (?:webinars?|events?|to attend)\b(?: for (members))?", text)
        if m:
            return [{"tier_label": "Members \u00b7 Free" if m.group(1) else "Standard \u00b7 Free", "price_gbp": 0.0, "currency": "GBP",
                     "is_early_bird": False, "early_bird_deadline": None}]
        return []

    # ---- Phase B -----------------------------------------------------------
    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out = super().detail_from_html(html, shell, llm_call)
        # the h2 under the breadcrumb is the event name; the listing title is only a fallback
        h2 = re.search(r"(?is)<header>.*?<h2>(.*?)</h2>", html)
        if h2 and _txt(h2.group(1)):
            out["conference_name"] = _txt(h2.group(1))
        meta = re.search(r'(?is)<span class="meta_date">(.*?)</span>', html)
        if meta and not shell.get("start_date"):
            d = pick_event_dates(_TIME_RE.sub(" ", _txt(meta.group(1))))
            if d:
                out["start_date"], out["end_date"] = d
        # external organiser links: "Further details" first (the event's own site), else "Book online"
        links = {}
        for m in re.finditer(r"""(?is)<a\b[^>]*href=["'](https?://[^"']+)["'][^>]*>(.*?)</a\s*>""", html):
            label = _txt(m.group(2)).lower()
            href = _html.unescape(m.group(1))
            if "bmfms.org.uk" in href:
                continue
            if "further details" in label:
                links.setdefault("details", href)
            elif "book online" in label:
                links.setdefault("book", href)
        if links.get("details") or links.get("book"):
            out["organiser_url"] = links.get("details") or links.get("book")
        out["event_type"] = classify_event_type(shell.get("title") or "", "")
        if not out.get("pricing_tiers"):
            tiers = self._prose_fee(html)
            if tiers:
                out["pricing_tiers"] = tiers
        if shell.get("start_time"):
            out["start_time"] = shell["start_time"]               # 24h from the listing; the page header's "5:30PM" is 12h
        # split_location mistakes "..., Blackshaw Road, SW17 0QT" (street as city) and "Wembley, London" (two bare names)
        raw = shell.get("venue_raw") or ""
        if raw and out.get("event_format") != "online":
            v, c, k = uk_place(raw)
            if not c and out.get("city") and _STREET_RE.search(out["city"]):
                out.pop("city")                                     # street, no town on the page: leave the city for the audit
                out.pop("region", None)
                if v:
                    out["venue_name"] = v
            elif c and (not out.get("city") or _STREET_RE.search(out["city"]) or out["city"] not in _UK_CITIES):
                out["city"], out["region"] = c, k
                if v:
                    out["venue_name"] = v
                out["event_format"] = "in_person"
            elif out.get("city") in _UK_CITIES and not out.get("region"):
                out["region"] = _UK_CITIES[out["city"]]
            elif out.get("city") and (" \u2013 " in out["city"] or len(out["city"].split()) >= 4):
                out["venue_name"], out["city"] = out["city"], None      # a hotel/venue string, not a town
        return out
