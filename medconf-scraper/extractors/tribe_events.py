"""Shared family helper for WordPress "The Events Calendar" (Tribe Events) sites.

A site that exposes `/wp-json/tribe/events/v1/events` can be onboarded with a
~20-line subclass of `TribeEventsExtractor`:

    class FooExtractor(TribeEventsExtractor):
        API_URL = "https://www.foo.org/wp-json/tribe/events/v1/events"
        SOCIETY = "FOO"
        DEFAULT_SPECIALTY = "Cardiology"      # used when the title classifier misses
        DEFAULT_CURRENCY = "GBP"              # for symbol-less fee lines
        # optional per-site hooks:
        #   skip_event(self, e)               -> True to drop an API record
        #   location_from_text(self, text, shell) -> (venue, city, country) | None
        #   classify_event_type(self, title, cats) -> 'conference'|'course'|'workshop'

Listing (Phase A): paginated API walk (`per_page=50&start_date=today`),
deduped by URL and by (title, start date), upcoming-only, cancelled dropped.
Every request goes through `http_fetch.fetch_html` (httpx first, Playwright
fallback when a runner IP is challenged) with a 3-try retry.

Detail (Phase B): everything comes from the API record carried in the shell,
so `extract_detail` makes no network call. Fees are parsed from the
description text (fee heading followed by `label ... amount` lines), falling
back to Tribe's structured `cost_details`. Description = first real
paragraph; specialty = title classifier, then the subclass default.
"""

import html as _html
import json
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

from playwright.sync_api import Page

from .base import BaseExtractor
from .http_fetch import fetch_html
from .specialty_classifier import classify_specialty
from logger import logger

_CURRENCY_SYMBOLS = {"£": "GBP", "€": "EUR", "$": "USD"}
_CURRENCY_CODES = ("GBP", "EUR", "USD", "CHF", "AUD", "CAD", "HKD", "SGD")
_AMOUNT_RE = re.compile(
    r"(?:(£|€|\$|" + "|".join(_CURRENCY_CODES) + r")\s?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)"
    r"|([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)\s?(" + "|".join(_CURRENCY_CODES) + r")\b)"
)
_FEE_HEADING_RE = re.compile(r"\b(registration fees?|course fees?|fees?|pricing|prices?|ticket prices?|cost)\b", re.I)
_FEE_STOP_RE = re.compile(r"deadline|payments? (?:are|is|can)|register now|book (?:here|now)|terms (?:&|and)", re.I)
_BOILERPLATE_RE = re.compile(
    r"cannot assume any liability|external event|information provided is preliminary|"
    r"subject to change|cookie|privacy policy|all rights reserved|click here|more information is available|"
    r"register now|book here|add to calendar",
    re.I,
)
_COUNTRY_FROM_US_STATE = {"CA", "NY", "TX", "FL", "IL", "MA", "PA", "OH", "GA", "WA", "DC", "NC", "AZ", "CO", "MN", "MO", "TN", "MD", "OR", "NV"}
_USER_AGENT_HEADERS = {"Accept": "application/json, text/html;q=0.8"}


# ── text helpers ────────────────────────────────────────────────────────────

