"""YourMembership "Community Calendar" family (eans.org, theabn.org): ASP list + `EventDetails.aspx` pages, server-rendered.

Listing `/events/event_list.asp` (page N = `?DGPCrSrt=&DGPCrPg=N`, 15 rows a page, an empty page ends the walk): each event is
`<span id="EventList<id>"><a href="/events/EventDetails.aspx?id=<id>&group="><b>Title</b></a></span>`, then "dd/mm/yyyy" or
"dd/mm/yyyy » dd/mm/yyyy" and an optional "Location:" line. Detail: `#SpTitleBar` title, a bold "dd/mm/yyyy [to dd/mm/yyyy]" line, a
"When:" row, an optional "Where:" row (venue / city / country on `<br>` lines) and a free-text body in the table row after the
"Go to Upcoming Event List" link. Fees are not published in the calendar: the body links out (organiser site, or the society's own
`/page/...` microsite page) and the shared discovery engine follows that link (`organiser_url`) behind its identity gate.

A subclass sets ROOT / SOCIETY / DEFAULT_SPECIALTY and may override `extra_shells()` (events the calendar does not list). Every dropped
title is logged at INFO. No LLM calls: description is the first real body paragraph, specialty the society's own field (DEFAULT_SPECIALTY).
"""
import html as html_lib
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from logger import logger

from .base import BaseExtractor
from .http_fetch import fetch_html
from .pricing_tables import parse_pricing_tables
from .tribe_events import html_to_lines

MAX_PAGES = 8

_DMY = r"(\d{2})/(\d{2})/(\d{4})"
_RANGE_RE = re.compile(rf"{_DMY}(?:\s*(?:»|&raquo;|to|-)\s*{_DMY})?")
_BLOCK_SPLIT_RE = re.compile(r"""<span id=["']EventList(\d+)["']>""")
_ONLINE_RE = re.compile(r"(?i)\b(teams|zoom|webinar|online|virtual|webex|remote)\b")
_COUNTRIES = {"united kingdom", "uk", "england", "scotland", "wales", "northern ireland", "ireland", "germany", "france", "italy",
              "spain", "portugal", "switzerland", "austria", "netherlands", "belgium", "greece", "turkey", "türkiye", "poland",
              "usa", "united states", "canada", "australia", "japan", "china", "india", "brazil", "norway", "sweden", "denmark",
              "finland", "croatia", "serbia", "romania", "hungary", "czech republic", "morocco", "south korea", "singapore"}
_VENUE_WORDS = re.compile(r"(?i)\b(hotel|centre|center|hall|university|universit[aà]|institute|hospital|palace|resort|congress|"
                          r"convention|college|museum|campus|building|house|school|clinic|arena|theatre|theater|laborator)\b")
_DROP_RE = re.compile(r"(?i)general assembly|annual general meeting|\bAGM\b|council meeting|board meeting|committee meeting|"
                      r"call for (?:bids|nominations)|fundrais|\bgala\b|golf|charity (?:ride|run|walk)|ride for")


def is_relevant(title: str) -> bool:
    """A calendar row is kept unless its title is society administration or fundraising. These calendars belong to clinical societies
    (neurosurgery, neurology), so everything dated and clinical stays by default. Pure."""
    return not _DROP_RE.search(title or "")


def _iso(d: str, m: str, y: str) -> Optional[str]:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", s or "")).replace("\xa0", " ")).strip()


