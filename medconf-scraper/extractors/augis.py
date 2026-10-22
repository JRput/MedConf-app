"""AUGIS (Association of Upper Gastrointestinal Surgeons of GB&I) events: DNN site, server-rendered, bespoke extractor.

`augis.org/Events` ("View as List" tab) is a plain table: `<time datetime="2026-11-20">`, a link to
`/Events/Event-Booking/EventId/<n>` (title), and the venue. The calendar tab and the page chrome say "October 2026 - March
2027", but the list is the whole set (no load-more control exists in the HTML; the recon note was wrong). One date per event.

`/Events/Event-Booking/EventId/<n>` only repeats title/date/venue and starts a booking flow with the notice "please log in
before making any bookings", so no fee is public: `pricing_tiers` stays empty (members' fees behind login). Events that have an
info page (`/Our-Events/<slug>`, linked from the left navigation) get a description from it; its "Programme" link points to a
Cvent summary page (title, date, "08:00-18:00", venue, street, "London WC2A 3PE") which is read once, with
safe_fetch.fetch_validated, for start time, full venue name and city. Cvent's registration step is a script app with no
fees in the HTML. CholeSafe's info page is a flyer image with no fees or text beyond what Cvent repeats.

The next Annual Scientific Meeting is announced only as a banner on the home page ("AUGIS ASM 2027 will take place on
15-17 September at ICC Wales!"); it is added from that sentence. The 2026 ASM (Harrogate, 23-25 Sep) is past.
Regional Meetings page lists no dated meetings beyond the one in the table.
"""
import html as _html
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from playwright.sync_api import Page

from logger import logger

from safe_fetch import check_url_safe, fetch_validated
from .base import BaseExtractor
from .http_fetch import fetch_html
from .tribe_events import html_to_lines
from .wordpress_generic import classify_event_type

_ROOT = "https://www.augis.org"
_LISTING = _ROOT + "/Events"
_SOCIETY = "Association of Upper Gastrointestinal Surgeons of GB&I (AUGIS)"
_REQUEST_GAP_S = 1.0
_MAX_FUTURE_DAYS = 550
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_NATION = {"yorkshire": "England", "london": "England", "gatwick": "England", "horley": "England", "harrogate": "England",
           "wales": "Wales", "scotland": "Scotland", "edinburgh": "Scotland", "glasgow": "Scotland", "belfast": "Northern Ireland"}


def _txt(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag))).replace("\xa0", " ").strip()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def parse_listing(html: str) -> List[Dict[str, Any]]:
    """/Events HTML -> [{title, url, start, venue}] from the list table (pure)."""
    out: List[Dict[str, Any]] = []
    for tr in re.findall(r"(?is)<tr\b[^>]*>(.*?)</tr\s*>", html or ""):
        t = re.search(r'(?is)<time\b[^>]*datetime="(\d{4}-\d{2}-\d{2})"', tr)
        a = re.search(r"""(?is)<a\b[^>]*href=['"]([^'"]*Event-Booking/EventId/\d+)['"][^>]*>(.*?)</a\s*>""", tr)
        if not (t and a):
            continue
        tds = re.findall(r"(?is)<td\b[^>]*>(.*?)</td\s*>", tr)
        out.append({"title": _txt(a.group(2)), "url": a.group(1), "start": t.group(1), "venue": _txt(tds[2]) if len(tds) > 2 else None})
    return out


def parse_info_links(html: str) -> Dict[str, str]:
    """Left-navigation links /Our-Events/<slug> -> {normalised link text: url} (pure)."""
    out: Dict[str, str] = {}
    for m in re.finditer(r"""(?is)<a\b[^>]*href=["'](https://www\.augis\.org/Our-Events/[^"'/]+)["'][^>]*>(.*?)</a\s*>""", html or ""):
        txt = _txt(m.group(2))
        if txt and not re.fullmatch(r"(?i)regional meetings|events calendar", txt):
            out[_norm(txt)] = m.group(1)
    return out


def parse_asm_banner(html: str) -> Optional[Dict[str, Any]]:
    """Home page banner "AUGIS ASM 2027 will take place on 15-17 September at ICC Wales!" (pure)."""
    m = re.search(r"AUGIS ASM (\d{4}) will take place on\s*(?:&nbsp;|\s)*(\d{1,2})\s*[–—-]\s*(\d{1,2})\s+([A-Za-z]+)\s+at\s+([^!<]{3,60})!", html or "")
    if not m or m.group(4)[:3].lower() not in _MONTHS:
        return None
    y, mon = int(m.group(1)), _MONTHS[m.group(4)[:3].lower()]
    try:
        return {"year": y, "start": date(y, mon, int(m.group(2))).isoformat(), "end": date(y, mon, int(m.group(3))).isoformat(), "venue": _txt(m.group(5))}
    except ValueError:
        return None


def parse_cvent_summary(html: str) -> Dict[str, Any]:
    """Cvent event summary -> start/end time, venue, city (pure)."""
    body = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1\s*>", " ", html or "")
    lines = html_to_lines(body)
    out: Dict[str, Any] = {}
    for i, l in enumerate(lines[:40]):
        tm = re.match(r"^(\d{1,2}):(\d{2})\s*([AP]M)?\s*[-–]\s*(\d{1,2}):(\d{2})\s*([AP]M)?$", l, re.I)
        if not tm:
            continue
        h, mi, ap = int(tm.group(1)), tm.group(2), (tm.group(3) or "").upper()
        if ap:
            h = h % 12 + (12 if ap == "PM" else 0)
        out["start_time"] = f"{h:02d}:{mi}"
        rest = [x for x in lines[i + 1:i + 5] if not re.match(r"(?i)^countdown", x)]
        if rest:
            out["venue"] = re.sub(r"\s+by IHG$", "", rest[0]).strip()
            last = rest[min(2, len(rest) - 1)] if len(rest) >= 2 else ""
            cm = re.match(r"^([A-Z][A-Za-z .'-]+?)\s+[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}$", last)
            if cm:
                out["city"] = cm.group(1).strip()
        break
    return out


