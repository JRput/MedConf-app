"""EADV (European Academy of Dermatology and Venereology) events: family subclass with a flat-page listing.

`/events/calendar/` is an Elementor page of "partner" meetings, not EADV's own: each card is an image link (target=_blank, to
the partner congress site) followed by `<p><strong>Title</strong></p><p>City, Country<br/>23-25 April 2026</p>`; cards are
repeated in hidden responsive variants and sorted by year (past ones stay on the page). No detail pages on eadv.org, so
shells are complete and booking_url is the partner site; fees live there (organiser_url is set for the explorer).
EADV's own meetings (the Spring Symposium and the autumn Congress) have dedicated pages `/symposium/` and `/congress/`
whose <title> reads "EADV Symposium | Dresden 20-22 May 2027 | eadv.org"; they are added as shells when still upcoming
(the Congress page still shows Vienna 2026, which is past). The venue comes from `<page>/about/the-venue/`. The
registration page shows only the previous year's fees ("information about the Symposium 2027 will be published soon"),
so no fees are stored for them. A UEMS diploma examination card is not a CME event and is skipped.
"""
import html as _html
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Page

from .http_fetch import fetch_html
from .tribe_events import html_to_lines
from .wordpress_generic import WordPressGenericExtractor, pick_event_dates, _iso, _mon, _meta
from logger import logger

_CARD_SPLIT_RE = re.compile(r"""(?is)<a href="(https?://[^"]+)" target="_blank" rel="nofollow noopener">""")
_TEXT_RE = re.compile(r"(?is)<p><strong>(.*?)</strong></p>\s*<p>(.*?)</p>")
_OWN_PAGES = ("https://eadv.org/symposium/", "https://eadv.org/congress/")
_MON_RE = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"


