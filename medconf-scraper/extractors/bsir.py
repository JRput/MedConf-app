"""BSIR (British Society of Interventional Radiology) events: WordPress-family subclass, Calm Digital CMS.

`bsir.org/events/` is NOT a dated listing: it is an index of ~13 event *series* pages (`/events/bsir-asm/`,
`/events/VITALS/`, `/events/bsir-iouk-annual-meeting/`, ...). Each series page holds the CURRENT year's event as prose
("VITALS 2027 : Thursday 11th - Friday 12th March, Sopwell Hosue, St Albans", "The Advanced Skills Course (ASC) 2027
will be held on Monday 26th & Tuesday 27th April at thestudio, Birmingham"), usually without a year and often with an
ordinal day or weekday list. Some series have one level of sub-pages (IR Juniors -> NIRS26 / RiiSE26 / Basic Skills
Course; Webinars -> Upcoming webinars, a title line followed by "Thursday 12th November 18:30"). One member-only page
("BSIR 2026: what's in store") answers "Access Denied" and is skipped.

Phase A therefore crawls hub -> series pages -> qualifying sub-pages (about 20 requests), finds the first line in each
page's main content that carries a date and does not read like a deadline ("registration will open on...", "available
until...", "closes"), resolves a missing year from the weekday (else the title's year, else the next occurrence), and
keeps events that have not ended. Past-year pages (NIRS26, Paediatric IR 2026) drop out by date.

Fees: VITALS has a `/vitals-2027-registration/` page with two parallel columns (Type / Fee); the Annual Scientific
Meeting registers on the CIRSE-built `bsirmeeting.org/attend/registration/` page whose fee grid (Early / Regular
columns) goes through `pricing_tables`. Both are fetched from the "Register" link on the event page. Fees for pages
with no Register link (ASC, IOUK: "registration will open in the New Year") stay empty.
"""
import html as _html
import re
import time
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from playwright.sync_api import Page

from logger import logger

from .http_fetch import fetch_html
from .pricing_tables import parse_pricing_tables
from .tribe_events import html_to_lines
from .wordpress_generic import (WordPressGenericExtractor, clip_venue, dedupe_consecutive, _year_from_weekday)

_ROOT = "https://www.bsir.org"
_MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_WD = r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?,?\s+)"
_D = r"\d{1,2}(?:st|nd|rd|th)?"
_MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_DATE_RE = re.compile(
    rf"(?P<days>{_WD}?{_D}(?:\s*(?:-|–|&|and|,|to)\s*{_WD}?{_D})*)\s+(?:of\s+)?(?P<mon>{_MONTH})\b\.?(?:,?\s+(?P<year>20\d\d))?", re.I)
_NOT_EVENT_LINE = re.compile(
    r"(?i)\b(?:will open|opens?|open(?:ed)? (?:on|from)|until|deadline|closes?|closed|closing|evaluation|thank you|gallery|ago|"
    r"submissions?\b.*\b(?:open|close)|available (?:until|from|shortly)|recordings?|scholarships?|accepted|was held|took place|"
    r"has taken place|were held|last year)\b")
_SKIP_SUB = re.compile(r"(?i)^(?:register|registration|sponsor|sponsorship|book|programme|submit|view|complete|evaluation|abstract|find out|join|membership|become)")
_UK_CITIES = {"London": "England", "Birmingham": "England", "Bristol": "England", "Manchester": "England", "Liverpool": "England",
              "Leeds": "England", "Glasgow": "Scotland", "Edinburgh": "Scotland", "Newcastle": "England", "Cardiff": "Wales",
              "Belfast": "Northern Ireland", "St Albans": "England", "Leicester": "England", "Nottingham": "England", "Oxford": "England",
              "Cambridge": "England", "Sheffield": "England", "Southampton": "England", "Harrogate": "England", "Aberdeen": "Scotland",
              "Dundee": "Scotland", "Swansea": "Wales", "Coventry": "England", "York": "England"}
_SKIP_SLUG = re.compile(r"(?i)whats-in-store")


def _txt(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag))).replace("\xa0", " ").strip()


