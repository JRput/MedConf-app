"""
Royal College of Ophthalmologists (RCOphth) — events/courses extractor.

Listing (source is a redirect to the canonical URL):
    https://www.rcophth.ac.uk/training-careers/courses-events-calendar/
Server-rendered WordPress page, no JS/pagination needed — ALL upcoming
cards are on one page as `<article class="js-card card card--courses-and-events ...">`
blocks. Each card gives everything needed for a shell without a detail
fetch: title (`.card__title`), a human-readable date chip
(`.tag__date`, e.g. "13 November 2026"), 0-2 `.card__location-time-text`
spans (location and/or a "9:00 am" time), and a one-line description
(`.card__copy`). `browser.get_event_cards_paginated()` finds 0 cards here
(confirmed by probe) — hence the override.

Detail pages (`/courses-and-events/<slug>/`) are also plain WordPress,
same theme, no anti-bot challenge observed (httpx via `fetch_html`
resolves them directly — no CloudFront/Cloudflare block like RCPsych).
Key structure, all in `.article-page-banner`:
  - `<h1 class="article-page-banner__heading">`             — canonical title
  - `.article-page-banner__event-item span`                 — 1-2 spans:
        location text (e.g. "London", "Via Zoom") and/or a time
        ("9:00 am"). Some pages (SORD/FORD Glasgow) omit location
        entirely — only a time span is present.
  - `.article-page-banner__member-item`                     — 0-2 <li>s:
        "Member fee: £60" and/or (often `hidden`, but still readable via
        textContent) "Non-member fee: £90". Some pages (Winter Meeting)
        have neither — multi-day flagship-ish events with fees handled
        via the external booking flow instead.
  - `.article-page-banner__copy` (a single `<p>`)            — the ONE
        clean descriptive paragraph on the page; no nav junk, no need to
        hunt for an Overview heading. This is the description source of
        truth for both the LLM prompt and the deterministic fallback.
  - No CPD point figures found on any probed page (nav has a generic
    "Approval of CPD points" link, which is not per-event data — do not
    let that leak into `cpd_points` via a naive body-text regex).
  - No schema.org Event JSON-LD — dates are NOT on the detail page at
    all (confirmed on "SAS 17th National Eye Day": zero date text in
    body). The listing chip is the only reliable date source; a title
    regex additionally recovers the end date for named multi-day spans
    ("RCOphth Winter meeting 7 & 8 December 2026").
  - Each "Register" CTA still points at the iHub ASP.NET registrar
    (`ihub.rcophth.ac.uk/RCO/Events/Event_Display.aspx?EventKey=...`) —
    we surface it as `organiser_url` but keep our own page as
    `source_url`/`booking_url` since that's what's stable and dedupeable.

Probed 7 of 12 live cards across the full shape range: a plain in-person
course (repeated 4x with different dates), a Zoom webinar, a two-tier
in-person workshop (member/non-member fee), a flat single-price workshop,
a no-fee-shown multi-day flagship-ish meeting, a location-less workshop,
and a training/"TTT" day. No cancelled/past cards seen on the live page
(the listing itself already appears to only show upcoming events).
"""

from __future__ import annotations

import html as html_lib
import re
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin

from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from .abstract_classifier import extract_abstract_info
from .pricing_tables import parse_pricing_tables
from .http_fetch import fetch_html
from logger import logger


LISTING_URL = "https://www.rcophth.ac.uk/training-careers/courses-events-calendar/"
BASE_URL = "https://www.rcophth.ac.uk"

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}

# Card date chip: "13 November 2026"
_CARD_DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")

# Multi-day span baked into the title itself: "7 & 8 December 2026",
# "7-8 December 2026", "7 and 8 December 2026".
_TITLE_SPAN_RE = re.compile(
    r"(\d{1,2})\s*(?:&|and|-|–|to)\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
    re.I,
)

_ONLINE_RE = re.compile(r"\b(online|webinar|virtual|zoom|teams|livestream|live stream)\b", re.I)

