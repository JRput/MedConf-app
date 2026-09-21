"""
Faculty of Public Health (FPH) — events/courses/exams extractor.

Custom (non-WordPress) CMS. Listing at /events-courses-exams/ is server-
rendered with query-param pagination (`?pageSize=12&pageIndex=N`, N starting
at 1 — pageIndex=0 302-redirects). Two pages currently (~16 raw links, one
duplicate across pages, ~15 unique upcoming events). Every listing card and
detail page renders the SAME markup shape:

  listing card:
    <a class="h4 card-title " href="/events-courses-exams/<slug>/">TITLE</a>
    ...<svg>...</svg>
    <div>
      <span>28th Sep 2026</span>
        <span> - 12:00pm,</span>
        <span>Online</span>            <!-- or a full venue address -->
    </div>

  detail page header:
    <h1>TITLE</h1>
    <p class="article-options__date">
      <svg>...</svg>
      <span>
        20th November 2026,  9:00am
          <span> - 5:00pm,</span>
          <span>Royal College of Psychiatrists, 21 Prescot Street, London E1 8BB</span>
      </span>
    </p>
    <div class="row"><div class="col-md-12"><div class="d-flex ... gap-5">
      <!-- optional: only present when FPH itself takes the booking -->
      <a class="btn btn-tertiary" href="https://members.fph.org.uk/?...">Book event as an FPH member</a>
      <a class="btn btn-tertiary" href="https://members.fph.org.uk/?...">Book event as a non-member</a>
    </div></div></div>
    <article>...prose...</article>

No source page (listing or any of 8 detail pages probed) publishes a fee
amount anywhere — FPH's own site never shows a price, only a link to book
(either its own members-portal login gate, or an external organiser site).
So `pricing_tiers` is always `[]` here; that matches "no fee on page -> []",
not a bug. `cpd_points`/`cpd_accredited` are likewise never mentioned on any
probed page outside the site-wide nav ("Regional CPD Resources" etc.), which
we deliberately don't scrape from — CPD stays null/False for this source.

Booking URL: most events keep registration on FPH's own members portal via
the `.btn-tertiary` "Book event as ..." buttons in the header CTA row (scope
the query to that row — the SAME class is reused by unrelated site-wide nav
buttons like "Eligibility Checker" elsewhere on the page). Prefer the
non-member link (a "public" pathway; the member one just adds a login/tab
in the same portal) as `booking_url`. Some events instead point off-site
entirely (RCPsych's own calendar, Eventscase, a Teams meeting link) via a
plain sentence in the article prose ("Register via the conference website
here" / "please visit <link>") — when a `.btn-tertiary` pair is absent, we
look for the first off-fph.org.uk link in the article whose surrounding
text mentions register/book/sign up/attend/rsvp, and use that instead.
Falls back to the FPH detail page URL itself when neither is found (a small
number of events, e.g. an invite-only Specialty Registrars session, have no
public booking link at all).
"""

from __future__ import annotations

import re
import html as html_lib
from datetime import date
from typing import Dict, Any, Optional, Callable, List, Tuple
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Page

from .base import BaseExtractor
from .http_fetch import fetch_html
from .specialty_classifier import classify_specialty
from .abstract_classifier import extract_abstract_info
from .pricing_tables import parse_pricing_tables
from logger import logger


BASE_URL = "https://www.fph.org.uk"
LISTING_URL = f"{BASE_URL}/events-courses-exams/"
LISTING_PAGE_TEMPLATE = f"{BASE_URL}/events-courses-exams/?pageSize=12&pageIndex={{page}}"
MAX_LISTING_PAGES = 6  # safety cap; site currently has 2

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

UK_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)

_UK_REGIONS = {
    "london": "London",
    "manchester": "North West England",
    "liverpool": "North West England",
    "leeds": "Yorkshire and the Humber",
    "sheffield": "Yorkshire and the Humber",
    "york": "Yorkshire and the Humber",
    "newcastle": "North East England",
    "birmingham": "West Midlands",
    "bristol": "South West England",
    "exeter": "South West England",
    "plymouth": "South West England",
    "cardiff": "Wales",
    "swansea": "Wales",
    "edinburgh": "Scotland",
    "glasgow": "Scotland",
    "aberdeen": "Scotland",
    "dundee": "Scotland",
    "belfast": "Northern Ireland",
    "cambridge": "East of England",
    "norwich": "East of England",
    "oxford": "South East England",
    "brighton": "South East England",
    "leicester": "East Midlands",
    "nottingham": "East Midlands",
}

