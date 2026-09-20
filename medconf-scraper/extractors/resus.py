# extractors/resus.py
"""
Resuscitation Council UK — Courses extractor (source 29).

Site is Drupal 10 + Commerce, fully server-rendered (js_required=false).

Listing strategy
----------------
The hub /training-courses links ~22 course pages (plus a few non-course
info pages we denylist). list_shells_override() fetches the hub with
httpx and emits ONE shell per course page — no browser pagination walk.

Detail page structure (verified 2026-08-15 on 4 pages)
------------------------------------------------------
Each course page server-renders:
  - <h1> = canonical course name (e.g. "ALS: 2 Day Course (Advanced
    Life Support) Course")
  - A Drupal Views "course availability" table
    (`<table class="table table-hover table-striped">`) with columns:
    Course centre town | Course centre | Start date | Organiser | Availability
    Rows carry class "course-available"; dates render as
    "Tuesday <br /> 18 Aug. '26"; availability cell text is
    "Candidates: places available" or "Candidates: course full"
    (optionally "+ Faculty: required").
  - Pagination via ?page=0..N (5 rows/page, up to ~37 pages for e-ALS).
    Last page number is in `pager__item--last` → href="?page=N".
  - A separate CPD-points table listing points per course flavour
    (ALS two-day=10, e-ALS=5, ILS=5, ...). We longest-substring-match
    the row label against the h1 to pick the right row.
  - Pure e-learning pages (e.g. Anaphylaxis essentials) have NO
    availability table → parent row with sessions=[] and format=online.

FEES ARE NOT PUBLISHED — each Course Centre sets its own fee locally and
booking is by contacting the organiser directly. We therefore emit NO
pricing tiers, ever, for this source. Do not "fix" this by scraping a
number; there isn't one.

Session pages are fetched with httpx (server-rendered HTML, no JS
needed) so we never navigate the Playwright page away from the detail
URL (PLAYBOOK mistake #10). GitHub Actions runners get a 403 from
resus.org.uk on datacenter IPs, so both the hub fetch and the session
walk go through extractors.http_fetch.fetch_html(), which falls back
to a throwaway browser page (opened fresh from the same context, never
the caller's page) when httpx is blocked.
"""

import html
import re
from datetime import date
from typing import Dict, Any, Optional, Callable, List, Tuple
from playwright.sync_api import Page

from .base import BaseExtractor
from .http_fetch import fetch_html
from .specialty_classifier import classify_specialty
from logger import logger


BASE = "https://www.resus.org.uk"
HUB_URL = f"{BASE}/training-courses"
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (MedConf scraper)"}

# Hub links that are NOT course pages (info / hub pages).
_NON_COURSE_SLUGS = {
    "instructor-courses",          # category hub (its children ARE courses)
    "information-instructors",     # instructor info page
    "dentalprofessionals",         # guidance page, not a bookable course
}

# Safety cap on ?page=0..N walking per course (5 sessions/page).
MAX_SESSION_PAGES = 40

# "18 Aug. '26" — Drupal short months with trailing dot ("May." included).
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DATE_RE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,4})\.?\s+'(\d{2})\b")

