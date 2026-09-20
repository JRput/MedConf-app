# extractors/rcsed.py
"""
Royal College of Surgeons of Edinburgh (RCSEd) — detail-page extractor.

RCSEd's real catalogue lives on the services.rcsed.ac.uk subdomain (a
custom, server-rendered CMS — no WordPress markers). The listing page
(https://services.rcsed.ac.uk/events-courses/rcsed-courses-and-events)
paginates via ?page=1..5 with ~15 items/page inside an accordion:

    dd.accordion-navigation.courseItem
      h4                          -> title
      div.content
        "All Locations: <text>"  -> location hint
        "CPD: <n> Hours"          -> CPD hint
        "Costs: From £X"          -> price hint
        a.expand[href]            -> the real detail URL

Detail pages carry a "Key Facts" panel (class `.keyFacts`) with the
canonical dated/venue/price info:

    <div class="panel keyFacts">
      <li>When is this course/event held? <date text>            </li>
      <li>Where is this course/event held? <location text>       </li>
      <li>How much does this cost? From £X - View more below     </li>
      <li>Is CPD awarded? Yes, N Hours/Points                     </li>
    </div>

Some pages have NO `.keyFacts` panel at all — usually courses that are
fully self-paced or have no scheduled instance right now. Those still
get a parent row; the next crawl retries when the college publishes a
new session.

Fees live in one of two shapes further down the page, both under a
"Costs" / "Course Fees" heading:
  - Layout A: `<ul class="feesList"><li><strong>Label</strong>: £X</li>`
  - Layout B: `<p>£X Label</p>` (price BEFORE the label text)

The "When is this X held?" text has three shapes we've observed:
  - "To be confirmed"                                  -> no date yet
  - "25 Nov 2026 (1 date)"                              -> single date
  - "16th & 17th May / 11th & 12th July 2026"           -> MULTIPLE
    date-groups (recurring course) — split on "/", each group becomes
    a `course_sessions` row. A shared trailing year applies to groups
    that don't carry their own year.
"""

import re
import html as _htmlmod
import json as _json
from datetime import date
from typing import Dict, Any, Optional, Callable, List, Tuple
import httpx
from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from .abstract_classifier import extract_abstract_info
from . import pricing_tables
from logger import logger


LISTING_URL = "https://services.rcsed.ac.uk/events-courses/rcsed-courses-and-events"
DETAIL_BASE = "https://services.rcsed.ac.uk"
MAX_PAGES = 8  # hard ceiling; recon observed 5 pages @ ~15/page (~75 items)

_ITEM_RE = re.compile(
    r'<dd class="accordion-navigation courseItem">(.*?)</dd>', re.DOTALL
)
_TITLE_RE = re.compile(r"<h4>(.*?)<i", re.DOTALL)
_HREF_RE = re.compile(r'class="button radius small success expand"\s+href="([^"]+)"')
_LOCATION_RE = re.compile(r"All Locations:</strong>\s*(.*?)</p>", re.DOTALL)
_DESC_RE = re.compile(r"Overview</h3>\s*<p>(.*?)</p>", re.DOTALL)
_VIEWING_TOTAL_RE = re.compile(r"Viewing.*?of\s*(\d+)", re.DOTALL)


def _clean_html_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = _htmlmod.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_RE = r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"

UK_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)

# RCSEd's own bricks-and-mortar venues (from the JSON-LD Organization
# schema every page carries). External venues (Cardiff, Kettering, ...)
# fall through to the generic UK city/region lookup below.
_KNOWN_VENUES = {
    "edinburgh": ("Nicolson Street, RCSEd", "Edinburgh", "Scotland"),
    "birmingham": ("The Walker Building, 58 Oxford Street, RCSEd", "Birmingham", "West Midlands"),
    "malaysia": ("Medical Academies of Malaysia, Putrajaya", "Putrajaya", None),
    "putrajaya": ("Medical Academies of Malaysia, Putrajaya", "Putrajaya", None),
}