def parse_listing(html: str, root: str) -> List[Dict[str, Any]]:
    """One listing page -> [{id, title, url, start_date, end_date, location}] in page order (past rows included). Pure."""
    out: List[Dict[str, Any]] = []
    parts = _BLOCK_SPLIT_RE.split(html or "")
    for i in range(1, len(parts) - 1, 2):
        eid, chunk = parts[i], parts[i + 1]
        chunk = re.split(r"Export to Your Calendar", chunk, 1)[0]
        tm = re.search(r"(?is)<b[^>]*>(.*?)</b>", chunk)
        title = _clean(tm.group(1)) if tm else ""
        rest = chunk[tm.end():] if tm else chunk
        rest = re.sub(r"(?is)<script.*?</script>", " ", rest)          # the tooltip script carries the card's blurb, not a date
        dm = _RANGE_RE.search(rest)
        if not title or not dm:
            continue
        start = _iso(dm.group(1), dm.group(2), dm.group(3))
        end = _iso(dm.group(4), dm.group(5), dm.group(6)) if dm.group(4) else None
        lm = re.search(r"(?is)Location:</b>(.*?)</div>", rest)
        loc = _clean(lm.group(1)) if lm else None
        out.append({"id": eid, "title": title, "url": f"{root}/events/EventDetails.aspx?id={eid}",
                    "start_date": start, "end_date": end if end and end != start else None, "location": loc or None})
    return out


def split_place(lines: List[str]) -> Dict[str, Any]:
    """Where-row lines ('Pullman Melbourne Albert Park', 'Melbourne') -> venue/city/region/format. A lone line is a city
    unless it names a venue; a trailing country line becomes `region`; Teams/Zoom/online lines mean an online event. Pure."""
    toks: List[str] = []
    for l in lines:
        for t in re.split(r"\s*,\s*", l or ""):
            t = re.sub(r"\s*\([A-Z]{2}\)\s*$", "", t).strip()
            if t and t.lower() not in [x.lower() for x in toks]:
                toks.append(t)
    if not toks:
        return {}
    if any(_ONLINE_RE.search(t) for t in toks):
        return {"event_format": "online"}
    out: Dict[str, Any] = {"event_format": "in_person"}
    countries = [t for t in toks if t.lower() in _COUNTRIES]
    if countries and len(toks) > len(countries):
        out["region"] = countries[-1]
        toks = [t for t in toks if t.lower() not in _COUNTRIES]
    if len(toks) == 1:
        if _VENUE_WORDS.search(toks[0]) or re.match(r"[A-Z]{2,}\b", toks[0]):          # 'ICC Wales': an acronym-led name is a venue
            out["venue_name"] = toks[0][:200]
        else:
            out["city"] = toks[0][:80]
    else:
        out["venue_name"] = ", ".join(toks[:-1])[:200]
        out["city"] = toks[-1][:80]
    return out


def parse_detail(html: str, root: str) -> Dict[str, Any]:
    """Event detail HTML -> {title, start_date, end_date, start_time, place_lines, body_html, body_lines, links}. Pure."""
    out: Dict[str, Any] = {}
    tm = re.search(r"""(?is)<td id=["']SpTitleBar["']>(.*?)</td>""", html or "")
    if tm:
        out["title"] = _clean(tm.group(1))
    dm = re.search(rf"(?is)<b>\s*{_DMY}(?:\s+to\s+{_DMY})?\s*</b>", html or "")
    if dm:
        out["start_date"] = _iso(dm.group(1), dm.group(2), dm.group(3))
        end = _iso(dm.group(4), dm.group(5), dm.group(6)) if dm.group(4) else None
        if end and end != out["start_date"]:
            out["end_date"] = end
    wm = re.search(r'(?is)<b>When:</b>\s*</td>\s*<td[^>]*>(.*?)</td>', html or "")
    if wm:
        tt = re.search(r"(?i)\b(\d{1,2}):(\d{2})\s*([ap]m)?", _clean(wm.group(1)))
        if tt:
            hh = int(tt.group(1))
            if tt.group(3):
                hh = hh % 12 + (12 if tt.group(3).lower() == "pm" else 0)
            if hh < 24:
                out["start_time"] = f"{hh:02d}:{tt.group(2)}"
    pm = re.search(r'(?is)<b>Where:</b>\s*</td>\s*<td[^>]*>(.*?)</td>', html or "")
    out["place_lines"] = html_to_lines(pm.group(1)) if pm else []
    bm = re.search(r"(?is)Go to Upcoming Event List</a>.*?</tr>\s*<tr>\s*<td colspan=[\"']3[\"']>(.*?)</td>\s*</tr>", html or "")
    body = bm.group(1) if bm else ""
    out["body_html"] = body
    out["body_lines"] = html_to_lines(re.sub(r"\s*\n\s*", " ", body))      # source line wraps are not paragraph breaks
    out["links"] = [(_clean(m.group(2)), html_lib.unescape(m.group(1)))
                    for m in re.finditer(r"""(?is)<a\b[^>]*href=["']([^"'#][^"']*)["'][^>]*>(.*?)</a>""", body)]
    return out


