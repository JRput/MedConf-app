"""IMCAS (International Master Course on Aging Science): congress listing + per-congress pages (imcas.com), server-rendered.

`/en/worldwide-events` is an agenda of the whole dermatology / plastic-surgery / aesthetics calendar, mostly OTHER organisers'
congresses (ASDS, JSAPS, SFED ...) that only link out to their own sites. Those are not IMCAS events and have no IMCAS page, so
they are dropped and counted in the log. What is kept are IMCAS's own congresses, listed in the site-wide "Congresses" menu that
is present on every page as `IMCAS World 2027` / `28 - 30 January 2027, PARIS & ONLINE`. The INVEST day (invest.imcas.com) is an
investor / C-level programme, not clinician CPD, and is dropped too.

Congress page `/en/imcas-<name>-<year>`: `Thursday January 28 - Saturday January 30` then `Palais des Congres de Paris, Paris`,
a status block ("Congress registration: open", "Abstract submission : open"), a pitch paragraph. The registration page is
disallowed by robots.txt (`Disallow: /*/registration`) and is not fetched, so there are no fee tiers.
"""
import html as html_lib
import re
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from logger import logger

from .base import BaseExtractor
from .http_fetch import fetch_html
from .tribe_events import html_to_lines

ROOT = "https://www.imcas.com"
LISTING_URL = ROOT + "/en/worldwide-events"
SOCIETY = "IMCAS"
SPECIALTY = "Aesthetic & Cosmetic Medicine"

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}
_MON = "|".join(_MONTHS)
# Cities of IMCAS's own congresses -> country (region field carries the country for international events).
_COUNTRY = {"paris": "France", "sao paulo": "Brazil", "bangkok": "Thailand", "shanghai": "China", "singapore": "Singapore",
            "dubai": "United Arab Emirates", "london": "United Kingdom", "mexico city": "Mexico", "hong kong": "Hong Kong"}
_MENU_RE = re.compile(rf"(?i)^(\d{{1,2}})\s*[-–]\s*(\d{{1,2}})\s+({_MON})\s+(20\d\d)\s*,\s*(.+)$")
_TITLE_RE = re.compile(r"^IMCAS\s+[A-Z][A-Za-z ]+?\s+20\d\d$")
_PAGE_DATES_RE = re.compile(rf"(?i)^(?:\w+day\s+)?({_MON})\s+(\d{{1,2}})\s*[-–]\s*(?:\w+day\s+)?(?:({_MON})\s+)?(\d{{1,2}})$")


def _iso(y: int, m: int, d: int) -> Optional[str]:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def with_title_token(desc: str, title: str) -> str:
    """Audit wants a description that names the event: prefix the title when the text shares no distinctive word with it. Pure."""
    words = [w for w in re.findall(r"[A-Za-z]{4,}", title)] + ([title.split()[1]] if len(title.split()) > 1 else [])
    return desc if any(w.lower() in desc.lower() for w in words) else f"{title}: {desc}"[:400]


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def parse_menu(html: str, today: Optional[date] = None) -> Dict[str, Any]:
    """Site-wide 'Congresses' menu -> {'kept': [shells], 'dropped': [titles]}. Own congresses with a full date range are kept;
    the INVEST investor day and anything over are dropped. Pure."""
    today = today or date.today()
    lines = html_to_lines(re.sub(r"(?is)<(script|style|svg)\b.*?</\1>", " ", html or ""))
    kept: List[Dict[str, Any]] = []
    dropped: List[str] = []
    seen = set()
    for i, l in enumerate(lines[:-1]):
        if l in seen or not (_TITLE_RE.match(l) or re.match(r"^INVEST by IMCAS", l)):
            continue
        if re.match(r"^INVEST", l):
            seen.add(l)
            dropped.append(f"{l} (investor / C-level day, not clinician CPD)")
            continue
        m = _MENU_RE.match(lines[i + 1])
        if not m:                                  # the hero-menu copy splits date and city over two lines; the drawer copy joins them
            continue
        seen.add(l)
        mon, y = _MONTHS[m.group(3).lower()], int(m.group(4))
        start, end = _iso(y, mon, int(m.group(1))), _iso(y, mon, int(m.group(2)))
        if not start or not end or end < today.isoformat():
            continue
        kept.append({"title": l, "booking_url": f"{ROOT}/en/{slugify(l)}", "start_date": start, "end_date": end, "place_raw": m.group(5).strip()})
    return {"kept": kept, "dropped": dropped}


def parse_agenda_titles(html: str) -> List[str]:
    """Titles of the third-party congresses on the worldwide agenda (for the drop log): the line before '<City> (<Country>)'. Pure."""
    lines = html_to_lines(re.sub(r"(?is)<(script|style|svg)\b.*?</\1>", " ", html or ""))
    return [lines[i - 1] for i, l in enumerate(lines) if i and re.search(r"\([A-Z][A-Za-z .]+\)$", l) and not re.match(r"^\d", lines[i - 1])]