def _region_for(*texts: Optional[str]) -> Optional[str]:
    blob = " ".join(t for t in texts if t).lower()
    for k, v in _NATION.items():
        if re.search(rf"\b{k}\b", blob):
            return v
    return None


class AugisExtractor(BaseExtractor):
    DEFAULT_SPECIALTY = "Surgery (General)"

    # ---- Phase A -----------------------------------------------------------
    def _get(self, url: str) -> Optional[str]:
        for attempt in range(3):
            body = fetch_html(url, browser=getattr(self, "browser", None))
            if body and len(body) > 1500:
                return body
            logger.warning(f"AUGIS fetch attempt {attempt + 1}/3 failed for {url}")
            time.sleep(2 * (attempt + 1))
        return None

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = self._get(_LISTING)
        if not html:
            return None
        today = date.today()
        info = parse_info_links(html)
        shells: List[Dict[str, Any]] = []
        seen = set()
        for r in parse_listing(html):
            if r["start"] < today.isoformat() or r["url"] in seen or re.search(r"(?i)cancel", r["title"]):
                continue
            if (date.fromisoformat(r["start"]) - today).days > _MAX_FUTURE_DAYS:
                continue
            seen.add(r["url"])
            nt = _norm(r["title"])
            info_url = next((u for k, u in info.items() if k and (k == nt or k in nt or nt in k)), None)
            shells.append({"title": r["title"], "booking_url": r["url"], "source_url": r["url"], "start_date": r["start"], "end_date": r["start"],
                           "start_time": None, "venue_raw": r["venue"], "category": None, "_info_url": info_url})
        time.sleep(_REQUEST_GAP_S)
        home = self._get(_ROOT + "/")
        asm = parse_asm_banner(home or "")
        if asm and asm["end"] >= today.isoformat() and (date.fromisoformat(asm["start"]) - today).days <= _MAX_FUTURE_DAYS:
            u = f"{_ROOT}/#asm-{asm['year']}"
            shells.append({"title": f"AUGIS Annual Scientific Meeting {asm['year']}", "booking_url": u, "source_url": u, "start_date": asm["start"],
                           "end_date": asm["end"], "start_time": None, "venue_raw": asm["venue"], "category": None, "_info_url": None, "_asm": True})
        shells.sort(key=lambda s: s["start_date"])
        logger.info(f"AUGIS: {len(shells)} upcoming shells")
        return shells or None

    # ---- Phase B -----------------------------------------------------------
    def extract_detail(self, page: Page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {"society": _SOCIETY, "specialty": self.DEFAULT_SPECIALTY, "start_date": shell["start_date"],
                               "end_date": shell.get("end_date") or shell["start_date"], "event_format": "in_person",
                               "event_type": classify_event_type(shell["title"], "")}
        venue = shell.get("venue_raw")
        if venue and not re.search(r"(?i)\b(online|virtual|webinar)\b", venue):
            out["venue_name"] = venue
        elif venue:
            out["event_format"] = "online"
        city = None
        cvent_url = None
        if shell.get("_info_url"):
            time.sleep(_REQUEST_GAP_S)
            ihtml = self._get(shell["_info_url"])
            if ihtml:
                cm = re.search(r"(?is)<div id=\"dnn_ContentPane\">(.*?)(?:<div class=\"row mt-4\">)", ihtml)
                lines = html_to_lines(cm.group(1) if cm else "")
                para = next((l for l in lines if len(l) >= 80 and re.search(r"[.!?]$", l)), "")
                if para:
                    out["description"] = para[:600]
                hm = re.search(r"(?i)\bat ([A-Z][^,\n]{3,40}(?:,\s*[A-Z][^,\n]{3,40})?),[^\n]*", " ".join(lines[:3]))
                if hm:
                    out["venue_name"] = hm.group(1).strip()
                for m in re.finditer(r"""(?is)<a\b[^>]*href=["'](https://[^"']*cvent\.com/[^"']+)["']""", ihtml):
                    host = (urlparse(_html.unescape(m.group(1))).hostname or "").lower().rstrip(".")
                    if host == "cvent.com" or host.endswith(".cvent.com"):
                        cvent_url = _html.unescape(m.group(1))
                        break
        if cvent_url:
            ok, why = check_url_safe(cvent_url)
            if not ok:
                logger.warning(f"AUGIS: Cvent link refused ({why}): {cvent_url}")
            else:
                time.sleep(_REQUEST_GAP_S)
                verdict, _final, body, enc, status = fetch_validated(cvent_url, deadline=time.monotonic() + 30, max_bytes=2_000_000)
                if verdict == "ok" and body:
                    cv = parse_cvent_summary(body.decode(enc or "utf-8", errors="replace"))
                    if cv.get("start_time"):
                        out["start_time"] = cv["start_time"]
                    if cv.get("venue"):
                        out["venue_name"] = cv["venue"]
                    city = cv.get("city")
                else:
                    logger.warning(f"AUGIS: Cvent summary not used (verdict={verdict}, status={status}): {cvent_url}")
        if city:
            out["city"] = city
        region = _region_for(city, out.get("venue_name"), shell.get("title"), shell.get("venue_raw"))
        if region:
            out["region"] = region
        return out