def _txt(frag: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", frag))).replace("\xa0", " ").strip()


class EadvExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://www.eadv.org/events/calendar/"
    SOCIETY = "EADV"
    DEFAULT_SPECIALTY = "Dermatology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "EUR"
    MAX_FUTURE_DAYS = 600

    # ---- listing -----------------------------------------------------------
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = self._fetch(self.LISTING_URL)
        if not html:
            return None
        today = date.today()
        shells: List[Dict[str, Any]] = []
        seen = set()
        parts = _CARD_SPLIT_RE.split(html)                        # [pre, href1, seg1, href2, seg2, ...]
        for href, seg in zip(parts[1::2], parts[2::2]):
            tm = _TEXT_RE.search(seg[:6000])
            if not tm:
                continue
            title = _txt(re.sub(r"(?is)<strong>\s*</strong>", "", tm.group(1)))
            lines = [x for x in (_txt(p) for p in re.split(r"(?i)<br\s*/?>", re.sub(r"(?is)<strong>.*", "", tm.group(2)))) if x]
            if not title or not lines or re.search(r"(?i)\bexamination\b", title):
                continue
            d = self._dates(lines[-1], href, today)
            if not d or d[1] < today.isoformat() or (date.fromisoformat(d[0]) - today).days > self.MAX_FUTURE_DAYS:
                continue
            key = (re.sub(r"\W+", "", title.lower()), d[0])
            if key in seen:
                continue
            seen.add(key)
            place = lines[0] if len(lines) > 1 else None
            remote = any(re.search(r"(?i)\bremote\b|\bonline\b|\bvirtual\b", x) for x in lines[1:-1])
            url = _html.unescape(href)
            shells.append({"title": title, "booking_url": url, "source_url": url, "start_date": d[0], "end_date": d[1],
                           "venue_raw": place, "category": "conference", "_place": place, "_remote": remote, "_partner": True})
        shells += self._own_events(today, seen)
        logger.info(f"{self.SOCIETY}: {len(shells)} upcoming events ({sum(1 for s in shells if s.get('_partner'))} partner, rest EADV's own)")
        return shells or None

    @staticmethod
    def _dates(line: str, href: str, today: date):
        line = line.replace("–", "-")
        d = pick_event_dates(line, today)
        if d:
            return d
        m = re.match(rf"(\d{{1,2}})\s*-\s*(\d{{1,2}})\s+({_MON_RE})$", line.strip())      # "20-22 May" (year only in the URL)
        ym = re.search(r"(20\d\d)", href)
        if m and ym:
            mon = _mon(m.group(3))
            return _iso(int(ym.group(1)), mon, int(m.group(1))), _iso(int(ym.group(1)), mon, int(m.group(2)))
        return None

    def _own_events(self, today: date, seen) -> List[Dict[str, Any]]:
        out = []
        for url in _OWN_PAGES:
            time.sleep(self.REQUEST_GAP_S)
            html = fetch_html(url, browser=getattr(self, "browser", None))
            tm = re.search(r"(?is)<title>(.*?)</title>", html or "")
            if not tm:
                continue
            t = _txt(tm.group(1))
            m = re.match(r"(EADV [A-Za-z ]+?)\s*(\d{4})?\s*\|\s*([^|]+?)\s+(\d{1,2})(?:\s+(" + _MON_RE + r"))?\s*-\s*(\d{1,2})\s+(" + _MON_RE + r")(?:\s+(\d{4}))?\s*\|", t)
            if not m:
                continue
            name, ytitle, city, d1, m1, d2, m2, y = m.groups()
            year = int(y or ytitle or 0)
            if not year:
                continue
            s = _iso(year, _mon(m1 or m2), int(d1))
            e = _iso(year, _mon(m2), int(d2))
            if not s or not e or e < today.isoformat():
                continue                                        # e.g. the Congress page still shows Vienna 2026 (past)
            title = f"{name} {year}" if not re.search(r"\d{4}", name) else name
            if (re.sub(r"\W+", "", title.lower()), s) in seen:
                continue
            out.append({"title": title, "booking_url": url, "source_url": url, "start_date": s, "end_date": e, "venue_raw": city,
                        "category": "conference", "_place": city, "_remote": False, "_partner": False, "_venue_page": url + "about/the-venue/"})
        return out

    # ---- detail ------------------------------------------------------------
    def extract_detail(self, page: Page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        html = ""
        if page is not None:
            try:
                html = page.content()
            except Exception:  # noqa: BLE001
                html = ""
        return self.detail_from_html(html, shell, llm_call)

    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        title = shell["title"]
        out: Dict[str, Any] = {"conference_name": title, "society": self.SOCIETY, "event_type": "conference",
                               "start_date": shell["start_date"], "end_date": shell["end_date"], "specialty": self.DEFAULT_SPECIALTY}
        place = shell.get("_place") or ""
        parts = [p.strip() for p in place.split(",") if p.strip()]
        venue = None
        if shell.get("_venue_page"):
            vh = fetch_html(shell["_venue_page"], browser=getattr(self, "browser", None)) or ""
            lines = html_to_lines(re.sub(r"(?is)<(script|style|svg|noscript|nav|header|footer)\b.*?</\1\s*>", " ", vh))
            ai = next((i for i, l in enumerate(lines) if re.match(r"^[\w .'-]+\d{4,5}\s+[\w-]+,\s*[A-Za-z ]+$", l) or re.search(r"\b\d{4,5}\b.*,\s*(?:Germany|Austria|France|Spain|Italy|Portugal|Greece|Czech Republic)$", l)), None)
            if ai and ai > 0:
                venue = lines[ai - 1]
                cm = re.search(r"\d{4,5}\s+([^,]+?)(?:-[A-Za-z]+)?,\s*([A-Za-z ]+)$", lines[ai])
                if cm:
                    parts = [cm.group(1).strip(), cm.group(2).strip()]
            md = _meta(vh, "og:description")
            if md:
                out["description"] = _html.unescape(md)[:600]
        if parts:
            out["city"] = parts[0]
            if len(parts) > 1:
                out["region"] = "United Kingdom" if parts[-1] == "UK" else parts[-1]
            out["event_format"] = "hybrid" if shell.get("_remote") else "in_person"
        elif shell.get("_remote"):
            out["event_format"] = "online"
        if venue:
            out["venue_name"] = venue
        if not out.get("description"):
            md = None
            if html and shell.get("_partner"):
                md = re.sub(r"\s+", " ", _html.unescape(_meta(html, "og:description") or _meta(html, "description") or "")).strip()
            if md and len(md) >= 60 and not re.search(r"(?i)cookie|javascript|just a moment|enable", md):
                out["description"] = md[:600]
            else:
                where = f" in {place}" if place else ""
                out["description"] = (f"{title}{where}. Dermatology meeting listed on the EADV events calendar." if shell.get("_partner")
                                      else f"{title}{where}: EADV's annual dermatology and venereology meeting.")
        if shell.get("_partner"):
            out["organiser_url"] = shell["booking_url"]               # fees / registration are on the partner congress site
        return out
