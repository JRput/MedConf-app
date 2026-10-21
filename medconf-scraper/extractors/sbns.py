"""SBNS (Society of British Neurological Surgeons) event calendar: WordPress-family subclass, Preside/Eventfolio CMS.

`sbns.org.uk/event-calendar.html` is a Preside (Pixl8) site with the Eventfolio events module, server-rendered. The
listing shows every upcoming event as `article.eventfolio-calendar-event` (date range, title link, optional "18 CPD"
line, teaser, type badge Conference / Training Course / Workshop, venue or city, and "External" / "Free" badges). The
"Displaying 0 result(s)" counter and the filters are JavaScript-only; all upcoming cards (12 on 2026-10-21) are in the
HTML and there is no pagination. Two cards at the top are the society's own meetings, the rest are courses run by
other bodies, listed on SBNS pages that carry a "Book Now" link to the organiser.

Detail pages (`/event-calendar/<slug>.html`) have an `event-header` block: type badge, `h1`, `span.event-date`, a
`+ Add to calendar` link and one or two `span.event-venue` (city; then "Venue , City<br>address"). The sidebar widget
`event-widget-ticket-price` lists the fee ("Free") and `event-booking-btn` links to the organiser. Flagship meetings
(SBNS 100, Harrogate, Glasgow) have sub-pages; the SBNS 100 registration fees are published as a PDF grid there, which
this extractor does not parse (left to the remediator's PDF follow-up).
"""
import html as _html
import re
import time
from datetime import date
from urllib.parse import urljoin, urlparse
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Page

from logger import logger

from .abstract_classifier import pdf_bytes_to_text
from .http_fetch import fetch_html
from .tribe_events import html_to_lines
from .wordpress_generic import (WordPressGenericExtractor, classify_event_type, clip_venue, dedupe_consecutive, pick_event_dates,
                                split_location)

_ROOT = "https://www.sbns.org.uk"
_CARD_RE = re.compile(r'(?is)<article class="eventfolio-calendar-event\b.*?</article>')
_UK_CITIES = {
    "London": "England", "Birmingham": "England", "Manchester": "England", "Liverpool": "England", "Leeds": "England",
    "Sheffield": "England", "Bristol": "England", "Newcastle": "England", "Nottingham": "England", "Leicester": "England",
    "Oxford": "England", "Cambridge": "England", "Southampton": "England", "Harrogate": "England", "Cardiff": "Wales",
    "Edinburgh": "Scotland", "Glasgow": "Scotland", "Aberdeen": "Scotland", "Dundee": "Scotland", "Belfast": "Northern Ireland",
}
_PROMOTER_RE = re.compile(r"(?i)^\s*\d+(?:st|nd|rd|th)\s+(?:international|world|global)\b.*\b(?:conference|congress|summit)\b")   # conference-mill titles ("5th International Conference on ...")


_MAX_PDF_BYTES = 5 * 1024 * 1024
_TYPE_MAP = {"conference": "conference", "training course": "course", "workshop": "workshop"}


def _txt(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag))).replace("\xa0", " ").strip()


def parse_listing(html: str) -> List[Dict[str, Any]]:
    """Listing HTML -> one dict per event card (pure)."""
    out: List[Dict[str, Any]] = []
    for c in _CARD_RE.findall(html or ""):
        d = re.search(r'(?is)article-date">(.*?)</div>', c)
        a = re.search(r'(?is)article-title">\s*<a href="([^"]+)"[^>]*>(.*?)</a>', c)
        if not (d and a):
            continue
        dates = pick_event_dates(_txt(d.group(1)))
        if not dates:
            continue
        ty = re.search(r'(?is)event-type-badge"[^>]*>(.*?)</span>', c)
        ve = re.search(r'(?is)class="event-venue"[^>]*>(.*?)</span>', c)
        cpd = re.search(r'(?is)article-cpd">(.*?)</div>', c)
        tease = re.search(r'(?is)article-teaser">(.*?)</div>', c)
        badges = [_txt(b) for b in re.findall(r'(?is)class="badge event-badge">(.*?)</span>', c)]
        out.append({"title": _txt(a.group(2)), "url": _html.unescape(a.group(1)).split("#")[0], "start_date": dates[0], "end_date": dates[1],
                    "type": _txt(ty.group(1)).lower() if ty else "", "venue_raw": _txt(ve.group(1)) if ve else None,
                    "cpd": _txt(cpd.group(1)) if cpd else "", "teaser": _txt(tease.group(1)) if tease else "",
                    "external": "External" in badges, "free": "Free" in badges})
    return out


