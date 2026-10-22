"""BTS (British Thoracic Society) education and events: WordPress-family subclass, four listings merged.

The site (`brit-thoracic.org.uk`, Umbraco, server-rendered) spreads its dated events over four places, all read here:

1. Short courses, `/education-and-events/bts-short-courses/`: `div.event-card__item` cards with a date block
   (`<p>04 - 05</p><span>NOVEMBER 2026</span>`), a mode/venue line ("Online", "QEII Conference Centre, London",
   "Preston Marriott Hotel (in-person)"), the title and the course page. The first card is an evergreen e-learning
   resource dated 1 January; the past-date filter drops it. Course pages carry a "Fees" block ("BTS Members: £190",
   "Non-members: £380") and a booking status ("Fully booked").
2. The Winter and Summer Meetings, found from the hub `/education-and-events/` as `/<winter|summer>-meeting-<year>/`
   pages (date block "25-27" + "November 2026", venue line). Fees are in a table on the `booking-rates/` sub-page.
   The "Meeting dates and programmes" page also lists FUTURE meetings ("2027: Summer Meeting 24 - 25 June, Newcastle");
   those within 18 months become shells with no page of their own (`<dates page>#<slug>`), detail comes from the shell.
3. Webinars, `/bts-webinars/`: an "Upcoming webinars" bullet list ("... Wednesday 21 October 2026, 12:30pm to 1:30pm",
   sometimes no year). Free to attend; the page says so.
4. Other respiratory courses, `/other-respiratory-courses/`: a table of third-party events (name, date, venue,
   a READ MORE link or a mailto). Mailto-only rows get a `<listing>#<slug>` URL and are built from the shell.
"""
import html as _html
import re
import time
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from playwright.sync_api import Page

from logger import logger

from .http_fetch import fetch_html
from .pricing_tables import parse_pricing_tables
from .tribe_events import html_to_lines
from .wordpress_generic import (WordPressGenericExtractor, classify_event_type, clip_venue, dedupe_consecutive,
                                find_dates, pick_event_dates, split_location)

_ROOT = "https://www.brit-thoracic.org.uk"
_HUB = _ROOT + "/education-and-events/"
_MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_CARD_RE = re.compile(r'(?is)<div class="event-card__item">(.*?)(?=<div class="event-card__item">|</div>\s*</div>\s*</div>)')
_UK_CITIES = {
    "London": "England", "Birmingham": "England", "Manchester": "England", "Liverpool": "England", "Leeds": "England",
    "Sheffield": "England", "Bristol": "England", "Newcastle": "England", "Nottingham": "England", "Leicester": "England",
    "Oxford": "England", "Cambridge": "England", "Southampton": "England", "Harrogate": "England", "Northampton": "England",
    "Preston": "England", "Coventry": "England", "Kettering": "England", "York": "England", "Brighton": "England",
    "Cardiff": "Wales", "Swansea": "Wales", "Edinburgh": "Scotland", "Glasgow": "Scotland", "Aberdeen": "Scotland",
    "Dundee": "Scotland", "Belfast": "Northern Ireland",
}


def _txt(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag))).replace("\xa0", " ").strip()



_JUNK_H1 = re.compile(r"(?i)cookie|consent|privacy|your choice|we value your|accept all")


def _real_h1(html: str) -> Optional[str]:
    """First <h1> that is not a cookie/consent banner heading (browser-rendered pages put one before the title)."""
    for m in re.finditer(r"(?is)<h1[^>]*>(.*?)</h1>", html or ""):
        t = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip()
        if t and not _JUNK_H1.search(t):
            return t
    return None

def _iso(y: int, m: int, d: int) -> Optional[str]:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def card_dates(day_text: str, month_text: str) -> Optional[Tuple[str, str]]:
    """'04 - 05' + 'NOVEMBER 2026' -> ('2026-11-04', '2026-11-05'); '30 - 02' + 'OCTOBER - NOVEMBER 2026' crosses months."""
    days = [int(x) for x in re.findall(r"\d+", day_text or "")]
    months = [_MON[w[:3].lower()] for w in re.findall(r"[A-Za-z]{3,}", month_text or "") if w[:3].lower() in _MON]
    year = re.search(r"\b(20\d\d)\b", month_text or "")
    if not days or not months or not year:
        return None
    y = int(year.group(1))
    m1, m2 = months[0], months[-1]
    s = _iso(y, m1, days[0])
    e = _iso(y + (1 if m2 < m1 else 0), m2, days[-1])
    return (s, e or s) if s else None