def split_place(raw: str) -> Dict[str, Any]:
    """'PARIS & ONLINE' / 'SAO PAULO - SP' / 'Palais des Congres de Paris, Paris' -> venue/city/region/format. Pure."""
    raw = re.sub(r"\s+", " ", raw or "").strip()
    out: Dict[str, Any] = {}
    hybrid = bool(re.search(r"(?i)&\s*online|\+\s*online|hybrid", raw))
    raw = re.sub(r"(?i)\s*(?:&|\+)\s*online\b", "", raw).strip(" ,-")
    raw = re.sub(r"\s+-\s+[A-Z]{2}$", "", raw)                # 'SAO PAULO - SP' (state code)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return out
    city = parts[-1]
    if city.isupper():
        city = city.title()
    out["city"] = city
    country = _COUNTRY.get(city.lower())
    if country:
        out["region"] = country
    if len(parts) > 1:
        out["venue_name"] = ", ".join(parts[:-1])[:200]
    out["event_format"] = "hybrid" if hybrid else "in_person"
    return out


class ImcasExtractor(BaseExtractor):
    # robots.txt disallows `/*/registration` and the shared discovery engine follows registration pages without checking robots
    # (observed 2026-11-09: it fetched .../registration and a badge page). Opt out of discovery; abstract deadlines still come from
    # the pipeline's own call-for-papers follow (`_ensure_submission_info` finds the congress's /submit-abstract link).
    DISCOVERY_ENABLED = False

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = fetch_html(LISTING_URL, browser=getattr(self, "browser", None))
        if not html:
            logger.warning("IMCAS: worldwide-events fetch failed")
            return None
        menu = parse_menu(html)
        third = parse_agenda_titles(html)
        for t in menu["dropped"]:
            logger.info(f"IMCAS: dropped {t!r}")
        logger.info(f"IMCAS: {len(third)} other-organiser congresses on the agenda dropped (not IMCAS events): {third[:40]!r}")
        shells = [{"title": c["title"], "booking_url": c["booking_url"], "start_date": c["start_date"], "end_date": c["end_date"],
                   "venue_raw": c["place_raw"]} for c in menu["kept"]]
        logger.info(f"IMCAS: {len(shells)} own congresses kept")
        return shells

    def extract_detail(self, page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        url = shell.get("booking_url") or ""
        html = fetch_html(url, browser=getattr(self, "browser", None), loaded_page=page) if url else None
        if not html:
            html = page.content() if page is not None else ""
        lines = html_to_lines(re.sub(r"(?is)<(script|style|svg|noscript)\b.*?</\1>", " ", html))
        title = shell.get("title") or ""
        out: Dict[str, Any] = {"society": SOCIETY, "event_type": "conference", "specialty": SPECIALTY, "pricing_tiers": [],
                               "start_date": shell.get("start_date"), "end_date": shell.get("end_date")}

        # Hero block: '<Title>' / 'Thursday January 28 - Saturday January 30' / '<Venue>, <City>'
        venue_line = None
        for i, l in enumerate(lines):
            if l == title and i + 2 < len(lines) and _PAGE_DATES_RE.match(lines[i + 1]):
                dm = _PAGE_DATES_RE.match(lines[i + 1])
                year = int(re.search(r"(20\d\d)$", title).group(1))
                m1 = _MONTHS[dm.group(1).lower()]
                m2 = _MONTHS[dm.group(3).lower()] if dm.group(3) else m1
                page_start, page_end = _iso(year, m1, int(dm.group(2))), _iso(year, m2, int(dm.group(4)))
                if page_start and page_start == shell.get("start_date") and page_end:
                    out["end_date"] = page_end
                venue_line = lines[i + 2]
                desc_from = i + 3
                break
        else:
            desc_from = 0
        place = split_place(venue_line) if venue_line else {}
        menu_place = split_place(shell.get("venue_raw") or "")
        if place.get("city"):
            if menu_place.get("event_format") == "hybrid":
                place["event_format"] = "hybrid"
            place.setdefault("region", menu_place.get("region"))
            out.update({k: v for k, v in place.items() if v})
        elif menu_place:
            out.update({k: v for k, v in menu_place.items() if v})

        text = " | ".join(lines[desc_from: desc_from + 60])
        for l in lines[desc_from:]:
            if re.match(r"(?i)^overview of the latest", l):
                break
            if len(l) >= 90 and not re.match(r"(?i)^(please note|congress available|secure your spot|expand your network)", l):
                l = l if len(l) <= 400 else (l[:400].rsplit(". ", 1)[0] + "." if ". " in l[:400] else l[:397] + "...")
                out["description"] = with_title_token(l, title)
                break
        return out