_TITLE_CITY_RE = re.compile(r"^.*\b20\d\d\s*,\s*([A-Z][A-Za-z.' -]{2,30})$")
_NATIONS = {"wales", "scotland", "england", "ireland", "uk", "united kingdom", "northern ireland"}


def city_from_title(title: str) -> Optional[str]:
    """'ABN Annual Meeting 2027, Belfast' -> 'Belfast': the event's own title names the host city after the year. Nations
    ('... 2028, Wales') are not cities. Used only when the page has no Where row. Pure."""
    m = _TITLE_CITY_RE.match((title or "").strip())
    if not m or m.group(1).strip().lower() in _NATIONS:
        return None
    return m.group(1).strip()


_CTA_RE = re.compile(r"(?i)regist|info|website|more|here|programme|book|details|visit")


def pick_organiser(links: List[tuple], page_url: str, root: str) -> Optional[str]:
    """The body's registration / information link: http(s) only, best anchor text first (register, info, website, ...),
    otherwise the first link. Never mailto/tel/the calendar itself. Pure."""
    cands = []
    for text, href in links:
        u = urljoin(page_url, href)
        pu = urlparse(u)
        if pu.scheme not in ("http", "https") or "/events/" in pu.path and urlparse(root).netloc == pu.netloc:
            continue
        cands.append((0 if _CTA_RE.search(text or "") else 1, u))
    cands.sort(key=lambda c: c[0])
    return cands[0][1] if cands else None


def _tokens(s: str) -> set:
    return set(re.findall(r"[a-z0-9]+", (s or "").lower())) - {"the", "of", "and", "a"}


def nav_page_for(html: str, title: str, root: str) -> Optional[str]:
    """The society's own `/page/...` link whose text restates the event title ('ABN Annual Meeting 2027 (Belfast)' for
    'ABN Annual Meeting 2027, Belfast'): >= 0.8 token overlap and the same year. Used only when the body holds no link. Pure."""
    want = _tokens(title)
    years = {t for t in want if re.fullmatch(r"20\d\d", t)}
    best = None
    for m in re.finditer(r"""(?is)<a\b[^>]*href=["'](/page/[^"'#?]+)["'][^>]*>(.*?)</a>""", html or ""):
        got = _tokens(_clean(m.group(2)))
        if not got or (years and not years <= got):
            continue
        score = len(want & got) / len(want | got)
        if score >= 0.8 and (best is None or score > best[0]):
            best = (score, root + m.group(1))
    return best[1] if best else None


