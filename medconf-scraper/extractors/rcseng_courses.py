# extractors/rcseng_courses.py
"""
Royal College of Surgeons of England — Courses extractor.

This source produces COURSES (event_type='course'), not conferences. A
course is one offering that runs on many dates (sometimes 50+ a year);
each scheduled run becomes a row in `course_sessions`. The data shape:

    conferences (event_type='course')   ← the course parent
      + course_sessions[]                ← one row per scheduled run
        - dates, venue, price, availability per row

Listing strategy
----------------
The /education-and-exams/courses/surgical/ listing is a JS-rendered
Angular SPA that only loads 10 items at a time with no obvious "next"
control. We bypass it entirely by reading sitemap.xml, which lists
every /education-and-exams/courses/search/<slug>/ URL directly. That
gives us the full catalogue (~48 URLs) without pagination gymnastics.

Detail page structure (verified)
--------------------------------
Each course detail page has a "Booking options" / "Approved regional
courses" section containing one `.bookingRow` per scheduled session:

    .bookingRow
      .optionDetails       (always-visible summary)
        .durationFrom → .day .month .year
        .durationTo   → .day .month .year
        .optionPrice  → "£990.00"
        .optionLocation → "Kettering, United Kingdom"
        .optionLink .soldOut → "Fully booked" (when applicable)
      .optionPanel         (expanded panel)
        .address > <address>  (full postal address)
        contact details, etc.

Some courses have zero `.bookingRow` rows — they're self-paced /
on-demand offerings without scheduled runs. They still get a parent
row in `conferences`; the next daily scrape picks up any new sessions
when they appear.
"""

import re
import httpx
from datetime import date, datetime
from typing import Dict, Any, Optional, Callable, List
from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from logger import logger


SITEMAP_URL = "https://www.rcseng.ac.uk/sitemap.xml"
COURSE_URL_RE = re.compile(
    r"https://www\.rcseng\.ac\.uk/education-and-exams/courses/search/[a-z0-9-]+/"
)

# Used for slug → title fallback when we haven't yet scraped the detail page.
# The proper title comes from the detail page h1 and replaces this at merge time.
def _slug_to_title(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.replace("-", " ").split()) if slug else "Course"


# Maps short month codes to numbers.
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


class RCSEngCoursesExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing override — sitemap instead of DOM walker
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as c:
                resp = c.get(SITEMAP_URL)
                resp.raise_for_status()
                xml = resp.text
        except Exception as e:
            logger.warning(f"RCSEng courses: sitemap fetch failed ({e}); falling back to DOM")
            return None

        urls = sorted(set(COURSE_URL_RE.findall(xml)))
        if not urls:
            logger.warning("RCSEng courses: no course URLs found in sitemap")
            return None

        logger.info(f"RCSEng courses: {len(urls)} courses found in sitemap")

        shells: List[Dict[str, Any]] = []
        for url in urls:
            slug = url.rstrip("/").split("/")[-1]
            shells.append({
                "title": _slug_to_title(slug),  # placeholder — detail h1 replaces it
                "booking_url": url,
                "is_sold_out": False,           # tracked per-session, not per-course
                "start_date": None,             # computed from sessions in detail extract
                "start_time": None,
                "location_hint": None,
                "description_hint": None,
                "category": "Course",
                "page_index": 1,
            })
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
        # 1. Real course name (the h1)
        try:
            h1 = page.evaluate("() => (document.querySelector('h1') || {}).textContent || ''")
        except Exception:
            h1 = ""
        course_name = (h1 or "").strip() or shell.get("title")

        # 2. Sessions — the .bookingRow rows
        sessions = self._extract_sessions(page)

        # 3. CPD points — body text scan
        body_text = page.evaluate("() => document.body.textContent || ''") or ""
        cpd_points, cpd_accredited = self._extract_cpd(body_text)

        # 4. Description — prefer the structured summary blurb, then first
        # paragraph of body, then LLM if both are absent.
        description = self._extract_description(page, course_name, llm_call)

        # 5. Specialty — heuristic from title + body
        specialty = classify_specialty(course_name, body_text)

        # 6. Compute parent course fields from sessions
        today_iso = date.today().isoformat()
        upcoming = [s for s in sessions if s["start_date"] and s["start_date"] >= today_iso]
        available = [s for s in upcoming if s["availability_status"] != "sold_out"]

        # Parent start_date = soonest available upcoming session, falling
        # through to soonest upcoming (even if sold out), falling through
        # to None.
        parent_start = None
        parent_end = None
        if available:
            available.sort(key=lambda s: s["start_date"])
            parent_start = available[0]["start_date"]
            parent_end = available[0].get("end_date") or parent_start
        elif upcoming:
            upcoming.sort(key=lambda s: s["start_date"])
            parent_start = upcoming[0]["start_date"]
            parent_end = upcoming[0].get("end_date") or parent_start

        # Parent venue/city/region — only set when every upcoming session
        # shares the same value (e.g. a course that always runs in London).
        # Otherwise leave null and the UI shows "Multiple locations".
        parent_venue = self._uniform([s["venue_name"] for s in upcoming if s.get("venue_name")])
        parent_city = self._uniform([s["city"] for s in upcoming if s.get("city")])
        parent_region = self._uniform([s["region"] for s in upcoming if s.get("region")])

        # Parent event_format
        parent_format = self._infer_parent_format(sessions, course_name, shell.get("booking_url") or "")

        return {
            "conference_name": course_name,
            "event_type": "course",
            "description": description,
            "specialty": specialty,
            "start_date": parent_start,
            "end_date": parent_end,
            "venue_name": parent_venue,
            "city": parent_city,
            "region": parent_region,
            "event_format": parent_format,
            "cpd_points": cpd_points,
            "cpd_accredited": cpd_accredited,
            "is_sold_out": False,  # course is never sold out as a whole — sessions are
            "abstract_open": False,  # courses don't take abstract submissions
            "abstract_deadline": None,
            "sessions": sessions,
            # Pricing tiers — one tier per session ("Course fee"), each with
            # its session_id slot so the scraper layer can wire it through.
            # We use the synthetic session __index__ key for now; the scraper
            # remaps after sessions get UUIDs assigned on insert.
            "pricing_tiers": self._build_pricing_tiers(sessions) or self._body_price_fallback(body_text),
        }

    # ------------------------------------------------------------------ #
    # Session extraction
    # ------------------------------------------------------------------ #
    def _extract_sessions(self, page: Page) -> List[Dict[str, Any]]:
        try:
            raw_rows = page.evaluate(r"""() => {
                const rows = Array.from(document.querySelectorAll('.bookingRow'));
                return rows.map((r, idx) => {
                    const pick = (root, sel) => {
                        const el = root.querySelector(sel);
                        return el ? (el.textContent || '').trim() : null;
                    };
                    const pickDate = (root) => {
                        if (!root) return { day: null, month: null, year: null };
                        return {
                            day:   pick(root, '.day'),
                            month: pick(root, '.month'),
                            year:  pick(root, '.year'),
                        };
                    };
                    return {
                        idx: idx,
                        from: pickDate(r.querySelector('.durationFrom')),
                        to:   pickDate(r.querySelector('.durationTo')),
                        price_text: pick(r, '.optionPrice'),
                        // Full textual content of the row — used to recover prices
                        // when .optionPrice is just a "View" toggle (happens on
                        // free courses) or only contains a non-GBP figure (e.g.
                        // overseas regional courses priced in local currency
                        // with a GBP equivalent further down the row).
                        row_text: (r.innerText || r.textContent || '').replace(/\s+/g,' ').trim().slice(0, 800),
                        location_text: pick(r, '.optionLocation'),
                        // Full postal address from the expanded panel
                        address_text: (() => {
                            const a = r.querySelector('.address address');
                            if (!a) return null;
                            return (a.innerText || a.textContent || '').replace(/\s+/g,' ').trim();
                        })(),
                        // .soldOut anywhere in the row means fully booked
                        is_sold_out: !!r.querySelector('.soldOut'),
                        // Phone / email contact in panel — useful for regional courses
                        // where you have to email the centre rather than book online
                        contact_text: (() => {
                            const c = r.querySelector('.packagePanel');
                            return c ? (c.textContent || '').replace(/\s+/g,' ').trim().slice(0, 400) : null;
                        })(),
                    };
                });
            }""") or []
        except Exception as e:
            logger.warning(f"RCSEng courses: .bookingRow probe failed: {e}")
            return []

        sessions: List[Dict[str, Any]] = []
        for raw in raw_rows:
            start_date = self._parse_iso(raw.get("from"))
            if not start_date:
                continue  # without a date, the row is unusable
            end_date = self._parse_iso(raw.get("to")) or start_date

            # Three-tier price extraction:
            # 1. .optionPrice text (the common case — "£990.00")
            # 2. Whole-row text (free-course toggles only show "View" in
            #    .optionPrice; the £0.00 lives elsewhere in the row;
            #    overseas regional courses show a non-GBP figure in
            #    .optionPrice with a GBP equivalent further down)
            # 3. Leave None → upper layer will try a body-level fallback
            price = self._parse_gbp(raw.get("price_text"))
            if price is None:
                price = self._parse_gbp(raw.get("row_text"))
            loc_text = (raw.get("location_text") or "").strip()
            addr_text = (raw.get("address_text") or "").strip()
            venue, city, region = self._parse_venue(loc_text, addr_text)

            is_sold = bool(raw.get("is_sold_out"))
            avail = "sold_out" if is_sold else "available"

            # duration_text shows a quick "DD Mon – DD Mon" summary
            dur = self._format_duration_text(start_date, end_date)

            sessions.append({
                "_idx": raw.get("idx", 0),
                "start_date": start_date,
                "end_date": end_date if end_date != start_date else None,
                "start_time": None,
                "duration_text": dur,
                "availability_status": avail,
                "spots_left": None,
                "booking_url": None,
                "venue_name": venue,
                "city": city,
                "region": region,
                "notes": (raw.get("contact_text") or None),
                # carry the price through so we can build a pricing tier per session
                "_price_gbp": price,
            })

        return sessions

    # ------------------------------------------------------------------ #
    # Pricing — one tier per session, attached via _idx
    # ------------------------------------------------------------------ #
    def _build_pricing_tiers(self, sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        tiers: List[Dict[str, Any]] = []
        for s in sessions:
            price = s.get("_price_gbp")
            if price is None:
                continue
            tiers.append({
                "tier_label": "Course fee",
                "price_gbp": price,
                "is_early_bird": False,
                "early_bird_deadline": None,
                # The scraper layer maps this to the real session UUID after insert.
                "_session_idx": s["_idx"],
            })
        return tiers

    def _body_price_fallback(self, body_text: str) -> List[Dict[str, Any]]:
        """
        Emit a single flat-priced tier (session_id=null) when no session-scoped
        price was found. Covers two real source patterns:

        - "Back to the Scalpel" — no .bookingRow at all, but the body text
          mentions "£150.00 2 Days 9.00 CPD Points" in the course summary.
        - The 12 self-paced courses without scheduled sessions where the
          source still publishes a flat price somewhere in the description.

        Heuristic: find the FIRST plausible-looking £ amount in the body
        (£10–£10,000 range). We deliberately stay conservative; a future
        false positive is better tolerated than guessing wrong on a free
        course or splash text.
        """
        if not body_text:
            return []
        for raw in re.findall(r"£\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)", body_text):
            try:
                value = float(raw.replace(",", ""))
            except ValueError:
                continue
            if 10 <= value <= 10_000:
                return [{
                    "tier_label": "Course fee",
                    "price_gbp": value,
                    "is_early_bird": False,
                    "early_bird_deadline": None,
                }]
        return []

    # ------------------------------------------------------------------ #
    # Description — Overview blurb → fallback paragraph → LLM
    # ------------------------------------------------------------------ #
    def _extract_description(
        self,
        page: Page,
        course_name: str,
        llm_call: Callable[[str], Optional[str]],
    ) -> Optional[str]:
        try:
            # The detail page exposes .itemDetailsSummary-blurb at the top
            blurb = page.evaluate(r"""() => {
                const el = document.querySelector('.itemDetailsSummary-blurb, .itemDetailsSummary');
                if (!el) return null;
                return (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
            }""")
        except Exception:
            blurb = None

        if blurb and len(blurb) > 40:
            return self._truncate_to_sentence(blurb, 320)

        # Fallback: take the first usable paragraph from the body
        try:
            paragraphs = page.evaluate(r"""() => {
                const ps = Array.from(document.querySelectorAll('article p, main p, .courseDetails p'));
                return ps.map(p => (p.innerText || p.textContent || '').replace(/\s+/g, ' ').trim())
                         .filter(t => t.length > 60);
            }""") or []
        except Exception:
            paragraphs = []

        first_para = next((p for p in paragraphs if p), None)
        if first_para:
            return self._truncate_to_sentence(first_para, 320)

        # Last resort — ask the LLM. Cheap because the prompt is small.
        if llm_call:
            try:
                text = page.evaluate("""() => {
                    const main = document.querySelector('main, article, [role=\"main\"]') || document.body;
                    return (main.innerText || main.textContent || '').replace(/\\s+/g, ' ').trim();
                }""")[:4000]
                prompt = f"""Summarise this surgical course in 30-50 words. Return ONLY the summary text, no JSON, no prefix.

COURSE: {course_name}

PAGE BODY:
{text}"""
                raw = llm_call(prompt)
                if raw:
                    raw = raw.strip().strip('"').strip("'")
                    if 40 < len(raw) < 600:
                        return raw
            except Exception as e:
                logger.warning(f"RCSEng courses LLM description failed: {e}")
        return None

    # ------------------------------------------------------------------ #
    # CPD
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_cpd(text: str) -> tuple[Optional[int], bool]:
        if not text:
            return None, False
        m = re.search(r"\b(\d+)\s*(?:CPD\s*)?(?:point|credit)s?\b", text, re.I)
        if m:
            try:
                return int(m.group(1)), True
            except ValueError:
                pass
        if re.search(r"\bCPD[- ]accredited|CPD[- ]approved\b", text, re.I):
            return None, True
        return None, False

    # ------------------------------------------------------------------ #
    # Format inference
    # ------------------------------------------------------------------ #
    @staticmethod
    def _infer_parent_format(
        sessions: List[Dict[str, Any]],
        course_name: str,
        booking_url: str,
    ) -> Optional[str]:
        # Slug / name hints first — wins for the dateless e-learning courses
        text = f"{course_name} {booking_url}".lower()
        if re.search(r"\b(online|virtual|e[- ]?learning|webinar|self[- ]paced)\b", text):
            return "online"

        if not sessions:
            return "in_person"  # most live courses default to in-person

        # Per-session: count physical vs online
        physical = 0
        online = 0
        for s in sessions:
            loc = (s.get("venue_name") or "") + " " + (s.get("city") or "")
            if re.search(r"\bonline\b|\bvirtual\b|\bteams\b|\bzoom\b", loc, re.I):
                online += 1
            elif s.get("city") or s.get("venue_name"):
                physical += 1
        if physical and online:
            return "hybrid"
        if online:
            return "online"
        return "in_person"

    # ------------------------------------------------------------------ #
    # Address parsing
    # ------------------------------------------------------------------ #
    UK_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)
    _COUNTRY_TOKENS = {"gb", "uk", "united kingdom", "england", "scotland", "wales", "northern ireland"}

    @classmethod
    def _parse_venue(cls, loc_text: str, addr_text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """
        loc_text: "Kettering, United Kingdom" (the summary line)
        addr_text: "Learnix Limited, Phoenix Leisure ... Kettering NN15 6PB United Kingdom email@..."
            (full postal address from the expanded panel)
        Returns (venue_name, city, region).
        """
        # City from the summary line (first comma-separated chunk)
        city = None
        if loc_text:
            parts = [p.strip() for p in loc_text.split(",") if p.strip()]
            non_country = [p for p in parts if p.lower() not in cls._COUNTRY_TOKENS]
            if non_country:
                city = non_country[0][:80]

        venue = None
        if addr_text:
            # Strip postcode + email so the venue name is clean
            cleaned = cls.UK_POSTCODE_RE.sub("", addr_text)
            cleaned = re.sub(r"\S+@\S+", "", cleaned)
            cleaned = re.sub(r"\bUnited Kingdom\b", "", cleaned, flags=re.I).strip(" ,")
            # Comma-split; first chunk is usually the venue name
            chunks = [p.strip() for p in cleaned.split(",") if p.strip()]
            if chunks:
                venue = chunks[0][:200]
            # Fallback city — use the second-to-last non-postcode chunk
            if not city and len(chunks) >= 2:
                city = chunks[-1][:80]

        region = cls._infer_uk_region(city) if city else None
        return venue, city, region

    _UK_REGIONS: Dict[str, str] = {
        "london": "London",
        "manchester": "North West England", "liverpool": "North West England",
        "warrington": "North West England", "preston": "North West England",
        "leeds": "Yorkshire and the Humber", "sheffield": "Yorkshire and the Humber",
        "york": "Yorkshire and the Humber", "doncaster": "Yorkshire and the Humber",
        "hull": "Yorkshire and the Humber",
        "newcastle": "North East England", "middlesbrough": "North East England",
        "sunderland": "North East England", "durham": "North East England",
        "birmingham": "West Midlands", "coventry": "West Midlands",
        "wolverhampton": "West Midlands", "stoke": "West Midlands",
        "bristol": "South West England", "exeter": "South West England",
        "plymouth": "South West England", "bath": "South West England",
        "cardiff": "Wales", "swansea": "Wales", "newport": "Wales",
        "edinburgh": "Scotland", "glasgow": "Scotland", "aberdeen": "Scotland",
        "dundee": "Scotland", "inverness": "Scotland",
        "belfast": "Northern Ireland",
        "cambridge": "East of England", "norwich": "East of England",
        "ipswich": "East of England", "luton": "East of England",
        "oxford": "South East England", "brighton": "South East England",
        "reading": "South East England", "southampton": "South East England",
        "portsmouth": "South East England", "kettering": "East Midlands",
        "leicester": "East Midlands", "nottingham": "East Midlands",
        "derby": "East Midlands", "northampton": "East Midlands",
    }

    @classmethod
    def _infer_uk_region(cls, city: str) -> Optional[str]:
        c = (city or "").lower()
        for key, val in cls._UK_REGIONS.items():
            if key in c:
                return val
        return None

    # ------------------------------------------------------------------ #
    # Utilities
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_iso(d: Optional[Dict[str, Any]]) -> Optional[str]:
        if not d:
            return None
        day = d.get("day"); month = d.get("month"); year = d.get("year")
        if not (day and month and year):
            return None
        m = _MONTHS.get(month.strip().lower()[:3])
        if not m:
            return None
        try:
            return f"{int(year):04d}-{m:02d}-{int(day):02d}"
        except ValueError:
            return None

    @staticmethod
    def _parse_gbp(text: Optional[str]) -> Optional[float]:
        if not text:
            return None
        m = re.search(r"£\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)", text)
        if not m:
            return None
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None

    @staticmethod
    def _uniform(values: List[Optional[str]]) -> Optional[str]:
        cleaned = [v for v in values if v]
        if not cleaned:
            return None
        unique = set(v.strip().lower() for v in cleaned)
        return cleaned[0] if len(unique) == 1 else None

    @staticmethod
    def _format_duration_text(start_iso: str, end_iso: Optional[str]) -> Optional[str]:
        try:
            s = datetime.strptime(start_iso, "%Y-%m-%d").date()
            if end_iso and end_iso != start_iso:
                e = datetime.strptime(end_iso, "%Y-%m-%d").date()
                days = (e - s).days + 1
                return f"{days} days"
            return "1 day"
        except Exception:
            return None

    @staticmethod
    def _truncate_to_sentence(text: str, max_chars: int = 320) -> str:
        text = text.strip()
        if len(text) <= max_chars:
            return text
        cut = text[:max_chars]
        candidates = [cut.rfind(p + " ") for p in (".", "!", "?")]
        last_end = max(candidates)
        if last_end > max_chars * 0.5:
            return cut[: last_end + 1].rstrip()
        return cut.rstrip() + "…"
