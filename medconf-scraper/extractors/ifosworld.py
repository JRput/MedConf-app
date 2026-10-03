# extractors/ifosworld.py
"""
IFOS — International Federation of Oto-Rhino-Laryngological Societies
(ifosworld.org). Wave 2b source.

Site shape: WordPress + The Events Calendar (Tribe) with a public REST API
at /wp-json/tribe/events/v1/events. The site is a *curated aggregator* of
ORL / ENT congresses, courses and endorsed meetings run by many third-party
organisers, so every event carries an `website` (the organiser's own page).
Volume is small (16 upcoming at build time; recon's "~160" was a misread of
the API's 16-page-at-10-per-page paging). The API is slow (~18 s for a full
page) so we ask for 50 per page and walk `total_pages` with a 1 s gap.

The API response already holds everything the thin /event/<slug>/ wrapper
page shows, so extract_detail() works from the shell and never parses HTML.

Quirks handled here:
  * the same real-world meeting is often listed twice (two organisers' posts):
    de-duplicated on (start_date, venue string), keeping the richer record;
  * `venue.city` is frequently empty and the venue string is free text
    ("Occidental Aran Park, Rome, Italy", "Rome, Italy", "Hong Kong");
  * `timezone` is "Europe/Paris" for non-European events — ignored; times
    are only reported when the event is not all-day and not midnight;
  * `cost` is only filled for a minority of events, with a currency code in
    `cost_details` (USD at build time) — no cost means no tiers.
"""

import html as _html
import re
import time
from datetime import date, timedelta
from typing import Dict, Any, Optional, Callable, List

import json
from playwright.sync_api import Page

from .base import BaseExtractor
from .http_fetch import fetch_html
from logger import logger


API_URL = "https://www.ifosworld.org/wp-json/tribe/events/v1/events"
PER_PAGE = 50
MAX_PAGES = 10          # hard safety cap; real total_pages is 1 at build time
FETCH_TRIES = 3
DEFAULT_SPECIALTY = "ENT"   # IFOS is the ORL federation; every listing is ENT

_VENUE_WORDS = re.compile(
    r"(hotel|centre|center|university|park|hall|lab|laborator|charit|institute|"
    r"hospital|congress|plaza|resort|inn\b|college|academy|convention|palace|"
    r"tower|campus|school|museum|auditorium|regency|hyatt|marriott|hilton)",
    re.I,
)
_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}


