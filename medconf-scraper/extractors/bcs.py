"""British Cardiovascular Society (BCS): courses + Annual Conference.

Two kinds of rows, both read from server-rendered pages (no LLM, no JS):

1. `/courses/` (WordPress / Elementor loop): one card per dated course: `<h6><a href=EventsAir-url>Title</a></h6>`, an ISO date
   (`2026-12-11`), optional venue + city lines, "Book now". The card link is the course's own EventsAir microsite
   (`bcs-<slug>.eventsair.site` / `.eventsairsite.com`), which is the row's booking_url. Those microsites are plain server-rendered
   pages whose layout differs per course: a date line ("11 December 2026" / "Date: 15 - 19 March 2027"), a venue line
   ("Venue Address: ..." / "Location: ..." / a bare name), and a fee block under "Pricing:" or "Attendance fee" holding one
   "label £amount" line per tier ("Members regular £998/ early bird £898", "Trainees - £65", "£56.00").
   Courses are `course`; webinars are `workshop`.
2. `/annual-conference/`: the next Annual Conference has no dated text on its own page yet ("watch this space"), but the organiser's
   own linked exhibitor rate-card PDF states "BCS Annual Conference Monday 7 - Wednesday 9 June 2027, Manchester Central". The date is
   read from that linked PDF; without it no conference row is emitted (never guessed). Delegate fees are not published (the PDF
   prices exhibition stands only, which are not attendee fees) so the conference row has no tiers.

robots.txt asks for a 10 s crawl delay: one listing + one conference page + one PDF + one page per course (each course lives on a
different EventsAir host).
"""
import html as html_lib
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from logger import logger

from .abstract_classifier import _default_fetcher, pdf_bytes_to_text
from browser import has_content_shape, looks_like_challenge
from .base import BaseExtractor
from .http_fetch import fetch_html
from .tribe_events import html_to_lines

ROOT = "https://britishcardiovascularsociety.org.uk"
COURSES_URL = ROOT + "/courses/"
CONFERENCE_URL = ROOT + "/annual-conference/"
SOCIETY = "BCS"
SPECIALTY = "Cardiology"

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}
_MON = "|".join(m[:3] for m in _MONTHS)
_M3 = {m[:3]: i for m, i in _MONTHS.items()}
_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_CARD_RE = re.compile(r'(?is)<h6\b[^>]*>\s*<a\s+href="([^"]+)"[^>]*>(.*?)</a>')
_UK_CITIES = {"london": "London", "manchester": "North West England", "liverpool": "North West England", "leeds": "Yorkshire and the Humber",
              "birmingham": "West Midlands", "bristol": "South West England", "newcastle": "North East England", "glasgow": "Scotland",
              "edinburgh": "Scotland", "cardiff": "Wales", "belfast": "Northern Ireland", "cambridge": "East of England",
              "oxford": "South East England", "nottingham": "East Midlands", "sheffield": "Yorkshire and the Humber"}
_ONLINE_RE = re.compile(r"(?i)\b(online|webinar|virtual|zoom|teams)\b")
_AMOUNT_RE = re.compile(r"£\s*(\d[\d,]*(?:\.\d{1,2})?)")
_FEE_HEAD_RE = re.compile(r"(?i)^(?:pricing|prices?|attendance fees?|fees?|registration fees?|ticket prices?)\s*:?$")
_FEE_STOP_RE = re.compile(r"(?i)^(?:accreditation|registration\b|download|our speakers|overview|who should|key reasons|programme|agenda)")
_PROMO_RE = re.compile(r"(?i)funding towards|provided funding|has had no editorial|sponsored by|register here|^home$|loading|©|cookie|days$|hours$|minutes$|^\d+$")


CRAWL_DELAY = 10.0                      # robots.txt `Crawl-delay: 10` on britishcardiovascularsociety.org.uk
_last_own_fetch = [0.0]


def _own_site_wait() -> None:
    """Sleep so consecutive requests to the BCS host (listing, conference page, PDF) are at least CRAWL_DELAY apart."""
    if _last_own_fetch[0]:
        gap = CRAWL_DELAY - (time.monotonic() - _last_own_fetch[0])
        if gap > 0:
            time.sleep(gap)
    _last_own_fetch[0] = time.monotonic()


