"""AAOS (American Academy of Orthopaedic Surgeons): Annual Meeting + live/virtual courses, family subclass.

Optimizely CMS, server-rendered. Courses: the three category pages (virtual-courses / skills-courses / seminars) hold
`card--basic` links with a `super-title` date that carries the year ("Nov. 5-7, 2026", "OCt. 8-9, 2026 Pre-Recording
Available"), unioned by URL (the Workers' Comp and Expert Witness courses share one page). The course page header says
"Dec. 4-5, 2026, Rosemont, IL" and fees live on the same-site `<course>/registration/` sub-page as `label` / `$2,599`
line pairs. Annual Meeting: `/annual/attend/future-meetings/` lists the next two meetings ("Las Vegas, Nevada—2027" then
"Wednesday, March 3 – Saturday, March 6 | Venetian Convention & Expo Center"); registration (and so fees) only opens in
November, so no tiers until then.
"""
import html as _html
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from logger import logger

from .http_fetch import fetch_html
from .tribe_events import html_to_lines
from .wordpress_generic import WordPressGenericExtractor, dedupe_consecutive, find_dates, _iso, _mon

_ROOT = "https://www.aaos.org"
_CATEGORY_PAGES = ["/education/courses/virtual-courses/", "/education/courses/skills-courses/", "/education/courses/seminars/"]
_CARD_RE = re.compile(r'(?is)<a class="card--basic"[^>]*href="([^"]*)".*?super-title">\s*(.*?)\s*</p>.*?card-title">\s*(.*?)\s*</p>')
_MEETING_RE = re.compile(r"([A-Z][A-Za-z .]+?,\s*[A-Z][A-Za-z ]+?)\s*[—–-]\s*(20\d\d)\s*\n?\s*(?:[A-Za-z]+day,\s*)?([A-Z][a-z]+)\s+(\d{1,2})\s*[–-]\s*(?:[A-Za-z]+day,\s*)?(?:([A-Z][a-z]+)\s+)?(\d{1,2})\s*\|\s*([^\n]+)")
_TXT = lambda s: re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()   # noqa: E731


class AaosExtractor(WordPressGenericExtractor):
    LISTING_URL = _ROOT + "/education/courses/"
    SOCIETY = "AAOS"
    DEFAULT_SPECIALTY = "Orthopaedics"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "USD"

    # ---- listing -----------------------------------------------------------
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today().isoformat()
        shells: List[Dict[str, Any]] = []
        seen = set()
        for path in _CATEGORY_PAGES:
            html = self._fetch(_ROOT + path)
            for href, sup, title in _CARD_RE.findall(html or ""):
                url = _ROOT + _html.unescape(href).rstrip("/") + "/"
                if url in seen:
                    continue
                dr = find_dates(re.sub(r"(?i)^(\w{2,3})\.", lambda m: m.group(1).title() + ".", _TXT(sup)))   # "OCt." -> "Oct."
                if not dr:
                    continue
                s, e = dr[0]["start"], dr[0]["end"]
                if (e or s) < today:
                    continue
                seen.add(url)
                shells.append({"title": _TXT(title), "booking_url": url, "source_url": url, "start_date": s, "end_date": e or s,
                               "start_time": None, "venue_raw": "Virtual" if "virtual" in path else None, "category": "Courses"})
            time.sleep(self.REQUEST_GAP_S)
        # annual meetings (next two)
        fm = self._fetch(_ROOT + "/annual/attend/future-meetings/") or ""
        text = "\n".join(dedupe_consecutive(html_to_lines(fm)))
        for m in _MEETING_RE.finditer(text):
            place, year, m1, d1, m2, d2, venue = m.groups()
            try:
                s, e = _iso(int(year), _mon(m1), int(d1)), _iso(int(year), _mon(m2 or m1), int(d2))
            except KeyError:
                continue
            if not s or (e or s) < today:
                continue
            url = _ROOT + "/annual/" if year == str(date.today().year + 1) or not any(x["title"].endswith("Annual Meeting") for x in shells) else f"{_ROOT}/annual/attend/future-meetings/#{year}"
            shells.append({"title": f"AAOS {year} Annual Meeting", "booking_url": url, "source_url": url, "start_date": s, "end_date": e,
                           "start_time": None, "venue_raw": f"{venue.strip()}, {place.strip()}", "category": "Annual Meeting"})
        logger.info(f"AAOS listing: {len(shells)} shells")
        return shells or None

    # ---- detail ------------------------------------------------------------
    @staticmethod
    def _reg_tiers(lines: List[str]) -> List[Dict[str, Any]]:
        """Registration sub-page: a '...Fees' heading, then 'label' (may wrap over two lines) / '$1,234' pairs."""
        tiers, section, label, seen = [], "Registration", [], set()
        for l in lines:
            if re.match(r"(?i)^cancellation policy", l):
                break
            if re.match(r"^\$\s?\d[\d,]*(?:\.\d\d)?$", l):
                if label:
                    name = re.sub(r"\s+", " ", " ".join(label)).strip(" ,")
                    key = (section, name)
                    if key not in seen:
                        seen.add(key)
                        tiers.append({"tier_label": f"{section} \u00b7 {name}", "price_gbp": float(re.sub(r"[^\d.]", "", l)), "currency": "USD",
                                      "is_early_bird": False, "early_bird_deadline": None})
                label = []
            elif re.match(r"(?i)^[\w ,&'/+-]{0,70}\bfees$", l) and len(l) < 70:
                section, label = l, []
            elif section and not re.match(r"(?i)^(register now|special discounts?|add\b|bundle\b)|\$", l):
                label = label + [l] if label and label[-1].endswith(",") else [l]
        return tiers

    def detail_from_html(self, html: str, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out = super().detail_from_html(html, shell, llm_call)
        is_meeting = shell.get("category") == "Annual Meeting"
        out["event_type"] = "conference" if is_meeting else "course"
        if "#" in shell["booking_url"]:
            out.pop("description", None)          # the shared future-meetings page blurb is not about this meeting
        out.pop("venue_name", None) if not is_meeting else None
        if is_meeting:
            parts = [p.strip() for p in (shell.get("venue_raw") or "").split(",") if p.strip()]
            if len(parts) >= 3:
                out["venue_name"], out["city"], out["region"] = parts[0], parts[1], "United States"
                out["event_format"] = "in_person"
            fees = None
        else:
            lines = dedupe_consecutive(html_to_lines(re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1\s*>", " ", html)))
            loc = next((m for m in (re.match(r"^[A-Z][a-z]+\.? [^,|]*\d[^,|]*, 20\d\d(?:,|\s*\|)\s*([A-Z][A-Za-z .]+), ([A-Z]{2})$", l) for l in lines[:80]) if m), None)
            if loc:
                out["city"], out["region"], out["event_format"] = loc.group(1), "United States", "in_person"
                out.pop("event_format") if shell.get("venue_raw") == "Virtual" else None
            if shell.get("venue_raw") == "Virtual":
                out["event_format"] = "online"
                out.pop("city", None)
                out.pop("region", None)
            # fees: same-site Registration sub-page
            if shell["booking_url"].rstrip("/").rsplit("/", 1)[-1]:
                time.sleep(self.REQUEST_GAP_S)
                reg = fetch_html(shell["booking_url"] + "registration/", browser=getattr(self, "browser", None))
                if reg:
                    rl = dedupe_consecutive(html_to_lines(re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1\s*>", " ", reg)))
                    tiers = self._reg_tiers(rl)
                    if tiers:
                        out["pricing_tiers"] = tiers
        return out