def parse_cards(html: str) -> List[Dict[str, Any]]:
    """Short-course / hub carousel cards -> dicts (pure)."""
    out: List[Dict[str, Any]] = []
    for it in _CARD_RE.findall(html or ""):
        date_blk = re.search(r'(?is)event-card__date">(.*?)</div>', it)
        day = re.search(r"(?is)<p>(.*?)</p>", date_blk.group(1)) if date_blk else None
        mon = re.search(r"(?is)<span>(.*?)</span>", date_blk.group(1)) if date_blk else None
        title = re.search(r'(?is)event-card__title">(.*?)</h3>', it)
        mode = re.search(r'(?is)event-card__mode">(.*?)</p>', it)
        link = re.search(r'(?is)href="(/education-and-events/[^"#?]+)"', it)
        d = card_dates(_txt(day.group(1)) if day else "", _txt(mon.group(1)) if mon else "")
        if not (title and link and d):
            continue
        out.append({"title": _txt(title.group(1)), "path": link.group(1), "start_date": d[0], "end_date": d[1], "mode": _txt(mode.group(1)) if mode else ""})
    return out


def _time_ampm(text: str) -> Optional[str]:
    m = re.search(r"(\d{1,2})(?::|\.)?(\d{2})?\s*([ap]m)\b", text or "", re.I)
    if not m:
        return None
    return f"{int(m.group(1)) % 12 + (12 if m.group(3).lower() == 'pm' else 0):02d}:{m.group(2) or '00'}"