def usable_loaded_page(page) -> Optional[Any]:
    """The browser page handed to extract_detail, or None when it is an error / challenge / empty page (chrome-error://, a failed
    EventsAir load): then fetch_html must fetch the course page afresh instead of parsing the error page. Pure-ish."""
    if page is None:
        return None
    try:
        if str(getattr(page, "url", "") or "").startswith("chrome-error"):
            return None
        html = page.content()
    except Exception:  # noqa: BLE001
        return None
    return page if has_content_shape(html) and not looks_like_challenge(html) else None


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _iso(y: int, m: int, d: int) -> Optional[str]:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def parse_courses_listing(html: str, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Cards of /courses/ -> shells (upcoming only). Pure."""
    today = today or date.today()
    shells: List[Dict[str, Any]] = []
    matches = list(_CARD_RE.finditer(html or ""))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(html)
        chunk = html[m.end():end]
        chunk = re.split(r"(?i)Sponsor a BCS course", chunk)[0]
        title = _clean_text(html_lib.unescape(re.sub(r"<[^>]+>", " ", m.group(2))))
        lines = html_to_lines(chunk)
        iso = next((l for l in lines if _ISO_RE.match(l)), None)
        if not title or not iso:
            continue
        y, mo, d = (int(x) for x in _ISO_RE.match(iso).groups())
        start = _iso(y, mo, d)
        if not start or start < today.isoformat() or re.search(r"(?i)cancel", title):
            continue
        after = lines[lines.index(iso) + 1:]
        place = []
        for l in after:
            if re.match(r"(?i)^book now$", l):
                break
            place.append(l)
        shells.append({"title": title, "booking_url": m.group(1).strip(), "start_date": start, "venue_raw": ", ".join(place) or None,
                       "category": "webinar" if re.search(r"(?i)webinar", title) else "course"})
    return shells


def parse_conference_dates(pdf_text: str, today: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """'BCS Annual Conference Monday 7 - Wednesday 9 June 2027, Manchester Central' -> start/end/venue, or None. Pure."""
    today = today or date.today()
    t = re.sub(r"\s+", " ", pdf_text or "")
    wd = r"(?:\w+day\s+)?"
    m = re.search(rf"Annual Conference\s+{wd}(\d{{1,2}})\s*[-–]\s*{wd}(\d{{1,2}})\s+({_MON})\w*\s+(20\d\d)(?:\s*,\s*([A-Z][A-Za-z ]+?))?(?=\s+(?:Exhibition|Sponsored|Stand|Package)|$)",
                  t, re.I)
    if not m:
        return None
    mon = _M3[m.group(3).lower()[:3]]
    a, b = _iso(int(m.group(4)), mon, int(m.group(1))), _iso(int(m.group(4)), mon, int(m.group(2)))
    if not (a and b and b >= a and b >= today.isoformat()):
        return None
    return {"start": a, "end": b, "venue": (m.group(5) or "").strip() or None}


def parse_course_dates(lines: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """First date or date range on an EventsAir page: '11 December 2026', 'Date: 15 - 19 March 2027', '29 Nov - 1 Dec 2026'. Pure."""
    for l in lines[:40]:
        m = re.match(rf"(?i)^(?:date\s*:\s*)?(\d{{1,2}})\s*(?:({_MON})\w*)?\s*[-–]\s*(\d{{1,2}})\s+({_MON})\w*\s+(20\d\d)\b", l)
        if m:
            y, mon2 = int(m.group(5)), _M3[m.group(4).lower()[:3]]
            mon1 = _M3[m.group(2).lower()[:3]] if m.group(2) else mon2
            return _iso(y, mon1, int(m.group(1))), _iso(y, mon2, int(m.group(3)))
        m = re.match(rf"(?i)^(?:date\s*:\s*)?(\d{{1,2}})\s+({_MON})\w*\s+(20\d\d)\b", l)
        if m:
            return _iso(int(m.group(3)), _M3[m.group(2).lower()[:3]], int(m.group(1))), None
    return None, None


def parse_fee_tiers(lines: List[str]) -> List[Dict[str, Any]]:
    """Fee block of an EventsAir course page -> GBP tiers (composite 'Category · Timeframe' labels). Pure.

    The block starts at a 'Pricing:' / 'Attendance fee' heading and ends at the next section ('Accreditation', 'Registration', ...).
    A line may carry several amounts: 'Members regular £998/ early bird £898' -> Regular + Early bird tiers."""
    start = next((i for i, l in enumerate(lines) if _FEE_HEAD_RE.match(l)), None)
    if start is None:
        return []
    block: List[str] = []
    for l in lines[start + 1:start + 25]:
        if _FEE_STOP_RE.match(l):
            break
        block.append(l)
    tiers: List[Dict[str, Any]] = []
    seen = set()
    for l in block:
        if re.match(r"(?i)^enter code", l):
            continue
        amts = list(_AMOUNT_RE.finditer(l))
        if not amts:
            continue
        base = re.sub(r"(?i)\bregular\b", "", l[:amts[0].start()])
        base = re.sub(r"\s*[:\-–—/]+\s*$", "", base).strip(" -:–—/")
        label_base = base or "Attendance"
        multi = len(amts) > 1
        for k, am in enumerate(amts):
            seg_label = l[amts[k - 1].end():am.start()] if k else ""
            early = bool(re.search(r"(?i)early", seg_label if k else ""))
            if k == 0:
                frame = "Regular" if (multi or re.search(r"(?i)\bregular\b", l[:amts[0].start()])) else None
            else:
                frame = "Early bird" if early else _clean_text(re.sub(r"^[\s/,\-–]+|[\s/,\-–:]+$", "", seg_label)) or None
            try:
                price = float(am.group(1).replace(",", ""))
            except ValueError:
                continue
            label = " · ".join(p for p in (label_base, frame) if p)[:120]
            if (label, price) in seen:
                continue
            seen.add((label, price))
            tiers.append({"tier_label": label, "price_gbp": price, "currency": "GBP", "is_early_bird": bool(frame and frame == "Early bird"),
                          "early_bird_deadline": None})
    return tiers


def split_place(raw: Optional[str]) -> Dict[str, Any]:
    """'Royal College of Physicians, London' / 'BMA House, Tavistock Square, London WC1H 9JP' / 'Online' -> venue/city/region/format. Pure."""
    raw = _clean_text(raw)
    if not raw:
        return {}
    if _ONLINE_RE.search(raw) and len(raw) < 40:
        return {"event_format": "online"}
    raw = re.sub(r"(?i)^(?:venue address|venue|location)\s*:\s*", "", raw)
    raw = re.sub(r"\s*\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", "", raw).strip(" ,")
    out: Dict[str, Any] = {"event_format": "in_person"}
    city = next((c for c in _UK_CITIES if re.search(rf"\b{c}\b", raw, re.I)), None)
    venue = raw
    if city:
        out["city"] = city.title()
        out["region"] = _UK_CITIES[city]
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        rest = [p for p in parts if p.lower() != city]            # drop a bare trailing city part, keep "Manchester Central"
        rest = [re.sub(rf"(?i)\s*\b{city}\b\s*$", "", p) if p.lower().endswith(" " + city) else p for p in rest]
        venue = ", ".join(x for x in rest if x) or raw
    if venue:
        out["venue_name"] = venue[:200]
    return out


def _description(lines: List[str], title: str) -> Optional[str]:
    for l in lines:
        if len(l) < 70 or l == title or _PROMO_RE.search(l) or re.match(r"(?i)^(date|time|venue|location|pricing)", l):
            continue
        if len(l) <= 380:
            return l
        cut = l[:380]
        idx = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        return cut[:idx + 1] if idx >= 150 else cut.rstrip() + "..."
    return None


class BcsExtractor(BaseExtractor):

    def _fetch(self, url: str) -> Optional[str]:
        if url.startswith(ROOT):
            _own_site_wait()
        return fetch_html(url, browser=getattr(self, "browser", None))

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = self._fetch(COURSES_URL)
        if not html:
            logger.warning("BCS: /courses/ fetch failed")
            return None
        shells = parse_courses_listing(html)
        conf = self._conference_shell()
        if conf:
            shells.append(conf)
        logger.info(f"BCS: {len(shells)} upcoming shells ({'with' if conf else 'no'} annual conference)")
        return shells

    def _conference_shell(self) -> Optional[Dict[str, Any]]:
        html = self._fetch(CONFERENCE_URL)
        if not html:
            return None
        pdfs = [urljoin(CONFERENCE_URL, h.replace("&amp;", "&")) for h in re.findall(r'(?is)href="([^"]+\.pdf)"', html)]
        pdfs = [u for u in pdfs if re.search(r"(?i)conference|bcs20\d\d", u)]
        info = None
        for u in pdfs[:2]:
            _own_site_wait()
            got = _default_fetcher(u.replace(" ", "%20"))
            if got and got[0] == "pdf":
                info = parse_conference_dates(pdf_bytes_to_text(got[1]))
                if info:
                    break
        if not info:
            logger.info("BCS: annual conference page lists no dated edition (rate-card PDF missing or dateless): no conference row")
            return None
        text = " ".join(html_to_lines(re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1>", " ", html)))
        pm = re.search(r"take place at ([A-Z][A-Za-z ]+?) in ([A-Z][a-z]+)", text)
        venue = (pm.group(1) if pm else None) or info["venue"]
        city = pm.group(2) if pm else None
        year = info["start"][:4]
        return {"title": f"BCS Annual Conference {year}", "booking_url": CONFERENCE_URL, "start_date": info["start"], "end_date": info["end"],
                "venue_raw": ", ".join(x for x in (venue, city) if x) or None, "category": "conference", "conference_page": True}

    def extract_detail(self, page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        url = shell.get("booking_url") or ""
        if url.startswith(ROOT):
            _own_site_wait()
        html = fetch_html(url, browser=getattr(self, "browser", None), loaded_page=usable_loaded_page(page)) if url else None
        if not html:
            html = page.content() if page is not None else ""
        body = re.sub(r"(?is)<(script|style|svg|nav|header|footer)\b.*?</\1>", " ", html or "")
        lines = html_to_lines(body)
        title = shell.get("title") or ""
        is_conf = bool(shell.get("conference_page"))
        webinar = shell.get("category") == "webinar" or bool(re.search(r"(?i)webinar", title))
        out: Dict[str, Any] = {"society": SOCIETY, "specialty": SPECIALTY, "pricing_tiers": [],
                               "event_type": "conference" if is_conf else ("workshop" if webinar else "course")}
        if is_conf:
            out["start_date"], out["end_date"] = shell["start_date"], shell.get("end_date")
            m = re.search(r"We look forward to welcoming delegates[^.]*\.", " ".join(lines))
            if m:
                out["description"] = _clean_text(m.group(0))
            out.update(split_place(shell.get("venue_raw")))
            return out

        start, end = parse_course_dates(lines)
        if start:
            out["start_date"] = start
        if end and end != start:
            out["end_date"] = end
        tm = next((re.match(r"(?i)^time\s*:\s*(\d{1,2}):(\d{2})", l) for l in lines[:40] if re.match(r"(?i)^time\s*:\s*\d", l)), None)
        if tm:
            out["start_time"] = f"{int(tm.group(1)):02d}:{tm.group(2)}"

        raw_place = None
        for i, l in enumerate(lines[:40]):
            pm = re.match(r"(?i)^(?:venue address|venue|location)\s*:\s*(.+)$", l)
            if pm:
                raw_place = pm.group(1)
                break
        if not raw_place:
            for i, l in enumerate(lines[:12]):                 # bare venue line right under the date line
                if re.match(rf"(?i)^\d{{1,2}}\s+({_MON})\w*\s+20\d\d", l) and i + 1 < len(lines):
                    nxt = lines[i + 1]
                    if len(nxt) < 80 and not re.match(r"(?i)^(pricing|time|overview|registration|loading)", nxt) and not _AMOUNT_RE.search(nxt):
                        raw_place = nxt
                    break
        place = split_place(raw_place) or split_place(shell.get("venue_raw"))
        if place.get("event_format") == "in_person" and "city" not in place:
            shell_place = split_place(shell.get("venue_raw"))
            if shell_place.get("city"):
                place.update({k: shell_place[k] for k in ("city", "region") if k in shell_place})
        if not place and webinar:
            place = {"event_format": "online"}
        out.update(place)

        out["pricing_tiers"] = parse_fee_tiers(lines)
        desc = _description(lines, title)
        if desc:
            out["description"] = desc
        text = " ".join(lines)
        cm = re.search(r"(\d+(?:\.\d+)?)\s*CPD\s*(?:points?|credits?)", text, re.I)
        if cm:
            out["cpd_points"], out["cpd_accredited"] = float(cm.group(1)), True
        return out