_UK_REGIONS = {
    "london": "London", "manchester": "North West England", "liverpool": "North West England",
    "leeds": "Yorkshire and the Humber", "sheffield": "Yorkshire and the Humber",
    "york": "Yorkshire and the Humber", "newcastle": "North East England",
    "birmingham": "West Midlands", "bristol": "South West England", "exeter": "South West England",
    "plymouth": "South West England", "cardiff": "Wales", "swansea": "Wales",
    "edinburgh": "Scotland", "glasgow": "Scotland", "aberdeen": "Scotland", "dundee": "Scotland",
    "belfast": "Northern Ireland", "cambridge": "East of England", "norwich": "East of England",
    "oxford": "South East England", "brighton": "South East England", "leicester": "East Midlands",
    "nottingham": "East Midlands", "kettering": "East Midlands", "southampton": "South East England",
}


def _infer_uk_region(city: str) -> Optional[str]:
    c = (city or "").lower()
    for key, val in _UK_REGIONS.items():
        if key in c:
            return val
    return None


class RCSEdExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing override — server-rendered accordion, no browser needed
    # ------------------------------------------------------------------ #
    # browser.get_event_cards() finds 0 cards here: RCSEd's real catalogue
    # is a custom CMS (services.rcsed.ac.uk) whose listing renders as a
    # Foundation <dl class="accordion"> of <dd class="courseItem"> blocks,
    # not any of the generic card-container selectors the shared walker
    # recognises. The listing is plain server-rendered HTML (confirmed via
    # recon: platform=static_html, js_required=false), so httpx is enough
    # — no Playwright round-trip needed for the listing phase.
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        shells: List[Dict[str, Any]] = []
        seen_urls = set()
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                for page_num in range(1, MAX_PAGES + 1):
                    resp = client.get(LISTING_URL, params={"page": page_num})
                    resp.raise_for_status()
                    html = resp.text
                    items = _ITEM_RE.findall(html)
                    if not items:
                        break
                    for item_html in items:
                        title_m = _TITLE_RE.search(item_html)
                        href_m = _HREF_RE.search(item_html)
                        if not title_m or not href_m:
                            continue
                        title = _clean_html_text(title_m.group(1))
                        # Skip non-event info pages: competitions ("Competition
                        # Details | RCSEd Surgical Skills Competition 2024/25")
                        # are award schemes, not bookable events.
                        if re.search(r"competition", title, re.I):
                            continue
                        href = href_m.group(1)
                        url = href if href.startswith("http") else DETAIL_BASE + href
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        loc_m = _LOCATION_RE.search(item_html)
                        location_hint = _clean_html_text(loc_m.group(1)) if loc_m else None
                        desc_m = _DESC_RE.search(item_html)
                        description_hint = _clean_html_text(desc_m.group(1)) if desc_m else None
                        shells.append({
                            "title": title,
                            "booking_url": url,
                            "is_sold_out": False,  # refined per-page in extract_detail
                            "start_date": None,    # RCSEd doesn't give dates on the
                                                    # listing card — always detail-page derived
                            "start_time": None,
                            "location_hint": location_hint,
                            "description_hint": description_hint,
                            "page_index": page_num,
                        })
                    # Stop once we've reached the total the CMS reports
                    total_m = _VIEWING_TOTAL_RE.search(html)
                    if total_m and len(seen_urls) >= int(total_m.group(1)):
                        break
        except Exception as e:
            logger.warning(f"RCSEd listing override failed: {e}")
            return None

        if not shells:
            logger.warning("RCSEd listing override found 0 shells; falling back to DOM walker")
            return None

        logger.info(f"RCSEd: {len(shells)} shells found across listing pages")
        return shells

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        # Real title from the h1, never the listing shell text (mistake #11)
        try:
            h1 = page.evaluate("() => (document.querySelector('h1') || {}).textContent || ''")
        except Exception:
            h1 = ""
        result["conference_name"] = (h1 or "").strip() or shell.get("title")

        key_facts = self._extract_key_facts(page)

        # Dates + sessions (deterministic)
        when_text = key_facts.get("when") or ""
        date_groups = self._parse_when_text(when_text)
        sessions = self._build_sessions(date_groups)

        if len(date_groups) >= 2:
            # Recurring skills course — emit sessions[], parent event_type='course'
            result["event_type"] = "course"
            result["sessions"] = sessions
            upcoming = [s for s in sessions if s["start_date"]]
            if upcoming:
                upcoming.sort(key=lambda s: s["start_date"])
                result["start_date"] = upcoming[0]["start_date"]
                result["end_date"] = upcoming[0].get("end_date") or upcoming[0]["start_date"]
        elif len(date_groups) == 1:
            result["start_date"] = date_groups[0][0]
            result["end_date"] = date_groups[0][1] or date_groups[0][0]
        # else: "To be confirmed" / no .keyFacts panel — leave dates null,
        # self-healing re-fetch picks it up once RCSEd publishes a date.

        # Venue / city / region / format
        result.update(self._extract_venue(key_facts.get("where"), result.get("conference_name")))

        # CPD
        cpd_points, cpd_accredited = self._extract_cpd(key_facts.get("cpd"), page)
        result["cpd_points"] = cpd_points
        result["cpd_accredited"] = cpd_accredited

        # Pricing tiers (deterministic) — flat pricing applies to all sessions
        result["pricing_tiers"] = self._extract_pricing(page)

        # Abstracts (mostly relevant to the symposia/conferences, not courses).
        # Gate on the page actually mentioning "abstract": application-based
        # RCSEd courses (e.g. HEST-UK) publish "Applications are now open …
        # Application deadline - <date>" wording that the shared classifier
        # otherwise misreads as an abstract-submission window.
        page_text = page.evaluate("() => document.body.textContent || ''")
        if re.search(r"abstract", page_text, re.I):
            is_open, deadline = extract_abstract_info(page_text)
            result["abstract_open"] = is_open
            result["abstract_deadline"] = deadline.isoformat() if deadline else None
        else:
            result["abstract_open"] = False
            result["abstract_deadline"] = None

        # Sold-out at parent level only makes sense for single-session events
        if len(date_groups) <= 1:
            result["is_sold_out"] = bool(re.search(r"\bFULL\b", when_text)) or bool(
                key_facts.get("full")
            )

        # Soft fields (LLM + deterministic fallback)
        result.update(self._extract_soft_fields(page, shell, llm_call))

        return result

    # ------------------------------------------------------------------ #
    # Key Facts panel
    # ------------------------------------------------------------------ #
    def _extract_key_facts(self, page: Page) -> Dict[str, Any]:
        try:
            return page.evaluate(r"""() => {
                const kf = document.querySelector('.keyFacts');
                if (!kf) return {};
                const items = Array.from(kf.querySelectorAll(':scope > ul.no-bullet > li'));
                const out = {};
                for (const li of items) {
                    const strong = li.querySelector(':scope > strong');
                    if (!strong) continue;
                    const label = (strong.textContent || '').trim().toLowerCase();
                    if (/when is this/.test(label)) {
                        // "When" is a short direct-text value (no nested dropdown) —
                        // safe to read the li's own text minus the <strong> label.
                        const full = (li.textContent || '').replace(/\s+/g, ' ').trim();
                        out.when = full.replace(strong.textContent.trim(), '').trim();
                        if (/\bFULL\b/.test(full)) out.full = true;
                    } else if (/where is this/.test(label)) {
                        // "Where" li nests a nav-only dropdown (location names +
                        // per-date booking links) — read ONLY the <strong> location
                        // names inside it, never the li's full textContent (that
                        // would swallow the whole hidden dropdown, dates included).
                        const dd = li.querySelector('.f-dropdown');
                        const names = dd
                            ? Array.from(dd.querySelectorAll(':scope > li > strong')).map(s => (s.textContent || '').trim())
                            : [];
                        out.where = names.join(', ');
                        // "FULL" badge text runs straight into the next word
                        // with no space ("FULLJoin waiting list"), so a
                        // \bFULL\b regex misses it — match the badge element
                        // itself instead.
                        if (dd && dd.querySelector('.label.alert')) out.full = true;
                    } else if (/how much/.test(label)) {
                        out.cost = (li.textContent || '').replace(/\s+/g, ' ').trim();
                    } else if (/cpd/.test(label)) {
                        out.cpd = (li.textContent || '').replace(/\s+/g, ' ').trim();
                    }
                }
                return out;
            }""") or {}
        except Exception as e:
            logger.warning(f"RCSEd key-facts extraction failed: {e}")
            return {}

    # ------------------------------------------------------------------ #
    # Date parsing — "When is this held?" text
    # ------------------------------------------------------------------ #
    def _parse_when_text(self, text: str) -> List[Tuple[Optional[str], Optional[str]]]:
        """
        Returns a list of (start_iso, end_iso) tuples, one per date-group.
        "To be confirmed" or empty text -> [].
        """
        if not text:
            return []
        text = text.strip()
        if not text or re.search(r"to be confirmed|tbc", text, re.I):
            return []
        # Strip trailing "(N date)" / "(N dates)" markers and sold-out labels
        text = re.sub(r"\(\s*\d+\s*dates?\s*\)", "", text, flags=re.I)
        text = re.sub(r"\bFULL\b", "", text)

        # Find a fallback year — the last 4-digit year mentioned anywhere
        year_matches = re.findall(r"\b(20\d{2})\b", text)
        fallback_year = year_matches[-1] if year_matches else None

        groups = [g.strip() for g in text.split("/") if g.strip()]
        results: List[Tuple[Optional[str], Optional[str]]] = []
        for group in groups:
            days, month, year = self._parse_date_group(group, fallback_year)
            if not days or not month or not year:
                continue
            mon_num = _MONTHS.get(month.lower()[:3])
            if not mon_num:
                continue
            try:
                start = date(int(year), mon_num, min(days))
                end = date(int(year), mon_num, max(days)) if max(days) != min(days) else None
                results.append((start.isoformat(), end.isoformat() if end else None))
            except ValueError:
                continue
        return results

    @staticmethod
    def _parse_date_group(group: str, fallback_year: Optional[str]) -> Tuple[List[int], Optional[str], Optional[str]]:
        """Parse one date-group like '16th & 17th May 2026' or '25 Nov 2026'."""
        month_m = re.search(_MONTH_RE, group, re.I)
        month = month_m.group(1) if month_m else None
        days = [int(d) for d in re.findall(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", group)
                if 1 <= int(d) <= 31]
        year_m = re.search(r"\b(20\d{2})\b", group)
        year = year_m.group(1) if year_m else fallback_year
        return days, month, year

    # ------------------------------------------------------------------ #
    # Sessions (only built when >=2 date-groups exist — recurring course)
    # ------------------------------------------------------------------ #
    def _build_sessions(
        self, date_groups: List[Tuple[Optional[str], Optional[str]]],
    ) -> List[Dict[str, Any]]:
        if len(date_groups) < 2:
            return []
        # NOTE: RCSEd's per-location booking dropdown links (.f-dropdown a)
        # carry a courseDate query param, but its text format ("November
        # 2026") is too coarse to reliably re-associate with a specific
        # multi-day date-group parsed above. Rather than risk mismatching
        # a session to the wrong booking link/FULL flag, we leave
        # availability_status='unknown' and booking_url=None for each
        # session — both are legitimate "don't know yet" values per the
        # PLAYBOOK's course_sessions availability guidance, and the parent
        # detail URL still lets users find the right booking option.
        sessions: List[Dict[str, Any]] = []
        for start_iso, end_iso in date_groups:
            sessions.append({
                "start_date": start_iso,
                "end_date": end_iso,
                "start_time": None,
                "duration_text": None,
                "availability_status": "unknown",
                "spots_left": None,
                "booking_url": None,
                "notes": None,
            })
        return sessions

    # ------------------------------------------------------------------ #
    # Venue / city / region / format
    # ------------------------------------------------------------------ #
    def _extract_venue(self, where_text: Optional[str], title: Optional[str]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        text = (where_text or "").strip()
        title_l = (title or "").lower()

        if re.search(r"\b(online|webinar|virtual|zoom|microsoft teams|ms teams|livestream)\b", text, re.I) or \
           re.search(r"\b(online|webinar|virtual)\b", title_l):
            out["event_format"] = "online"
            out["venue_name"] = None
            out["city"] = None
            out["region"] = None
            return out

        if not text:
            return out  # unknown yet — leave null, self-healing retries

        # Known RCSEd venues first (Edinburgh / Birmingham / Malaysia)
        for key, (venue, city, region) in _KNOWN_VENUES.items():
            if re.search(rf"\b{re.escape(key)}\b", text, re.I):
                out["event_format"] = "in_person"
                out["venue_name"] = venue
                out["city"] = city
                out["region"] = region
                return out

        # External venue — strip postcode, walk the UK city lookup, else
        # take the leading clean token as the city name.
        cleaned = UK_POSTCODE_RE.sub("", text).strip(" ,")
        cleaned = re.sub(r"see location specific details", "", cleaned, flags=re.I).strip(" ,-")
        city = None
        for key in _UK_REGIONS:
            if re.search(rf"\b{re.escape(key)}\b", cleaned, re.I):
                city = key.title()
                break
        if not city and cleaned:
            # Take the first clean word-ish token as a best-effort city
            token = re.split(r"[,\-]", cleaned)[0].strip()
            city = token[:80] if token else None

        if not city:
            return out

        out["event_format"] = "in_person"
        out["venue_name"] = None
        out["city"] = city
        out["region"] = _infer_uk_region(city)
        return out

    # ------------------------------------------------------------------ #
    # CPD
    # ------------------------------------------------------------------ #
    def _extract_cpd(self, cpd_value: Optional[str], page: Page) -> Tuple[Optional[int], bool]:
        if cpd_value:
            m = re.search(r"(\d+)\s*(?:CPD\s*)?(?:hours?|points?|credits?)", cpd_value, re.I)
            if m:
                return int(m.group(1)), True
            if re.search(r"\byes\b", cpd_value, re.I):
                return None, True
        text = page.evaluate("() => document.body.textContent || ''")
        m = re.search(r"\b(\d+)\s*(?:CPD\s*)?(?:hours?|points?|credits?)\b", text, re.I)
        if m:
            return int(m.group(1)), True
        if re.search(r"\bCPD[- ]accredited|CPD[- ]approved\b", text, re.I):
            return None, True
        return None, False

    # ------------------------------------------------------------------ #
    # Pricing — two on-page layouts + shared pricing_tables fallback
    # ------------------------------------------------------------------ #
    def _extract_pricing(self, page: Page) -> List[Dict[str, Any]]:
        try:
            data = page.evaluate(r"""() => {
                const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4'));
                const feeH = headings.find(h => /^(course\s+)?(costs?|fees?|price[s]?)\s*:?$/i.test(h.textContent.trim()));
                if (!feeH) return {html: '', list: []};
                let html = '';
                let cur = feeH.nextElementSibling;
                let n = 0;
                while (cur && !/^H[1-4]$/.test(cur.tagName) && n < 8) {
                    html += cur.outerHTML;
                    cur = cur.nextElementSibling;
                    n++;
                }
                return {html};
            }""") or {}
        except Exception as e:
            logger.warning(f"RCSEd pricing section fetch failed: {e}")
            data = {}

        fee_html = data.get("html") or ""
        tiers: List[Dict[str, Any]] = []

        # Layout A: <li><strong>Label</strong>: £X</li>  (feesList)
        for m in re.finditer(r"<li[^>]*>(.*?)</li>", fee_html, re.DOTALL):
            item_html = m.group(1)
            text = re.sub(r"<[^>]+>", " ", item_html)
            text = re.sub(r"\s+", " ", text).strip()
            price = self.parse_gbp(text)
            if price is None:
                continue
            label = re.split(r"£", text)[0].strip(" :-")
            if not label:
                continue
            tiers.append({"tier_label": label[:120], "price_gbp": price,
                           "is_early_bird": bool(re.search(r"early[- ]?bird", label, re.I)),
                           "early_bird_deadline": None})

        # Layout B: <p>£X Label</p>  (price precedes label)
        if not tiers:
            for m in re.finditer(r"<p[^>]*>(.*?)</p>", fee_html, re.DOTALL):
                text = re.sub(r"<[^>]+>", " ", m.group(1))
                text = re.sub(r"\s+", " ", text).strip()
                if not text:
                    continue
                price = self.parse_gbp(text)
                if price is None:
                    continue
                label = re.sub(r"£\s*[0-9,]+(?:\.[0-9]+)?", "", text).strip(" :-")
                if not label:
                    label = "Standard"
                tiers.append({"tier_label": label[:120], "price_gbp": price,
                               "is_early_bird": bool(re.search(r"early[- ]?bird", label, re.I)),
                               "early_bird_deadline": None})

        # Shared fallback: plain-number <table> under a fee heading (try
        # before giving up, per PLAYBOOK guidance)
        if not tiers:
            try:
                full_html = page.content()
                tiers = pricing_tables.parse_pricing_tables(full_html, default_currency="GBP")
            except Exception as e:
                logger.warning(f"RCSEd pricing_tables fallback failed: {e}")

        # Layout C: some course pages have NO fee section at all — their
        # "View more information below" #costs anchor is a dead template
        # link — and the only price on the page is the FAQ line
        # "How much does this course cost? From £X". Emit it as a single
        # tier so the course isn't listed feeless when the site shows a fee.
        if not tiers:
            try:
                faq_text = page.evaluate(r"""() => {
                    const items = Array.from(document.querySelectorAll('li'));
                    const hit = items.find(li =>
                        /how much (does|will) this (course|event) cost/i.test(li.textContent || ''));
                    return hit ? (hit.textContent || '').replace(/\s+/g, ' ').trim() : '';
                }""") or ""
            except Exception:
                faq_text = ""
            m = re.search(r"From\s*£\s*([0-9,]+(?:\.[0-9]{2})?)", faq_text, re.I)
            if m:
                price = self.parse_gbp("£" + m.group(1))
                if price is not None:
                    tiers.append({"tier_label": "Course fee · From",
                                  "price_gbp": price,
                                  "is_early_bird": False,
                                  "early_bird_deadline": None})

        # Dedupe (label, price) — defends against responsive shadow copies
        seen = set()
        deduped = []
        for t in tiers:
            key = (t["tier_label"], t["price_gbp"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(t)
        return deduped

    # ------------------------------------------------------------------ #
    # Description + specialty (LLM, small prompt, heuristic fallback)
    # ------------------------------------------------------------------ #
    def _extract_soft_fields(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        # Overview / About section — walk siblings until the next H2/H3/H4,
        # per PLAYBOOK mistake #9 (don't pass raw body.innerText to the LLM).
        text = page.evaluate(r"""() => {
            function collectAfter(heading, cap) {
                let cur = heading.nextElementSibling;
                let collected = '';
                let n = 0;
                while (cur && !/^H[1-4]$/.test(cur.tagName) && n < cap) {
                    collected += (cur.textContent || '').trim() + ' ';
                    cur = cur.nextElementSibling;
                    n++;
                }
                return collected.replace(/\s+/g, ' ').trim();
            }
            const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4'));
            const overviewH = headings.find(h => /overview/i.test(h.textContent.trim()));
            if (overviewH) {
                const out = collectAfter(overviewH, 10);
                if (out.length > 40) return out;
            }
            // RCSEd repeats the course title as an H2/H3 right after the H1
            // on pages that skip a literal "Overview" heading (e.g. "The
            // 10th Surgical Approaches to the Spine") — that heading's
            // sibling content IS the overview prose.
            const h1 = document.querySelector('h1');
            const h1Text = h1 ? h1.textContent.trim() : '';
            if (h1) {
                const next = headings.find(h => h !== h1 && (
                    h.textContent.trim() === h1Text ||
                    new RegExp('^the\\s+' + h1Text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i').test(h.textContent.trim())
                ));
                if (next) {
                    const out = collectAfter(next, 4);
                    if (out.length > 40) return out;
                }
            }
            // Last resort: full body text, with nav/footer/scripts AND the
            // Cookiebot consent-banner dialog stripped out (mistake #9 —
            // that banner's "About / This website uses cookies…" text was
            // otherwise being fed to the LLM as if it were the page body).
            const main = document.querySelector('main, article, [role="main"]') || document.body;
            const clone = main.cloneNode(true);
            clone.querySelectorAll(
                'nav, footer, script, style, noscript, header, ' +
                '[id*="Cookiebot" i], [class*="Cookiebot" i], [class*="cookie" i], [id*="cookie" i]'
            ).forEach(n => n.remove());
            return clone.textContent.replace(/\s+/g, ' ').trim();
        }""")[:5000]

        title = shell.get("title") or ""
        prompt = f"""You are summarising a single medical course/event detail page. Extract ONLY two fields.

EVENT TITLE: {title}

PAGE BODY:
{text}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the page text" or null,
  "specialty": "primary clinical/surgical specialty (e.g. Trauma & Orthopaedics, ENT Surgery, General Surgery, Neurosurgery)" or null
}}"""

        result: Dict[str, Any] = {}
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
                raw = m.group(0)
            try:
                parsed = _json.loads(raw)
                result = {
                    "description": parsed.get("description"),
                    "specialty": parsed.get("specialty"),
                }
            except _json.JSONDecodeError as e:
                logger.warning(f"RCSEd soft-fields JSON parse failed: {e}; raw[:200]={raw[:200]!r}")

        # Heuristic specialty backstop
        if not result.get("specialty"):
            heuristic = classify_specialty(title, text)
            if heuristic:
                result["specialty"] = heuristic

        # Description fallback — first clean chunk of the Overview text
        if not result.get("description") and text:
            if len(text) > 40:
                result["description"] = self._truncate_to_sentence(text, 320)

        return result

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
