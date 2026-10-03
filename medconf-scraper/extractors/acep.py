"""
ACEP (American College of Emergency Physicians) — Event Calendar extractor.

Wave 2b source 59. https://www.acep.org/master-calendar is an AngularJS SPA,
but the list it renders comes from one unauthenticated JSON endpoint:

    GET https://www.acep.org/api/events/currentevents

It returns EVERY event on the calendar in a single array (≈54 rows on
2026-10-03, no pagination, no params). Each row has MeetingName, Sponsor,
EventTypeText (Conference | Webinar), Country/State/City/Address,
EventStartDate / EventEndDate, CMEHours, Website (external organiser link,
sometimes a bare domain, an internal /link/<guid>.aspx redirect, or even free
text such as "OHIO CHAPTER ACEP") and PageUrl (the ACEP detail page).

The calendar is a mix of ACEP's own meetings (Scientific Assembly, Accelerate,
Leadership & Advocacy) and third-party courses/webinars ACEP lists for
chapters and partners. Listing = API (`list_shells_override`). Detail pages
(`/master-calendar/<slug>`) are server-rendered with stable classes:
mcEvent-host, mcEvent-date, mcEvent-time, mcEvent-location, mcEvent-cme-hours,
mcEvent-web, mcEvent-description. NO fees appear anywhere on ACEP's pages
(registration happens on the organiser's own site), so pricing_tiers is [].

Quirks:
- EventEndDate carries a bogus "Z" suffix; only the date part is used.
- Start times in the API are unreliable placeholders (12:00-05:00, 00:00);
  start_time is read only from the detail page's mcEvent-time element.
- Location is thin: often just a US state (the venue is not published).
  Never invented — city stays None, region = state / country.
- Everything is typed "Conference" by ACEP; event_type is derived from the
  title (course / workshop / webinar → course|workshop, else conference).
- Horizon: events starting more than ~24 months out (ACEP29-32 placeholders)
  are skipped; they have no dates worth listing yet.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Page

from .base import BaseExtractor
from .http_fetch import fetch_html
from .specialty_classifier import classify_specialty
from logger import logger

SITE = "https://www.acep.org"
API_URL = f"{SITE}/api/events/currentevents"
HORIZON_DAYS = 730

_VENUE_WORDS = re.compile(
    r"(?i)\b(resort|hotel|center|centre|convention|inn|suites|marriott|hilton|hyatt|"
    r"hall|university|hospital|campus|lodge|casino)\b"
)
_US = {"united states", "usa", "us", "united states of america"}


def _flatten(fragment: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", fragment)
    text = re.sub(r"(?i)<br\s*/?>|</p>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def _iso(value: Optional[str]) -> Optional[str]:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", value or "")
    return m.group(1) if m else None


def _classify_event_type(title: str, type_text: str) -> str:
    t = (title or "").lower()
    if "webinar" in t or (type_text or "").lower() == "webinar":
        return "workshop"
    if any(k in t for k in ("workshop", "master class", "masterclass", "symposium workshop")):
        return "workshop"
    if any(k in t for k in ("course", "training", "academy", "boot camp", "lab", "review")):
        return "course"
    return "conference"


def _parse_time(text: str) -> Optional[str]:
    m = re.search(r"(\d{1,2}):(\d{2})\s*([AP]M)", text or "", re.I)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), m.group(2), m.group(3).upper()
    if ap == "PM" and h != 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{mi}"


def _organiser_url(website: Optional[str]) -> Optional[str]:
    w = (website or "").strip()
    if not w:
        return None
    if w.startswith("/"):
        return SITE + w
    if re.match(r"(?i)^https?://", w):
        return w
    if re.match(r"(?i)^(www\.)?[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?$", w):
        return "https://" + w
    return None  # free text such as "OHIO CHAPTER ACEP"


class AcepExtractor(BaseExtractor):
    """ACEP master calendar — JSON API listing + server-rendered detail pages."""

    # ------------------------------------------------------------------ #
    # Phase A — one API call, 3-try retry.
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_api(body: str) -> Optional[List[Dict[str, Any]]]:
        """JSON when `Accept: application/json` is honoured; the endpoint
        otherwise answers XML (what a browser fallback sees), so parse both."""
        body = body.strip()
        i, j = body.find("["), body.rfind("]")
        if body.startswith("[") or (body.startswith("<") and "<pre" in body[:400] and i != -1):
            try:
                raw = body[i:j + 1]
                if body.startswith("<"):
                    raw = html_lib.unescape(re.sub(r"<[^>]+>", "", raw))
                data = json.loads(raw)
                return data if isinstance(data, list) else None
            except Exception:
                return None
        if body.startswith("<ArrayOfEventSearchResult"):
            import xml.etree.ElementTree as ET
            try:
                root = ET.fromstring(body)
            except ET.ParseError:
                return None
            rows = []
            for el in root:
                rows.append({c.tag.split("}")[-1]: (c.text or "") for c in el})
            for r in rows:
                r["CMECreditAvailable"] = str(r.get("CMECreditAvailable", "")).lower() == "true"
            return rows
        return None

    def _fetch_via_browser_request(self) -> Optional[List[Dict[str, Any]]]:
        b = getattr(self, "browser", None)
        page = getattr(b, "page", b)
        try:
            resp = page.context.request.get(API_URL, headers={"Accept": "application/json"}, timeout=30000)
            if resp.ok:
                return self._parse_api(resp.text())
        except Exception as e:
            logger.warning(f"ACEP browser-request fetch failed: {e}")
        return None

    def _fetch_api(self) -> Optional[List[Dict[str, Any]]]:
        for attempt in range(3):
            body = fetch_html(API_URL, browser=getattr(self, "browser", None),
                              headers={"Accept": "application/json"})
            if body:
                rows = self._parse_api(body)
                if rows:
                    return rows
                logger.warning(f"ACEP API unparseable (try {attempt + 1}); trying browser request API")
            # Chromium renders the XML/JSON as a viewer page, so ask for the raw
            # body through the browser context's request API instead.
            rows = self._fetch_via_browser_request()
            if rows:
                return rows
            time.sleep(2 * (attempt + 1))
        return None

    @staticmethod
    def _location(row: Dict[str, Any]) -> Dict[str, Any]:
        country = (row.get("Country") or "").strip()
        state = (row.get("State") or "").strip()
        city = (row.get("City") or "").strip()
        address = (row.get("Address") or "").strip()
        etype = (row.get("EventTypeText") or "").lower()

        out: Dict[str, Any] = {"venue_name": None, "city": None, "region": None,
                               "event_format": "in_person"}
        if etype == "webinar" or re.search(r"(?i)live\s*stream|virtual|online|webinar", address):
            out["event_format"] = "online"
            return out

        if not city and address and address not in (state, country):
            # e.g. "La Paz, BCS, Mexico" — first part city, last part country.
            parts = [p.strip() for p in address.split(",") if p.strip()]
            if len(parts) >= 2:
                city = parts[0]
                if not country:
                    country = parts[-1]
        if city and _VENUE_WORDS.search(city):
            out["venue_name"], city = city, ""
        out["city"] = city or None
        if country and country.lower() not in _US:
            out["region"] = country
        else:
            out["region"] = state or None
        return out

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        rows = self._fetch_api()
        if rows is None:
            logger.error("ACEP: calendar API unreachable after 3 tries")
            return []
        today = date.today()
        horizon = today + timedelta(days=HORIZON_DAYS)
        shells: List[Dict[str, Any]] = []
        seen: set = set()
        for row in rows:
            title = re.sub(r"\s+", " ", (row.get("MeetingName") or "")).strip()
            path = (row.get("PageUrl") or "").strip()
            start, end = _iso(row.get("EventStartDate")), _iso(row.get("EventEndDate"))
            if not title or not path or not start:
                continue
            end = end if end and end >= start else start
            if date.fromisoformat(end) < today or date.fromisoformat(start) > horizon:
                continue
            url = SITE + path if path.startswith("/") else path
            if url in seen:
                continue
            seen.add(url)
            hours = None
            try:
                hours = float(row["CMEHours"]) if row.get("CMEHours") else None
            except (TypeError, ValueError):
                pass
            desc = _flatten(row.get("Description") or "")
            shell = {
                "title": title,
                "booking_url": url,
                "source_url": url,
                "start_date": start,
                "end_date": end,
                "event_type": _classify_event_type(title, row.get("EventTypeText") or ""),
                "cpd_points": hours,
                "cpd_accredited": bool(row.get("CMECreditAvailable")) or None,
                "organiser_url": _organiser_url(row.get("Website")),
                "description_hint": desc[:600] or None,
                "sponsor": (row.get("Sponsor") or "").strip() or None,
            }
            shell.update(self._location(row))
            shells.append(shell)
        shells.sort(key=lambda s: (s["start_date"], s["title"]))
        logger.info(f"ACEP: {len(shells)} upcoming events (API rows: {len(rows)})")
        return shells

    # ------------------------------------------------------------------ #
    # Phase B — detail page (already loaded in `page`).
    # ------------------------------------------------------------------ #
    @staticmethod
    def _grab(html: str, cls: str) -> Optional[str]:
        m = re.search(rf'(?is)<(p|h3|span|div)[^>]*class="[^"]*{cls}[^"]*"[^>]*>(.*?)</\1>', html)
        return _flatten(m.group(2)) if m else None

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        url = shell.get("booking_url")
        html = fetch_html(url, browser=getattr(self, "browser", None), loaded_page=page) or ""
        title = shell.get("title")

        result: Dict[str, Any] = {
            "event_type": shell.get("event_type") or "conference",
            "pricing_tiers": [],  # ACEP publishes no fees; registration is on organiser sites
            "is_sold_out": False,
        }
        for k in ("start_date", "end_date", "venue_name", "city", "region", "event_format",
                  "cpd_points", "cpd_accredited", "organiser_url"):
            if shell.get(k) is not None:
                result[k] = shell[k]

        mch = self._grab(html, "mcEvent-title") or None
        if mch and not title:
            result["title"] = mch

        t = self._grab(html, "mcEvent-time")
        if t:
            st = _parse_time(t)
            if st:
                result["start_time"] = st

        web = re.search(r'(?is)class="[^"]*mcEvent-web[^"]*".*?<a[^>]+href="([^"]+)"', html)
        if web:
            ou = _organiser_url(html_lib.unescape(web.group(1)))
            if ou:
                result["organiser_url"] = ou
        result["booking_url"] = result.get("organiser_url") or url

        if "cpd_points" not in result:
            m = re.search(r"(?is)mcEvent-cme-hours[^>]*>\s*([\d.]+)", html)
            if m:
                result["cpd_points"] = float(m.group(1))
                result["cpd_accredited"] = True

        dm = re.search(r'(?is)<div[^>]*class="[^"]*mcEvent-description[^"]*"[^>]*>(.*?)</div>', html)
        body = _flatten(dm.group(1)) if dm else (shell.get("description_hint") or "")
        result.update(self._soft_fields(title, body, shell, llm_call))
        return result

    def _soft_fields(self, title: Optional[str], body: str, shell: Dict[str, Any],
                     llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        text = (body or "")[:3000]
        if len(text) >= 80:
            prompt = f"""You are summarising one medical education event. Extract ONLY two fields.

EVENT TITLE: {title}

EVENT TEXT:
{text}

Respond with valid JSON only, no markdown:
{{
  "description": "concise 30-50 word summary built only from the text" or null,
  "specialty": "primary clinical area (e.g. Emergency Medicine, Ultrasound, Paediatrics)" or null
}}"""
            raw = llm_call(prompt)
            if raw:
                m = re.search(r"\{.*\}", raw.replace("```json", "").replace("```", ""), re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                        out["description"] = parsed.get("description") or None
                        out["specialty"] = parsed.get("specialty") or None
                    except Exception as e:
                        logger.warning(f"ACEP soft-fields JSON parse failed: {e}")
        if not out.get("specialty"):
            out["specialty"] = classify_specialty(title, text) or "Emergency Medicine"
        if not out.get("description"):
            for line in re.split(r"\n+", body or ""):
                line = line.strip()
                if len(line) >= 60 and not line.startswith("http"):
                    out["description"] = line[:500]
                    break
            else:
                out["description"] = shell.get("description_hint")
        return out
