"""AAN (American Academy of Neurology) upcoming conferences: bespoke extractor, no LLM.

`aan.com/events/upcoming-events` is server-rendered. One `<h4><a href=series-page>` per conference series, then `<p>` blocks
of "<strong>City, ST and online</strong><br>May 1-5, 2027<br>..." where a place line applies to every date line under it
(Fall Conference lists 2027 and 2028 under one "Las Vegas and online"). The series pages carry the NEXT edition's header
("May 1-5 | Washington, DC, and Online") or, once an edition is over, a thank-you for the PAST edition ("October 9-11 |
Las Vegas and Online" in 2026), so a page's text is only trusted when its header date equals the shell's month/day.
Registration opens in November for the Annual Meeting; no fee is public, so `pricing_tiers` stays empty.

NO AI: aan.com/robots.txt disallows GPTBot, ClaudeBot, anthropic-ai and the other AI agents, and the Terms of Use forbid
feeding AAN content into any AI model without written permission. Nothing from this site is ever sent to `llm_call`;
description and specialty are deterministic (meta description / fixed specialty).
"""
import html as _html
import re
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Page

from logger import logger

from .base import BaseExtractor
from .http_fetch import fetch_html
from .tribe_events import html_to_lines
from .wordpress_generic import find_dates

_ROOT = "https://www.aan.com"
_LISTING = _ROOT + "/events/upcoming-events"
_SOCIETY = "American Academy of Neurology (AAN)"
_MAX_FUTURE_DAYS = 550                       # 18 months; later editions are save-the-dates with no page behind them
_DATE_LINE_RE = re.compile(r"^[A-Z][a-z]+\.? \d{1,2}(?:\s*[–—-]\s*\d{1,2})?,\s*\d{4}$")
_TITLES = {"annual meeting": "AAN Annual Meeting", "fall conference": "AAN Fall Conference",
           "app conference": "AAN Advanced Practice Provider (APP) Conference", "autoimmune neurology conference": "AAN Autoimmune Neurology Conference"}


def _txt(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag))).replace("\xa0", " ").strip()


def parse_listing(html: str) -> List[Dict[str, Any]]:
    """Listing HTML -> one dict per (series, edition): series, url, start, end, place, hybrid (pure)."""
    out: List[Dict[str, Any]] = []
    for sec in re.split(r"(?i)<hr\b[^>]*>", html or ""):
        h = re.search(r'(?is)<h4>\s*<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>\s*</h4>', sec)
        if not h:
            continue
        url, series = h.group(1), _txt(h.group(2))
        for p in re.findall(r"(?is)<p>(.*?)</p>", sec[h.end():]):
            place = None
            for ln in [_txt(x) for x in re.split(r"(?i)<br\s*/?>|</strong>", p)]:
                if not ln:
                    continue
                if _DATE_LINE_RE.match(ln):
                    ds = find_dates(ln)
                    if ds:
                        out.append({"series": series, "url": url, "start": ds[0]["start"], "end": ds[0]["end"], "place": place})
                else:
                    place = ln
    return out


def split_place(place: Optional[str]) -> Dict[str, Any]:
    """"Washington, DC, and online" -> city "Washington, DC", hybrid. "Las Vegas and online, ahead of the Fall Conference" -> Las Vegas."""
    if not place:
        return {}
    hybrid = bool(re.search(r"(?i)\band online\b|\blive online\b", place))
    city = re.split(r"(?i),?\s+and online|,\s*ahead of", place)[0].strip(" ,")
    return {"city": city or None, "event_format": "hybrid" if hybrid else "in_person"}


class AanExtractor(BaseExtractor):
    DEFAULT_SPECIALTY = "Neurology"

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = fetch_html(_LISTING, browser=getattr(self, "browser", None))
        if not html or len(html) < 2000:
            return None
        today = date.today()
        shells: List[Dict[str, Any]] = []
        seen = set()
        for r in parse_listing(html):
            start, end = date.fromisoformat(r["start"]), date.fromisoformat(r["end"])
            if end < today:
                continue
            if (start - today).days > _MAX_FUTURE_DAYS:
                logger.info(f"AAN: {r['series']} {start.year} beyond the 18-month horizon, skipped")
                continue
            title = f"{_TITLES.get(r['series'].lower(), 'AAN ' + r['series'])} {start.year}"
            url = f"{r['url'].split('#')[0]}#{start.year}"
            if url in seen:
                continue
            seen.add(url)
            shells.append({"title": title, "booking_url": url, "source_url": url, "start_date": r["start"], "end_date": r["end"],
                           "start_time": None, "venue_raw": None, "category": None, "_place": r["place"]})
        logger.info(f"AAN: {len(shells)} upcoming shells")
        return shells or None

    def extract_detail(self, page: Page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        html = page.content() if page is not None else ""
        start, end = shell["start_date"], shell.get("end_date") or shell["start_date"]
        out: Dict[str, Any] = {"society": _SOCIETY, "event_type": "conference", "specialty": self.DEFAULT_SPECIALTY,
                               "start_date": start, "end_date": end, "region": "United States"}
        out.update(split_place(shell.get("_place")))
        body = re.sub(r"(?s)<!--.*?-->", " ", re.sub(r"(?is)<(script|style|svg|noscript|nav|header|footer)\b.*?</\1\s*>", " ", html))
        lines = html_to_lines(body)
        text = " ".join(lines)
        # the page speaks for THIS edition only when its header date ("May 1-5 | Washington, DC, and Online") is this edition's
        s = date.fromisoformat(start)
        e = date.fromisoformat(end)
        hdr = next((l for l in lines if re.match(r"^[A-Z][a-z]+ \d{1,2}(?:\s*[–-]\s*\d{1,2})?\s*\|", l)), "")
        hm = re.match(r"^([A-Z][a-z]+) (\d{1,2})(?:\s*[–-]\s*(\d{1,2}))?\s*\|", hdr)
        same = bool(hm and hm.group(1) == s.strftime("%B") and int(hm.group(2)) == s.day and int(hm.group(3) or hm.group(2)) == e.day)
        if same:
            md = re.search(r"""(?i)<meta\b[^>]*name=["']description["'][^>]*content=["']([^"']*)""", html)
            desc = re.sub(r"\s+", " ", _html.unescape(md.group(1))).strip() if md else ""
            if len(desc) >= 60:
                out["description"] = desc[:600]
        if re.search(r"(?i)accredited by the Accreditation Council for Continuing Medical Education", text):
            out["cpd_accredited"] = True
        return out
