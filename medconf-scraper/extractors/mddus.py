"""
MDDUS (Medical and Dental Defence Union of Scotland) — Training & CPD events
extractor.

Recon called this domain "parked" behind Cloudflare (curl-only probe). It
is not: `browser.navigate()` clears the challenge on the first load (it
rotates to `ALT_PROFILE` automatically — no extra code needed here), and
the real listing lives at `/training-and-cpd/events` (linked from the
`/training-and-cpd` landing page as "CPD courses"), not at the recon's
`start_url`. 71 upcoming events observed 2026-09-29, paginated 10/page via
`?page=N&orderby=date&ordertype=asc` (`.pagination a.js--search--pagination`
— 8 pages). Every event is an "Interactive Zoom" training course — no
in-person/hybrid events seen in a full pass over all 8 pages.

LISTING: each card is an `<a class="result-item result-item--event">`
wrapping an `<h2>` title, a `<p>` intro sentence ("Taking place on
<weekday>, <day> <month> [year] ...") and a `.result-item__meta` `<li>`
list whose ORDER varies (sometimes a formatted date string, sometimes
"Online course" / "Still Available" / "Book Now", a training-type label,
and a "N CPD hours|points" string — treated as an unordered bag, not by
position). The generic `browser.get_event_cards()` DOM walker misses this
card shape entirely: the title `<h2>` is INSIDE the anchor (not a sibling),
and the detail URL's path is `/events/<year>/<month>/<slug>` — the digit
right after `/events/` fails the walker's `isEventUrl` regex, and the
lack of a weekday-prefixed or `Date:`-labelled inline date fails its date
regex too, so every card is dropped by the quality filter. Hence the
`list_shells_override()` below.

DATE BUG (verified on-site, not a parsing artefact): the detail page's own
structured "Date" sidebar field is WRONG on some rows — three "AI for
hospital doctors" clones (at /2027/january/, /2026/october/ and
/2026/september/) all render sidebar Date = "03 September 2026" regardless
of which clone you're on. Conversely, the card/detail INTRO SENTENCE
("Taking place on ...") is wrong on at least one row (the "Team
communication: Safer MDT working in secondary care" card under
/2026/november/ says "Tuesday, 9 September" while its sidebar Date, 12
November 2026, matches the URL and is correct there). Neither source is
trustworthy alone. `_resolve_date()` cross-checks both against the
unambiguous ground truth — the URL's `/events/<year>/<month>/` segments —
and only trusts the structured Date when its year+month agrees with the
URL; otherwise it falls back to the day parsed out of the intro sentence
(anchored on the URL's month name so an unrelated month elsewhere in the
sentence can't be picked up). Confirmed this resolves both known cases
correctly against by-hand inspection.

DETAIL: `.p--vacancy--sidebar-details li` renders each fact as
`<p>Label&nbsp;<strong>Value</strong></p>` — Date, Availability
("Still Available" / "Book Now" / occasionally "Sold Out"), an optional
"Resource type" ("Online course") ahead of "Training type" on member-only
free courses, and "CPD hours" or "CPD points". No `<table>` markup
anywhere — `pricing_tables.py`'s table parser does not apply. Pricing is
plain rich-text: "Course Fee:" followed by "MDDUS member: £120" /
"Non-member: £175" lines, OR (member-only courses) a sentence saying the
course is free for MDDUS members with no non-member rate at all. All
prices are GBP.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin

from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from logger import logger

BASE_URL = "https://www.mddus.com"
LISTING_URL = f"{BASE_URL}/training-and-cpd/events"
MAX_PAGES = 20

_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"],
        start=1,
    )
}

_URL_DATE_RE = re.compile(r"/events/(\d{4})/([a-z]+)/[^/?#]+/?$", re.I)
_STRUCTURED_DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")
_TIME_RE = re.compile(r"\b(\d{1,2})[.:](\d{2})\s*(am|pm)\b", re.I)
_CPD_RE = re.compile(r"(\d+(?:\.\d+)?)\s*CPD", re.I)
_SOLD_OUT_RE = re.compile(r"\b(sold\s*out|fully\s*booked|waiting\s*list)\b", re.I)
_FEE_LINE_RE = re.compile(
    r"(MDDUS\s+members?|Non[- ]?members?|Members?)\s*:?\s*£\s*([\d,]+(?:\.\d{1,2})?)",
    re.I,
)


def _to_24h(hh: str, mm: str, ap: str) -> str:
    h = int(hh) % 12
    if ap.lower() == "pm":
        h += 12
    return f"{h:02d}:{mm}"


def _first_time(text: Optional[str]) -> Optional[str]:
    m = _TIME_RE.search(text or "")
    if not m:
        return None
    return _to_24h(m.group(1), m.group(2), m.group(3))


def _parse_structured_date(text: Optional[str]) -> Optional[date]:
    if not text:
        return None
    m = _STRUCTURED_DATE_RE.search(text)
    if not m:
        return None
    day, month_name, year = m.groups()
    month = _MONTHS.get(month_name.lower())
    if not month:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def _resolve_date(url: str, structured_text: Optional[str], free_text: str) -> Optional[date]:
    """See module docstring's DATE BUG note. URL year+month is ground truth;
    the structured "Date" field and the intro sentence both have independent,
    observed failure modes, so cross-check rather than trust either alone."""
    m = _URL_DATE_RE.search(url or "")
    if not m:
        # No year/month in the URL to anchor on — trust the structured
        # field if there is one, else give up.
        return _parse_structured_date(structured_text)
    year, month_name = int(m.group(1)), m.group(2).lower()
    month = _MONTHS.get(month_name)
    if not month:
        return None

    structured = _parse_structured_date(structured_text)
    if structured and structured.year == year and structured.month == month:
        return structured

    day_m = re.search(
        rf"(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*{re.escape(month_name)}\b",
        free_text or "",
        re.I,
    )
    if day_m:
        try:
            return date(year, month, int(day_m.group(1)))
        except ValueError:
            pass
    return None


class MDDUSExtractor(BaseExtractor):
    """Browser-first (Cloudflare); see module docstring."""

    # ------------------------------------------------------------------ #
    # Phase A — listing
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        browser = getattr(self, "browser", None)
        if browser is None or getattr(browser, "page", None) is None:
            logger.warning("MDDUS: no launched browser available")
            return None

        today = date.today()
        shells: List[Dict[str, Any]] = []
        seen: set = set()

        for page_no in range(1, MAX_PAGES + 1):
            url = f"{LISTING_URL}?page={page_no}&orderby=date&ordertype=asc"
            try:
                browser.navigate(url)
                browser.page.wait_for_timeout(1200)
            except Exception as e:
                logger.warning(f"MDDUS: listing page {page_no} navigation failed ({e}); stopping")
                break

            cards = self._parse_listing_cards(browser.page)
            if not cards:
                break

            new_on_page = 0
            for c in cards:
                bu = c["booking_url"]
                if bu in seen:
                    continue
                seen.add(bu)
                new_on_page += 1
                start = c.pop("_start_date_obj", None)
                if not start:
                    logger.info(f"MDDUS: unresolvable date on '{c['title'][:60]}' ({bu}) — skipping")
                    continue
                if start < today:
                    continue
                c["start_date"] = start.isoformat()
                shells.append(c)

            if new_on_page == 0:
                break

        logger.info(f"MDDUS: {len(shells)} upcoming shells")
        return shells

    @staticmethod
    def _parse_listing_cards(page: Page) -> List[Dict[str, Any]]:
        raw = page.evaluate(
            """() => Array.from(document.querySelectorAll('a.result-item--event')).map(a => ({
                href: a.href,
                title: ((a.querySelector('h2') || {}).innerText || '').trim(),
                summary: ((a.querySelector('p') || {}).innerText || '').trim(),
                meta: Array.from(a.querySelectorAll('.result-item__meta li')).map(li => li.textContent.trim())
            }))"""
        )
        out: List[Dict[str, Any]] = []
        for r in raw:
            href, title = r.get("href"), r.get("title")
            if not href or not title:
                continue
            summary = r.get("summary") or ""
            meta = r.get("meta") or []
            structured = next((m for m in meta if _STRUCTURED_DATE_RE.fullmatch(m.strip())), None)
            start = _resolve_date(href, structured, summary)
            out.append(
                {
                    "title": title,
                    "booking_url": href,
                    "start_time": _first_time(summary),
                    "description_hint": (summary[:500] or None),
                    "location_hint": "Online",
                    "_start_date_obj": start,
                }
            )
        return out

    # ------------------------------------------------------------------ #
    # Phase B — detail
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        url = shell.get("booking_url") or page.url
        try:
            data = page.evaluate(
                r"""() => {
                    const items = Array.from(document.querySelectorAll('.p--vacancy--sidebar-details li')).map(li => {
                        const strong = li.querySelector('strong');
                        const value = strong ? strong.textContent.trim() : '';
                        let full = (li.textContent || '').replace(/ /g, ' ').trim();
                        const label = value ? full.slice(0, full.length - value.length).trim() : full;
                        return [label, value];
                    });
                    return { sidebar: items, body: document.body.innerText };
                }"""
            )
        except Exception as e:
            logger.warning(f"MDDUS: could not read detail page {url}: {e}")
            return {}

        sidebar = {(k or "").strip().lower(): v for k, v in (data.get("sidebar") or [])}
        body = data.get("body") or ""

        start = _resolve_date(url, sidebar.get("date"), body[:1500])
        availability = sidebar.get("availability") or ""

        result: Dict[str, Any] = {
            "event_type": "workshop" if "workshop" in (shell.get("title") or "").lower() else "course",
            "start_time": _first_time(body[:1500]) or shell.get("start_time"),
            "is_sold_out": bool(_SOLD_OUT_RE.search(availability)),
            "event_format": "online",
            "cpd_points": self._cpd_points(sidebar),
            "pricing_tiers": self._pricing_tiers(body),
        }
        if start:
            result["start_date"] = start.isoformat()
        result["cpd_accredited"] = (
            "accredited by" in body.lower() if result["cpd_points"] is not None else None
        )
        result.update(self._soft_fields(shell.get("title"), body, llm_call))
        return {k: v for k, v in result.items() if v is not None}

    @staticmethod
    def _cpd_points(sidebar: Dict[str, str]) -> Optional[float]:
        raw = sidebar.get("cpd hours") or sidebar.get("cpd points") or ""
        m = _CPD_RE.search(raw)
        if not m:
            return None
        try:
            return float(m.group(1))
        except ValueError:
            return None

    @staticmethod
    def _pricing_tiers(body: str) -> List[Dict[str, Any]]:
        idx = body.lower().find("course fee")
        if idx < 0:
            return []
        section = body[idx: idx + 400]
        tiers: List[Dict[str, Any]] = []
        seen: set = set()
        for raw_label, amount in _FEE_LINE_RE.findall(section):
            # Normalise "Member"/"Members"/"MDDUS member(s)" and
            # "Non-member"/"Non-members" — the site uses both singular and
            # plural forms interchangeably across course pages.
            if re.search(r"non", raw_label, re.I):
                label = "Non-member"
            elif re.search(r"mddus", raw_label, re.I):
                label = "MDDUS member"
            else:
                label = "Member"
            try:
                price = float(amount.replace(",", ""))
            except ValueError:
                continue
            key = (label.lower(), price)
            if key in seen:
                continue
            seen.add(key)
            tiers.append({"tier_label": label, "price_gbp": price, "currency": "GBP"})
        if not tiers and re.search(r"\bfree\b", section, re.I):
            label = "MDDUS member" if "member" in section.lower() else "Standard fee"
            tiers.append({"tier_label": label, "price_gbp": 0.0, "currency": "GBP"})
        return tiers

    @staticmethod
    def _soft_fields(
        title: Optional[str],
        body: str,
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        # First real paragraph: the intro strapline sits right after the
        # title, before the "Date"/"Availability" sidebar block.
        idx = body.lower().find("account.")
        snippet = body[idx + len("account."):idx + 1800] if idx >= 0 else body[:1800]
        # Trim trailing chrome — "Related Content" link list, share buttons,
        # the footer address block — before it reaches the LLM or the
        # keyword classifier. Without this, unrelated related-article titles
        # (e.g. "Complaints management for healthcare practitioners" on a
        # wellbeing course) leak keywords into the specialty guess.
        cutoff = re.search(r"\n\s*(Related Content|Share this page|Book now)\b", snippet, re.I)
        if cutoff:
            snippet = snippet[:cutoff.start()]

        prompt = f"""You are summarising a single medico-legal CPD training-course page. Extract ONLY two fields.

COURSE TITLE: {title}

PAGE BODY:
{snippet[:2500]}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the page text" or null,
  "specialty": "primary topic area (e.g. Leadership & Management, Risk Management, Professionalism & Ethics, General Practice)" or null
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
                result = {"description": parsed.get("description"), "specialty": parsed.get("specialty")}
            except Exception as e:
                logger.warning(f"MDDUS soft-fields JSON parse failed: {e}; raw[:200]={raw[:200]!r}")

        if not result.get("specialty"):
            result["specialty"] = classify_specialty(title, snippet) or "Medico-legal & Risk Management"

        if not result.get("description"):
            paragraphs = [p.strip() for p in snippet.split("\n") if len(p.strip()) > 60]
            if paragraphs:
                result["description"] = MDDUSExtractor._truncate_to_sentence(paragraphs[0], 400)

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
