"""
Faculty of Occupational Medicine (FOM) — events extractor.

Old WordPress theme, no JS rendering needed. Listing page
(https://www.fom.ac.uk/media-events/conferences-and-events) is a single
page, no pagination, no cards from the shared browser DOM walker (it's a
plain custom loop, not a recognisable card grid) — so this extractor
overrides listing via a direct HTML fetch + regex, same approach as
rcpsych.py but through the shared `http_fetch.fetch_html()` helper
(rcpsych predates that helper and calls httpx directly — don't copy that
part).

Listing card shape (regex-friendly, no card wrapper class to hook onto):

    <h2 style="padding-top:10px;"><a href="URL">Title</a></h2>
    <description prose with a "Read more..." link>
    ...
    <strong>Start Date:</strong> DD/MM/YYYY | <strong>End Date:</strong> DD/MM/YYYY
      [| <strong>CPD Points:</strong> N [/ M]]

Only TWO upcoming FOM-run events exist at onboarding time (2026-09-21):
  - "Medical Review Officer (MRO) workshops" — a modular two-part
    programme (Part 1 = 6 CPD, Part 2 = 5.5 CPD) that "runs throughout
    the year". The listing's Start/End Date is a season window
    (04/02/2026-08/10/2026), not one continuous event; the actual
    per-run dates are published only via an external Mailchimp-tracked
    link on the detail page (out of scope to follow — third-party
    tracking redirect, not a page we should scrape). We surface the
    window as-is (directly off FOM's own listing fields, not invented)
    and flag it `event_type='course'` with no sessions (unknown).
  - "MRO Training by MROs, for MROs" — externally run (Reviresco), but
    the FOM detail page itself lists three concrete session dates in
    plain prose ("Thursday 15th October 2026" etc.) — these DO get
    turned into `sessions[]`.

No pricing is published on FOM's own pages for either event (both route
bookings to external providers) — `pricing_tiers` is always `[]`, never
fabricated.

There's also a large "External Events" / "External training courses"
section on the listing (other organisations' CPD-approved events, not
FOM's own) — deliberately NOT scraped here; it's a curated bulletin
board, not primary-source event data we can validate field-by-field.
"""

from __future__ import annotations

import html as html_lib
import re
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from .abstract_classifier import extract_abstract_info
from .http_fetch import fetch_html
from logger import logger


LISTING_URL = "https://www.fom.ac.uk/media-events/conferences-and-events"

CARD_RE = re.compile(
    r'<h2 style="padding-top:10px;"><a href="(?P<url>[^"]+)">(?P<title>[^<]+)</a></h2>'
    r"(?P<desc>.*?)"
    r"<strong>Start Date:</strong>\s*(?P<start>\d{2}/\d{2}/\d{4})\s*"
    r"(?:\|\s*<strong>End Date:</strong>\s*(?P<end>\d{2}/\d{2}/\d{4})\s*)?"
    r"(?:\|\s*<strong>CPD Points:</strong>\s*(?P<cpd>[^<]+))?",
    re.S,
)

# Plain-prose session dates on the detail page, e.g. "Thursday 15th October 2026"
SESSION_DATE_RE = re.compile(
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{4})\b",
    re.I,
)

CPD_VALUE_RE = re.compile(r"(?:value of|has)\s+([\d.]+)\s*CPD\s*points?", re.I)


def _parse_uk_date(text: str) -> Optional[date]:
    try:
        return datetime.strptime(text, "%d/%m/%Y").date()
    except ValueError:
        return None


