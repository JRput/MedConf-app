"""World Federation of Neurosurgical Societies (wfns.org): ASP.NET events list, server-rendered, one long page.

Listing `/events` ("All Events", about 1.5 MB with the whole archive): a "Future Events" tab (`#tab1`) and a "Past Events" tab (`#tab2`).
Only `#tab1` is read. Each future event is a table with a day/month badge, `<a href="/events/<cat>/<id>/<slug>"><span class="eventTitle">`,
a bold date line ("20 - 22 November 2026", "30 October - 1 November 2026"), an optional organiser website and Announcement/Brochure files.
Detail: `<h1><span id="..._lblTitle">`, a blue line `(20/11/2026 - 22/11/2026) / Swiss Hotel Grand Efes, Izmir, Türkiye, , Türkiye` (dates
dd/mm/yyyy with unpadded parts, place = comma list with empty slots), the organiser website, PDF links and a free-text body.

No fees are published on WFNS: the organiser website is passed on as `organiser_url` for the shared discovery engine (it follows
registration pages and the announcement PDF behind its identity gate). No LLM calls: description is the first real body paragraph,
specialty is neurosurgery unless the title classifier finds something more specific.
"""
import html as html_lib
import re
import time
from datetime import date
from urllib.parse import urlparse
from typing import Any, Callable, Dict, List, Optional

from logger import logger

from .abstract_classifier import classify_submission
from .base import BaseExtractor
from .http_fetch import fetch_html
from .tribe_events import html_to_lines

ROOT = "https://wfns.org"
LISTING_URL = ROOT + "/events"
SOCIETY = "WFNS"
DEFAULT_SPECIALTY = "Neurosurgery"

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}
_MON = "|".join(_MONTHS)
_LIST_DATE_RE = re.compile(rf"(?i)^\s*(\d{{1,2}})(?:\s+({_MON}))?(?:\s+(20\d\d))?(?:\s*[-–]\s*(\d{{1,2}})\s+({_MON})\s+(20\d\d))?\s*$")
_ANCHOR_RE = re.compile(r"""(?is)<a [^>]*href=["'](/events/\d+/[^"']+)["'][^>]*>\s*<span class=["']readMore eventTitle["']>(.*?)</span>""")
_DETAIL_DATE_RE = re.compile(r"\((\d{1,2})/(\d{1,2})/(\d{4})(?:\s*-\s*(\d{1,2})/(\d{1,2})/(\d{4}))?\)\s*/?\s*([^<]*)")
_ONLINE_RE = re.compile(r"(?i)\b(webinar|zoom|teams|online|virtual)\b")
_VENUE_WORDS = re.compile(r"(?i)\b(hotel|centre|center|hall|university|institute|hospital|palace|resort|congress|convention|college|"
                          r"museum|campus|building|school|clinic|arena|theatre|laborator|swiss[oô]tel|hilton|marriott)\b")
_DROP_RE = re.compile(r"(?i)general assembly|annual general meeting|\bAGM\b|council meeting|board meeting|committee meeting|fundrais|\bgala\b")
_FILE_LABELS = re.compile(r"(?i)^(announcement|brochure|flyer|scientific program(?:me)?|programme?|poster|invitation|abstract(?:s| book)?)$")


def _iso(y: int, m: int, d: int) -> Optional[str]:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", s or "")).replace("\xa0", " ")).strip()


def is_relevant(title: str) -> bool:
    return not _DROP_RE.search(title or "")


def future_region(html: str) -> Optional[str]:
    """The `#tab1` (Future Events) container HTML, or None when the page has no such container. Pure."""
    m1 = re.search(r"""id=["']tab1["']""", html or "")
    if not m1:
        return None
    m2 = re.search(r"""id=["']tab2["']""", html[m1.end():])
    return html[m1.start(): m1.end() + m2.start()] if m2 else html[m1.start():]


def empty_signal(html: str) -> bool:
    """Positive proof of an empty future list: the container exists and holds no links and no date-like text (or says 'no events').
    A container whose rows simply did not match the row regex is NOT empty. Pure."""
    region = future_region(html)
    if region is None:
        return False
    if "<a " in region.lower() or re.search(rf"(?i)\b(?:20\d\d|{_MON})\b", _clean(region)):
        return bool(re.search(r"(?i)\bno (?:upcoming |future )?events\b", _clean(region))) and "<a " not in region.lower()
    return True