_AVAIL_TABLE_RE = re.compile(
    r'<table class="table table-hover[^"]*">.*?</table>', re.S
)
_ROW_RE = re.compile(r'<tr class="([^"]*)">(.*?)</tr>', re.S)
_LAST_PAGE_RE = re.compile(r'pager__item--last.*?href="\?page=(\d+)"', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(raw_html: str) -> str:
    text = re.sub(r"\s+", " ", _TAG_RE.sub(" ", raw_html or "")).strip()
    return html.unescape(text)


def _cell(row_html: str, header_id_fragment: str) -> Optional[str]:
    m = re.search(
        r'headers="view-' + header_id_fragment + r'-table-column"[^>]*>(.*?)</td>',
        row_html, re.S,
    )
    return _strip_tags(m.group(1)) if m else None


class ResusExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing override — hub page instead of DOM walker
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = fetch_html(HUB_URL, browser=getattr(self, "browser", None),
                           headers=HTTP_HEADERS, timeout=30.0)
        if html is None:
            logger.warning("Resus: hub fetch failed (httpx + browser fallback); falling back to DOM")
            return None

        paths = sorted(set(re.findall(r'href="(/training-courses/[^"#?]+)"', html)))
        shells: List[Dict[str, Any]] = []
        for path in paths:
            slug = path.rstrip("/").split("/")[-1]
            if slug in _NON_COURSE_SLUGS:
                continue
            shells.append({
                "title": " ".join(w.capitalize() for w in slug.replace("-", " ").split()),
                "booking_url": BASE + path,
                "is_sold_out": False,      # tracked per-session
                "start_date": None,        # computed from sessions
                "start_time": None,
                "location_hint": None,
                "description_hint": None,
                "category": "Course",
                "page_index": 1,
            })

        if not shells:
            logger.warning("Resus: no course links found on hub; falling back to DOM")
            return None
        logger.info(f"Resus: {len(shells)} course pages found on hub")
        return shells

    # ------------------------------------------------------------------ #
    # Detail extraction
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        detail_url = shell.get("booking_url") or ""

        # 1. Canonical course name from the detail h1 (never trust shell title)
        try:
            h1 = page.evaluate(
                "() => (document.querySelector('h1') || {}).textContent || ''"
            )
        except Exception:
            h1 = ""
        course_name = (h1 or "").strip() or shell.get("title")

        # 2. Body text (page 0) — CPD + specialty input. textContent, not innerText.
        try:
            body_text = page.evaluate("() => document.body.textContent || ''") or ""
        except Exception:
            body_text = ""

        # 3. Sessions — walk ?page=0..last via httpx (server-rendered)
        sessions = self._extract_sessions(detail_url)

        # 4. CPD — course-specific row of the shared CPD-points table
        cpd_points, cpd_accredited = self._extract_cpd(page, course_name, body_text)

        # 5. Description — first real paragraph of the course prose, LLM last
        description = self._extract_description(page, course_name, llm_call)

        # 6. Specialty — deterministic classifier (resus courses are
        #    cross-specialty; the classifier + title usually lands on
        #    Emergency Medicine / Paediatrics / etc.)
        specialty = classify_specialty(course_name, body_text[:5000])

        # 7. Parent fields from sessions
        today_iso = date.today().isoformat()
        upcoming = [s for s in sessions if s["start_date"] and s["start_date"] >= today_iso]
        available = [s for s in upcoming if s["availability_status"] != "sold_out"]

        parent_start = None
        pool = available or upcoming
        if pool:
            pool = sorted(pool, key=lambda s: s["start_date"])
            parent_start = pool[0]["start_date"]

        parent_venue = self._uniform([s.get("venue_name") for s in upcoming])
        parent_city = self._uniform([s.get("city") for s in upcoming])
        parent_region = self._uniform([s.get("region") for s in upcoming])

        return {
            "conference_name": course_name,
            "event_type": "course",
            "description": description,
            "specialty": specialty,
            "start_date": parent_start,
            "end_date": self._end_from_duration(parent_start, course_name),
            "venue_name": parent_venue,
            "city": parent_city,
            "region": parent_region,
            "event_format": self._infer_format(course_name, detail_url, upcoming),
            "cpd_points": cpd_points,
            "cpd_accredited": cpd_accredited,
            "is_sold_out": False,   # per-session, never for the whole course
            "abstract_open": False,
            "abstract_deadline": None,
            "sessions": upcoming,
            # FEES NOT PUBLISHED by this source (set locally per Course
            # Centre) — always empty, never fabricate.
            "pricing_tiers": [],
        }

    # ------------------------------------------------------------------ #
    # Sessions — httpx walk of the Drupal Views availability table
    # ------------------------------------------------------------------ #
    def _extract_sessions(self, detail_url: str) -> List[Dict[str, Any]]:
        if not detail_url:
            return []
        sessions: List[Dict[str, Any]] = []
        seen: set = set()
        browser = getattr(self, "browser", None)
        try:
            last_page = 0
            page_no = 0
            while page_no <= min(last_page, MAX_SESSION_PAGES - 1):
                url = f"{detail_url}?page={page_no}"
                html = fetch_html(url, browser=browser, headers=HTTP_HEADERS, timeout=30.0)
                if html is None:
                    logger.warning(f"Resus: session page fetch failed {url}")
                    break
                if page_no == 0:
                    m = _LAST_PAGE_RE.search(html)
                    if m:
                        last_page = int(m.group(1))
                rows = self._parse_rows(html)
                if not rows and page_no > 0:
                    break  # walked past the end
                for s in rows:
                    key = (s["start_date"], s.get("venue_name"), s.get("city"))
                    if key in seen:
                        continue
                    seen.add(key)
                    sessions.append(s)
                page_no += 1
        except Exception as e:
            logger.warning(f"Resus: session walk failed for {detail_url}: {e}")
        return sessions

    def _parse_rows(self, html: str) -> List[Dict[str, Any]]:
        m = _AVAIL_TABLE_RE.search(html)
        if not m:
            return []  # pure e-learning course — no availability table
        out: List[Dict[str, Any]] = []
        for row_cls, row_html in _ROW_RE.findall(m.group(0)):
            town = _cell(row_html, "field-course-centre-town")
            centre = _cell(row_html, "field-course-centre")
            date_text = _cell(row_html, "field-start-date-1")
            organiser = _cell(row_html, "field-organiser")
            avail_text = _cell(row_html, "nothing") or ""

            start_date = self._parse_date(date_text or "")
            if not start_date:
                continue  # undated row is unusable

            avail = "unknown"
            low = avail_text.lower()
            if "course full" in low or "sold out" in low or "fully booked" in low:
                avail = "sold_out"
            elif "places available" in low:
                avail = "available"
            elif "limited" in low or "last few" in low:
                avail = "limited"
            if "course-full" in row_cls:
                avail = "sold_out"

            city = self._clean_city(town)
            out.append({
                "start_date": start_date,
                "end_date": None,      # only start dates are published
                "start_time": None,
                "duration_text": None,
                "availability_status": avail,
                "spots_left": None,    # never published as a number
                "booking_url": None,   # booking is via the organiser contact
                "venue_name": (centre or None),
                "city": city,
                "region": self._infer_uk_region(city) if city else None,
                "notes": (f"Organiser: {organiser}" if organiser else None),
            })
        return out

    UK_POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", re.I)

    @classmethod
    def _clean_city(cls, town: Optional[str]) -> Optional[str]:
        if not town:
            return None
        t = town.strip()
        if not t or cls.UK_POSTCODE_RE.match(t):
            return None
        return t[:80]

    @staticmethod
    def _parse_date(text: str) -> Optional[str]:
        m = _DATE_RE.search(text)
        if not m:
            return None
        day, mon, yy = m.groups()
        month = _MONTHS.get(mon.lower()[:3])
        if not month:
            return None
        try:
            return f"{2000 + int(yy):04d}-{month:02d}-{int(day):02d}"
        except ValueError:
            return None

    # ------------------------------------------------------------------ #
    # CPD — pick the right row of the shared CPD-points table
    # ------------------------------------------------------------------ #
    def _extract_cpd(
        self, page: Page, course_name: str, body_text: str
    ) -> Tuple[Optional[int], bool]:
        try:
            rows = page.evaluate(r"""() => {
                const out = [];
                for (const tbl of document.querySelectorAll('table')) {
                    const head = (tbl.querySelector('thead') || {}).textContent || '';
                    if (!/CPD\s*points/i.test(head)) continue;
                    for (const tr of tbl.querySelectorAll('tbody tr')) {
                        const tds = Array.from(tr.querySelectorAll('td'))
                            .map(td => (td.textContent || '').trim());
                        if (tds.length >= 2) out.push(tds);
                    }
                }
                return out;
            }""") or []
        except Exception:
            rows = []

        points = self._match_cpd_row(rows, course_name)
        accredited = points is not None or bool(
            re.search(r"\bCPD\b|continuing professional development", body_text, re.I)
        )
        return points, accredited

    @staticmethod
    def _match_cpd_row(rows: List[List[str]], course_name: str) -> Optional[int]:
        """
        Row labels look like "ALS (two day course)", "e-ALS (one day course)",
        "NLS / OH-NLS / NLS recertification". Normalise both sides and pick
        the LONGEST label variant that appears in the course name — so
        "ALS Recertification" prefers the recert row over the plain ALS row,
        and "e-ALS" prefers e-ALS over ALS.
        """
        def norm(s: str) -> str:
            s = re.sub(r"\([^)]*\)", " ", s or "")           # drop parentheticals
            s = re.sub(r"[^a-z0-9\- ]", " ", s.lower())
            return re.sub(r"\s+", " ", s).strip()

        name = norm(course_name)
        best: Tuple[int, Optional[int]] = (0, None)  # (label_len, points)
        for row in rows:
            label, points_text = row[0], row[1]
            m = re.search(r"\d+", points_text or "")
            if not m:
                continue
            points = int(m.group(0))
            for variant in label.split("/"):
                v = norm(variant)
                if not v:
                    continue
                # match as a whole token sequence inside the course name
                if re.search(r"(?:^| )" + re.escape(v) + r"(?: |$)", name):
                    if len(v) > best[0]:
                        best = (len(v), points)
        return best[1]

    # ------------------------------------------------------------------ #
    # Description — first substantial prose paragraph, LLM last resort
    # ------------------------------------------------------------------ #
    def _extract_description(
        self,
        page: Page,
        course_name: str,
        llm_call: Callable[[str], Optional[str]],
    ) -> Optional[str]:
        try:
            paragraphs = page.evaluate(r"""() => {
                const root = document.querySelector('main, article, [role="main"]')
                             || document.body;
                return Array.from(root.querySelectorAll('p'))
                    .map(p => (p.textContent || '').replace(/\s+/g, ' ').trim())
                    .filter(t => t.length > 60);
            }""") or []
        except Exception:
            paragraphs = []

        _noise = re.compile(
            r"cookie|privacy|charity (no|number)|registered charity|sign up|"
            r"newsletter|©|\bT\s*\+?44|@resus\.org", re.I,
        )
        first = next((p for p in paragraphs if not _noise.search(p)), None)
        if first:
            return self._truncate_to_sentence(first, 320)

        if llm_call:
            try:
                text = (page.evaluate("""() => {
                    const main = document.querySelector('main, article, [role="main"]')
                                 || document.body;
                    return (main.textContent || '').replace(/\\s+/g, ' ').trim();
                }""") or "")[:4000]
                prompt = (
                    "Summarise this resuscitation training course in 30-50 words. "
                    "Return ONLY the summary text, no JSON, no prefix.\n\n"
                    f"COURSE: {course_name}\n\nPAGE BODY:\n{text}"
                )
                raw = llm_call(prompt)
                if raw:
                    raw = raw.strip().strip('"').strip("'")
                    if 40 < len(raw) < 600:
                        return raw
            except Exception as e:
                logger.warning(f"Resus: LLM description failed: {e}")
        return None

    # ------------------------------------------------------------------ #
    # Format / dates
    # ------------------------------------------------------------------ #
    @staticmethod
    def _infer_format(
        course_name: str, url: str, upcoming: List[Dict[str, Any]]
    ) -> Optional[str]:
        if upcoming:
            return "in_person"  # scheduled runs are at physical course centres
        if re.search(r"\be[- ]?learning\b|\bonline\b|\bvirtual\b|\be-(als|ils)\b",
                     f"{course_name} {url}", re.I):
            return "online"
        return None  # unknown → retry next run (self-healing)

    @staticmethod
    def _end_from_duration(start_iso: Optional[str], course_name: str) -> Optional[str]:
        """'ALS: 2 Day Course' → start + 1 day. Anything else → same day/None."""
        if not start_iso:
            return None
        m = re.search(r"\b(\d)\s*[- ]?day\b", course_name, re.I)
        if m and int(m.group(1)) > 1:
            from datetime import datetime, timedelta
            try:
                d = datetime.strptime(start_iso, "%Y-%m-%d").date()
                return (d + timedelta(days=int(m.group(1)) - 1)).isoformat()
            except ValueError:
                pass
        return start_iso

    # ------------------------------------------------------------------ #
    # Region + utils
    # ------------------------------------------------------------------ #
    _UK_REGIONS: Dict[str, str] = {
        "london": "London",
        "manchester": "North West England", "liverpool": "North West England",
        "warrington": "North West England", "preston": "North West England",
        "blackpool": "North West England", "bolton": "North West England",
        "leeds": "Yorkshire and the Humber", "sheffield": "Yorkshire and the Humber",
        "york": "Yorkshire and the Humber", "doncaster": "Yorkshire and the Humber",
        "hull": "Yorkshire and the Humber", "bradford": "Yorkshire and the Humber",
        "newcastle": "North East England", "middlesbrough": "North East England",
        "sunderland": "North East England", "durham": "North East England",
        "birmingham": "West Midlands", "coventry": "West Midlands",
        "wolverhampton": "West Midlands", "stoke": "West Midlands",
        "bristol": "South West England", "exeter": "South West England",
        "plymouth": "South West England", "bath": "South West England",
        "truro": "South West England", "gloucester": "South West England",
        "cardiff": "Wales", "swansea": "Wales", "newport": "Wales",
        "wrexham": "Wales", "bangor": "Wales",
        "edinburgh": "Scotland", "glasgow": "Scotland", "aberdeen": "Scotland",
        "dundee": "Scotland", "inverness": "Scotland", "stirling": "Scotland",
        "belfast": "Northern Ireland", "derry": "Northern Ireland",
        "cambridge": "East of England", "norwich": "East of England",
        "ipswich": "East of England", "luton": "East of England",
        "chelmsford": "East of England", "peterborough": "East of England",
        "oxford": "South East England", "brighton": "South East England",
        "reading": "South East England", "southampton": "South East England",
        "portsmouth": "South East England", "guildford": "South East England",
        "milton keynes": "South East England", "canterbury": "South East England",
        "kettering": "East Midlands", "leicester": "East Midlands",
        "nottingham": "East Midlands", "derby": "East Midlands",
        "northampton": "East Midlands", "lincoln": "East Midlands",
    }

    @classmethod
    def _infer_uk_region(cls, city: str) -> Optional[str]:
        c = (city or "").lower()
        for key, val in cls._UK_REGIONS.items():
            if key in c:
                return val
        return None

    @staticmethod
    def _uniform(values: List[Optional[str]]) -> Optional[str]:
        cleaned = [v for v in values if v]
        if not cleaned:
            return None
        unique = set(v.strip().lower() for v in cleaned)
        return cleaned[0] if len(unique) == 1 else None

    @staticmethod
    def _truncate_to_sentence(text: str, max_chars: int = 320) -> str:
        text = text.strip()
        if len(text) <= max_chars:
            return text
        cut = text[:max_chars]
        last_end = max(cut.rfind(p + " ") for p in (".", "!", "?"))
        if last_end > max_chars * 0.5:
            return cut[: last_end + 1].rstrip()
        return cut.rstrip() + "…"