def html_to_lines(fragment: str) -> List[str]:
    """HTML → list of non-empty text lines (block tags become line breaks)."""
    if not fragment:
        return []
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", fragment)
    t = re.sub(r"(?i)<br\s*/?>|</(p|li|tr|div|h[1-6]|td|th|ul|ol|table)>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = _html.unescape(t).replace("\xa0", " ")
    lines = [re.sub(r"[ \t\r]+", " ", ln).strip() for ln in t.split("\n")]
    return [ln for ln in lines if ln]


def html_to_text(fragment: str) -> str:
    return re.sub(r"\s+", " ", " ".join(html_to_lines(fragment))).strip()


def _first_sentences(text: str, limit: int = 600) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    idx = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if idx >= 150:
        return cut[: idx + 1]
    return cut[: limit - 3].rstrip() + "..."


def pick_description(lines: List[str], title: str) -> Optional[str]:
    """First real paragraph: long enough, has sentence punctuation, is not the
    title/date header block, nav strip or a legal disclaimer."""
    title_l = (title or "").lower()
    good: List[str] = []
    for ln in lines:
        if len(ln) < 60 or ln.startswith("*") or not re.search(r"[.!?](\s|$)", ln):
            continue
        if _BOILERPLATE_RE.search(ln):
            continue
        if title_l and ln.lower().startswith(title_l) and not re.search(r"(?:pleased|welcome|join|is a|offers|will)\b", ln, re.I):
            continue
        # "Course Overview Registration Fees Faculty ..." nav strips have no verbs/sentences
        if re.match(r"(?i)^(course overview|overview)\b.*\bfaculty\b", ln):
            continue
        good.append(ln)
        if sum(len(g) for g in good) >= 250:
            break
    if not good:
        return None
    desc = " ".join(good)
    desc = _first_sentences(desc.strip(), 600)
    return desc if len(desc) >= 50 else None


# ── location-from-text helper (shared by sites whose API venue is empty) ────

_TWO_WORD_COUNTRIES = {
    "South Korea", "North Korea", "United Kingdom", "United States", "Czech Republic", "North Macedonia",
    "Saudi Arabia", "New Zealand", "South Africa", "Hong Kong", "Costa Rica", "Sri Lanka", "United Arab",
    "Puerto Rico", "San Marino", "Bosnia and",
}
_US_STATE_NAMES = set(
    "Alabama Alaska Arizona Arkansas California Colorado Connecticut Delaware Florida Georgia Hawaii Idaho Illinois Indiana "
    "Iowa Kansas Kentucky Louisiana Maine Maryland Massachusetts Michigan Minnesota Mississippi Missouri Montana Nebraska "
    "Nevada Ohio Oklahoma Oregon Pennsylvania Tennessee Texas Utah Vermont Virginia Washington Wisconsin Wyoming".split()
) | {"New York", "New Jersey", "New Mexico", "New Hampshire", "North Carolina", "South Carolina", "North Dakota",
     "South Dakota", "Rhode Island", "West Virginia"}
_US_STATE_CODES = {"AL", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "IL", "IN", "IA", "KS", "KY", "LA", "MA", "MD", "MI",
                   "MN", "MO", "NC", "NJ", "NV", "NY", "OH", "OK", "OR", "PA", "SC", "TN", "TX", "UT", "VA", "WA", "WI", "DC"}


def city_country_after_year(text: str) -> Optional[Tuple[str, str]]:
    """Header lines read "<dates> <year> <City>, <Country|State>". Returns
    (city, country) with US states/codes mapped to "United States"."""
    m = re.search(
        r"(?:19|20)\d\d\s+([A-Z][\w .'’-]{2,30}?),\s+([A-Z]{2}\b|[A-Z][a-z]+)(?:\s+([A-Z][a-z]+))?",
        text[:250],
    )
    if not m:
        return None
    city, a, b = m.group(1).strip(), m.group(2), m.group(3)
    tail = f"{a} {b}" if b and (f"{a} {b}" in _TWO_WORD_COUNTRIES or f"{a} {b}" in _US_STATE_NAMES) else a
    if tail in _US_STATE_CODES or tail in _US_STATE_NAMES:
        tail = "United States"
    return city, tail


# ── fees ────────────────────────────────────────────────────────────────────

def _amount_in(line: str, default_currency: str) -> Optional[Tuple[float, str, int]]:
    """(amount, currency, start index of the amount) for the first money token."""
    m = _AMOUNT_RE.search(line)
    if not m:
        return None
    if m.group(1):
        cur = _CURRENCY_SYMBOLS.get(m.group(1), m.group(1))
        raw = m.group(2)
    else:
        cur = m.group(4)
        raw = m.group(3)
    try:
        amt = float(raw.replace(",", ""))
    except ValueError:
        return None
    return amt, cur or default_currency, m.start()


def _clean_label(label: str) -> str:
    label = re.sub(r"[\*†‡]+", "", label)
    label = re.sub(r"^[\s:;\-–—•·]+|[\s:;\-–—•·]+$", "", label)
    label = re.sub(r"\s+", " ", label)
    return label[:90]


def parse_fee_lines(
    lines: List[str],
    *,
    default_currency: str = "GBP",
    max_tiers: int = 30,
) -> List[Dict[str, Any]]:
    """Find a fee heading, then read `label ... amount` rows beneath it.

    Handles both "BAETS members: £225*" (label and amount on one line) and
    "ESP Members (course programme only)" / "EUR 380" (amount on its own line,
    label on the previous one). Footnote lines (start with `*`) are ignored.
    """
    for h_idx, heading in enumerate(lines):
        if len(heading) > 40 or not _FEE_HEADING_RE.search(heading):
            continue
        section = _clean_label(heading).title()
        tiers: List[Dict[str, Any]] = []
        prev_label: Optional[str] = None
        for ln in lines[h_idx + 1: h_idx + 41]:
            if tiers and (len(ln) > 160 or _FEE_STOP_RE.search(ln)):
                break
            if _FEE_STOP_RE.search(ln) and len(ln) < 60:
                break
            if ln.startswith("*"):
                continue
            hit = _amount_in(ln, default_currency)
            if hit:
                amt, cur, pos = hit
                label = _clean_label(ln[:pos]) or (prev_label or "")
                if not label:
                    prev_label = None
                    continue
                tiers.append({
                    "tier_label": f"{section} · {label}",
                    "price_gbp": amt,
                    "currency": cur,
                    "is_early_bird": bool(re.search(r"early[\s-]?bird", label, re.I)),
                    "early_bird_deadline": None,
                })
                prev_label = None
                if len(tiers) >= max_tiers:
                    break
            elif len(ln) <= 110:
                prev_label = ln
            else:
                prev_label = None
        if tiers:
            return tiers
    return []


def tiers_from_cost_details(e: Dict[str, Any], default_currency: str) -> List[Dict[str, Any]]:
    """Tribe's structured cost (usually empty). `cost_details.values` = ['25', '50']."""
    cd = e.get("cost_details") or {}
    vals = cd.get("values") or []
    cur = (cd.get("currency_code") or "").upper() or _CURRENCY_SYMBOLS.get(cd.get("currency_symbol") or "", default_currency)
    tiers: List[Dict[str, Any]] = []
    for v in vals:
        try:
            amt = float(str(v).replace(",", ""))
        except ValueError:
            continue
        tiers.append({"tier_label": "Free" if amt == 0 else "Standard", "price_gbp": amt, "currency": cur,
                      "is_early_bird": False, "early_bird_deadline": None})
    if not tiers and re.search(r"\bfree\b", str(e.get("cost") or ""), re.I):
        tiers.append({"tier_label": "Free", "price_gbp": 0.0, "currency": cur, "is_early_bird": False,
                      "early_bird_deadline": None})
    return tiers


# ── the family base class ───────────────────────────────────────────────────

class TribeEventsExtractor(BaseExtractor):
    API_URL: str = ""                # full URL of /wp-json/tribe/events/v1/events
    SOCIETY: str = ""
    DEFAULT_SPECIALTY: Optional[str] = None
    DEFAULT_CURRENCY: str = "GBP"
    PREFER_DEFAULT_SPECIALTY: bool = False   # single-specialty societies: ignore title rules
    PER_PAGE: int = 50
    MAX_PAGES: int = 10
    REQUEST_GAP_S: float = 1.0

    # ---- hooks -------------------------------------------------------------
    def skip_event(self, e: Dict[str, Any]) -> bool:
        return False

    def location_from_text(self, text: str, shell: Dict[str, Any]) -> Optional[Tuple[Optional[str], Optional[str], Optional[str]]]:
        return None

    def classify_event_type(self, title: str, cats: List[str]) -> str:
        t = (title or "").lower()
        c = " ".join(cats).lower()
        if re.search(r"\b(course|masterclass|master class|training|cadaver|bootcamp|boot camp)\b", t):
            return "course"
        if re.search(r"\b(workshop|webinar|study day|symposium day)\b", t) or "webinar" in c or "workshop" in c:
            return "workshop"
        return "conference"

    # ---- fetching ----------------------------------------------------------
    @staticmethod
    def _parse_json_body(body: str) -> Optional[dict]:
        if not body:
            return None
        try:
            return json.loads(body)
        except ValueError:
            pass
        # Browser fallback wraps JSON in <pre>…</pre> / <html><body>…
        m = re.search(r"(\{.*\})", _html.unescape(re.sub(r"<[^>]+>", "", body)), re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except ValueError:
                return None
        return None

    def _fetch_api_page(self, url: str) -> Optional[dict]:
        for attempt in range(3):
            body = fetch_html(url, browser=getattr(self, "browser", None), headers=_USER_AGENT_HEADERS)
            data = self._parse_json_body(body) if body else None
            if isinstance(data, dict) and "events" in data:
                return data
            logger.warning(f"{self.SOCIETY} Tribe API attempt {attempt + 1}/3 failed for {url}")
            time.sleep(2 * (attempt + 1))
        return None

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today().isoformat()
        base = f"{self.API_URL}?per_page={self.PER_PAGE}&start_date={today}"
        shells: List[Dict[str, Any]] = []
        seen_urls, seen_keys = set(), set()
        total_pages = 1
        page_no = 1
        while page_no <= min(total_pages, self.MAX_PAGES):
            data = self._fetch_api_page(f"{base}&page={page_no}")
            if data is None:
                if page_no == 1:
                    return None
                break
            total_pages = int(data.get("total_pages") or 1)
            for e in data.get("events") or []:
                shell = self._to_shell(e, today)
                if not shell:
                    continue
                key = (re.sub(r"\W+", "", shell["title"].lower()), shell["start_date"])
                if shell["booking_url"] in seen_urls or key in seen_keys:
                    continue
                seen_urls.add(shell["booking_url"])
                seen_keys.add(key)
                shells.append(shell)
            page_no += 1
            if page_no <= min(total_pages, self.MAX_PAGES):
                time.sleep(self.REQUEST_GAP_S)
        logger.info(f"{self.SOCIETY} Tribe API returned {len(shells)} shells")
        return shells or None

    def _to_shell(self, e: Dict[str, Any], today: str) -> Optional[Dict[str, Any]]:
        title = _html.unescape(re.sub(r"<[^>]+>", "", e.get("title") or "")).strip()
        url = (e.get("url") or "").strip()
        if not title or not url:
            return None
        if re.search(r"\b(cancell?ed|postponed)\b", title, re.I) or self.skip_event(e):
            return None
        start = (e.get("start_date") or "")[:10] or None
        end = (e.get("end_date") or "")[:10] or start
        if not start or (end or start) < today:
            return None
        cats = [c.get("name") for c in (e.get("categories") or []) if c.get("name")]
        venue = e.get("venue") if isinstance(e.get("venue"), dict) else {}
        organizer = e.get("organizer") if isinstance(e.get("organizer"), list) and e.get("organizer") else []
        start_time = None
        if not e.get("all_day"):
            m = re.search(r"\b(\d{2}:\d{2}):\d{2}$", e.get("start_date") or "")
            start_time = m.group(1) if m else None
        return {
            "title": title,
            "booking_url": url,
            "source_url": url,
            "start_date": start,
            "end_date": end,
            "start_time": start_time,
            "venue_name": (venue.get("venue") or "").strip() or None,
            "city": (venue.get("city") or "").strip() or None,
            "country": (venue.get("country") or "").strip() or None,
            "province": (venue.get("province") or "").strip() or None,
            "organizer": (organizer[0].get("organizer") if organizer and isinstance(organizer[0], dict) else None),
            "website": (e.get("website") or "").strip() or None,
            "categories": cats,
            "category": cats[0] if cats else None,
            "description_html": e.get("description") or "",
            "cost_raw": e.get("cost") or "",
            "cost_details": e.get("cost_details") or {},
            "image_url": (e.get("image") or {}).get("url") if isinstance(e.get("image"), dict) else None,
        }

    # ---- detail ------------------------------------------------------------
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        title = shell.get("title") or ""
        cats = shell.get("categories") or []
        lines = html_to_lines(shell.get("description_html") or "")
        text = re.sub(r"\s+", " ", " ".join(lines))

        out["event_type"] = self.classify_event_type(title, cats)
        out["society"] = self.SOCIETY

        # Location: API venue first, then per-site text hook
        venue, city, country = shell.get("venue_name"), shell.get("city"), shell.get("country")
        if not (venue or city):
            hit = self.location_from_text(text, shell)
            if hit:
                venue, city, country = hit
        if city and "," in city:
            city = city.split(",")[0].strip()
        if venue and venue.lower() in ("online", "virtual", "webinar"):
            venue = None
        probe = f"{title} {' '.join(cats)} {text[:300]}".lower()
        is_online_word = bool(re.search(
            r"\b(webinar|webcast|zoom|livestream|live[- ]stream|"
            r"virtual (?:event|meeting|conference|congress|course|workshop|session)s?|"
            r"online (?:event|meeting|conference|congress|course|workshop|session|only|webinar)s?)\b", probe))
        if venue or city:
            out["event_format"] = "hybrid" if re.search(r"\bhybrid\b", probe) else "in_person"
            if venue:
                out["venue_name"] = venue
            if city:
                out["city"] = city
            region = country or shell.get("province")
            if region:
                out["region"] = region
        elif is_online_word:
            out["event_format"] = "online"

        # Fees: text first (richer), then Tribe's structured cost
        tiers = parse_fee_lines(lines, default_currency=self.DEFAULT_CURRENCY)
        if not tiers:
            tiers = tiers_from_cost_details({"cost": shell.get("cost_raw"), "cost_details": shell.get("cost_details")},
                                            self.DEFAULT_CURRENCY)
        if tiers:
            out["pricing_tiers"] = tiers

        # Description (deterministic) + specialty (title rule → society default)
        desc = pick_description(lines, title)
        if desc:
            out["description"] = desc
        if self.PREFER_DEFAULT_SPECIALTY and self.DEFAULT_SPECIALTY:
            out["specialty"] = self.DEFAULT_SPECIALTY
        else:
            out["specialty"] = classify_specialty(title) or self.DEFAULT_SPECIALTY
        return out