def parse_listing(html: str) -> List[Dict[str, Any]]:
    """`#tab1` (Future Events) -> [{url, title, start_date, end_date, website}]. Past events are never read. Pure."""
    m1 = re.search(r"""id=["']tab1["']""", html or "")
    i = m1.start() if m1 else -1
    m2 = re.search(r"""id=["']tab2["']""", html or "") if i >= 0 else None
    j = m2.start() if m2 and m2.start() > i else -1
    if i < 0:
        return []
    region = html[i:j if j > i else len(html)]
    anchors = list(_ANCHOR_RE.finditer(region))
    out: List[Dict[str, Any]] = []
    for n, m in enumerate(anchors):
        chunk = region[m.end(): anchors[n + 1].start() if n + 1 < len(anchors) else len(region)]
        title = _clean(m.group(2)).lstrip("»").strip()
        dm = re.search(r"""(?is)font-weight:\s*600;?["'][^>]*>(.*?)</td>""", chunk)
        start = end = None
        if dm:
            start, end = _parse_list_dates(_clean(dm.group(1)))
        wm = re.search(r"""(?is)<img src=["']/images/web\.png["'][^>]*>\s*<a href=["']([^"']+)["']""", chunk)
        out.append({"url": ROOT + m.group(1), "title": title, "start_date": start, "end_date": end,
                    "website": html_lib.unescape(wm.group(1)) if wm else None})
    return out


