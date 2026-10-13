"""Interface Aesthetics (UK injectables / aesthetics training) courses: family subclass with a course+sessions detail.

`/courses/` links to ~12 course pages (`/courses/<slug>/`). A course page has an "Upcoming Dates" block, rendered twice
(mobile + desktop, plus a "View more upcoming dates" repeat), each row being "Location/Date: London 17/10/2026",
"Availability: FULL | 4 places", "Price: From £1,150.00". Courses with no dates ("Enquire" only: complications
masterclass, 1-to-1, mentorship, RPEL diploma) are dropped at listing time, because the listing page itself shows no dates.
One parent row per course (event_type='course') with a `sessions` list, like alsg.py. Fees are per session ("From" the
published price), CPD points are stated as "8 CPD points" in the course bullets.
"""
import html as _html
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Page

from .http_fetch import fetch_html
from .tribe_events import html_to_lines
from .wordpress_generic import WordPressGenericExtractor, dedupe_consecutive
from logger import logger

_COURSE_HREF_RE = re.compile(r"""href=["'](https://interfaceaesthetics\.co\.uk/courses/[a-z0-9-]+/)["']""", re.I)
_SESSION_RE = re.compile(r"^([A-Z][A-Za-z .'-]{2,30}?)\s+(\d{2})/(\d{2})/(\d{4})$")
_AVAIL_RE = re.compile(r"^(?:FULL|SOLD OUT|(\d+)\s+places?(?:\s+left)?)$", re.I)
_CHROME = re.compile(r"(?is)<(script|style|svg|noscript|nav|header|footer|template)\b.*?</\1\s*>")


def _cpd(text: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)[\s\xa0]+CPD points?", text)
    return float(m.group(1)) if m else None


class InterfaceAestheticsExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://interfaceaesthetics.co.uk/courses/"
    SOCIETY = "Interface Aesthetics"
    DEFAULT_SPECIALTY = "Aesthetic & Cosmetic Medicine"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"
    DEFAULT_EVENT_TYPE = "course"
    MAX_COURSES = 30

    # ---- parsing -----------------------------------------------------------
    @staticmethod
    def parse_sessions(html: str) -> List[Dict[str, Any]]:
        lines = dedupe_consecutive(html_to_lines(_CHROME.sub(" ", html)))
        out: List[Dict[str, Any]] = []
        seen = set()
        for i, l in enumerate(lines):
            m = _SESSION_RE.match(l.strip())
            if not m:
                continue
            iso = f"{m.group(4)}-{m.group(3)}-{m.group(2)}"
            try:
                date.fromisoformat(iso)
            except ValueError:
                continue
            tail = lines[i + 1: i + 8]
            av = next((t for t in tail if _AVAIL_RE.match(t.strip())), None)
            if av is None:
                continue                                              # a date in running prose, not a session row
            loc = m.group(1).strip()
            if (loc, iso) in seen:
                continue
            seen.add((loc, iso))
            price = None
            for j, t in enumerate(tail):
                if re.search(r"(?i)^(?:from\s*)?£$|^from$", t.strip()) and j + 1 < len(tail):
                    pm = re.match(r"^£?\s?(\d[\d,]*(?:\.\d{1,2})?)$", tail[j + 1].strip())
                    if pm:
                        price = float(pm.group(1).replace(",", ""))
                        break
                pm = re.match(r"^(?:from\s*)?£\s?(\d[\d,]*(?:\.\d{1,2})?)$", t.strip(), re.I)
                if pm:
                    price = float(pm.group(1).replace(",", ""))
                    break
            full = bool(re.match(r"(?i)full|sold out", av.strip()))
            pl = re.match(r"(\d+)", av.strip())
            out.append({"city": loc, "start_date": iso, "availability_status": "sold_out" if full else "available",
                        "spots_left": int(pl.group(1)) if pl else None, "_price_gbp": price})
        out.sort(key=lambda s: (s["start_date"], s["city"]))
        return out

    # ---- listing -----------------------------------------------------------
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = self._fetch(self.LISTING_URL)
        if not html:
            return None
        urls: List[str] = []
        for u in _COURSE_HREF_RE.findall(html):
            if u not in urls and u.rstrip("/") != self.LISTING_URL.rstrip("/"):
                urls.append(u)
        today = date.today().isoformat()
        shells: List[Dict[str, Any]] = []
        for u in urls[:self.MAX_COURSES]:
            time.sleep(self.REQUEST_GAP_S)
            body = fetch_html(u, browser=getattr(self, "browser", None))
            if not body:
                logger.warning(f"{self.SOCIETY}: course page fetch failed {u}")
                continue
            upcoming = [s for s in self.parse_sessions(body) if s["start_date"] >= today]
            if not upcoming:
                continue
            title = self._title(body)
            shells.append({"title": title, "booking_url": u, "source_url": u, "start_date": upcoming[0]["start_date"],
                           "end_date": upcoming[0]["start_date"], "venue_raw": upcoming[0]["city"], "category": "course"})
        logger.info(f"{self.SOCIETY}: {len(shells)} courses with upcoming dates (of {len(urls)} course pages)")
        return shells or None

    @staticmethod
    def _title(html: str) -> str:
        m = re.search(r"(?is)<h1\b[^>]*>(.*?)</h1\s*>", html)
        t = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip() if m else ""
        if not t:
            m = re.search(r"(?is)<title>(.*?)</title>", html)
            t = re.sub(r"\s*\|.*$", "", re.sub(r"\s+", " ", _html.unescape(m.group(1)))).strip() if m else ""
        return t

    # ---- detail ------------------------------------------------------------
    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        today = date.today().isoformat()
        sessions = [s for s in self.parse_sessions(html) if s["start_date"] >= today]
        lines = dedupe_consecutive(html_to_lines(_CHROME.sub(" ", html)))
        text = " ".join(lines)
        title = self._title(html) or shell.get("title") or ""
        desc = self._description(html, lines, title)
        out: Dict[str, Any] = {
            "conference_name": title, "society": self.SOCIETY, "event_type": "course", "specialty": self.DEFAULT_SPECIALTY,
            "event_format": "in_person", "is_sold_out": bool(sessions) and all(s["availability_status"] == "sold_out" for s in sessions),
        }
        if desc:
            out["description"] = desc
        pts = _cpd(text)
        if pts:
            out["cpd_points"], out["cpd_accredited"] = pts, True
        if sessions:
            first = sessions[0]
            cities = {s["city"] for s in sessions}
            out["start_date"] = out["end_date"] = first["start_date"]
            out["city"] = first["city"] if len(cities) == 1 else None
            out["region"] = "United Kingdom"
            out["sessions"] = [{"_idx": i, "start_date": s["start_date"], "end_date": None, "start_time": None,
                                "duration_text": None, "availability_status": s["availability_status"], "spots_left": s["spots_left"],
                                "booking_url": shell.get("booking_url"), "venue_name": None, "city": s["city"],
                                "region": "United Kingdom", "notes": None, "_price_gbp": s["_price_gbp"]}
                               for i, s in enumerate(sessions)]
            out["pricing_tiers"] = [{"tier_label": "Course fee · From", "price_gbp": s["_price_gbp"], "currency": "GBP",
                                     "is_early_bird": False, "early_bird_deadline": None, "_session_idx": i}
                                    for i, s in enumerate(sessions) if s["_price_gbp"] is not None]
        if not out.get("city"):
            out.pop("city", None)
        return out

    @staticmethod
    def _description(html: str, lines: List[str], title: str) -> Optional[str]:
        md = re.search(r"""(?is)<meta[^>]+property=["']og:description["'][^>]+content=["']([^"']+)["']""", html) \
            or re.search(r"""(?is)<meta[^>]+name=["']description["'][^>]+content=["']([^"']+)["']""", html)
        if md:
            d = re.sub(r"\s+", " ", _html.unescape(md.group(1))).strip()
            if len(d) >= 60:
                return d[:600]
        tl = re.sub(r"\W+", "", title.lower())
        idx = next((i for i, l in enumerate(lines) if re.sub(r"\W+", "", l.lower()) == tl), -1)
        for l in lines[idx + 1: idx + 14]:
            if len(l) >= 80 and not re.search(r"(?i)secure your spot|check availability|cookie", l):
                return l[:600]
        return None