def _strip_tags(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


class FOMExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing phase — plain regex over the fetched listing HTML; the
    # shared browser card-walker has nothing to hook onto here (no
    # per-card class, just an h2 + a floating date/CPD strip).
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = fetch_html(LISTING_URL, browser=getattr(self, "browser", None))
        if not html:
            logger.warning("FOM: listing fetch failed, no shells")
            return None

        today = date.today()
        shells: List[Dict[str, Any]] = []
        seen_urls = set()

        for m in CARD_RE.finditer(html):
            url = m.group("url").strip()
            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = html_lib.unescape(m.group("title")).strip()
            start_d = _parse_uk_date(m.group("start"))
            end_d = _parse_uk_date(m.group("end")) if m.group("end") else None

            # Keep only events that haven't fully lapsed yet — use end_date
            # when published (season windows), else start_date.
            cutoff = end_d or start_d
            if cutoff and cutoff < today:
                continue

            shells.append({
                "title": title,
                "booking_url": url,
                "start_date": start_d.isoformat() if start_d else None,
                "end_date": end_d.isoformat() if end_d else None,
                "description_hint": _strip_tags(m.group("desc"))[:400] or None,
            })

        logger.info(f"FOM: {len(shells)} upcoming shells from listing")
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
            logger.warning(f"FOM: detail fetch failed for {url}")
            return result

        try:
            page.set_content(detail_html, timeout=15000)
        except Exception as e:
            logger.warning(f"FOM: page.set_content failed for {url}: {e}")
            # Fall through — page is still parked on the real URL from the
            # scraper's navigate(), so page.evaluate() below still works
            # against the live DOM even if set_content() failed.

        h1 = (page.evaluate(r"""() => {
            const h = document.querySelector('h1');
            return h ? h.textContent.trim() : '';
        }""") or "").strip()
        if h1:
            result["conference_name"] = h1
        title = h1 or shell.get("title")

        # Main content — this WordPress theme wraps the real article body
        # (event-details table + h1 + prose + share buttons) in
        # #in-content-i, with all the site chrome (search/social/nav bars,
        # not marked up as <header>/<nav>) living OUTSIDE it as siblings.
        # Strip the details table (dates/CPD, already captured from the
        # listing) and the share-button block, keep the rest.
        body_text = page.evaluate(r"""() => {
            const scope = document.querySelector('#in-content-i') || document.body;
            const clone = scope.cloneNode(true);
            clone.querySelectorAll(
                '#event-details-panel, .addtoany_share_save_container, ' +
                '#in-nav-o, script, style, noscript, form'
            ).forEach(n => n.remove());
            return (clone.textContent || '').replace(/\s+/g, ' ').trim();
        }""") or ""

        # No pricing published on FOM's own pages for either known event —
        # both route bookings to external providers. Never fabricate a fee.
        result["pricing_tiers"] = []

        # No venue/location is stated on either detail page (both are
        # externally-run, modular/multi-city programmes) — leave null
        # rather than guess; self-healing re-fetch picks it up if FOM
        # later adds a venue field.
        result["event_format"] = None
        result["venue_name"] = None
        result["city"] = None
        result["region"] = None

        # CPD points — prefer an unambiguous single "value of N CPD points"
        # mention; when the page states multiple part-values (FOM's MRO
        # workshops: "Part 1 has a value of 6 CPD points and Part 2 has 5.5
        # CPD Points") the total isn't a single stated number, so we mark
        # it accredited but leave the points count null rather than guess
        # whether a delegate does one part or both.
        cpd_matches = CPD_VALUE_RE.findall(body_text)
        if len(cpd_matches) == 1:
            try:
                result["cpd_points"] = int(round(float(cpd_matches[0])))
            except ValueError:
                result["cpd_points"] = None
            result["cpd_accredited"] = True
        elif len(cpd_matches) > 1:
            result["cpd_points"] = None
            result["cpd_accredited"] = True
        elif re.search(r"\bCPD\b", body_text, re.I):
            result["cpd_points"] = None
            result["cpd_accredited"] = True
        else:
            result["cpd_points"] = None
            result["cpd_accredited"] = False

        # Sessions — only when the detail page itself states concrete
        # dated occurrences in prose (MRO Training by MROs, for MROs).
        # The MRO workshops page has no per-run dates on FOM's own site
        # (only via an external Mailchimp link) — leave sessions unset
        # there and keep the shell's season-window start/end date.
        sessions = self._extract_sessions(body_text, url)
        if sessions:
            result["event_type"] = "course"
            result["sessions"] = sessions
            result["start_date"] = sessions[0]["start_date"]
            result["end_date"] = None
        else:
            result["event_type"] = "course"

        # Abstract/CFP — neither event takes submissions; deterministic
        # classifier confirms this from page text rather than us assuming.
        is_open, deadline = extract_abstract_info(body_text)
        result["abstract_open"] = is_open
        result["abstract_deadline"] = deadline.isoformat() if deadline else None

        result.update(self._extract_soft_fields(body_text, title))

        return result

    # ------------------------------------------------------------------ #
    # Sessions — "Thursday 15th October 2026" style date lines.
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_sessions(body_text: str, detail_url: str) -> List[Dict[str, Any]]:
        _MONTHS = {
            "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
            "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        }
        today = date.today()
        sessions: List[Dict[str, Any]] = []
        seen = set()
        for day_s, month_s, year_s in SESSION_DATE_RE.findall(body_text):
            month = _MONTHS.get(month_s.lower())
            if not month:
                continue
            try:
                d = date(int(year_s), month, int(day_s))
            except ValueError:
                continue
            if d < today or d in seen:
                continue
            seen.add(d)
            sessions.append({
                "start_date": d.isoformat(),
                "end_date": None,
                "start_time": None,
                "duration_text": "1 day",
                "availability_status": "unknown",
                "spots_left": None,
                "booking_url": None,
                "notes": None,
            })
        sessions.sort(key=lambda s: s["start_date"])
        return sessions

    # ------------------------------------------------------------------ #
    # Description + specialty. FOM is a single-specialty faculty — every
    # event it lists is occupational medicine, so that's the deterministic
    # fallback (checked BEFORE the shared classifier's generic rules,
    # same per-source-hint pattern as RCPsych — see specialty_classifier.py
    # header; this is a per-source fix, not a shared-file change).
    # ------------------------------------------------------------------ #
    def _extract_soft_fields(self, body_text: str, title: Optional[str]) -> Dict[str, Any]:
        # Trim the leading duplicated h1 (the page repeats the title as
        # plain text right before the prose) and the trailing external-
        # link boilerplate before it reaches description fallback (avoid
        # "For more information ... website: https://..." leaking into a
        # card summary).
        clean = body_text.strip()
        if title and clean.lower().startswith(title.lower()):
            clean = clean[len(title):].strip()
        clean = re.split(r"For more information and to book", clean, flags=re.I)[0].strip()
        clean = re.split(r"Please see the link for upcoming dates", clean, flags=re.I)[0].strip()

        result: Dict[str, Any] = {
            "specialty": "Occupational Medicine",
            "description": None,
        }
        if clean:
            result["description"] = self._truncate_to_sentence(clean, 320)
        elif body_text:
            result["description"] = self._truncate_to_sentence(body_text, 320)

        # Belt-and-braces: if the generic classifier disagrees strongly
        # (shouldn't happen for this source), still prefer occupational
        # medicine — FOM has no other kind of event.
        _ = classify_specialty(title, body_text)
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