def _clean(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", _html.unescape(s or "")).strip()


def _strip_html(h: str) -> str:
    return _clean(re.sub(r"<[^>]+>", " ", h or ""))


def _paragraphs(h: str) -> List[str]:
    paras = re.findall(r"<p[^>]*>(.*?)</p>", h or "", re.S | re.I)
    out = []
    for p in paras:
        t = _strip_html(p)
        if t and not re.match(r"(?i)^(more info|for more information|website|register)", t):
            out.append(t)
    return out


def _fetch_json(url: str, browser: Any) -> Optional[dict]:
    for attempt in range(FETCH_TRIES):
        body = fetch_html(url, browser=browser, timeout=90.0, reuse_page=True)
        if body:
            m = re.search(r"\{.*\}", body, re.S)   # browser fallback wraps JSON in <pre>
            if m:
                try:
                    return json.loads(_html.unescape(m.group(0)) if body.lstrip().startswith("<") else m.group(0))
                except ValueError:
                    pass
        logger.warning(f"IFOS: API fetch attempt {attempt + 1}/{FETCH_TRIES} failed")
        time.sleep(2 * (attempt + 1))
    return None


def _classify_event_type(title: str) -> str:
    t = (title or "").lower()
    if re.search(r"\b(course|dissection|cadaver\w*|masterclass)\b", t):
        return "course"
    if re.search(r"\b(workshop|webinar|hands-on|study day)\b", t):
        return "workshop"
    return "conference"


def _split_venue(venue_raw: str, city: str, country: str, desc: str):
    """Return (venue_name, city, region) from Tribe's loose venue fields."""
    venue_raw, city, country = _clean(venue_raw), _clean(city), _clean(country)
    region = country or None
    if region in ("UK", "United Kingdom"):
        region = "United Kingdom"
    if city:
        parts = [p.strip() for p in venue_raw.split(",") if p.strip()]
        while len(parts) > 1 and parts[-1].lower() in (city.lower(), (country or "").lower()):
            parts.pop()
        if len(parts) > 1 and parts[0].lower() == city.lower():
            parts.pop(0)                     # "Berlin, Charite" -> "Charite"
        if len(parts) == 2 and parts[0].lower() == city.lower():
            parts.pop(0)
        v = ", ".join(parts)
        if not v or v.lower() == city.lower():
            return None, city, region
        if len(parts) == 1 and len(venue_raw.split(",")) == 2 and not _VENUE_WORDS.search(v) \
                and venue_raw.split(",")[0].strip().lower() == city.lower() and v == venue_raw.split(",")[1].strip():
            return None, city, (region or v)  # "Rome, Italy": second token is the country
        return v, city, region
    if not venue_raw:
        return None, None, region
    def _city_from_desc(text: str) -> Optional[str]:
        # a capitalised word of the venue string that the description uses as "in <Place>"
        for w in re.findall(r"[A-Z][\w'\u2019-]{3,}", text):
            if re.search(rf"\bin\s+{re.escape(w)}\b", desc or ""):
                return w
        return None

    parts = [p.strip() for p in venue_raw.split(",") if p.strip()]
    # trailing country token
    if len(parts) > 1 and (not country or parts[-1].lower() == country.lower()):
        if not country:
            region = parts[-1]
        parts = parts[:-1]
    if len(parts) == 1:
        p = parts[0]
        if _VENUE_WORDS.search(p) and "," in venue_raw:
            return p, _city_from_desc(p), region
        if _VENUE_WORDS.search(p):
            # a single named venue ("Hyatt Regency (Sha Tin) | CUHK ..."): city = country-state like HK
            return p, (region if region == "Hong Kong" else _city_from_desc(p)), region
        return None, p, (region or (p if p == "Hong Kong" else None))          # bare place name: "Hong Kong", "London", "Porto"
    if len(parts) == 2:
        a, b = parts
        a_v, b_v = bool(_VENUE_WORDS.search(a)), bool(_VENUE_WORDS.search(b))
        if a_v and not b_v:
            return a, b, region
        if b_v and not a_v:
            return b, a, region
        for cand, other in ((a, b), (b, a)):
            if re.search(rf"\bin\s+{re.escape(cand)}\b", desc or "", re.I):
                return other, cand, region
    return venue_raw, (region if region == "Hong Kong" else _city_from_desc(venue_raw)), region


def _parse_cost(ev: dict) -> List[Dict[str, Any]]:
    details = ev.get("cost_details") or {}
    code = details.get("currency_code") or _CURRENCY_SYMBOLS.get(details.get("currency_symbol") or "", "USD")
    text = _clean(ev.get("cost"))
    if text and re.search(r"\bfree\b", text, re.I):
        return [{"tier_label": "Free", "price_gbp": 0.0, "currency": code,
                 "is_early_bird": False, "early_bird_deadline": None}]
    vals: List[float] = []
    for v in details.get("values") or []:
        try:
            vals.append(float(str(v).replace(",", "")))
        except ValueError:
            pass
    if not vals and text:
        vals = [float(x.replace(",", "")) for x in re.findall(r"(\d[\d,]*(?:\.\d+)?)", text)]
    vals = sorted(set(v for v in vals if v > 0))
    if not vals:
        return []
    mk = lambda label, v: {"tier_label": label, "price_gbp": v, "currency": code,
                           "is_early_bird": False, "early_bird_deadline": None}
    if len(vals) == 1:
        return [mk("Registration", vals[0])]
    return [mk("Registration · From", vals[0]), mk("Registration · To", vals[-1])]


def _richness(s: Dict[str, Any]) -> tuple:
    return (bool(s.get("website")), bool(s.get("cost_values")), len(s.get("description_text") or ""))


class IfosworldExtractor(BaseExtractor):
    """IFOS — curated ORL congress calendar (Tribe Events API)."""

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today()
        end = today + timedelta(days=365 * 5)
        browser = getattr(self, "browser", None)
        events: List[dict] = []
        total = None
        total_pages = 1
        page_no = 1
        while page_no <= min(total_pages, MAX_PAGES):
            url = (f"{API_URL}?per_page={PER_PAGE}&page={page_no}"
                   f"&start_date={today.isoformat()}&end_date={end.isoformat()}")
            data = _fetch_json(url, browser)
            if data is None:
                logger.warning(f"IFOS: giving up on API page {page_no}")
                break
            total = data.get("total", total)
            total_pages = int(data.get("total_pages") or 1)
            events.extend(data.get("events") or [])
            page_no += 1
            if page_no <= total_pages:
                time.sleep(1.0)
        if not events:
            return None
        if total is not None and len(events) != int(total):
            logger.warning(f"IFOS: fetched {len(events)} events but API says total={total}")

        shells: List[Dict[str, Any]] = []
        seen_urls = set()
        for e in events:
            title = _clean(e.get("title"))
            url = e.get("url") or ""
            start = (e.get("start_date") or "")[:10]
            end_d = (e.get("end_date") or "")[:10] or start
            if not title or not url or not start or url in seen_urls:
                continue
            if end_d < today.isoformat() or e.get("status") not in (None, "publish"):
                continue
            if re.search(r"\b(cancelled|canceled|postponed)\b", title, re.I):
                continue
            seen_urls.add(url)
            venue = e.get("venue") if isinstance(e.get("venue"), dict) else {}
            desc_html = e.get("description") or ""
            time_str = None
            if not e.get("all_day"):
                hh, mm = (e.get("start_date") or "")[11:16].split(":") if len(e.get("start_date") or "") >= 16 else (None, None)
                if hh and (hh, mm) != ("00", "00"):
                    time_str = f"{hh}:{mm}"
            shells.append({
                "title": title,
                "booking_url": url,
                "source_url": url,
                "start_date": start,
                "end_date": end_d,
                "start_time": time_str,
                "venue_raw": venue.get("venue") or "",
                "city_raw": venue.get("city") or "",
                "country_raw": venue.get("country") or "",
                "website": e.get("website") or "",
                "cost_text": e.get("cost") or "",
                "cost_values": (e.get("cost_details") or {}).get("values") or [],
                "cost_details": e.get("cost_details") or {},
                "description_html": desc_html,
                "description_text": _strip_html(desc_html),
                "categories": [c.get("name") for c in (e.get("categories") or []) if c.get("name")],
            })

        # Same meeting listed twice (different posts): keep the richer one.
        best: Dict[tuple, Dict[str, Any]] = {}
        for s in shells:
            key = (s["start_date"], _clean(s["venue_raw"]).lower()) if s["venue_raw"] else (s["booking_url"],)
            if key not in best or _richness(s) > _richness(best[key]):
                best[key] = s
        deduped = [s for s in shells if best[(s["start_date"], _clean(s["venue_raw"]).lower()) if s["venue_raw"] else (s["booking_url"],)] is s]
        # A venue string that resolves to a city for one event (e.g. via its
        # description) gives that city to other events at the identical venue.
        known: Dict[str, str] = {}
        for s in deduped:
            _, c, _r = _split_venue(s["venue_raw"], s["city_raw"], s["country_raw"], s["description_text"])
            if c and s["venue_raw"]:
                known.setdefault(_clean(s["venue_raw"]).lower(), c)
        for s in deduped:
            if not s["city_raw"] and s["venue_raw"]:
                s["city_raw"] = known.get(_clean(s["venue_raw"]).lower(), "")
        logger.info(f"IFOS Tribe API: total={total} fetched={len(events)} "
                    f"upcoming={len(shells)} after_dedupe={len(deduped)}")
        return deduped or None

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        title = shell.get("title") or ""
        desc_text = shell.get("description_text") or ""

        out["event_type"] = _classify_event_type(title)
        out["society"] = "IFOS"

        # Venue / city / region
        venue, city, region = _split_venue(
            shell.get("venue_raw"), shell.get("city_raw"), shell.get("country_raw"), desc_text)
        if venue:
            out["venue_name"] = venue
        if city:
            out["city"] = city
        if region:
            out["region"] = region
        if city == "Hong Kong" and not region:
            out["region"] = "Hong Kong"
        if city == "London" and region == "United Kingdom":
            out["region"] = "London"

        # Format
        blob = f"{title} {desc_text}".lower()
        if re.search(r"\bhybrid\b", blob):
            out["event_format"] = "hybrid"
        elif not shell.get("venue_raw") and re.search(r"\b(virtual|online|webinar)\b", blob):
            out["event_format"] = "online"
        else:
            out["event_format"] = "in_person"

        if shell.get("start_time"):
            out["start_time"] = shell["start_time"]

        # Booking: the organiser's own site when the listing gives one
        if shell.get("website"):
            out["booking_url"] = shell["website"]

        # Fees
        tiers = _parse_cost({"cost": shell.get("cost_text"), "cost_details": shell.get("cost_details")})
        if tiers:
            out["pricing_tiers"] = tiers

        # CPD — only when stated numerically
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:CPD|CME)\s*(?:credits?|points?|hours?)", desc_text, re.I)
        if m:
            out["cpd_points"] = float(m.group(1))
            out["cpd_accredited"] = True

        # Description: first real paragraphs, trimmed (validator-safe 50-700)
        paras = _paragraphs(shell.get("description_html") or "")
        desc = ""
        for p in paras:
            desc = f"{desc} {p}".strip() if desc else p
            if len(desc) >= 120:
                break
        if len(desc) > 700:
            desc = desc[:697].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."
        if len(desc) >= 50:
            out["description"] = desc

        # Specialty: IFOS lists ORL/ENT meetings only. The keyword classifier
        # mis-tags e.g. "Interventional Thyroidology" (an ENT head & neck
        # congress) as Endocrinology, so the source default wins.
        out["specialty"] = DEFAULT_SPECIALTY
        return out