# UK city -> region, kept local to this extractor (see PLAYBOOK "Region
# inference for UK cities" — small per-source lookup is the norm).
_UK_REGIONS = {
    "london": "London",
    "manchester": "North West England",
    "liverpool": "North West England",
    "leeds": "Yorkshire and the Humber",
    "sheffield": "Yorkshire and the Humber",
    "newcastle": "North East England",
    "birmingham": "West Midlands",
    "bristol": "South West England",
    "exeter": "South West England",
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

# Source-specific event_type hints the shared llm_agent title-keyword list
# doesn't cover (RCOphth's "TTT" abbreviation, "review day" pattern).
_WORKSHOP_TITLE_RE = re.compile(
    r"\b(ttt|train the trainer|review day|national eye day|study day)\b", re.I
)


def _parse_card_date(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = _CARD_DATE_RE.search(text)
    if not m:
        return None
    day, mon_name, year = m.groups()
    mon = _MONTHS.get(mon_name.lower())
    if not mon:
        return None
    try:
        return date(int(year), mon, int(day)).isoformat()
    except ValueError:
        return None


def _parse_title_end_date(title: Optional[str], start_iso: Optional[str]) -> Optional[str]:
    """Recover an end date from a title like "... 7 & 8 December 2026"."""
    if not title:
        return None
    m = _TITLE_SPAN_RE.search(title)
    if not m:
        return None
    day1, day2, mon_name, year = m.groups()
    mon = _MONTHS.get(mon_name.lower())
    if not mon:
        return None
    try:
        end = date(int(year), mon, int(day2))
        start_from_title = date(int(year), mon, int(day1))
    except ValueError:
        return None
    # Sanity: the title's first day should match the listing's start date
    # (when we have one) — otherwise this isn't really a span for THIS event.
    if start_iso:
        try:
            if datetime.fromisoformat(start_iso).date() != start_from_title:
                return None
        except ValueError:
            pass
    if end <= start_from_title:
        return None
    return end.isoformat()


def _infer_uk_region(city: Optional[str]) -> Optional[str]:
    if not city:
        return None
    c = city.lower()
    for key, region in _UK_REGIONS.items():
        if key in c:
            return region
    return None


class RCOphthExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing phase
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = fetch_html(LISTING_URL, browser=getattr(self, "browser", None))
        if not html:
            logger.warning("RCOphth: listing fetch failed, no shells")
            return None

        blocks = html.split('class="js-card card card--courses-and-events')[1:]
        if not blocks:
            logger.warning("RCOphth: 0 card blocks found in listing HTML")
            return None

        today = date.today()
        shells: List[Dict[str, Any]] = []
        seen_urls = set()

        for block in blocks:
            title_m = re.search(r'card__title">(.*?)</h3>', block, re.S)
            href_m = re.search(r'card__heading-link[^>]*href="([^"]+)"', block)
            date_m = re.search(r'tag__date">([^<]*)<', block)
            desc_m = re.search(r'card__copy">(.*?)</p>', block, re.S)
            loc_texts = re.findall(r'card__location-time-text">([^<]*)<', block)

            if not (title_m and href_m):
                continue

            title = html_lib.unescape(re.sub(r"<[^>]+>", "", title_m.group(1))).strip()
            if not title or "cancelled" in title.lower():
                continue

            url = urljoin(BASE_URL, html_lib.unescape(href_m.group(1)))
            if url in seen_urls:
                continue
            seen_urls.add(url)

            start_date = _parse_card_date(date_m.group(1) if date_m else None)
            if start_date:
                try:
                    if datetime.fromisoformat(start_date).date() < today:
                        continue
                except ValueError:
                    pass

            location_hint = None
            time_hint = None
            texts = [html_lib.unescape(t).strip() for t in loc_texts if t.strip()]
            if len(texts) >= 2:
                location_hint, time_hint = texts[0], texts[1]
            elif len(texts) == 1:
                if re.search(r"\d\s*(am|pm)\b", texts[0], re.I):
                    time_hint = texts[0]
                else:
                    location_hint = texts[0]

            description_hint = None
            if desc_m:
                description_hint = html_lib.unescape(
                    re.sub(r"<[^>]+>", "", desc_m.group(1))
                ).strip() or None

            shells.append({
                "title": title,
                "booking_url": url,
                "start_date": start_date,
                "location_hint": location_hint,
                "start_time_hint": time_hint,
                "description_hint": description_hint,
            })

        logger.info(f"RCOphth: {len(shells)} upcoming shells from listing (of {len(blocks)} cards)")
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

        # 1. Title — never trust the shell title, read h1 (playbook mistake #11).
        h1 = (page.evaluate(r"""() => {
            const hs = Array.from(document.querySelectorAll('h1'));
            for (const h of hs) {
                const t = (h.textContent || '').trim();
                if (t) return t;
            }
            return '';
        }""") or "").strip()
        title = h1 or shell.get("title")
        if h1:
            result["conference_name"] = h1

        # 2. Location / time chips
        event_items = page.evaluate(r"""() => {
            return Array.from(document.querySelectorAll('.article-page-banner__event-item span'))
                .map(s => (s.textContent || '').trim())
                .filter(Boolean);
        }""") or []
        result.update(self._extract_venue(event_items, title))

        # 3. Pricing (deterministic — member/non-member fee lines)
        tiers = self._extract_pricing(page)
        if not tiers:
            try:
                page_html = page.content()
            except Exception:
                page_html = ""
            tiers = parse_pricing_tables(page_html, default_currency="GBP")
        result["pricing_tiers"] = tiers

        # 4. CPD — none observed on any probed page; keep the hook narrow
        # (main content only) so the generic nav link "Approval of CPD
        # points" can never leak in as a false positive.
        cpd_points, cpd_accredited = self._extract_cpd(page)
        result["cpd_points"] = cpd_points
        result["cpd_accredited"] = cpd_accredited

        # 5. Dates — listing chip is the only date source on the page at
        # all; the title occasionally spells out a second day.
        start_date = shell.get("start_date")
        if start_date:
            result["start_date"] = start_date
        end_date = _parse_title_end_date(title, start_date)
        if end_date:
            result["end_date"] = end_date

        start_time = self._extract_time(event_items) or shell.get("start_time_hint")
        if start_time:
            result["start_time"] = start_time

        # 6. event_type — source-specific keyword before the shared
        # title-heuristic default (TTT / review day / national eye day
        # aren't in the shared "workshop" keyword list).
        if title and _WORKSHOP_TITLE_RE.search(title):
            result["event_type"] = "workshop"

        # 7. Description + specialty
        body_text = page.evaluate(r"""() => {
            const main = document.querySelector('main') || document.body;
            const clone = main.cloneNode(true);
            clone.querySelectorAll(
                'nav, footer, script, style, noscript, header, .breadcrumbs, ' +
                '.article-page-banner__member-details, .article-page-banner__event-details'
            ).forEach(n => n.remove());
            return clone.textContent.replace(/\s+/g, ' ').trim();
        }""") or ""
        copy_text = (page.evaluate(
            "() => (document.querySelector('.article-page-banner__copy')||{}).textContent || ''"
        ) or "").replace("\xa0", " ").strip()

        is_open, deadline = extract_abstract_info(body_text)
        result["abstract_open"] = is_open
        result["abstract_deadline"] = deadline.isoformat() if deadline else None

        result.update(self._extract_soft_fields(title, copy_text, llm_call))

        return result

    # ------------------------------------------------------------------ #
    # Venue / format
    # ------------------------------------------------------------------ #
    def _extract_venue(self, event_items: List[str], title: Optional[str]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        # Whichever item ISN'T a time ("9:00 am") is the location, if any.
        location = None
        for item in event_items:
            if re.search(r"\d\s*(am|pm)\b", item, re.I):
                continue
            location = item
            break

        if not location:
            # Backstop: some pages (SORD/FORD Glasgow) omit location from
            # the banner entirely. Try a title-based city guess.
            if title:
                low = title.lower()
                for key in _UK_REGIONS:
                    if re.search(rf"\b{re.escape(key)}\b", low):
                        location = key.title()
                        break

        if not location:
            return out

        if _ONLINE_RE.search(location):
            out["event_format"] = "online"
            out["venue_name"] = None
            out["city"] = None
            out["region"] = None
            return out

        out["event_format"] = "in_person"
        out["venue_name"] = location[:200]
        out["city"] = location[:80]
        out["region"] = _infer_uk_region(location)
        return out

    @staticmethod
    def _extract_time(event_items: List[str]) -> Optional[str]:
        for item in event_items:
            m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", item, re.I)
            if m:
                hour, minute, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
                if ap == "pm" and hour != 12:
                    hour += 12
                if ap == "am" and hour == 12:
                    hour = 0
                return f"{hour:02d}:{minute:02d}"
        return None

    # ------------------------------------------------------------------ #
    # Pricing — `.article-page-banner__member-item` lines: "Member fee:
    # £60" / "Non-member fee: £90" (the latter often `hidden` via CSS but
    # still present in textContent — playbook mistake #4, don't use
    # innerText here).
    # ------------------------------------------------------------------ #
    def _extract_pricing(self, page: Page) -> List[Dict[str, Any]]:
        try:
            rows = page.evaluate(r"""() => {
                return Array.from(document.querySelectorAll('.article-page-banner__member-item'))
                    .map(li => (li.textContent || '').replace(/\s+/g, ' ').trim());
            }""") or []
        except Exception as e:
            logger.warning(f"RCOphth pricing extraction failed: {e}")
            return []

        tiers: List[Dict[str, Any]] = []
        for row in rows:
            m = re.match(r"(member|non-member)\s*fee\s*:\s*£\s*([\d,.]+)", row, re.I)
            if not m:
                continue
            label = "Member" if m.group(1).lower() == "member" else "Non-member"
            price = self.parse_gbp(f"£{m.group(2)}")
            if price is None:
                continue
            tiers.append({
                "tier_label": label,
                "price_gbp": price,
                "is_early_bird": False,
                "early_bird_deadline": None,
            })

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
    # CPD — main-content only, never the site nav.
    # ------------------------------------------------------------------ #
    def _extract_cpd(self, page: Page) -> tuple[Optional[int], bool]:
        try:
            text = page.evaluate(r"""() => {
                const main = document.querySelector('main') || document.body;
                const clone = main.cloneNode(true);
                clone.querySelectorAll('nav, footer, header').forEach(n => n.remove());
                return clone.textContent || '';
            }""") or ""
        except Exception:
            return None, False
        m = re.search(r"\b(\d+)\s*(?:CPD\s*)?(?:points?|credits?)\b", text, re.I)
        if m:
            return int(m.group(1)), True
        if re.search(r"\bCPD[- ]accredited|CPD[- ]approved\b", text, re.I):
            return None, True
        return None, False

    # ------------------------------------------------------------------ #
    # Description + specialty
    # ------------------------------------------------------------------ #
    def _extract_soft_fields(
        self,
        title: Optional[str],
        copy_text: str,
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        text = copy_text[:3000]

        result: Dict[str, Any] = {}
        if text:
            prompt = f"""You are summarising a single medical event detail page. Extract ONLY two fields.

EVENT TITLE: {title}

PAGE BODY:
{text}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the page text" or null,
  "specialty": "primary clinical/topic area (e.g. Ophthalmology, Cataract Surgery, Medical Education, Retina)" or null
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
                    raw = m.group(0)
                try:
                    import json
                    parsed = json.loads(raw)
                    result = {
                        "description": parsed.get("description"),
                        "specialty": parsed.get("specialty"),
                    }
                except Exception as e:
                    logger.warning(f"RCOphth soft-fields JSON parse failed: {e}; raw[:200]={raw[:200]!r}")

        if not result.get("specialty"):
            result["specialty"] = classify_specialty(title, text) or "Ophthalmology"

        if not result.get("description") and text:
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