def _parse_list_dates(text: str) -> tuple:
    """'20 - 22 November 2026' / '30 October - 1 November 2026' / '31 October 2026' -> (start, end) ISO. Pure."""
    t = text.replace("–", "-")
    m = re.match(rf"(?i)^(\d{{1,2}})\s*-\s*(\d{{1,2}})\s+({_MON})\s+(20\d\d)$", t)
    if m:
        mo = _MONTHS[m.group(3).lower()]
        return _iso(int(m.group(4)), mo, int(m.group(1))), _iso(int(m.group(4)), mo, int(m.group(2)))
    m = re.match(rf"(?i)^(\d{{1,2}})\s+({_MON})\s*-\s*(\d{{1,2}})\s+({_MON})\s+(20\d\d)$", t)
    if m:
        y = int(m.group(5))
        return _iso(y, _MONTHS[m.group(2).lower()], int(m.group(1))), _iso(y, _MONTHS[m.group(4).lower()], int(m.group(3)))
    m = re.match(rf"(?i)^(\d{{1,2}})\s+({_MON})\s+(20\d\d)$", t)
    if m:
        d = _iso(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
        return d, None
    return None, None


def split_place(raw: str) -> Dict[str, Any]:
    """'Swiss Hotel Grand Efes, Izmir, Türkiye, , Türkiye' / 'Chicago, Illinois, , USA' / ', Bali' -> venue/city/region/format.
    Empty slots and a repeated country are dropped; the last item of two or more is the country (`region`); a part naming a venue
    (hotel, centre, university ...) is the venue; the first remaining part is the city (a trailing state/province is ignored). Pure."""
    parts: List[str] = []
    for p in (x.strip() for x in (raw or "").split(",")):
        if p and p.lower() not in [q.lower() for q in parts]:
            parts.append(p)
    if not parts:
        return {}
    if len(parts) == 1 and _ONLINE_RE.search(parts[0]):
        return {"event_format": "online"}
    out: Dict[str, Any] = {"event_format": "in_person"}
    if len(parts) > 1:
        out["region"] = parts.pop()
    venue = next((p for p in parts if _VENUE_WORDS.search(p)), None)
    rest = [p for p in parts if p != venue]
    if venue:
        out["venue_name"] = venue[:200]
    if rest:
        out["city"] = rest[0][:80]
    return out


def parse_detail(html: str) -> Dict[str, Any]:
    """Detail HTML -> {title, start_date, end_date, place, website, body_lines}. Pure."""
    out: Dict[str, Any] = {}
    tm = re.search(r"""(?is)<span id=["'][^"']*lblTitle["']>(.*?)</span>""", html or "")
    if tm:
        out["title"] = _clean(tm.group(1))
    dm = _DETAIL_DATE_RE.search(html or "")
    if dm:
        out["start_date"] = _iso(int(dm.group(3)), int(dm.group(2)), int(dm.group(1)))
        if dm.group(4):
            end = _iso(int(dm.group(6)), int(dm.group(5)), int(dm.group(4)))
            if end and end != out["start_date"]:
                out["end_date"] = end
        out["place"] = _clean(dm.group(7))
    i = (html or "").find("PanelEvent")
    if i >= 0:
        i = (html or "").find(">", i) + 1
    jm = re.search(r"""<div class=["']col-sm-12 col-md-3 box["']>""", html or "")
    j = jm.start() if jm and jm.start() > i else -1
    region = html[i:j] if i >= 0 and j > i else ""
    wm = re.search(r"""(?is)<img src=["']/images/web\.png["'][^>]*>\s*<a href=["']([^"']+)["']""", region)
    out["website"] = html_lib.unescape(wm.group(1)) if wm else None
    lines = []
    for ln in html_to_lines(re.sub(r"\s*\n\s*", " ", region)):
        if ln.startswith("(") and _DETAIL_DATE_RE.match(ln):
            continue
        if re.match(r"(?i)^https?://", ln) or _FILE_LABELS.match(ln) or re.match(r"(?i)^(please )?register at\b", ln):
            continue
        lines.append(ln)
    out["body_lines"] = lines
    return out


def abstract_fields(lines: List[str], start_iso: Optional[str]) -> Dict[str, Any]:
    """Abstract status from the event page's own text lines (one line per cell keeps 'Abstract Submission Deadline' next to its date).
    Open only with a future deadline or explicit open wording; a programme with no date gives a note. Pure."""
    try:
        start = date.fromisoformat(start_iso) if start_iso else None
    except ValueError:
        start = None
    is_open, deadline, note = classify_submission("\n".join(lines), date.today(), start)
    out: Dict[str, Any] = {}
    if deadline:
        out["abstract_open"], out["abstract_deadline"] = is_open, deadline.isoformat()
    elif note:
        out["abstract_open"], out["abstract_deadline_note"] = is_open, note
    return out


class WfnsExtractor(BaseExtractor):

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = fetch_html(LISTING_URL, browser=getattr(self, "browser", None), expect_selector=".events_container")
        if not html:
            logger.warning("WFNS: listing fetch failed")
            return []
        today = date.today().isoformat()
        shells: List[Dict[str, Any]] = []
        rows = parse_listing(html)
        for r in rows:
            if not r["start_date"] or r["start_date"] < today:
                logger.info(f"WFNS: dropped {r['title']!r} (start {r['start_date']})")
                continue
            if not is_relevant(r["title"]):
                logger.info(f"WFNS: dropped {r['title']!r} (administrative)")
                continue
            shells.append({"title": r["title"], "booking_url": r["url"], "start_date": r["start_date"],
                           "end_date": r["end_date"], "organiser_url": r["website"]})
        logger.info(f"WFNS: {len(shells)} kept of {len(rows)} future events listed")
        if not shells and empty_signal(html):
            self.verified_empty = "WFNS 'Future Events' tab present with no links and no dates"
        elif not shells:
            logger.warning("WFNS: 0 shells without a positive empty signal (parser break or all rows dropped); not verified empty")
        return shells

    def extract_detail(self, page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        url = shell.get("booking_url") or ""
        html = ""
        try:
            html = page.content() if page is not None else ""
        except Exception:
            html = ""
        if "lblTitle" not in html:
            html = fetch_html(url, browser=getattr(self, "browser", None), loaded_page=page) or html
        d = parse_detail(html)
        title = shell.get("title") or d.get("title") or ""
        out: Dict[str, Any] = {"society": SOCIETY}
        if d.get("title"):
            out["conference_name"] = d["title"]
        for k in ("start_date", "end_date"):
            if d.get(k):
                out[k] = d[k]
        place = split_place(d.get("place") or "")
        out.update(place)
        if not out.get("event_format") and _ONLINE_RE.search(f"{title} {shell.get('organiser_url') or ''}"):
            out["event_format"] = "online"
        web = d.get("website") or shell.get("organiser_url")
        if web:
            pw = urlparse(web.strip())
            if pw.scheme in ("http", "https") and pw.netloc and not re.search(r"(?i)teams\.|zoom\.us|meet\.google", web):
                out["organiser_url"] = web.strip()
        desc = next((l for l in d.get("body_lines") or [] if len(l) >= 60 and re.match(r"[A-Za-z\"'(0-9]", l)), None)
        if desc:
            if len(desc) > 400:
                cut = desc[:400]
                idx = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
                desc = cut[:idx + 1] if idx >= 150 else cut.rstrip() + "..."
            out["description"] = desc
        out.update(abstract_fields(d.get("body_lines") or [], out.get("start_date") or shell.get("start_date")))
        out["specialty"] = DEFAULT_SPECIALTY
        return out