_AMOUNT_RE = re.compile(r"\u00a3\s?(\d[\d,]*(?:\.\d{2})?)")
_COL_RE = re.compile(r"(?i)(early|standard|late)\s+registration\s+until\s+(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)")
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def fee_tiers_from_pdf_text(text: str, year: int) -> List[Dict[str, Any]]:
    """SBNS flagship fee PDF -> tiers (pure). Header names the date columns ("Early Registration until 1st August ...");
    each row is "<attendance type> \u00a3650.00 \u00a3760.00 \u00a3870.00" under a delegate-category heading.
    Tier label = attendance type \u00b7 delegate category \u00b7 column."""
    flat = re.sub(r"[ \t]+", " ", text or "")
    cols = [(m.group(1).title(), f"{m.group(1).title()} until {int(m.group(2))} {m.group(3)}", m.group(3)[:3].lower(), int(m.group(2)))
            for m in _COL_RE.finditer(re.sub(r"\s+", " ", flat))]
    if not cols:
        return []
    tiers: List[Dict[str, Any]] = []
    pending: List[str] = []
    last_cat = ""
    skip_wrap = False
    for ln in [l.strip() for l in flat.split("\n")]:
        if not ln:
            continue
        amts = _AMOUNT_RE.findall(ln)
        if not amts:
            if re.search(r"(?i)registration fees|registration until|^early|^standard|^late|^until|information on|^\d+(?:st|nd|rd|th)? ", ln):
                continue
            if re.match(r"(?i)attendance by country", ln):
                skip_wrap = True                              # group heading wraps onto a second line ending in '*'
                pending = []
                continue
            if re.search(r"\*+\s*$", ln):                    # group heading ("... **" / "... *"), not a delegate category
                skip_wrap = False
                pending = []
                continue
            if skip_wrap or len(ln) >= 160:
                continue
            pending.append(ln.strip("* "))
            continue
        label = _AMOUNT_RE.sub("", ln).strip(" -\u2013")
        category = re.sub(r"\s+", " ", " ".join(pending)).strip(" *") or last_cat
        pending = []
        if len(amts) != len(cols) and len(amts) != 1:
            continue
        if not re.search(r"(?i)attendance|day rate", label):
            category = ""                                     # reception / dinner rows apply to every category
        else:
            last_cat = category
        for i, a in enumerate(amts):
            full = len(amts) == len(cols)
            name, tf, mon, day = cols[i] if full else (None, None, None, None)
            early = name == "Early"
            dl = None
            if early and mon in _MONTHS:
                try:
                    dl = date(year, _MONTHS[mon], day).isoformat()
                except ValueError:
                    dl = None
            room = max(20, 120 - len(label) - len(tf or "") - 6)          # shorten the category, never the timeframe
            cat = category if len(category) <= room else category[:room].rsplit(" ", 1)[0] + "\u2026"
            tiers.append({"tier_label": " \u00b7 ".join(x for x in (label, cat, tf) if x),
                          "price_gbp": float(a.replace(",", "")), "currency": "GBP", "is_early_bird": early, "early_bird_deadline": dl})
    seen, out = set(), []
    for t in tiers:
        k = (t["tier_label"], t["price_gbp"])
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


