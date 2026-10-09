"""EUSEM (European Society for Emergency Medicine).

eusem.org is a Joomla/K2 site with no structured events list: `/events` is a news feed (dates are
publication dates), the RSEvents calendar at `/courses-and-events` is empty, and every course is a
free-text article under `/education/courses-traineeships/<slug>` linked from the site menu. So the
listing walks those article links, reads each page once and keeps the ones that state an upcoming
date. The Congress lives on eusemcongress.org (2026 edition is over; no 2027 page yet).
"""
import difflib
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from logger import logger

from .http_fetch import fetch_html
from .tribe_events import html_to_lines
from .wordpress_generic import WordPressGenericExtractor, clip_venue, pick_event_dates, split_location

_ROOT = "https://eusem.org"
_COURSE_LINK_RE = re.compile(r"""href=["'](/education/courses-traineeships/[a-z0-9][^"'#?]*)["']""", re.I)
_NOT_EVENT_RE = re.compile(r"endorsement-policy|volunteering|refresher-courses|em-monthly|eusemcast", re.I)
_DEADLINE_LINE_RE = re.compile(r"deadline|register|registration|closes?\b|closed|opens?\b|abstract|apply|application|before|until|webinar", re.I)
_TITLE_RE = re.compile(r"(?is)<title>(.*?)</title>")
_FEE_HEAD_RE = re.compile(r"^(?:course\s+)?fees?\s*:?$", re.I)
_FEE_ROW_RE = re.compile(r"([A-Za-z][A-Za-z0-9 &/+'-]{1,60}?)\s*:\s*(?:€\s*([\d.,]+)|([\d.,]+)\s*(?:EUR|€))", re.I)
_VENUE_STOP_RE = re.compile(r"contact number|\+\d|faculty|course fees|registration|programme|how to get|accommodation|^dates?\b", re.I)


class EusemExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://eusem.org/"
    SOCIETY = "EUSEM"
    DEFAULT_SPECIALTY = "Emergency Medicine"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "EUR"
    MAX_PAGES = 1

    @staticmethod
    def _page_dates(lines: List[str]) -> Optional[tuple]:
        """First stated event date in the article: a line after a 'Date(s)' label, else the first
        non-deadline line carrying a full date."""
        for i, ln in enumerate(lines[:80]):
            if re.match(r"^dates?\s*:?$", ln, re.I) and i + 1 < len(lines):
                d = pick_event_dates(lines[i + 1])
                if d:
                    return d
        for ln in lines[:80]:
            if _DEADLINE_LINE_RE.search(ln) or len(ln) > 400 and not re.search(r"\b(?:from|taking place|will be)\b", ln, re.I):
                continue
            d = pick_event_dates(ln)
            if d:
                return d
        return None

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        home = self._fetch(self.LISTING_URL)
        if not home:
            return None
        paths: List[str] = []
        for m in _COURSE_LINK_RE.finditer(home):
            p = m.group(1).rstrip("/")
            if p not in paths and not _NOT_EVENT_RE.search(p):
                paths.append(p)
        today = date.today().isoformat()
        shells: List[Dict[str, Any]] = []
        for p in paths[:25]:
            url = _ROOT + p
            html = fetch_html(url, browser=getattr(self, "browser", None))
            time.sleep(self.REQUEST_GAP_S)
            if not html:
                continue
            lines = html_to_lines(re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1\s*>", " ", html))
            dates = self._page_dates(lines)
            if not dates or (dates[1] or dates[0]) < today:
                continue
            tm = _TITLE_RE.search(html)
            title = re.sub(r"^\s*Eusem\s*-\s*", "", re.sub(r"\s+", " ", tm.group(1))).strip() if tm else ""
            h1 = next((l for l in lines[:8] if 3 < len(l) < 120 and l.lower() not in ("home", "education", "courses & traineeships")), "")
            title = title or h1
            if not title:
                continue
            sold_out = bool(re.search(r"fully booked|sold out|course is full", " ".join(lines[:60]), re.I))
            shells.append({"title": title, "booking_url": url, "source_url": url, "start_date": dates[0],
                           "end_date": dates[1], "start_time": None, "venue_raw": None, "category": None,
                           "is_sold_out": sold_out})                       # llm_agent's merge reads is_sold_out from the shell only
        logger.info(f"EUSEM: {len(shells)} dated course pages of {len(paths)} linked")
        return shells or None

    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out = super().detail_from_html(html, shell, llm_call)
        lines = html_to_lines(re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1\s*>", " ", html))
        # fee rows under a bare "Fee"/"Course fees" heading: 'Label: 650 EUR' / 'Physician: €350 Nurse: €180'
        for i, ln in enumerate(lines):
            if not _FEE_HEAD_RE.match(ln):
                continue
            tiers, seen = [], set()
            for row in lines[i + 1:i + 8]:
                for m in _FEE_ROW_RE.finditer(row):
                    label, amt = m.group(1).strip(), (m.group(2) or m.group(3)).replace(",", "")
                    try:
                        price = float(amt)
                    except ValueError:
                        continue
                    if label.lower() not in seen:
                        seen.add(label.lower())
                        tiers.append({"tier_label": f"Fees \u00b7 {label}", "price_gbp": price, "currency": "EUR",
                                      "is_early_bird": False, "early_bird_deadline": None})
            if len(tiers) > len(out.get("pricing_tiers") or []):
                out["pricing_tiers"] = tiers
            break
        # "Venue - Hotel Park, Cesta Svobode 15, 4260 Bled, Slovenia, contact number: ..." (one line) or a "Venue" label then lines
        vtxt = None
        for i, ln in enumerate(lines):
            m = re.match(r"^venue\s*[-:\u2013]\s*(.+)$", ln, re.I)
            if m:
                vtxt = m.group(1)
            elif ln.lower().rstrip(":- ") == "venue":
                parts: List[str] = []
                for nxt in lines[i + 1:i + 7]:
                    if nxt.strip(" -,") == "":
                        continue
                    if _VENUE_STOP_RE.search(nxt) and _VENUE_STOP_RE.search(nxt).start() == 0:
                        break
                    parts.append(nxt.strip(" ,"))
                vtxt = ", ".join(parts)
            if vtxt:
                break
        if vtxt:
            stop = _VENUE_STOP_RE.search(vtxt)
            vtxt = re.sub(r"\b\d{4}\s+(?=[A-Z])", "", vtxt[:stop.start()] if stop else vtxt).strip(" ,")
            v, c, k = split_location(vtxt)
            if v and (not out.get("venue_name") or out["venue_name"].isupper()):
                out["venue_name"] = clip_venue(v)
            if c and not out.get("city"):
                out["city"] = c
            if k and not out.get("region"):
                out["region"] = k
        if True:
            m = re.search(r"\bin ([A-Z][\w\u00c0-\u017f]+(?: [A-Z][\w\u00c0-\u017f]+)?), ([A-Z][a-z]+)(?:,)? from \d", " ".join(lines[:60]))
            if m and (not out.get("city") or difflib.SequenceMatcher(None, out["city"].lower(), m.group(1).lower()).ratio() > 0.8):
                out["city"], out["region"] = m.group(1), out.get("region") or m.group(2)   # intro sentence beats a typo'd address ("Bilboa")
        return out