def _iso(y: int, m: int, d: int) -> Optional[str]:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def find_event_dates(line: str, today: date, year_hint: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """First 'Thursday 11th - Friday 12th March' / '4th-6th November 2026' / 'Thursday 12th November' in a line
    -> {start, end, endpos}. Missing year: from the weekday, else `year_hint`, else the next occurrence.
    "A and B" with a gap of more than a day is not a range (the source's own typo, e.g. 10th and 12th for Thu/Fri)."""
    for m in _DATE_RE.finditer(line or ""):
        mon = _MON[m.group("mon")[:3].lower()]
        days_txt = m.group("days")
        days = [int(x) for x in re.findall(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?", days_txt)]
        if not days or any(d < 1 or d > 31 for d in days):
            continue
        wds = re.findall(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)", days_txt, re.I)
        year = int(m.group("year")) if m.group("year") else None
        if not year and wds:
            year = _year_from_weekday(wds[0], days[0], mon, today)
        if not year:
            year = year_hint
        if not year:
            year = today.year if (_iso(today.year, mon, days[0]) or "") >= today.isoformat() else today.year + 1
        start = _iso(year, mon, days[0])
        end = _iso(year, mon, days[-1]) or start
        if not start:
            continue
        if len(days) == 2 and re.search(r"(?i)\band\b|&", days_txt) and days[1] - days[0] > 1:
            end = start                                    # non-consecutive "10th and 12th": only the first day is reliable
        if end < start:
            end = start
        return {"start": start, "end": end, "endpos": m.end()}
    return None


def _main_lines(html: str) -> List[str]:
    """Lines of the page's main content: from the first <h1> to the footer/site menu."""
    i = html.find("<h1")
    body = html[i:] if i >= 0 else html
    body = re.split(r"(?i)<footer|<div class=\"footer|id=\"footer", body)[0]
    body = re.sub(r"(?is)<(script|style|svg|noscript|nav)\b.*?</\1\s*>", " ", body)
    return dedupe_consecutive(html_to_lines(body))


def events_from_page(html: str, url: str, today: date) -> List[Dict[str, Any]]:
    """One series/sub page -> the upcoming events it announces (pure)."""
    if re.search(r"(?i)member only content|access denied", html or ""):
        return []
    t = re.search(r"(?is)<title>(.*?)</title>", html)
    series = _txt(t.group(1)).split("|")[0].strip() if t else ""
    h1 = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", html)
    series = _txt(h1.group(1)) if h1 and _txt(h1.group(1)) else series
    lines = _main_lines(html)
    # drop the section-menu block that precedes the content ("In this section" list) when present
    if "In this section" in lines:
        k = lines.index("In this section")
        j = next((i for i in range(k + 1, len(lines)) if lines[i] == series and i > k + 3), None)
        lines = lines[j:] if j is not None else lines[k + 1:]
    out: List[Dict[str, Any]] = []
    year_hint = int(m.group(1)) if (m := re.search(r"\b(20\d\d)\b", series)) else None
    # webinar-style pages: "<title>" line directly followed by a "Thursday 12th November at 18:30" line
    if re.search(r"(?i)webinars?", url):
        for i in range(1, len(lines)):
            d = find_event_dates(lines[i], today, year_hint) if len(lines[i]) <= 60 and re.search(_WD, lines[i]) else None
            if d and 8 <= len(lines[i - 1]) <= 140 and not _NOT_EVENT_LINE.search(lines[i - 1]) and not find_event_dates(lines[i - 1], today):
                tm = re.search(r"\b(\d{1,2}):(\d{2})\b", lines[i])
                out.append({"title": lines[i - 1], "start": d["start"], "end": d["end"], "time": f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else None,
                            "place": "online", "pair": True})
    else:
        for i, ln in enumerate(lines[:40]):
            if _NOT_EVENT_LINE.search(ln) or len(ln) > 400:
                continue
            d = find_event_dates(ln, today, year_hint)
            if not d:
                continue
            after = ln[d["endpos"]:]
            year = d["start"][:4]
            title = series if (year in series or year[2:] in series) else f"{series} {year}"
            sub = next((l for l in lines[max(0, i - 4):i] if 25 <= len(l) <= 120 and l != series and not find_event_dates(l, today)
                        and not re.search(r"(?i)save the date|queries|programme|register", l)), None)
            if len(series) <= 12 and sub:
                title = f"{title}: {sub}"
            out.append({"title": title, "start": d["start"], "end": d["end"], "time": None, "place": after, "pair": False, "line": ln})
            break
    return [e for e in out if e["end"] >= today.isoformat()]


def two_column_tiers(html: str) -> List[Dict[str, Any]]:
    """Calm Digital registration page: parallel 'Type' and 'Fee' columns of <p> lines (pure)."""
    cols = {}
    for h, body in re.findall(r'(?is)class="section__heading">(.*?)</div>\s*<div class="section__content">(.*?)</div>', html or ""):
        cols[_txt(h).lower()] = [_txt(p) for p in re.findall(r"(?is)<p>(.*?)</p>", body)]
    types, fees = cols.get("type") or cols.get("category") or [], cols.get("fee") or cols.get("price") or []
    tiers: List[Dict[str, Any]] = []
    for label, fee in zip(types, fees):
        m = re.search(r"£\s?(\d[\d,]*(?:\.\d{2})?)", fee)
        if not m or re.search(r"(?i)staff member|^sponsoring industry$|please ensure", label):
            continue
        tiers.append({"tier_label": f"Registration · {label}"[:120], "price_gbp": float(m.group(1).replace(",", "")), "currency": "GBP",
                      "is_early_bird": False, "early_bird_deadline": None})
    return tiers


def clean_tiers(tiers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop the page-section prefix ("Sponsored registration for BSIR 2026 ·") and footnote asterisks."""
    out = []
    for t in tiers:
        label = re.sub(r"^(?:Sponsored|Individual) registration for [^·]*·\s*", "Registration · ", t["tier_label"])
        out.append({**t, "tier_label": re.sub(r"\s*\*+", "", label)[:120]})
    return out


class BsirExtractor(WordPressGenericExtractor):
    LISTING_URL = _ROOT + "/events/"
    SOCIETY = "BSIR"
    DEFAULT_SPECIALTY = "Radiology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"
    MAX_SUBPAGES = 8

    # ---- Phase A -----------------------------------------------------------
    def _get(self, url: str) -> Optional[str]:
        time.sleep(self.REQUEST_GAP_S)
        return fetch_html(url, browser=getattr(self, "browser", None))

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        hub = self._fetch(self.LISTING_URL)
        if not hub:
            return None
        today = date.today()
        series = [p for p in dict.fromkeys(re.findall(r'href="(/events/[A-Za-z0-9\-]+/)"', hub)) if not _SKIP_SLUG.search(p)]
        shells: List[Dict[str, Any]] = []
        seen_urls = set()
        sub_budget = self.MAX_SUBPAGES

        def handle(url: str, html: str) -> None:
            for e in events_from_page(html, url, today):
                burl = url if not e["pair"] else f"{url}#{re.sub(r'[^a-z0-9]+', '-', e['title'].lower()).strip('-')[:60]}"
                if burl in seen_urls:
                    continue
                seen_urls.add(burl)
                shells.append({"title": e["title"], "booking_url": burl, "source_url": burl, "start_date": e["start"], "end_date": e["end"],
                               "start_time": e["time"], "venue_raw": e["place"], "category": "webinar" if e["pair"] else None, "page_url": url})

        for path in series:
            url = _ROOT + path
            html = self._get(url)
            if not html:
                continue
            handle(url, html)
            # one level of sub-pages whose link text names an event or listing ("NIRS26", "Webinars"), not an action
            for m in re.finditer(r'(?is)<a\b[^>]*href="(/events/[A-Za-z0-9\-]+/[A-Za-z0-9\-]+/)"[^>]*>(.*?)</a>', html):
                sp, label = m.group(1), _txt(m.group(2))
                if (_ROOT + sp) in seen_urls or len(label) < 4 or _SKIP_SUB.match(label) or sub_budget <= 0 or _SKIP_SLUG.search(sp):
                    continue
                if not sp.startswith(path):
                    continue
                seen_urls.add(_ROOT + sp)
                sub_budget -= 1
                sub = self._get(_ROOT + sp)
                if sub:
                    handle(_ROOT + sp, sub)
        logger.info(f"BSIR: {len(shells)} upcoming shells from {len(series)} series pages")
        return shells or None

    # ---- Phase B -----------------------------------------------------------
    def _fees(self, html: str, page_url: str) -> List[Dict[str, Any]]:
        """Follow the page's "Register" link (BSIR page or the CIRSE-built meeting site) and read the public fee grid."""
        target = None
        for m in re.finditer(r"""(?is)<a\b[^>]*href=["']([^"']+)["'][^>]*>(.*?)</a\s*>""", html):
            href, label = _html.unescape(m.group(1)), _txt(m.group(2))
            if re.match(r"(?i)^register(?: for the \w+)?$", label) and re.search(r"(?i)regist", href) and "meeting-booking" not in href:
                target = urljoin(page_url, href)
                break
        if not target:
            return []
        reg = self._get(target)
        if not reg:
            return []
        body = re.sub(r"(?is)<(script|style|nav|footer|header)\b.*?</\1\s*>", " ", reg)
        return clean_tiers(two_column_tiers(body) or parse_pricing_tables(body, default_currency="GBP"))

    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out = super().detail_from_html(html, shell, llm_call)
        out["conference_name"] = shell["title"]
        out["start_date"], out["end_date"] = shell["start_date"], shell.get("end_date") or shell["start_date"]
        if shell.get("start_time"):
            out["start_time"] = shell["start_time"]
        for k in ("venue_name", "city", "region", "event_format", "pricing_tiers"):
            out.pop(k, None)
        place = (shell.get("venue_raw") or "").strip(" ,.-–:")
        place = re.sub(r"(?i)^(?:will\s+(?:be\s+)?(?:held|take place)\s*)?(?:at|in|,)?\s*", "", place).strip(" ,")
        if place == "online" or re.search(r"(?i)^(?:held )?via\b|\bteams\b|\bzoom\b|\bonline\b", place):
            out["event_format"] = "online"
        elif place:
            part = re.split(r"\.\s|\bMore detail", place)[0].strip(" ,.")
            bits = [b.strip() for b in part.split(",") if b.strip()]
            bits = [b for b in bits if not re.match(r"(?i)^(?:please|more|further|registration|programme)\b", b)]
            if bits:
                out["event_format"] = "in_person"
                if len(bits) == 1:
                    (out.__setitem__("venue_name", clip_venue(re.sub(r"(?i)^at\s+(?:the\s+)?", "", bits[0]))) if re.search(
                        r"(?i)hotel|centre|center|studio|house|university|college|hospital|marriott|\bICC\b", bits[0]) else out.__setitem__("city", bits[0]))
                else:
                    out["venue_name"] = clip_venue(re.sub(r"(?i)^at\s+(?:the\s+)?", "", bits[0]))
                    out["city"] = bits[-1]
        if out.get("venue_name"):
            out["venue_name"] = re.sub(r"(?i)^the\s+", "", out["venue_name"])
            if not out.get("city"):
                hit = next((c for c in _UK_CITIES if re.search(rf"\b{c}\b", out["venue_name"])), None)
                if hit:
                    out["city"] = hit                          # "Bristol Marriott Royal Hotel"
        if out.get("city") in _UK_CITIES:
            out["region"] = _UK_CITIES[out["city"]]
        tiers = self._fees(html, shell.get("page_url") or shell["booking_url"]) if not shell["booking_url"].count("#") else []
        if tiers:
            out["pricing_tiers"] = tiers
        txt = " ".join(dedupe_consecutive(html_to_lines(re.sub(r"(?is)<(script|style|svg|noscript|nav|footer)\b.*?</\1\s*>", " ", html))))
        m = re.search(r"(?i)\b(\d+)\s+CPD points? (?:are )?available(?: for each day)?", txt)
        if m:
            out["cpd_points"] = float(m.group(1))
            out["cpd_accredited"] = True
        return out
