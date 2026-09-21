"""
Faculty of Pharmaceutical Medicine (FPM) — events extractor.

Custom WordPress theme (not Tribe Events — /wp-json/tribe/... 404s). Listing
page (https://www.fpm.org.uk/events/) renders server-side
`<article class="post-... events">` cards — no JS rendering needed, so this
extractor overrides listing via a direct HTML fetch + regex, same pattern as
fom.py/rcpsych.py, through the shared `http_fetch.fetch_html()` helper.
Pagination is `/events/page/N/` (6 cards p1, 3 p2 at onboarding — 9 total,
no p3).

Card shape:

    <article class="post-NNNNN events ... events_cats-online events_cats-...">
        ...
        <span class="post-category category-grey">Online</span>
        <h2>Title</h2>
        <p class="post-content-post-date">
            Thursday 1 October 2026  <br>10:00 - 17:00
        </p>
        ...
    </article>
    <a href="/event/<slug>/" aria-label="Read more about Title"></a>

The `events_cats-*` classes / `post-category` badges are a reliable,
deterministic signal for event_format (Online / In-Person / hybrid-both)
and for members-only/free-to-attend flags — used instead of trying to
parse prose venue mentions for that split.

Detail-page shape is consistent across the WHOLE mixed catalogue (courses,
webinars, the AGM, the flagship conference all share one theme):

    <h1>Title</h1>
    <p style="margin-bottom:0;"><b>DayName D Month YYYY<br> HH:MM - HH:MM</p>

— except the flagship "FPM Annual Conference" page, which uses a different
hero-block template (nested/styled <h1>, no dated <p> under it) and states
its date/venue in a `content-block-col-2` prose paragraph instead
(`<strong>Tuesday 24 November 2026</strong><br /><strong>10 Union Street,
London or Online</strong>`) — handled by `_HERO_VENUE_DATE_RE` as a fallback
when the standard header paragraph isn't found.

3 detail layouts probed for pricing (all deterministic, no LLM):
  1. A proper `<table>` under an "Ticket Prices" heading, columns
     Location | Ticket Type | Pricing (FPM Annual Conference) — parsed by
     `_extract_table_pricing()`, composite label `Location · Ticket Type`.
  2. Plain-prose "Label: £NNN" / "Label: Free" lines under a
     "Price Options" / fee heading (webinars, DPM training courses) —
     parsed by `_extract_prose_pricing()`.
  3. No price stated at all (bookings closed pages, member-portal-gated
     pricing, free-to-attend social events) — `pricing_tiers` stays `[]`,
     never fabricated.

Multi-date courses: "Understanding Real-World Studies and Evidence" states
"This course will take place online on the following dates:" followed by
2+ plain date lines — turned into `sessions[]` (event_type='course'), same
pattern as alsg.py/resus.py. Single-date DPM training modules (SAQ/CAP/MCQ
exam-revision) are NOT sessions of one course — each module is its own
listing/detail page and is emitted as its own `event_type='course'` row
with no sessions.

Deliberately skipped from the listing:
  - "FPM Sponsorship Opportunities" / anything with "sponsorship" in the
    title — not a dated event.
  - Anything under "FPM On Demand" — recorded content, not a live/bookable
    upcoming event (per PLAYBOOK: skip and flag in concerns when unsure).
Neither appeared in the live 9-card listing at onboarding time, but the
title filter guards against them reappearing.

No numeric CPD points are published anywhere on fpm.org.uk (only "Gain CPD
points" banners / "self-allocate your CPD points" guidance) — `cpd_points`
is always None; `cpd_accredited` is True wherever a "CPD Credits"/"Gain CPD"
section is present on the page, else False.
"""

from __future__ import annotations

import html as html_lib
import re
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from .abstract_classifier import extract_abstract_info
from .http_fetch import fetch_html
from logger import logger


BASE_URL = "https://www.fpm.org.uk"
LISTING_URL = f"{BASE_URL}/events/"
PAGE_URL_TMPL = f"{BASE_URL}/events/page/{{n}}/"
MAX_PAGES = 6  # safety cap; the live catalogue is 2 pages / 9 events

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

