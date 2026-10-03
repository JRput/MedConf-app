# extractors/eanm.py
"""
EANM (European Association of Nuclear Medicine) — Calendar of Events.

Wave 2b source. The public calendar page
(/the-eanm-community/opportunities/calendar-of-events/) is rendered client
side by the Stachethemes "Stec" event-calendar plugin, but the plugin
exposes the complete event list as a public REST endpoint:

    https://eanm.org/wp-json/stec/v5/events?per_page=100&page=N

(`X-WP-Total` = 499, 5 pages of 100 on 2026-10-03.) The endpoint is NOT
date-filtered and is ordered by publication date, so we walk every page
(<= 1 req/s), dedupe by permalink and filter to upcoming events locally.
Only ~35 of the 499 are upcoming — the rest is the archive back to 2017.

Event pages (/stec_event/<slug>/) are JS-only shells that show nothing the
API doesn't already carry (and they print dates shifted into the viewer's
timezone), so every field is built from the API record carried on the
shell. `extract_detail` therefore never needs the loaded page.

What the calendar lists is a MIX:
  * EANM's own events — the Annual Congress and ESMIT (the EANM school)
    live webinars / onsite courses. society = "EANM".
  * Third-party events other organisers asked EANM to list (UCG
    Conferences, Scientex, EMUC, MELODI, …). Owner decision (as with
    ACPGBI): list everything the calendar lists, but tag the society
    correctly — `_society()` maps the organiser from the external link
    host / title, never "EANM".

Gotchas:
  * API start/end are sloppy for third-party entries (a conference on
    4-5 Feb 2027 is stored as 11 Aug 2026 -> 5 Feb 2027). When the body
    text states an explicit date range that lies INSIDE the API range we
    narrow to it; otherwise the API dates stand.
  * `all_day` events carry T00:00 — start_time only when not all_day.
  * Description is `content.rendered` (HTML); `excerpt` holds the location
    line ("Venue, City, Country") for third-party events and just a URL /
    scratch text for EANM's own. No fees are published anywhere on these
    pages: pricing_tiers=[] unless the text says the event is free.
  * EANM's own events have empty content; the Congress description comes
    from the meta description of its microsite (eanm26.eanm.org). ESMIT
    events point at one generic landing page, so they get no description
    (a per-event template would be invented text).
"""

from __future__ import annotations

import html as html_lib
import json
import re
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from playwright.sync_api import Page

from .base import BaseExtractor
from .http_fetch import fetch_html
from .specialty_classifier import classify_specialty
from logger import logger

API_URL = "https://eanm.org/wp-json/stec/v5/events"
PER_PAGE = 100
MAX_PAGES = 12          # hard cap; real total is 5 pages
FETCH_DELAY_S = 1.0     # <= 1 req/s
FETCH_TRIES = 3

_MONTHS = {
    m.lower()[:3]: i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"], start=1)
}
_MON = r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"