class CommunityCalendarExtractor(BaseExtractor):
    ROOT = ""
    SOCIETY = ""
    DEFAULT_SPECIALTY = "Multi-specialty"
    LISTING_PATH = "/events/event_list.asp"

    def extra_shells(self) -> List[Dict[str, Any]]:
        """Hook: events the calendar does not list (a society's own flagship page). Default none."""
        return []

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today().isoformat()
        shells: List[Dict[str, Any]] = []
        seen = set()
        dropped: List[str] = []
        total = 0
        listing_ok = False
        for page_no in range(1, MAX_PAGES + 1):
            url = self.ROOT + self.LISTING_PATH + ("" if page_no == 1 else f"?DGPCrSrt=&DGPCrPg={page_no}")
            html = fetch_html(url, browser=getattr(self, "browser", None), expect_selector="#SpContent")
            if not html:
                if page_no == 1:
                    logger.warning(f"{self.SOCIETY} calendar: listing fetch failed")
                    return []
                break
            listing_ok = listing_ok or bool(re.search(r"""id=["']EventList["']""", html))
            rows = [r for r in parse_listing(html, self.ROOT) if r["id"] not in seen]
            if not rows:
                break
            for r in rows:
                seen.add(r["id"])
                total += 1
                if not r["start_date"] or r["start_date"] < today:
                    dropped.append(f"{r['title']} (started {r['start_date']})")
                    continue
                if not is_relevant(r["title"]):
                    dropped.append(f"{r['title']} (administrative)")
                    continue
                shells.append({"title": r["title"], "booking_url": r["url"], "start_date": r["start_date"],
                               "end_date": r["end_date"], "venue_raw": r["location"]})
            time.sleep(0.5)
        for t in dropped:
            logger.info(f"{self.SOCIETY} calendar: dropped {t!r}")
        extras = self.extra_shells()
        have = {s["booking_url"] for s in shells}
        shells.extend(s for s in extras if s["booking_url"] not in have)
        logger.info(f"{self.SOCIETY} calendar: {len(shells)} kept of {total} listed ({len(dropped)} dropped, {len(extras)} extra)")
        if not shells and listing_ok:
            self.verified_empty = f"{self.SOCIETY} community calendar loaded and lists no upcoming events"
        return shells

    def extract_detail(self, page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        url = shell.get("booking_url") or ""
        if shell.get("_extra"):
            return self.extra_detail(page, shell)
        html = ""
        try:
            html = page.content() if page is not None else ""
        except Exception:
            html = ""
        if "SpTitleBar" not in html:
            html = fetch_html(url, browser=getattr(self, "browser", None), loaded_page=page) or html
        d = parse_detail(html, self.ROOT)
        title = shell.get("title") or d.get("title") or ""
        out: Dict[str, Any] = {"society": self.SOCIETY}
        if d.get("title"):
            out["conference_name"] = d["title"]
        for k in ("start_date", "end_date", "start_time"):
            if d.get(k):
                out[k] = d[k]

        place = split_place(d.get("place_lines") or [])
        if not place and shell.get("venue_raw"):
            place = split_place([shell["venue_raw"]])
        out.update(place)
        if not out.get("event_format") and _ONLINE_RE.search(title):
            out["event_format"] = "online"
        if not place and not out.get("city") and city_from_title(title):
            out["city"] = city_from_title(title)

        lines = d.get("body_lines") or []
        desc = next((l for l in lines if len(l) >= 60 and re.match(r"[A-Za-z\"'(0-9]", l)
                     and not re.match(r"(?i)^(website|register|info|click)\b", l)), None)
        if desc:
            if len(desc) > 400:
                cut = desc[:400]
                idx = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
                desc = cut[:idx + 1] if idx >= 150 else cut.rstrip() + "..."
            out["description"] = re.sub(r"\s+([.,;:!?])", r"\1", desc)

        org = pick_organiser(d.get("links") or [], url, self.ROOT) or nav_page_for(html, title, self.ROOT)
        if org and org != url:
            out["organiser_url"] = org

        if d.get("body_html"):
            tiers = parse_pricing_tables(d["body_html"], default_currency="") or []
            if tiers:
                out["pricing_tiers"] = tiers
        body_text = " ".join(lines)
        cm = re.search(r"(\d+(?:\.\d+)?)\s*(?:external\s+)?CPD\s*(?:points?|credits?|hours?)", body_text, re.I)
        if cm:
            out["cpd_points"], out["cpd_accredited"] = float(cm.group(1)), True
        out["specialty"] = self.DEFAULT_SPECIALTY      # single-specialty society calendar: the shared classifier mis-tags spine courses as MSK
        return out

    def extra_detail(self, page, shell: Dict[str, Any]) -> Dict[str, Any]:
        """Detail for a shell produced by `extra_shells()`; subclasses that add extras override this."""
        return {"society": self.SOCIETY}
