"""BAAPS events calendar (baaps.org.uk/about/events): bespoke extractor (the single-congress family does not fit).

baaps.org.uk/about/events is a CALENDAR of many events (own courses, webinars, training days, residents day, plus
third-party listings) rather than one congress, so this follows the rcpath.py pattern (listing -> detail) instead
of SingleCongressExtractor.

LISTING  /about/events/date/<YYYY>/ (server-rendered, one `div.date_row` per event: date | title link | location).
         Walks the current year and the next two, dedupes by URL, keeps events that have not finished.
         The calendar also carries unrelated promoter listings (nursing/polymer/healthcare congresses), so a shell is
         kept only when the event page itself is plastic/aesthetic-surgery related (keyword gate below) or organised
         by BAAPS.
DETAIL   /about/events/<id>/<slug>: title, date line, location line, "Event" description block, "Organised by".
         Fees are not published (booking is external or behind login) -> pricing_tiers [].
"""
import html as _html
import re
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin

from playwright.sync_api import Page

from logger import logger

from .base import BaseExtractor
from .http_fetch import fetch_html
from .single_congress import html_lines
from .wordpress_generic import json_ld_events
from .specialty_classifier import classify_specialty
from .tribe_events import pick_description

BASE = "https://baaps.org.uk"
_MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_RELEVANT_RE = re.compile(
    r"plastic surg|aesthetic|cosmetic|rhinoplast|reconstruct|craniofacial|facial|blepharoplast|abdominoplast|"
    r"body contour|breast (?:aug|surg|recon)|hair transplant|face lift|facelift", re.I)
_UK_REGIONS = {
    "london": "London", "manchester": "North West England", "liverpool": "North West England",
    "leeds": "Yorkshire and the Humber", "sheffield": "Yorkshire and the Humber", "york": "Yorkshire and the Humber",
    "newcastle": "North East England", "birmingham": "West Midlands", "bristol": "South West England",
    "exeter": "South West England", "plymouth": "South West England", "cardiff": "Wales", "swansea": "Wales",
    "newport": "Wales", "edinburgh": "Scotland", "glasgow": "Scotland", "aberdeen": "Scotland", "dundee": "Scotland",
    "belfast": "Northern Ireland", "cambridge": "East of England", "norwich": "East of England",
    "oxford": "South East England", "brighton": "South East England", "leicester": "East Midlands",
    "nottingham": "East Midlands",
}
_POSTCODE_RE = re.compile(r"\s*\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")


def parse_when(text: str):
    """"5 Nov 8:30AM – 7 Nov 5:00PM 2026" | "8 Jan 2027 9:00AM – 5:00PM" -> (start, end, start_time) or None."""
    t = re.sub(r"\s+", " ", _html.unescape(text or "")).strip()
    dm = [(int(m.group(1)), _MON.get(m.group(2)[:3].lower())) for m in re.finditer(r"\b(\d{1,2}) ([A-Z][a-z]{2,8})\b(?!:)", t)]
    dm = [x for x in dm if x[1]]
    years = re.findall(r"\b(20\d\d)\b", t)
    if not dm or not years:
        return None
    try:
        y0 = int(years[0])
        start = date(y0, dm[0][1], dm[0][0])
        end = date(int(years[-1]), dm[1][1], dm[1][0]) if len(dm) > 1 else start
    except ValueError:
        return None
    tm = re.search(r"\b(\d{1,2}):(\d{2})\s?([AP]M)\b", t)
    st = None
    if tm:
        h = int(tm.group(1)) % 12 + (12 if tm.group(3) == "PM" else 0)
        st = f"{h:02d}:{tm.group(2)}"
    return start, end, st


def event_type_for(title: str) -> str:
    t = title.lower()
    if re.search(r"webinar|study day|training day|residents day|masterclass|workshop|skills|interview", t):
        return "workshop"
    if "course" in t:
        return "course"
    return "conference"