# "Feb 01-02, 2027" / "February 04–05, 2027"
_RANGE_MD = re.compile(rf"\b{_MON}\s+(\d{{1,2}})\s*[–—-]\s*(\d{{1,2}}),?\s+(\d{{4}})\b", re.I)
# "04–05 February 2027"
_RANGE_DM = re.compile(rf"\b(\d{{1,2}})\s*[–—-]\s*(\d{{1,2}})\s+{_MON},?\s+(\d{{4}})\b", re.I)
# "March 30 – April 2, 2027"
_RANGE_CROSS = re.compile(
    rf"\b{_MON}\s+(\d{{1,2}})\s*[–—-]\s*{_MON}\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.I)
# "February 4, 2027"
_SINGLE_MD = re.compile(rf"\b{_MON}\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.I)

# Organiser (society) by external-link host fragment, then by title text.
_HOST_SOCIETY = [
    ("ucgconferences.com", "UCG Conferences"),
    ("utilitarianconferences.com", "UCG Conferences"),
    ("scientexconference.com", "Scientex Conferences"),
    ("stressandbehavior.com", "Stress and Behavior Conference"),
    ("emuc.org", "EMUC"),
    ("nmn-society.org", "NMN Society"),
    ("radiationcarcinogenesismelodi.com", "MELODI Association"),
    ("esmit.eanm.org", "EANM"),
    ("eanm.org", "EANM"),
]
_TITLE_SOCIETY = [
    (re.compile(r"\bPakistan Society of Nuclear Medicine\b", re.I), "Pakistan Society of Nuclear Medicine"),
    (re.compile(r"\bICPO\b"), "ICPO"),
    (re.compile(r"\bESMIT\b"), "EANM"),
    (re.compile(r"\bEANM\b"), "EANM"),
]
FALLBACK_THIRD_PARTY_SOCIETY = "Third-party organiser (EANM calendar)"

_COUNTRIES = {
    "albania", "armenia", "australia", "austria", "bahrain", "belgium", "brazil", "bulgaria",
    "canada", "china", "croatia", "cyprus", "czechia", "czech republic", "denmark", "egypt",
    "estonia", "finland", "france", "georgia", "germany", "greece", "hong kong", "hungary",
    "iceland", "india", "indonesia", "ireland", "israel", "italy", "japan", "jordan", "kenya",
    "latvia", "lithuania", "luxembourg", "malaysia", "malta", "mexico", "monaco", "morocco",
    "netherlands", "the netherlands", "new zealand", "nigeria", "norway", "oman", "pakistan",
    "poland", "portugal", "qatar", "romania", "saudi arabia", "serbia", "singapore", "slovakia",
    "slovenia", "south africa", "south korea", "spain", "sri lanka", "st. lucia", "saint lucia",
    "sweden", "switzerland", "thailand", "turkey", "türkiye", "uae", "united arab emirates",
    "uk", "united kingdom", "usa", "united states", "vietnam",
}


def _strip_html(fragment: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", fragment or "")
    text = re.sub(r"(?i)</(p|div|li|h\d|br)\s*>|<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _mon(name: str) -> int:
    return _MONTHS[name.lower()[:3]]


def _safe_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _parse_json_body(body: Optional[str]) -> Optional[Any]:
    """The REST body, either raw JSON (httpx) or wrapped by the browser
    fallback in <html><pre>…</pre></html>."""
    if not body:
        return None
    body = body.strip()
    if not body.startswith(("[", "{")):
        m = re.search(r"(?is)<pre[^>]*>(.*?)</pre>", body)
        if m:
            body = html_lib.unescape(m.group(1)).strip()
        else:
            body = re.sub(r"(?s)<[^>]+>", "", body).strip()
    try:
        return json.loads(body)
    except Exception:
        return None


class EanmExtractor(BaseExtractor):
    """European Association of Nuclear Medicine — Calendar of Events (Stec REST API)."""

    # ------------------------------------------------------------------ #
    # Phase A — walk the REST API
    # ------------------------------------------------------------------ #

    def _fetch_page(self, page_no: int) -> Optional[List[Dict[str, Any]]]:
        """One API page: a list (possibly empty past the last page) or None
        on persistent failure. 3 tries, polite delay between attempts."""
        url = f"{API_URL}?per_page={PER_PAGE}&page={page_no}"
        for attempt in range(1, FETCH_TRIES + 1):
            body = fetch_html(
                url,
                browser=getattr(self, "browser", None),
                headers={"Accept": "application/json"},
            )
            data = _parse_json_body(body)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and data.get("code") == "rest_post_invalid_page_number":
                return []           # walked past the end
            logger.warning(f"EANM: API page {page_no} attempt {attempt}/{FETCH_TRIES} failed")
            time.sleep(FETCH_DELAY_S * attempt)
        return None

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today()
        records: Dict[str, Dict[str, Any]] = {}
        total_seen = 0
        for page_no in range(1, MAX_PAGES + 1):
            if page_no > 1:
                time.sleep(FETCH_DELAY_S)
            rows = self._fetch_page(page_no)
            if rows is None:
                logger.warning(f"EANM: API page {page_no} unreachable; aborting listing")
                return None         # partial walk is worse than none — keep old rows
            if not rows:
                break
            total_seen += len(rows)
            for r in rows:
                link = r.get("link") or ((r.get("guid") or {}).get("rendered"))
                if link and link not in records:
                    records[link] = r
            if len(rows) < PER_PAGE:
                break

        shells: List[Dict[str, Any]] = []
        for link, r in records.items():
            shell = self._shell_from_record(link, r, today)
            if shell:
                shells.append(shell)
        shells.sort(key=lambda s: (s["start_date"] or "9999", s["title"]))
        logger.info(f"EANM: API {total_seen} records ({len(records)} unique) -> {len(shells)} upcoming shells")
        return shells or None

    def _shell_from_record(self, link: str, r: Dict[str, Any], today: date) -> Optional[Dict[str, Any]]:
        if r.get("status") != "publish":
            return None
        meta = r.get("meta") or {}
        status = str(meta.get("event_status") or "EventScheduled")
        title = _flat(html_lib.unescape((r.get("title") or {}).get("rendered") or ""))
        if not title or status != "EventScheduled" or re.search(r"(?i)\b(cancel+ed|postponed)\b", title):
            return None

        start_raw = str(meta.get("start_date") or "")
        end_raw = str(meta.get("end_date") or "") or start_raw
        start = start_raw[:10]
        end = end_raw[:10] or start
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start):
            return None
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
            end = start

        content_html = (r.get("content") or {}).get("rendered") or ""
        body_text = _strip_html(content_html)
        # Narrow sloppy third-party ranges to the explicit dates in the text.
        narrowed = self._narrow_dates(body_text, start, end)
        if narrowed:
            start, end = narrowed
        if end < today.isoformat():
            return None

        all_day = bool(meta.get("all_day"))
        m_time = re.search(r"T(\d{2}:\d{2})", start_raw)
        start_time = None if all_day or not m_time or m_time.group(1) == "00:00" else m_time.group(1)

        ext = meta.get("external_link")
        ext_url = (ext.get("url") if isinstance(ext, dict) else None) or None
        if not ext_url:
            ex = _flat(_strip_html((r.get("excerpt") or {}).get("rendered") or ""))
            if re.fullmatch(r"https?://\S+", ex):
                ext_url = ex
        if ext_url and not re.match(r"https?://", ext_url, re.I):
            ext_url = "https://" + ext_url.lstrip("/")

        # Third-party entries carry the calendar's default 08:00/09:00, not a
        # time the organiser published — only EANM's own events keep a time.
        if self._society(title, ext_url or "") != "EANM":
            start_time = None

        return {
            "title": title,
            "booking_url": link,
            "source_url": link,
            "start_date": start,
            "end_date": end if end != start else None,
            "start_time": start_time,
            "description_html": content_html,
            "excerpt_raw": _flat(_strip_html((r.get("excerpt") or {}).get("rendered") or "")),
            "external_url": ext_url,
        }

    @staticmethod
    def _narrow_dates(text: str, api_start: str, api_end: str) -> Optional[Tuple[str, str]]:
        """First explicit date range in the body text that lies inside the
        API's [start, end] window (±1 day). None when nothing qualifies."""
        flat = _flat(text)
        lo = datetime.strptime(api_start, "%Y-%m-%d").date() - timedelta(days=1)
        hi = datetime.strptime(api_end, "%Y-%m-%d").date() + timedelta(days=1)
        cands: List[Tuple[int, date, date]] = []
        for m in _RANGE_MD.finditer(flat):
            mo, d1, d2, y = _mon(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            a, b = _safe_date(y, mo, d1), _safe_date(y, mo, d2)
            if a and b and a <= b:
                cands.append((m.start(), a, b))
        for m in _RANGE_DM.finditer(flat):
            d1, d2, mo, y = int(m.group(1)), int(m.group(2)), _mon(m.group(3)), int(m.group(4))
            a, b = _safe_date(y, mo, d1), _safe_date(y, mo, d2)
            if a and b and a <= b:
                cands.append((m.start(), a, b))
        for m in _RANGE_CROSS.finditer(flat):
            m1, d1, m2, d2, y = _mon(m.group(1)), int(m.group(2)), _mon(m.group(3)), int(m.group(4)), int(m.group(5))
            a, b = _safe_date(y, m1, d1), _safe_date(y, m2, d2)
            if a and b and a <= b:
                cands.append((m.start(), a, b))
        for m in _SINGLE_MD.finditer(flat):
            a = _safe_date(int(m.group(3)), _mon(m.group(1)), int(m.group(2)))
            if a:
                cands.append((m.start(), a, a))
        for _, a, b in sorted(cands, key=lambda c: c[0]):
            if lo <= a and b <= hi:
                return a.isoformat(), b.isoformat()
        return None

    # ------------------------------------------------------------------ #
    # Phase B — everything derives from the API record on the shell
    # ------------------------------------------------------------------ #

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        title = shell.get("title") or ""
        body = _strip_html(shell.get("description_html") or "")
        body_flat = _flat(body)
        excerpt = shell.get("excerpt_raw") or ""
        ext_url = shell.get("external_url") or ""

        society = self._society(title, ext_url)
        own = society == "EANM"

        out: Dict[str, Any] = {
            "society": society,
            "event_type": self._event_type(title, body_flat),
            "organiser_url": ext_url or None,
        }
        if title.startswith("EANM") and "Annual Congress" in title:
            out["is_flagship"] = True

        # Location: title "(in Valencia, Spain)", then excerpt line, then body.
        out.update(self._location(title, excerpt, body))
        out["event_format"] = self._event_format(title, excerpt, body_flat, out)
        if out["event_format"] == "online":
            for k in ("venue_name", "city", "region"):
                out.pop(k, None)

        # CPD (third-party bodies state hours/credits).
        cpd = self._cpd(body_flat)
        if cpd:
            out["cpd_accredited"] = True
            if cpd[0] is not None:
                out["cpd_points"] = cpd[0]

        # Fees: nothing published; "free" only if the text says so.
        out["pricing_tiers"] = self._pricing(body_flat)

        # Soft fields.
        out.update(self._soft_fields(title, body, ext_url, own, llm_call))

        return {k: v for k, v in out.items() if v not in (None, "")}

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _society(title: str, ext_url: str) -> str:
        for rx, name in _TITLE_SOCIETY:
            if rx.search(title):
                # An "EANM" word inside a third-party title is not enough
                # when the link goes to an unrelated organiser.
                if name == "EANM" and ext_url:
                    host = (urlparse(ext_url).netloc or "").lower()
                    if host and "eanm.org" not in host:
                        continue
                return name
        host = (urlparse(ext_url).netloc or "").lower()
        for frag, name in _HOST_SOCIETY:
            if frag in host:
                return name
        return FALLBACK_THIRD_PARTY_SOCIETY

    @staticmethod
    def _event_type(title: str, body_flat: str = "") -> str:
        t = title.lower()
        if re.search(r"\bwebinar\b|\bworkshop\b|\bsummit\b", t) and "conference" not in t:
            return "workshop"
        if re.search(r"\b(?:is|a) (?:free,? )?(?:online )?webinar\b", body_flat[:400].lower()):
            return "workshop"
        if re.search(r"\bcourse\b|\btraining\b|\bschool\b", t):
            return "course"
        return "conference"

    @staticmethod
    def _location(title: str, excerpt: str, body: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        # "(in Valencia, Spain)" in the title (ESMIT onsite courses).
        m = re.search(r"\(\s*in\s+([^,()]+),\s*([^()]+?)\s*\)", title)
        if m:
            out["city"], out["region"] = m.group(1).strip(), m.group(2).strip()
            return out

        parts = [p.strip() for p in excerpt.split(",") if p.strip()] if excerpt and "http" not in excerpt else []
        if len(parts) >= 2 and len(excerpt) < 160 and not re.search(r"(?i)teams|zoom|webinar|event:", excerpt):
            if parts[-1].lower() in _COUNTRIES:
                out["region"] = parts[-1]
                out["city"] = parts[-2]
                if len(parts) >= 3:
                    out["venue_name"] = ", ".join(parts[:-2])[:200]
            else:
                # "Novotel Al Barsha, Dubai": venue + city, no country given.
                out["city"] = parts[-1]
                out["venue_name"] = ", ".join(parts[:-1])[:200]
        # Body "Venue: X" line is the most explicit venue name.
        m = re.search(r"(?im)^\W*(?:conference\s+)?venue\s*:\s*([^\n]{3,160})$", body)
        if m:
            venue = re.sub(r"\s*&\s*Online\s*$", "", m.group(1)).strip(" .")
            vparts = [p.strip() for p in venue.split(",") if p.strip()]
            if "city" not in out and len(vparts) >= 2:
                if vparts[-1].lower() in _COUNTRIES:
                    out["region"], out["city"] = vparts[-1], vparts[-2]
                    if len(vparts) >= 3:
                        out["venue_name"] = ", ".join(vparts[:-2])
                else:
                    out["city"] = vparts[-1]
                    out["venue_name"] = ", ".join(vparts[:-1])
            elif "city" not in out and len(vparts) == 1:
                out["city"] = vparts[0]
            elif "venue_name" not in out and vparts and out.get("city", "").lower() not in vparts[0].lower():
                out["venue_name"] = ", ".join(vparts[:-2] or vparts[:1])[:200]
        return out

    @staticmethod
    def _event_format(title: str, excerpt: str, body_flat: str, loc: Dict[str, Any]) -> Optional[str]:
        t = title.lower()
        if re.search(r"(?i)\bhybrid\b", body_flat) or re.search(r"(?i)venue\s*:[^.]{0,120}&\s*online", body_flat):
            return "hybrid"
        if re.search(r"\bwebinar\b|\bvirtual\b|\bonline\b", t) or re.search(
                r"(?i)microsoft teams|\bzoom\b|\bis a free, online\b", excerpt + " " + body_flat[:400]):
            return "online"
        if re.search(r"(?i)\bonsite\b|\bon-site\b", t) or loc.get("city") or loc.get("venue_name"):
            return "in_person"
        return None     # e.g. EANM Annual Congress: calendar doesn't say

    @staticmethod
    def _cpd(body_flat: str) -> Optional[Tuple[Optional[float], bool]]:
        if not re.search(r"(?i)\b(?:CME|CPD)\b", body_flat):
            return None
        for pat in (r"(\d{1,3})\s*(?:CPD|CME)\s*(?:hours?|credits?|points?)",
                    r"(\d{1,3})\s*(?:CPD|CME)\b",
                    r"(?:earn|gain)\s+(\d{1,3})\s+(?:continuing|credit|hours)"):
            m = re.search(pat, body_flat, re.I)
            if m:
                return float(m.group(1)), True
        return None, True

    @staticmethod
    def _pricing(body_flat: str) -> List[Dict[str, Any]]:
        if re.search(r"(?i)\bis a free,?\s+(?:online\s+)?(?:webinar|event|conference|course)\b|\bfree to attend\b",
                     body_flat):
            return [{
                "tier_label": "Registration · Free",
                "price_gbp": 0.0,
                "currency": "GBP",
                "is_early_bird": False,
                "early_bird_deadline": None,
            }]
        return []

    @staticmethod
    def _first_paragraph(body: str) -> Optional[str]:
        for line in re.split(r"\n+", body):
            line = _flat(line)
            if len(line) < 60 or line.lower().startswith(("http", "dear", "greetings")) or "@" in line:
                continue
            if len(line) <= 450:
                return line
            cut = line[:450].rsplit(". ", 1)
            return (cut[0] + ".") if len(cut) == 2 else line[:450].rstrip() + "…"
        return None

    def _microsite_description(self, ext_url: str) -> Optional[str]:
        """Meta description of an EANM-run microsite (the Congress site)."""
        host = (urlparse(ext_url).netloc or "").lower()
        if not host.endswith("eanm.org") or host in ("esmit.eanm.org", "www.eanm.org", "eanm.org"):
            return None
        doc = fetch_html(ext_url, browser=getattr(self, "browser", None))
        if not doc:
            return None
        m = (re.search(r'(?i)<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{40,500})["\']', doc)
             or re.search(r'(?i)<meta[^>]+content=["\']([^"\']{40,500})["\'][^>]+name=["\']description["\']', doc))
        return _flat(html_lib.unescape(m.group(1))) if m else None

    def _soft_fields(self, title: str, body: str, ext_url: str, own: bool,
                     llm_call: Callable[[str], Optional[str]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        text = body[:3000]
        description: Optional[str] = None
        specialty: Optional[str] = None

        if len(text) >= 200:
            prompt = f"""You are summarising one listing from a medical conference calendar. Extract ONLY two fields.

EVENT TITLE: {title}

LISTING TEXT:
{text}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the listing text" or null,
  "specialty": "primary clinical specialty (e.g. Cardiology, Pathology, Nuclear Medicine)" or null
}}"""
            raw = llm_call(prompt)
            if raw:
                raw = raw.strip()
                if raw.startswith("```"):
                    parts = raw.split("```")
                    if len(parts) >= 3:
                        raw = parts[1]
                        if raw.startswith("json"):
                            raw = raw[4:]
                        raw = raw.strip()
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                        description = (parsed.get("description") or "").strip() or None
                        specialty = (parsed.get("specialty") or "").strip() or None
                    except Exception as e:
                        logger.warning(f"EANM soft-fields JSON parse failed: {e}")

        if not description:
            description = self._first_paragraph(body)
        if not description and own:
            description = self._microsite_description(ext_url)

        if own:
            specialty = "Nuclear Medicine"      # EANM's own events: the whole society's field
        # Backstops are TITLE-only: these bodies are promotional boilerplate
        # (accreditation blurbs, topic lists) that mis-tag when classified.
        if not specialty and re.search(r"(?i)nuclear medicine|theranost|\bPET\b|radioligand|radiopharm|isotope", title):
            specialty = "Nuclear Medicine"
        if not specialty and re.search(r"(?i)patholog", title):
            specialty = "Pathology"
        if not specialty and re.search(r"(?i)neuroscience|neurolog", title):
            specialty = "Neurology"
        if not specialty:
            specialty = classify_specialty(title)

        if description and len(description) >= 40:
            result["description"] = description[:700]
        result["specialty"] = specialty
        return result