ARTICLE_RE = re.compile(r'<article[^>]*class="([^"]*)"[^>]*>(.*?)</article>', re.S)
LINK_RE = re.compile(r'<a href="([^"]+)"\s+aria-label="Read more', re.S)
TITLE_RE = re.compile(r"<h2>(.*?)</h2>", re.S)
DATE_BLOCK_RE = re.compile(r'post-content-post-date">(.*?)</p>', re.S)
CATEGORY_RE = re.compile(r"post-category[^>]*>([^<]+)<")

DATE_TOKEN_RE = re.compile(
    r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})",
    re.I,
)
TIME_TOKEN_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*-\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
    re.I,
)

# Header <p> that carries the detail page's own date/time — present on
# every page EXCEPT the flagship Annual Conference template.
HEADER_DATE_RE = re.compile(
    r'<p style="margin-bottom:0;">\s*<b>(.*?)</b>\s*</p>', re.S
)
# Explicit "Start date: ... End date: ..." variant (multi-date course page).
START_END_RE = re.compile(
    r"<b>Start date:</b>\s*([^<]+?)<br>\s*<b>End date:</b>\s*([^<]+)", re.I
)
# Fallback for the Annual Conference's hero-block prose date/venue pair.
HERO_DATE_VENUE_RE = re.compile(
    r"<strong>\s*<strong>\s*([A-Za-z]+\s+\d{1,2}\s+[A-Za-z]+\s+\d{4})\s*</strong>\s*<br\s*/?>\s*"
    r"<strong>([^<]+)</strong>",
    re.S,
)
# "This course will take place online on the following dates:" list.
SESSIONS_INTRO_RE = re.compile(
    r"following dates?:</strong>\s*</p>\s*<p>(.*?)</p>", re.I | re.S
)
# "This hybrid event is taking place online and at <address> on <date>."
HYBRID_VENUE_RE = re.compile(
    r"taking place online and at ([^.]+?) on ", re.I
)
ADDRESS_RE = re.compile(
    # Street-number + (at most 3 words) + street-type word, optionally
    # followed by ", <City words>" and/or a UK postcode. Word-count-limited
    # (not char-count) so a stray digit earlier in the same sentence (a
    # date, a time) can't be swept into the match along with unrelated
    # trailing prose.
    r"\b(\d+(?:[\-–]\d+)?\s+(?:[A-Za-z]+\s+){0,3}(?:Street|Road|Avenue|Square|Lane|Place|Court|Way|Row)"
    r"(?:,\s*[A-Za-z]+(?:\s+[A-Za-z]+)?)?(?:\s+[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})?)",
)
UK_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b")

PRICING_HEADING_RE = re.compile(
    r"<h[2-5][^>]*>(?:\s*<[a-z]+[^>]*>)*\s*(?:Price Options|Ticket Prices|Prices|Fees|Registration)\s*"
    r"(?:</[a-z]+>\s*)*</h[2-5]>",
    re.I,
)
PROSE_PRICE_LINE_RE = re.compile(
    r"\*?([A-Za-z][A-Za-z \-]{2,40}?)(?:\s+fee)?:\s*(Free|£\s?[\d,]+(?:\.\d+)?)",
    re.I,
)

SKIP_TITLE_RE = re.compile(r"sponsorship|on\s*demand", re.I)


def _strip_tags(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment or "")
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_listing_date_html(date_html: str) -> str:
    """Unescape + turn <br> and &nbsp;-separated ranges into a single
    plain-text line we can regex over, e.g.:
      'Wed 7 Oct 2026&nbsp;&nbsp;-&nbsp;Wed 14 Oct 2026 <br>'
      -> 'Wed 7 Oct 2026 - Wed 14 Oct 2026 |'
    """
    text = html_lib.unescape(date_html or "")
    text = re.sub(r"<br\s*/?>", " | ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_date_token(day: str, mon_abbr: str, year: str) -> Optional[date]:
    mon = _MONTHS.get(mon_abbr[:3].lower())
    if not mon:
        return None
    try:
        return date(int(year), mon, int(day))
    except ValueError:
        return None


def _parse_time_token(text: str) -> Optional[str]:
    """First 'HH:MM(am/pm)? - HH:MM(am/pm)?' style match -> 'HH:MM:00'."""
    m = TIME_TOKEN_RE.search(text)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    meridiem = (m.group(3) or "").lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}:00"