def parse_webinars(html: str, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """`Upcoming webinars` bullet list -> dicts (pure)."""
    out: List[Dict[str, Any]] = []
    m = re.search(r"(?is)Upcoming webinars\s*</h\d>\s*(<ul>.*?</ul>)", html or "")
    if not m:
        return out
    for li in re.findall(r"(?is)<li>(.*?)</li>", m.group(1)):
        a = re.search(r'(?is)<a href="(/education-and-events/bts-webinars/[^"#?]+)"[^>]*>(.*?)</a>', li)
        rest = _txt(li[a.end():]) if a else ""
        ds = find_dates(rest, today)
        if not (a and ds):
            continue
        out.append({"title": _txt(a.group(2)), "path": a.group(1), "start_date": ds[0]["start"], "end_date": ds[0]["end"], "start_time": _time_ampm(rest)})
    return out


def parse_future_meetings(html: str, today: date, horizon_days: int = 548) -> List[Dict[str, Any]]:
    """'2027:' / 'Summer Meeting 24 - 25 June, Newcastle' lines on the dates page -> dicts (pure)."""
    lines = dedupe_consecutive(html_to_lines(re.sub(r"(?is)<(script|style|nav|footer|header)\b.*?</\1\s*>", " ", html or "")))
    out: List[Dict[str, Any]] = []
    year = None
    for ln in lines:
        ym = re.match(r"^(20\d\d)\s*:?$", ln)
        if ym:
            year = int(ym.group(1))
            continue
        mm = re.match(r"(?i)^(summer|winter) meeting\s*:?\s*(.+)$", ln)
        if not (mm and year):
            continue
        body = mm.group(2)
        place = body.split(",", 1)[1].strip() if "," in body else None
        ds = pick_event_dates(f"{body.split(',', 1)[0]} {year}")
        if not ds:
            continue
        if date.fromisoformat(ds[1]) < today or (date.fromisoformat(ds[0]) - today).days > horizon_days:
            continue
        out.append({"title": f"BTS {mm.group(1).title()} Meeting {year}", "start_date": ds[0], "end_date": ds[1], "place": place})
    return out


def parse_other_courses(html: str) -> List[Dict[str, Any]]:
    """Third-party table rows (name, `YYYYMMDD display`, venue, link) -> dicts (pure)."""
    out: List[Dict[str, Any]] = []
    tb = re.search(r"(?is)<tbody.*?</tbody>", html or "")
    for row in re.findall(r"(?is)<tr\b.*?</tr>", tb.group(0) if tb else ""):
        cells = [_txt(c) for c in re.findall(r"(?is)<td\b.*?</td>", row)]
        if len(cells) < 3:
            continue
        m = re.match(r"(\d{4})(\d{2})(\d{2})", cells[1])
        # a range shows as "20-21 November 2026"; the sort key is the first day
        ds = pick_event_dates(re.sub(r"^\d{8}\s*", "", cells[1]))
        start = ds[0] if ds else (_iso(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None)
        if not start:
            continue
        href = re.search(r'(?is)href="([^"]+)"', row)
        out.append({"title": cells[0], "start_date": start, "end_date": ds[1] if ds else start, "venue_raw": cells[2],
                    "href": _html.unescape(href.group(1)) if href else None})
    return out


class BritThoracicExtractor(WordPressGenericExtractor):
    LISTING_URL = _HUB
    SOCIETY = "BTS"
    DEFAULT_SPECIALTY = "Respiratory"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"
    FUTURE_HORIZON_DAYS = 548

    # ---- Phase A -----------------------------------------------------------
    def _get(self, url: str) -> Optional[str]:
        time.sleep(self.REQUEST_GAP_S)
        return fetch_html(url, browser=getattr(self, "browser", None))

    @staticmethod
    def _venue_for_mode(mode: str) -> Optional[str]:
        mode = re.sub(r"(?i)\(in[- ]person\)", "", mode or "").strip(" ,-")
        return None if not mode or re.match(r"(?i)^(online|virtual|webinar)\b", mode) else mode

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today()
        iso_today = today.isoformat()
        hub = self._fetch(self.LISTING_URL)
        if not hub:
            return None
        shells: List[Dict[str, Any]] = []

        def add(sh: Dict[str, Any]) -> None:
            if (sh["end_date"] or sh["start_date"]) < iso_today:
                return
            if any(x["booking_url"] == sh["booking_url"] for x in shells):
                return
            shells.append(sh)

        # 1. short courses (own page; the hub carousel repeats it)
        courses = self._get(_ROOT + "/education-and-events/bts-short-courses/") or hub
        for c in parse_cards(courses):
            url = _ROOT + c["path"]
            add({"title": c["title"], "booking_url": url, "source_url": url, "start_date": c["start_date"], "end_date": c["end_date"],
                 "start_time": None, "venue_raw": self._venue_for_mode(c["mode"]), "category": "course",
                 "online_hint": bool(re.match(r"(?i)^online", c["mode"])), "bts_kind": "course"})
        # 2. Winter / Summer meeting pages linked from the hub
        for path in dict.fromkeys(re.findall(r'href="(/education-and-events/(?:winter|summer)-meeting-\d{4}/)"', hub)):
            page = self._get(_ROOT + path)
            if not page:
                continue
            lines = dedupe_consecutive(html_to_lines(re.sub(r"(?is)<(script|style|nav|footer|header)\b.*?</\1\s*>", " ", page)))
            title = re.search(r"(?is)<title>(.*?)</title>", page)
            title = _txt(title.group(1)).split("|")[0].strip() if title else path.strip("/").split("/")[-1].replace("-", " ").title()
            start = end = venue = None
            for i, ln in enumerate(lines):                 # a JS cookie banner can push the date block far down the browser-rendered page
                if re.match(r"^\d{1,2}(?:\s*[-–]\s*\d{1,2})?$", ln) and i + 1 < len(lines) and re.match(r"^[A-Za-z]+ \d{4}$", lines[i + 1]):
                    d = card_dates(ln, lines[i + 1])
                    if d:
                        start, end = d
                        for nxt in lines[i + 2:i + 12]:
                            if re.search(r"(?i)centre|center|hotel|convention|conference|hall", nxt) and len(nxt) <= 90 and not re.search(r"(?i)download|abstract|programme", nxt):
                                venue = nxt
                                break
                    break
            if start:
                url = _ROOT + path
                add({"title": title, "booking_url": url, "source_url": url, "start_date": start, "end_date": end, "start_time": None,
                     "venue_raw": venue, "category": "conference", "bts_kind": "meeting", "rates_url": url + "booking-rates/"})
        # future meetings (dates page; no page of their own)
        dates_url = _ROOT + "/education-and-events/meeting-dates-and-programmes/"
        dates_html = self._get(dates_url)
        have = {re.sub(r"\W+", "", s["title"].lower()) for s in shells}
        for fm in parse_future_meetings(dates_html or "", today, self.FUTURE_HORIZON_DAYS):
            if re.sub(r"\W+", "", fm["title"].lower()) in have:
                continue
            url = f"{dates_url}#{re.sub(r'[^a-z0-9]+', '-', fm['title'].lower()).strip('-')}"
            add({"title": fm["title"], "booking_url": url, "source_url": url, "start_date": fm["start_date"], "end_date": fm["end_date"],
                 "start_time": None, "venue_raw": fm["place"], "category": "conference", "bts_kind": "static"})
        # 3. webinars
        web = self._get(_ROOT + "/education-and-events/bts-webinars/")
        for w in parse_webinars(web or "", today):
            url = _ROOT + w["path"]
            add({"title": w["title"], "booking_url": url, "source_url": url, "start_date": w["start_date"], "end_date": w["end_date"],
                 "start_time": w["start_time"], "venue_raw": None, "category": "workshop", "online_hint": True, "bts_kind": "webinar"})
        # 4. other organisations' courses
        other_url = _ROOT + "/education-and-events/other-respiratory-courses/"
        other = self._get(other_url)
        for o in parse_other_courses(other or ""):
            href = o["href"] if (o["href"] or "").startswith("http") else f"{other_url}#{re.sub(r'[^a-z0-9]+', '-', o['title'].lower()).strip('-')}"
            add({"title": o["title"], "booking_url": href, "source_url": href, "start_date": o["start_date"], "end_date": o["end_date"],
                 "start_time": None, "venue_raw": o["venue_raw"], "category": classify_event_type(o["title"], ""),
                 "bts_kind": "static" if href.startswith(other_url) else "external", "third_party": True})
        logger.info(f"BTS: {len(shells)} upcoming shells")
        return shells or None

    # ---- Phase B -----------------------------------------------------------
    @staticmethod
    def _place(raw: Optional[str], online_hint: bool) -> Dict[str, Any]:
        if online_hint and not raw:
            return {"event_format": "online"}
        if not raw:
            return {}
        out: Dict[str, Any] = {"event_format": "in_person"}
        v, c, k = split_location(raw)
        city = next((x for x in _UK_CITIES if re.search(rf"\b{x}\b", raw)), None)
        if city:
            c, k = city, _UK_CITIES[city]
        if c and not v and re.search(r"(?i)hotel|centre|center|hospital|marriott|convention|university", c):
            v, c = c, city
        if v:
            out["venue_name"] = clip_venue(v)
        if c:
            out["city"] = c
        if k:
            out["region"] = k
        return out

    @staticmethod
    def _fees(lines: List[str]) -> List[Dict[str, Any]]:
        """Course fee block: 'Fees' + 'BTS Members: £190' / 'Non-members: £380' (own lines, or on one line before
        'Payment options'). A page saying delegate fees are 'fully funded by BTS' is a free course (refundable deposit)."""
        text = " ".join(lines)
        i = re.search(r"(?i)payment options", text)
        window = text[max(0, (i.start() if i else len(text)) - 260):(i.start() if i else len(text))]
        tiers: List[Dict[str, Any]] = []
        for m in re.finditer(r"(?i)((?:BTS )?members?|non[- ]?members?)\s*:?\s*\u00a3\s?(\d[\d,]*(?:\.\d{2})?)", window):
            tiers.append({"tier_label": f"Delegate \u00b7 {m.group(1).strip().capitalize() if m.group(1).lower().startswith('non') else m.group(1).strip()}"[:120],
                          "price_gbp": float(m.group(2).replace(",", "")), "currency": "GBP", "is_early_bird": False, "early_bird_deadline": None})
        if not tiers and re.search(r"(?i)delegate fees[^.]{0,80}fully funded by BTS", text):
            tiers = [{"tier_label": "Delegate \u00b7 Funded by BTS (refundable deposit)", "price_gbp": 0.0, "currency": "GBP",
                      "is_early_bird": False, "early_bird_deadline": None}]
        seen, out = set(), []
        for t in tiers:
            k = (t["tier_label"].lower(), t["price_gbp"])
            if k not in seen:
                seen.add(k)
                out.append(t)
        return out

    @staticmethod
    def _rates_tiers(html: str) -> List[Dict[str, Any]]:
        """Meeting 'Booking rates' tables: thead = section + rate column, rows = delegate type (first <strong>) + price."""
        tiers: List[Dict[str, Any]] = []
        for tb in re.findall(r"(?is)<table\b.*?</table\s*>", html or ""):
            heads = [_txt(h) for h in re.findall(r"(?is)<th\b.*?</th\s*>", tb)]
            section = heads[0] if heads else None
            column = heads[1] if len(heads) > 1 else None
            if section and re.search(r"(?i)group", section):
                section, column = "Group booking (6 or more)", "Per person, per day"
            for row in re.findall(r"(?is)<tr\b.*?</tr\s*>", tb):
                cells = re.findall(r"(?is)<td\b.*?</td\s*>", row)
                if len(cells) < 2:
                    continue
                pm = re.search(r"\u00a3\s?(\d[\d,]*(?:\.\d{2})?)", _txt(cells[-1]))
                strong = re.search(r"(?is)<strong>(.*?)</strong>", cells[0])
                label = _txt(strong.group(1)) if strong else _txt(cells[0])
                label = re.sub(r"[*]+$", "", label).strip()
                if not pm or not label:
                    continue
                tiers.append({"tier_label": " \u00b7 ".join(x for x in (section, label, column) if x)[:120], "price_gbp": float(pm.group(1).replace(",", "")),
                              "currency": "GBP", "is_early_bird": False, "early_bird_deadline": None})
        return tiers

    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        kind = shell.get("bts_kind")
        if kind == "static":
            return self._static_detail(shell)
        out = super().detail_from_html(html, shell, llm_call)
        lines = dedupe_consecutive(html_to_lines(re.sub(r"(?is)<(script|style|svg|noscript|nav|footer|header|aside)\b.*?</\1\s*>", " ", html)))
        if kind in ("course", "meeting", "webinar"):
            out["start_date"], out["end_date"] = shell["start_date"], shell.get("end_date") or shell["start_date"]
            if shell.get("start_time"):
                out["start_time"] = shell["start_time"]
            h1 = _real_h1(html)
            if h1:
                out["conference_name"] = h1
            for k in ("venue_name", "city", "region", "event_format"):
                out.pop(k, None)
            out.update(self._place(shell.get("venue_raw"), bool(shell.get("online_hint"))))
            out["event_type"] = {"course": "course", "meeting": "conference", "webinar": "workshop"}[kind]
        if kind == "course":
            tiers = self._fees(lines)
            if tiers:
                out["pricing_tiers"] = tiers
            if re.search(r"(?i)fully booked|sold out", " ".join(lines[:40])):
                out["is_sold_out"] = True
            if not out.get("cpd_points") and re.search(r"(?i)CPD points will be available|CPD (?:approved|accredited)", " ".join(lines)):
                out["cpd_accredited"] = True
        elif kind == "webinar" and not out.get("pricing_tiers") and re.search(r"(?i)\bfree webinars?\b|free to (?:access|attend)", " ".join(lines)):
            out["pricing_tiers"] = [{"tier_label": "Standard · Free", "price_gbp": 0.0, "currency": "GBP", "is_early_bird": False, "early_bird_deadline": None}]
        elif kind == "meeting" and shell.get("rates_url"):
            rates = self._get(shell["rates_url"])
            if rates:
                body = re.sub(r"(?is)<(script|style|nav|footer|header)\b.*?</\1\s*>", " ", rates)
                tiers = self._rates_tiers(body) or parse_pricing_tables(body, default_currency="GBP")
                if tiers:
                    out["pricing_tiers"] = tiers
        elif kind == "webinar":
            out.pop("cpd_points", None)                      # the webinar index says they are not CPD-accredited (except RESP)
            out.pop("cpd_accredited", None)
        if shell.get("third_party"):
            out["event_type"] = classify_event_type(shell.get("title") or "", "")
            out.update(self._place(shell.get("venue_raw"), False) if not out.get("venue_name") and not out.get("city") else {})
        return out

    def _static_detail(self, shell: Dict[str, Any]) -> Dict[str, Any]:
        """Rows with no page of their own: everything comes from the dates page / third-party table row."""
        out: Dict[str, Any] = {"society": self.SOCIETY, "conference_name": shell["title"], "start_date": shell["start_date"],
                               "end_date": shell.get("end_date") or shell["start_date"], "specialty": self.DEFAULT_SPECIALTY,
                               "event_type": "conference" if shell.get("bts_kind") == "static" and not shell.get("third_party") else classify_event_type(shell["title"], "")}
        out.update(self._place(shell.get("venue_raw"), False))
        if shell.get("third_party"):
            out["description"] = f"{shell['title']} is a respiratory event run by another organisation and listed on the BTS 'Other respiratory courses' page."
        else:
            where = f" in {shell['venue_raw']}" if shell.get("venue_raw") else ""
            out["description"] = f"{shell['title']}{where}. Dates are listed on the BTS meeting dates page; programme and booking details are not yet published."
        return out