def _start_time(text: str) -> Optional[str]:
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap]m)\b", text or "", re.I)
    if not m:
        return None
    return f"{int(m.group(1)) % 12 + (12 if m.group(3).lower() == 'pm' else 0):02d}:{m.group(2) or '00'}"


class SbnsExtractor(WordPressGenericExtractor):
    LISTING_URL = _ROOT + "/event-calendar.html"
    SOCIETY = "SBNS"
    DEFAULT_SPECIALTY = "Neurosurgery"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"

    # ---- Phase A -----------------------------------------------------------
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = self._fetch(self.LISTING_URL)
        if not html:
            return None
        today = date.today().isoformat()
        shells: List[Dict[str, Any]] = []
        seen = set()
        for c in parse_listing(html):
            if c["end_date"] < today or c["url"] in seen or re.search(r"(?i)cancel", c["title"]):
                continue
            if _PROMOTER_RE.search(c["title"]):
                logger.info(f"SBNS: dropped promoter-style event: {c['title']}")
                continue
            seen.add(c["url"])
            shells.append({"title": c["title"], "booking_url": c["url"], "source_url": c["url"], "start_date": c["start_date"],
                           "end_date": c["end_date"], "start_time": None, "venue_raw": c["venue_raw"], "category": c["type"] or None,
                           "sbns_cpd": c["cpd"], "sbns_free": c["free"], "teaser": c["teaser"]})
        logger.info(f"SBNS: {len(shells)} upcoming shells")
        return shells or None

    # ---- Phase B -----------------------------------------------------------
    def _pdf_fees(self, html: str, shell: Dict[str, Any], out: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Flagship meetings: event page -> 'Registration and Accommodation' sub-page -> fee PDF (/asset/<id>/, no .pdf suffix)."""
        slug = urlparse(shell["booking_url"]).path.rsplit("/", 1)[-1].replace(".html", "")
        m = next((x for x in re.finditer(r'href="(https?://[^"]*sbns\.org\.uk/event-calendar/([^"/]+)/registration[^"]*\.html)"', html)
                  if x.group(2) == slug or slug.startswith(x.group(2)) or x.group(2).startswith(slug)), None)
        if not m:
            return []
        time.sleep(self.REQUEST_GAP_S)
        sub = fetch_html(m.group(1), browser=getattr(self, "browser", None))
        a = re.search(r'(?is)<a[^>]*href="([^"]*/asset/[^"]+)"[^>]*>(?:(?!</a>).){0,200}PDF', sub or "")
        if not a:
            return []
        try:
            import httpx
            data = b""
            with httpx.stream("GET", urljoin(m.group(1), _html.unescape(a.group(1))), timeout=20, follow_redirects=True,
                              headers={"User-Agent": "Mozilla/5.0 (MedConf scraper)"}) as r:
                if r.status_code < 400 and int(r.headers.get("content-length") or 0) <= _MAX_PDF_BYTES:
                    buf = bytearray()
                    for chunk in r.iter_bytes():
                        buf += chunk
                        if len(buf) > _MAX_PDF_BYTES:
                            buf = bytearray()
                            break
                    data = bytes(buf) if buf[:4] == b"%PDF" else b""
        except Exception:                                   # noqa: BLE001
            data = b""
        year = int((out.get("start_date") or shell.get("start_date") or str(date.today().year))[:4])
        return fee_tiers_from_pdf_text(pdf_bytes_to_text(data), year) if data else []

    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out = super().detail_from_html(html, shell, llm_call)
        header = re.search(r'(?is)<div class="event-header-post-meta">(.*?)</div>', html)
        hh = header.group(1) if header else ""
        h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", html)
        if h1 and _txt(h1.group(1)):
            out["conference_name"] = _txt(h1.group(1))
        ed = re.search(r'(?is)class="event-date">(.*?)</span>', hh)
        d = pick_event_dates(_txt(ed.group(1))) if ed else None
        out["start_date"], out["end_date"] = d if d else (shell["start_date"], shell.get("end_date") or shell["start_date"])
        lines = dedupe_consecutive(html_to_lines(re.sub(r"(?is)<(script|style|svg|noscript|nav|footer)\b.*?</\1\s*>", " ", html)))
        st = None
        for i, ln in enumerate(lines):
            if "Add to calendar" in ln:
                st = _start_time(" ".join(lines[max(0, i - 2):i]))        # "12pm - 5pm" sits just above the calendar link
                break
        if st:
            out["start_time"] = st
        # ---- type: badge, else title keywords
        ty = _TYPE_MAP.get((shell.get("category") or "").strip().lower())
        out["event_type"] = ty or classify_event_type(shell.get("title") or "", "")
        # ---- venue: first line of the last event-venue span; the first span is the card's city
        for k in ("venue_name", "city", "region", "event_format"):
            out.pop(k, None)
        spans = [re.sub(r"(?is)<br\s*/?>.*$", "", s) for s in re.findall(r'(?is)class="event-venue"[^>]*>(.*?)</span>', hh)]
        spans = [_txt(s) for s in spans if _txt(s)]
        city_hint = spans[0] if spans else (shell.get("venue_raw") or None)
        venue_line = spans[-1] if len(spans) > 1 else None
        v, c, k = split_location(venue_line or city_hint)
        if venue_line and not c and city_hint:
            c2 = split_location(city_hint)
            c, k = c2[1] or c2[0], c2[2]
        hit = next((x for x in _UK_CITIES if re.search(rf"\b{x}\b", f"{c or ''} {venue_line or ''} {city_hint or ''}")), None)
        if hit and (not c or c not in _UK_CITIES):
            if c and not v:
                v = c                                          # "INNSiDE by Melia Liverpool": a hotel, not a town
            c, k = hit, _UK_CITIES[hit]
        elif c in _UK_CITIES and (not k or k == "United Kingdom"):
            k = _UK_CITIES[c]
        if v:
            out["venue_name"] = clip_venue(v)
        if c:
            out["city"] = c
        if k:
            out["region"] = k
        if v or c:
            out["event_format"] = "in_person"
        # ---- fee widget + organiser link
        w = re.search(r'(?is)event-widget-ticket-price">(.*?)</ul>', html)
        tiers: List[Dict[str, Any]] = []
        for li in re.findall(r"(?is)<li>(.*?)</li>", w.group(1)) if w else []:
            t = _txt(li)
            pm = re.search(r"£\s?(\d[\d,]*(?:\.\d{2})?)", t)
            if pm:
                label = re.sub(r"[:\-–\s]*£.*$", "", t).strip() or "Ticket"
                tiers.append({"tier_label": f"Ticket · {label}"[:120], "price_gbp": float(pm.group(1).replace(",", "")), "currency": "GBP",
                              "is_early_bird": False, "early_bird_deadline": None})
            elif re.fullmatch(r"(?i)free", t):
                tiers.append({"tier_label": "Ticket · Free", "price_gbp": 0.0, "currency": "GBP", "is_early_bird": False, "early_bird_deadline": None})
        b = re.search(r'(?is)event-booking-btn">\s*<a href="(https?://[^"]+)"', html)
        external = bool(b and "sbns.org.uk" not in b.group(1))
        if external:
            out["organiser_url"] = _html.unescape(b.group(1))
            if all(t["price_gbp"] == 0 for t in tiers):
                tiers = []                      # the SBNS widget says "Free" but the organiser's booking page charges: let the explorer follow organiser_url
        if tiers:
            out["pricing_tiers"] = tiers
        else:
            out.pop("pricing_tiers", None)
        if not tiers:
            pdf_tiers = self._pdf_fees(html, shell, out)
            if pdf_tiers:
                out["pricing_tiers"] = pdf_tiers
        cpd = re.search(r"(\d+(?:\.\d+)?)\s*CPD", shell.get("sbns_cpd") or "")
        if cpd:
            out["cpd_points"] = float(cpd.group(1))
            out["cpd_accredited"] = True
        return out