# Card / header date text: "28th Sep 2026" or "20th November 2026" — ordinal
# suffix on the day, month may be abbreviated (listing) or full (detail).
_DATE_RE = re.compile(
    r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,})\s+(\d{4})"
)
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*(am|pm)", re.I)

# Anchor text / surrounding-sentence keywords that mark an off-site link as
# the actual booking/registration link (as opposed to an unrelated citation
# link, e.g. a partner organisation's homepage).
_REGISTER_HINT_RE = re.compile(
    r"regist|\bbook\b|sign up|sign-up|rsvp|please visit|conference website|attend",
    re.I,
)

_CARD_RE = re.compile(
    r'<a class="h4 card-title[^"]*"\s+href="([^"]+)"[^>]*>\s*(.*?)\s*</a>'
    r'.*?</svg>\s*<div>(.*?)</div>',
    re.S,
)
_SPAN_RE = re.compile(r"<span>(.*?)</span>", re.S)


def _clean(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(s or "")).strip()


def _parse_date_text(text: str) -> Optional[str]:
    m = _DATE_RE.search(text or "")
    if not m:
        return None
    day, mon_text, year = m.groups()
    mon = _MONTHS.get(mon_text.lower()[:3])
    if not mon:
        return None
    try:
        return date(int(year), mon, int(day)).isoformat()
    except ValueError:
        return None


def _parse_time_text(text: str) -> Optional[str]:
    m = _TIME_RE.search(text or "")
    if not m:
        return None
    hour, minute, ampm = m.groups()
    hour = int(hour)
    if ampm.lower() == "pm" and hour != 12:
        hour += 12
    if ampm.lower() == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute}"


class FPHExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing phase
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        browser = getattr(self, "browser", None)
        shells: List[Dict[str, Any]] = []
        seen_urls = set()
        today = date.today()

        for page_num in range(1, MAX_LISTING_PAGES + 1):
            url = LISTING_PAGE_TEMPLATE.format(page=page_num)
            html = fetch_html(url, browser=browser)
            if not html:
                logger.warning(f"FPH: listing fetch failed for page {page_num}")
                break

            cards = _CARD_RE.findall(html)
            if not cards:
                # No more cards -> we've walked past the last page.
                break

            new_on_this_page = 0
            for href, title_html, date_block in cards:
                detail_url = urljoin(BASE_URL, html_lib.unescape(href))
                if detail_url in seen_urls:
                    continue
                seen_urls.add(detail_url)
                new_on_this_page += 1

                title = _clean(re.sub(r"<[^>]+>", "", title_html))
                spans = [_clean(s) for s in _SPAN_RE.findall(date_block)]
                date_text = spans[0] if len(spans) > 0 else ""
                time_text = spans[1] if len(spans) > 1 else ""
                location_hint = spans[2] if len(spans) > 2 else None

                start_date = _parse_date_text(date_text)
                if start_date and start_date < today.isoformat():
                    continue  # past event slipped onto the "upcoming" listing

                shells.append({
                    "title": title or None,
                    "booking_url": detail_url,
                    "start_date": start_date,
                    "start_time": _parse_time_text(time_text),
                    "location_hint": location_hint,
                })

            if new_on_this_page == 0:
                # Every card on this page was a duplicate of one already
                # seen (site sometimes repeats an item across page boundaries
                # near the boundary, e.g. one CHAD webinar shown on p1 & p2).
                # Only stop early if this ALSO wasn't the first page.
                if page_num > 1:
                    break

        logger.info(f"FPH: {len(shells)} upcoming shells from {page_num if shells else 0} listing page(s)")
        return shells

    # ------------------------------------------------------------------ #
    # Detail phase
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        url = shell.get("booking_url") or ""
        detail_html = fetch_html(url, browser=getattr(self, "browser", None), loaded_page=page) if url else None
        if not detail_html:
            logger.warning(f"FPH: detail fetch failed for {url}")
            return result

        try:
            page.set_content(detail_html, timeout=15000)
        except Exception as e:
            logger.warning(f"FPH: page.set_content failed for {url}: {e}")
            return result

        # 1. Conference name from h1 — never trust the listing shell title.
        h1 = (page.evaluate(r"""() => {
            const hs = Array.from(document.querySelectorAll('h1'));
            for (const h of hs) {
                const t = (h.textContent || '').trim();
                if (t) return t;
            }
            return '';
        }""") or "").strip()
        if h1:
            result["conference_name"] = h1
        title_for_soft_fields = h1 or shell.get("title")

        # 2. Dates + venue from the header's article-options__date block.
        start_date, start_time, end_time_text, venue_text = self._extract_header_date(page)
        result["start_date"] = start_date or shell.get("start_date")
        result["start_time"] = start_time or shell.get("start_time")
        # No probed page ever showed a distinct end date (all single-day
        # events) — leave end_date null rather than guess from the header's
        # end TIME, which belongs to the same day as start_date.
        result.update(self._extract_venue(venue_text or shell.get("location_hint")))

        # 3. Pricing — never observed on this source (booking always routes
        # to a members-portal login or an off-site organiser page), but try
        # the shared plain-number table parser as a defensive backstop in
        # case a future event publishes one directly.
        result["pricing_tiers"] = parse_pricing_tables(detail_html, default_currency="GBP")

        # 4. CPD — not published on any probed page; leave null/False rather
        # than fabricate. (Deliberately NOT regexing the whole body — the
        # site-wide nav mentions "Regional CPD Resources" on every page.)
        result["cpd_points"] = None
        result["cpd_accredited"] = False

        # 5. Booking URL override (members-portal buttons, else an off-site
        # register link found in the article prose).
        booking_override = self._extract_booking_url(page)
        if booking_override:
            result["booking_url"] = booking_override

        # 6. Abstract / poster submission info (deterministic)
        page_text = page.evaluate("() => document.body.textContent || ''") or ""
        is_open, deadline = extract_abstract_info(page_text)
        result["abstract_open"] = is_open
        result["abstract_deadline"] = deadline.isoformat() if deadline else None

        # 7. Description + specialty (LLM w/ deterministic fallback)
        result.update(self._extract_soft_fields(page, title_for_soft_fields, llm_call))

        return result

    # ------------------------------------------------------------------ #
    # Header date/time/venue block
    # ------------------------------------------------------------------ #
    def _extract_header_date(self, page: Page) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        try:
            parts = page.evaluate(r"""() => {
                const p = document.querySelector('.article-options__date');
                if (!p) return null;
                const outer = p.querySelector('span');
                if (!outer) return null;
                const nested = Array.from(outer.querySelectorAll('span'));
                const endTimeText = nested[0] ? (nested[0].textContent || '').trim() : '';
                const venueText = nested[1] ? (nested[1].textContent || '').trim() : '';
                const clone = outer.cloneNode(true);
                clone.querySelectorAll('span').forEach(s => s.remove());
                const startText = (clone.textContent || '').replace(/\s+/g, ' ').trim();
                return {startText, endTimeText, venueText};
            }""")
        except Exception as e:
            logger.warning(f"FPH header-date extraction failed: {e}")
            parts = None

        if not parts:
            return None, None, None, None

        start_text = parts.get("startText") or ""
        return (
            _parse_date_text(start_text),
            _parse_time_text(start_text),
            _clean(parts.get("endTimeText")) or None,
            _clean(parts.get("venueText")) or None,
        )

    # ------------------------------------------------------------------ #
    # Venue / city / region / format
    # ------------------------------------------------------------------ #
    def _extract_venue(self, location_value: Optional[str]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        loc = (location_value or "").strip().rstrip(".")
        if not loc:
            return out

        if re.search(r"\b(online|webinar|virtual|zoom|microsoft teams|ms teams|teams|livestream|live stream)\b", loc, re.I):
            out["event_format"] = "online"
            out["venue_name"] = None
            out["city"] = None
            out["region"] = None
            return out

        out["event_format"] = "in_person"

        address = UK_POSTCODE_RE.sub("", loc).strip(" ,.")

        city = None
        region = None
        for key in _UK_REGIONS:
            if re.search(rf"\b{re.escape(key)}\b", address, re.I):
                city = key.title()
                region = _UK_REGIONS[key]
                break

        if not city:
            parts = [p.strip() for p in address.split(",") if p.strip()]
            if parts:
                city = parts[-1][:80]
                region = self._infer_uk_region(city)

        venue = address
        if city:
            cut = re.split(rf"\b{re.escape(city)}\b", address, flags=re.I)[0].strip(" ,")
            venue = cut or address
        out["venue_name"] = venue[:200] if venue else None
        out["city"] = city
        out["region"] = region
        return out

    @staticmethod
    def _infer_uk_region(city: str) -> Optional[str]:
        c = (city or "").lower()
        for key, val in _UK_REGIONS.items():
            if key in c:
                return val
        return None

    # ------------------------------------------------------------------ #
    # Booking URL: header CTA buttons, else an off-site register link
    # found within the article prose.
    # ------------------------------------------------------------------ #
    def _extract_booking_url(self, page: Page) -> Optional[str]:
        try:
            cta = page.evaluate(r"""() => {
                const row = document.querySelector('.article-options');
                if (!row) return [];
                return Array.from(row.querySelectorAll('a.btn-tertiary')).map(a => ({
                    text: (a.textContent || '').trim(),
                    href: a.getAttribute('href') || '',
                }));
            }""") or []
        except Exception as e:
            logger.warning(f"FPH CTA-button extraction failed: {e}")
            cta = []

        book_links = [c for c in cta if re.search(r"book event", c.get("text", ""), re.I)]
        if book_links:
            non_member = next((c for c in book_links if re.search(r"non-member", c["text"], re.I)), None)
            chosen = non_member or book_links[0]
            href = chosen.get("href")
            if href:
                return urljoin(BASE_URL, href)

        # No member-portal CTA — look for an off-site link inside <article>
        # whose surrounding text reads like a registration pointer.
        try:
            article_links = page.evaluate(r"""() => {
                const art = document.querySelector('article');
                if (!art) return [];
                return Array.from(art.querySelectorAll('a[href]')).map(a => {
                    const parentText = (a.closest('p') || a.parentElement || a).textContent || '';
                    return {href: a.getAttribute('href') || '', context: parentText.trim().slice(0, 300)};
                });
            }""") or []
        except Exception as e:
            logger.warning(f"FPH article-link extraction failed: {e}")
            article_links = []

        for link in article_links:
            href = link.get("href") or ""
            if not href.startswith("http"):
                continue
            if urlparse(href).netloc.endswith("fph.org.uk"):
                continue
            if _REGISTER_HINT_RE.search(link.get("context") or ""):
                return href

        return None

    # ------------------------------------------------------------------ #
    # Description + specialty (LLM, small prompt, heuristic fallback)
    # ------------------------------------------------------------------ #
    def _extract_soft_fields(
        self,
        page: Page,
        title: Optional[str],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        # Article prose only — strip anything that could leak nav/CTA/legal
        # boilerplate into the LLM prompt (HQ LESSONS #9).
        text = page.evaluate(r"""() => {
            const art = document.querySelector('article');
            if (!art) return '';
            const clone = art.cloneNode(true);
            clone.querySelectorAll('script, style, nav, footer').forEach(n => n.remove());
            return clone.textContent.replace(/\s+/g, ' ').trim();
        }""")[:5000]

        prompt = f"""You are summarising a single medical/public-health event detail page. Extract ONLY two fields.

EVENT TITLE: {title}

PAGE BODY:
{text}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the page text" or null,
  "specialty": "primary clinical/topic area (e.g. Public Health, Health Protection, Mental Health, Epidemiology)" or null
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
                import json
                parsed = json.loads(raw)
                result = {
                    "description": parsed.get("description"),
                    "specialty": parsed.get("specialty"),
                }
            except Exception as e:
                logger.warning(f"FPH soft-fields JSON parse failed: {e}; raw[:200]={raw[:200]!r}")

        if not result.get("specialty"):
            result["specialty"] = classify_specialty(title, text) or "Public Health"

        if not result.get("description") and text and len(text) > 40:
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