class BaapsExtractor(BaseExtractor):
    LISTING_URL = BASE + "/about/events/date/{year}/"

    def _get(self, url: str) -> Optional[str]:
        return fetch_html(url, browser=getattr(self, "browser", None))

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today()
        seen, shells = set(), []
        for yr in (today.year, today.year + 1, today.year + 2):
            html = self._get(self.LISTING_URL.format(year=yr))
            if not html:
                continue
            for row in re.findall(r'(?is)<div class="date_row[^"]*".*?(?=<div class="date_row|</section>|<footer)', html):
                a = re.search(r'(?is)<a href="(/about/events/\d+/[^"]+)">(.*?)</a>', row)
                cells = re.findall(r'(?is)<div class="col-sm-4">(.*?)</div>', row)
                if not a or not cells:
                    continue
                url = urljoin(BASE, a.group(1))
                when = parse_when(re.sub(r"<[^>]+>", " ", cells[0]))
                if url in seen or not when or when[1] < today:
                    continue
                seen.add(url)
                title = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", a.group(2)))).strip()
                loc = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", cells[2] if len(cells) > 2 else ""))).strip()
                shells.append({"title": title, "booking_url": url, "start_date": when[0].isoformat(), "end_date": when[1].isoformat(),
                               "start_time": when[2], "venue_raw": loc or None, "event_type": event_type_for(title)})
        kept = []
        for s in shells[:30]:
            body = self._get(s["booking_url"]) or ""
            lines = html_lines(body)
            try:      # page chrome ("BAAPS Home", "About BAAPS") must not count: only the Event block + organiser line
                core = lines[lines.index("Event") + 1:]
            except ValueError:
                core = lines
            text = " ".join(core)
            org = re.search(r"Organised by:\s*(.+?)(?:\s+Phone|\s*$)", text)
            if _RELEVANT_RE.search(s["title"] + " " + text) or re.search(r"\bBAAPS\b", s["title"]) or (org and "BAAPS" in org.group(1)):
                if re.search(r"(?i)\bwebinar\b", text) and s["event_type"] == "conference":
                    s["event_type"] = "workshop"
                kept.append(s)
            else:
                logger.info(f"BAAPS: skipping unrelated listing {s['title']!r}")
        logger.info(f"BAAPS: {len(kept)} relevant upcoming events of {len(shells)} listed")
        return kept

    @staticmethod
    def parse_location(loc: Optional[str]):
        """-> (venue, city, region, online)."""
        if not loc:
            return None, None, None, False
        if re.fullmatch(r"(?i)online|virtual|zoom|webinar|teams", loc.strip()):
            return None, None, None, True
        addr = _POSTCODE_RE.sub("", loc).strip(" ,")
        m = re.match(r"^(.+?) in ([A-Z][A-Za-z ]+)$", addr)
        if m:
            venue, city = m.group(1).strip(), m.group(2).strip()
        else:
            parts = [p.strip() for p in addr.split(",") if p.strip()]
            venue = parts[0] if parts else None
            city = next((p.title() for p in reversed(parts) if p.lower() in _UK_REGIONS), None)
        if city is None:
            city = next((k.title() for k in _UK_REGIONS if re.search(rf"\b{k}\b", loc, re.I)), None)
        return venue, city, _UK_REGIONS.get((city or "").lower()), False

    def extract_detail(self, page: Page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        html = page.content()
        lines = html_lines(html)
        title = shell.get("title") or ""
        out: Dict[str, Any] = {"society": "BAAPS", "event_type": shell.get("event_type") or event_type_for(title),
                               "start_date": shell.get("start_date"), "end_date": shell.get("end_date"), "pricing_tiers": []}
        if shell.get("start_time"):
            out["start_time"] = shell["start_time"]
        # header block: title (2nd occurrence) / date line / location line
        idx = [i for i, l in enumerate(lines) if l == title]
        loc = shell.get("venue_raw")
        if idx:
            nxt = lines[idx[-1] + 2] if idx[-1] + 2 < len(lines) else None
            if nxt and not re.match(r"(?i)^(book online|register|event$)", nxt):
                loc = nxt
        venue, city, region, online = self.parse_location(loc)
        if online:
            out["event_format"] = "online"
        elif venue or city:
            out["event_format"] = "in_person"
        if venue:
            out["venue_name"] = venue
        if city:
            out["city"] = city
        if region:
            out["region"] = region
        # description: the "Event" block up to the booking / organiser footer
        try:
            s = lines.index("Event") + 1
        except ValueError:
            s = idx[-1] + 3 if idx else 0
        e = next((i for i in range(s, len(lines)) if re.match(r"(?i)^(further details|book online|organised by|← other events)", lines[i])), len(lines))
        body = [l for l in lines[s:e] if l not in ("Terms and Conditions",)]
        desc = pick_description(body, title)
        if desc:
            out["description"] = desc[:600]
        text = " ".join(lines)
        if re.search(r"(?i)approved for (?:CPD|CME)|CPD certified", text):
            out["cpd_accredited"] = True
        out["specialty"] = classify_specialty(title, out.get("description")) or "Plastic Surgery"
        out["booking_url"] = shell.get("booking_url")
        tiers = self._external_offers(html)
        if tiers:
            out["pricing_tiers"] = tiers
        return out

    def _external_offers(self, html: str) -> List[Dict[str, Any]]:
        """Organiser-run events link to their own site ("Further details about this event"); its JSON-LD Event.offers are the fees.
        Events booked through the BAAPS account system (members' / account holders' fees behind login) publish none."""
        skip = re.compile(r"facebook|twitter|x\.com|linkedin|instagram|youtube|baaps\.org\.uk|mailto:|tel:|google|login", re.I)
        link = next((h for h in re.findall(r'(?is)<a [^>]*href="(https?://[^"]+)"', html) if not skip.search(h)), None)
        if not link:
            return []
        body = self._get(link)
        if not body:
            return []
        tiers: List[Dict[str, Any]] = []
        for ev in json_ld_events(body):
            offers = (ev.get("offers") or {})
            offers = offers.get("offers") if isinstance(offers, dict) and offers.get("offers") else offers
            for o in (offers if isinstance(offers, list) else [offers]):
                if not isinstance(o, dict) or o.get("price") in (None, ""):
                    continue
                name = re.sub(r"\s+", " ", str(o.get("name") or "Ticket")).strip()
                if re.search(r"dinner|gala", name, re.I):
                    continue
                try:
                    price = float(str(o["price"]).replace(",", ""))
                except ValueError:
                    continue
                sold_out = "SoldOut" in str(o.get("availability") or "")
                tiers.append({"tier_label": f"Registration \u00b7 {name}" + (" \u00b7 Sold out" if sold_out else ""), "price_gbp": price,
                              "currency": o.get("priceCurrency") or "GBP", "is_early_bird": False, "early_bird_deadline": None})
            if tiers:
                break
        return tiers