def _parse_dates_and_time(clean_text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    tokens = DATE_TOKEN_RE.findall(clean_text)
    dates = [_parse_date_token(*t) for t in tokens]
    dates = [d for d in dates if d]
    start = dates[0].isoformat() if dates else None
    end = dates[1].isoformat() if len(dates) > 1 else None
    start_time = _parse_time_token(clean_text)
    return start, end, start_time


class FPMExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing phase
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today()
        shells: List[Dict[str, Any]] = []
        seen_urls = set()

        for n in range(1, MAX_PAGES + 1):
            url = LISTING_URL if n == 1 else PAGE_URL_TMPL.format(n=n)
            html_text = fetch_html(url, browser=getattr(self, "browser", None))
            if not html_text:
                if n == 1:
                    logger.warning("FPM: listing fetch failed, no shells")
                    return None
                break

            page_articles = ARTICLE_RE.findall(html_text)
            if not page_articles:
                break

            new_on_page = 0
            for classes, body in page_articles:
                link_m = LINK_RE.search(body)
                title_m = TITLE_RE.search(body)
                date_m = DATE_BLOCK_RE.search(body)
                if not link_m or not title_m:
                    continue

                url_path = link_m.group(1).strip()
                event_url = url_path if url_path.startswith("http") else BASE_URL + url_path
                if event_url in seen_urls:
                    continue
                seen_urls.add(event_url)
                new_on_page += 1

                title = html_lib.unescape(re.sub(r"<[^>]+>", "", title_m.group(1))).strip()
                if not title or SKIP_TITLE_RE.search(title):
                    continue

                categories = [c.strip() for c in CATEGORY_RE.findall(body)]
                cats_lower = {c.lower() for c in categories}
                is_online = "online" in cats_lower
                is_in_person = "in-person" in cats_lower
                if is_online and is_in_person:
                    event_format = "hybrid"
                elif is_online:
                    event_format = "online"
                elif is_in_person:
                    event_format = "in_person"
                else:
                    event_format = None

                start_date = end_date = start_time = None
                if date_m:
                    clean = _clean_listing_date_html(date_m.group(1))
                    start_date, end_date, start_time = _parse_dates_and_time(clean)

                # Defensive: drop anything that's already fully lapsed.
                cutoff = end_date or start_date
                if cutoff and cutoff < today.isoformat():
                    continue

                shells.append({
                    "title": title,
                    "booking_url": event_url,
                    "start_date": start_date,
                    "end_date": end_date,
                    "start_time": start_time,
                    "event_format": event_format,
                    "categories": categories,
                    "is_dpm_training": "dpm training" in cats_lower,
                    "is_free": "free to attend" in cats_lower,
                })

            if new_on_page == 0:
                break
            # No explicit "has next page" check needed — an empty next
            # fetch (404/empty article list) ends the loop above.

        logger.info(f"FPM: {len(shells)} upcoming shells from listing")
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
            logger.warning(f"FPM: detail fetch failed for {url}")
            return result

        try:
            page.set_content(detail_html, timeout=15000)
        except Exception as e:
            logger.warning(f"FPM: page.set_content failed for {url}: {e}")
            # Page is still parked on the real URL from the scraper's own
            # navigate() — page.evaluate() below still works against the
            # live DOM even when set_content() failed.

        h1 = (page.evaluate(r"""() => {
            const h = document.querySelector('h1');
            return h ? h.textContent.trim() : '';
        }""") or "").strip()
        if h1:
            result["conference_name"] = h1
        title = h1 or shell.get("title")

        body_text = page.evaluate(r"""() => {
            const clone = document.body.cloneNode(true);
            clone.querySelectorAll('nav, footer, header, script, style, noscript, form').forEach(n => n.remove());
            return (clone.textContent || '').replace(/\s+/g, ' ').trim();
        }""") or ""

        # 1. event_type — DPM training modules / exam-revision courses and
        # the multi-date "Understanding Real-World Studies" webinar series
        # are courses; the flagship conference and AGM are conferences;
        # everything else (single-session webinars, the festive gathering)
        # is a workshop.
        title_lower = (title or "").lower()
        if shell.get("is_dpm_training") or "exam revision" in title_lower or "training programme" in title_lower:
            event_type = "course"
        elif "annual conference" in title_lower:
            event_type = "conference"
        else:
            event_type = "workshop"

        # 2. Sessions — only when the page states multiple concrete dates
        # in a "following dates:" list (RWE course). Modules/exam-revision
        # courses each have exactly one date and are NOT session-ified.
        sessions = self._extract_sessions(detail_html)
        if sessions:
            event_type = "course"
            result["sessions"] = sessions
            result["start_date"] = sessions[0]["start_date"]
            result["end_date"] = sessions[-1]["start_date"]
        else:
            start_date, end_date, start_time = self._extract_header_dates(detail_html)
            if start_date:
                result["start_date"] = start_date
            if end_date:
                result["end_date"] = end_date
            if start_time:
                result["start_time"] = start_time

        result["event_type"] = event_type

        # 3. Venue / city / region / event_format
        result.update(self._extract_venue(detail_html, body_text, shell))

        # 4. Pricing (deterministic; [] when nothing published)
        tiers = self._extract_table_pricing(detail_html)
        if not tiers:
            tiers = self._extract_prose_pricing(detail_html)
        result["pricing_tiers"] = tiers

        # 5. CPD — no numeric points ever published; accredited flag only.
        result["cpd_points"] = None
        result["cpd_accredited"] = bool(
            re.search(r"CPD Credits|Gain CPD points", detail_html, re.I)
        )

        # 6. Sold-out / closed bookings
        result["is_sold_out"] = bool(
            re.search(r"bookings?\s+(?:for [^<.]*?\s+)?(?:are\s+)?now\s+closed", body_text, re.I)
        )

        # 7. Abstract / CFP — deterministic classifier over page text.
        is_open, deadline = extract_abstract_info(body_text)
        result["abstract_open"] = is_open
        result["abstract_deadline"] = deadline.isoformat() if deadline else None

        # 8. Description + specialty
        result.update(self._extract_soft_fields(body_text, title, llm_call))

        return result

    # ------------------------------------------------------------------ #
    # Dates from the standard per-page header block
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_header_dates(html_text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
        m = START_END_RE.search(html_text)
        if m:
            start_toks = DATE_TOKEN_RE.search(m.group(1))
            end_toks = DATE_TOKEN_RE.search(m.group(2))
            start = _parse_date_token(*start_toks.groups()).isoformat() if start_toks else None
            end = _parse_date_token(*end_toks.groups()).isoformat() if end_toks else None
            return start, end, None

        m = HEADER_DATE_RE.search(html_text)
        if m:
            clean = _strip_tags(m.group(1).replace("<br>", " | ").replace("<br/>", " | "))
            return _parse_dates_and_time(clean)

        m = HERO_DATE_VENUE_RE.search(html_text)
        if m:
            clean = _strip_tags(m.group(1))
            start, _, start_time = _parse_dates_and_time(clean)
            return start, None, start_time

        return None, None, None

    # ------------------------------------------------------------------ #
    # Sessions — "...following dates:" plain-text date list.
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_sessions(html_text: str) -> List[Dict[str, Any]]:
        m = SESSIONS_INTRO_RE.search(html_text)
        if not m:
            return []
        clean = _strip_tags(m.group(1).replace("<br />", " | ").replace("<br/>", " | "))
        lines = [s.strip() for s in clean.split("|") if s.strip()]

        today_iso = date.today().isoformat()
        sessions: List[Dict[str, Any]] = []
        for line in lines:
            date_m = re.search(
                r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
                r"September|October|November|December)",
                line, re.I,
            )
            if not date_m:
                continue
            # No year in the per-line text — the course spans one calendar
            # year; take it from the intro sentence / page as a whole.
            year_m = re.search(r"(20\d{2})", html_text)
            year = year_m.group(1) if year_m else str(date.today().year)
            mon = _MONTHS.get(date_m.group(2)[:3].lower())
            if not mon:
                continue
            try:
                d = date(int(year), mon, int(date_m.group(1)))
            except ValueError:
                continue
            if d.isoformat() < today_iso:
                continue
            start_time = _parse_time_token(line)
            sessions.append({
                "start_date": d.isoformat(),
                "end_date": None,
                "start_time": start_time,
                "duration_text": None,
                "availability_status": "unknown",
                "spots_left": None,
                "booking_url": None,
                "notes": None,
            })
        sessions.sort(key=lambda s: s["start_date"])
        return sessions

    # ------------------------------------------------------------------ #
    # Venue / city / region / event_format
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_venue(html_text: str, body_text: str, shell: Dict[str, Any]) -> Dict[str, Any]:
        shell_format = shell.get("event_format")
        if shell_format == "online":
            return {"event_format": "online", "venue_name": None, "city": None, "region": None}

        # In-person / hybrid — look for a hybrid "...online and at <addr> on"
        # sentence first (AGM pattern), else a plain street-address regex,
        # else give up gracefully (never fabricate a venue).
        addr_text = None
        m = HYBRID_VENUE_RE.search(body_text)
        if m:
            addr_text = m.group(1).strip()
        else:
            m2 = ADDRESS_RE.search(body_text)
            if m2:
                addr_text = m2.group(1).strip()

        if not addr_text:
            # No street address found even though listing badges say
            # in-person/hybrid — keep the listing's format signal but
            # leave venue/city/region null rather than guess.
            return {
                "event_format": shell_format or "in_person",
                "venue_name": None,
                "city": None,
                "region": None,
            }

        postcode_m = UK_POSTCODE_RE.search(addr_text)
        without_postcode = UK_POSTCODE_RE.sub("", addr_text).strip(" ,")
        parts = [p.strip() for p in without_postcode.split(",") if p.strip()]
        city = parts[-1][:80] if len(parts) > 1 else None
        if city:
            # "London or Online" -> "London" — the address prose often
            # trails into an online-alternative mention rather than
            # stopping cleanly at the city name.
            city = re.split(r"\bor\b", city, flags=re.I)[0].strip()[:80] or None
        venue_name = parts[0][:200] if parts else without_postcode[:200]
        region = "London" if city and "london" in city.lower() else None

        return {
            "event_format": shell_format or ("hybrid" if "online" in body_text.lower() else "in_person"),
            "venue_name": venue_name,
            "city": city,
            "region": region,
            "_postcode": postcode_m.group(1) if postcode_m else None,
        }

    # ------------------------------------------------------------------ #
    # Pricing layout 1 — proper <table> under a Ticket Prices heading,
    # e.g. Location | Ticket Type | Pricing (FPM Annual Conference).
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_table_pricing(html_text: str) -> List[Dict[str, Any]]:
        heading_m = PRICING_HEADING_RE.search(html_text)
        if not heading_m:
            return []
        after = html_text[heading_m.end():heading_m.end() + 6000]
        table_m = re.search(r"<table[^>]*>(.*?)</table>", after, re.S)
        if not table_m:
            return []
        table_html = table_m.group(1)
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.S)
        tiers: List[Dict[str, Any]] = []
        for row in rows:
            cells = [
                _strip_tags(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
            ]
            if len(cells) < 3:
                continue
            section, category, price_text = cells[0], cells[1], cells[2]
            price = BaseExtractor.parse_gbp(price_text)
            if price is None:
                continue
            if section.lower() in {"location"} or category.lower() in {"ticket type"}:
                continue  # header row
            label = f"{section} · {category}"[:120] if section else category[:120]
            tiers.append({
                "tier_label": label,
                "price_gbp": price,
                "is_early_bird": False,
                "early_bird_deadline": None,
            })
        # Dedupe by (label, price)
        seen = set()
        out = []
        for t in tiers:
            key = (t["tier_label"], t["price_gbp"])
            if key in seen:
                continue
            seen.add(key)
            out.append(t)
        return out

    # ------------------------------------------------------------------ #
    # Pricing layout 2 — plain-prose "Label: £NNN" / "Label: Free" lines
    # under a fee-related heading (webinars, DPM training courses).
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_prose_pricing(html_text: str) -> List[Dict[str, Any]]:
        heading_m = PRICING_HEADING_RE.search(html_text)
        if not heading_m:
            return []
        # Search from the heading up to the next <hr> / heading boundary.
        after = html_text[heading_m.end():]
        end_m = re.search(r"<hr\s*/?>|<h[2-5][^>]*>", after)
        window = after[: end_m.start()] if end_m else after[:1500]
        window = re.sub(r"<br\s*/?>", "\n", window)
        # Strip remaining tags WITHOUT collapsing the newlines just
        # inserted — _strip_tags() flattens all whitespace to one space,
        # which would merge every price line back into a single string
        # and break the per-line regex below.
        window = re.sub(r"<[^>]+>", " ", window)
        text = html_lib.unescape(window)
        text = "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n"))

        tiers: List[Dict[str, Any]] = []
        for line in text.split("\n"):
            m = PROSE_PRICE_LINE_RE.search(line)
            if not m:
                continue
            label = m.group(1).strip()[:120]
            price_text = m.group(2).strip()
            price = 0.0 if price_text.lower() == "free" else BaseExtractor.parse_gbp(price_text)
            if price is None:
                continue
            tiers.append({
                "tier_label": label,
                "price_gbp": price,
                "is_early_bird": False,
                "early_bird_deadline": None,
            })
        seen = set()
        out = []
        for t in tiers:
            key = (t["tier_label"], t["price_gbp"])
            if key in seen:
                continue
            seen.add(key)
            out.append(t)
        return out

    # ------------------------------------------------------------------ #
    # Description (LLM w/ deterministic backstop) + specialty. FPM is a
    # single-specialty faculty — every event it lists is pharmaceutical
    # medicine — so specialty is ALWAYS the deterministic value, same
    # per-source-hint pattern as fom.py/rcpsych.py; we don't let the LLM
    # or the shared generic classifier override it, since both can drift
    # (e.g. wrong casing, or latching onto an unrelated keyword in a
    # webinar title).
    # ------------------------------------------------------------------ #
    def _extract_soft_fields(
        self, body_text: str, title: Optional[str], llm_call: Callable[[str], Optional[str]]
    ) -> Dict[str, Any]:
        clean = re.split(r"Please note our booking|For cancellation terms", body_text, flags=re.I)[0].strip()
        description = self._truncate_to_sentence(clean or body_text, 320) if (clean or body_text) else None

        try:
            prompt = (
                "Given this event page text, return strict JSON "
                '{"description": "one sentence summary"}. '
                f"Title: {title}\nText: {body_text[:3000]}"
            )
            raw = llm_call(prompt)
            if raw:
                import json as _json
                match = re.search(r"\{.*\}", raw, re.S)
                if match:
                    parsed = _json.loads(match.group(0))
                    if parsed.get("description"):
                        description = parsed["description"][:320]
        except Exception:
            pass

        # Belt-and-braces: confirm against the shared classifier, but FPM
        # has no other kind of event — always keep the deterministic value.
        _ = classify_specialty(title, description)
        return {"description": description, "specialty": "Pharmaceutical Medicine"}

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
