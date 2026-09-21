"""
Royal College of Paediatrics and Child Health (RCPCH) — events extractor.

Drupal 10 server-rendered site, no JS needed for either listing or detail
pages (plain httpx GET returns the fully-rendered HTML). `https://www.rcpch.ac.uk/events`
301-redirects to `/news-events/events`, a paginated search view (`?page=0..N`,
0-indexed) that interleaves two content types in one card grid:

  - "Event"  badge  → `/news-events/events/<slug>`             (field prefix `field-ev-*`)
  - "Course" badge  → `/education-careers/courses/rcpch-course/<slug>`
                       or `/education-careers/courses/rcpch-webinar/<slug>` (field prefix `field-cs-*`)

Card markup (regex-friendly, no JS needed):

    <article class="content-listing-card ...">
      <div class="type"><div class="field ...bundle-fieldnode...">Course</div></div>
      <div class="text-container">
        <h2><a href="URL" hreflang="en">Title</a></h2>
        <div class="infos">
          <div class="field ...field-(cs|ev)-start-date...">DATE_TEXT_OR_<time datetime="ISO">...</div>
        </div>
        <div class="body">description snippet…</div>
      </div>
    </article>

Detail pages carry the SAME two field families (`field-cs-*` for courses,
`field-ev-*` for events) with identical DOM shapes, so one generic reader
handles both — this is deliberate: don't split into two extractors.

  - Date/time: two Views EVA blocks per page — `.view-display-id-(course|event)_date_eva`
    and `..._time_eva` — each rendering one or two `<time datetime="ISO8601">`
    tags (one = single-day, two = start/end).
  - Location: `.field--name-field-(cs|ev)-location` → a Drupal `address`
    field (`.organization` / `.address-line1` / `.locality` / `.postal-code`
    / `.country` spans). ABSENT entirely for online-only events/courses —
    that's the only location signal; there's no separate "online" flag.
  - Availability: `.field--name-field-(cs|ev)-availability` — plain text
    ("Spaces available" / "Limited availability" / "Fully booked").
  - Fee: `.field--name-field-(cs|ev)-fee` — either a `<ul><li>Label - £NNN</li></ul>`
    /`<li>Label: £NNN</li>` list (optionally split into `<p>Section header:</p>`
    + `<ul>` blocks for member/non-member tiers), free-form prose stating the
    event is free, or (for at least one flagship conference observed) absent
    entirely — no fee published at all, `pricing_tiers` must stay `[]`, not
    inferred as free.
  - Booking: `.field--name-field-(cs|ev)-booking a[href]`.
  - Body/description: `.field--name-field-sh-body` — the ONE clean content
    div shared by both event and course pages; no nav/menu leakage since
    it's a dedicated field, unlike sites that hand the LLM the whole
    `<body>`.
  - Topics (specialty backstop): `.tags a[href^="/topic/"]` — deterministic
    topic taxonomy links (e.g. "Endocrinology", "Diabetes", "Safeguarding").
    Far more reliable than the shared keyword classifier for this source,
    so it's tried FIRST; `specialty_classifier` is only the last resort.

No CPD point *counts* were found on any of the 5 probed pages (RCPCH doesn't
publish a numeric CPD figure the way RCP/RCEM do) — `cpd_points` stays None;
`cpd_accredited` is set True only when the body-box content itself mentions
CPD (not the site-wide nav "CPD Diary" link, which sits outside the body div
we read).

Recurring-course instances (e.g. "Statement and report writing... - online,
September" / "...- online, November" / "...January 2027") are each their
OWN separate listing card + detail URL — confirmed by inspecting the full
34-card listing for duplicate titles with different date suffixes. This is
the ordinary one-row-per-dated-instance shape, NOT the `sessions[]` /
course_sessions pattern (which is for ONE offering spanning MANY dates on
ONE page — RCPCH doesn't do that). Each row is emitted as a standalone
conference/course/workshop with no `sessions`.
"""

from __future__ import annotations

import html as html_lib
import re
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from .abstract_classifier import extract_abstract_info
from .pricing_tables import parse_pricing_tables
from .http_fetch import fetch_html
from logger import logger


BASE_URL = "https://www.rcpch.ac.uk"
LISTING_URL = "https://www.rcpch.ac.uk/events"
MAX_LISTING_PAGES = 8  # observed: 4 pages (0-3) for ~34 cards; generous cap

CARD_SPLIT_RE = re.compile(r'<article class="content-listing-card')
TITLE_RE = re.compile(r'<h2>\s*<a href="([^"]+)"[^>]*>(.*?)</a>', re.S)
TYPE_BADGE_RE = re.compile(
    r'field--name-bundle-fieldnode[^>]*>([^<]+)</div>', re.S
)
START_DATE_FIELD_RE = re.compile(
    r'field--name-field-(?:cs|ev)-start-date[^"]*"[^>]*>(.*?)</div>', re.S
)
BODY_SNIPPET_RE = re.compile(r'<div class="body">(.*?)</div>', re.S)
DATETIME_ATTR_RE = re.compile(r'datetime="([^"]+)"')
PLAIN_DATE_RE = re.compile(
    r'(\d{1,2})\s+(January|February|March|April|May|June|July|August|'
    r'September|October|November|December)\s+(\d{4})',
    re.I,
)
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

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
    "stirling": "Scotland",
    "belfast": "Northern Ireland",
    "cambridge": "East of England",
    "norwich": "East of England",
    "oxford": "South East England",
    "brighton": "South East England",
    "leicester": "East Midlands",
    "nottingham": "East Midlands",
}

_GENERIC_TOPICS = {"area of medicine", "conditions", "general", "other"}

_ONLINE_RE = re.compile(
    r"\b(online|webinar|virtual|zoom|microsoft teams|ms teams|teams|livestream|live stream)\b",
    re.I,
)


def _strip_tags(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment or "")
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_field_date(raw_field_html: str) -> Optional[date]:
    """A start-date field's inner HTML is either a bare '<time datetime=ISO>'
    tag (event cards) or plain 'DD Month YYYY' text (course cards)."""
    m = DATETIME_ATTR_RE.search(raw_field_html)
    if m:
        try:
            return datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).date()
        except ValueError:
            pass
    m = PLAIN_DATE_RE.search(_strip_tags(raw_field_html))
    if m:
        day, mon_name, year = m.group(1), m.group(2), m.group(3)
        mon = _MONTHS.get(mon_name.lower())
        if mon:
            try:
                return date(int(year), mon, int(day))
            except ValueError:
                pass
    return None


class RCPCHExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing phase — paginated card grid, plain httpx fetch.
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today()
        shells: List[Dict[str, Any]] = []
        seen_urls = set()

        for page_num in range(MAX_LISTING_PAGES):
            url = LISTING_URL if page_num == 0 else f"{LISTING_URL}?page={page_num}"
            html = fetch_html(url, browser=getattr(self, "browser", None))
            if not html:
                logger.warning(f"RCPCH: listing fetch failed for page {page_num}")
                break

            cards = CARD_SPLIT_RE.split(html)[1:]
            if not cards:
                break

            page_had_new = False
            for chunk in cards:
                title_m = TITLE_RE.search(chunk)
                if not title_m:
                    continue
                href, title_html = title_m.group(1), title_m.group(2)
                title = _strip_tags(title_html)
                if not title:
                    continue

                full_url = urljoin(BASE_URL, html_lib.unescape(href))
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)
                page_had_new = True

                if "[CANCELLED]" in title.upper() or "CANCELLED" == title.strip().upper():
                    continue

                badge_m = TYPE_BADGE_RE.search(chunk)
                badge = (badge_m.group(1).strip() if badge_m else "").lower()

                date_m = START_DATE_FIELD_RE.search(chunk)
                start_d = _parse_field_date(date_m.group(1)) if date_m else None

                # Keep only upcoming (or undated — let the detail page decide;
                # dropping undated shells silently would lose real events).
                if start_d and start_d < today:
                    continue

                body_m = BODY_SNIPPET_RE.search(chunk)
                description_hint = _strip_tags(body_m.group(1))[:400] if body_m else None

                category = None
                if "webinar" in full_url:
                    category = "workshop"
                elif badge == "course":
                    category = "course"
                # badge == "event" -> leave category unset; title heuristic
                # + default 'conference' handle RCPCH's Events section well
                # (e.g. "... Training Day" -> workshop via title keyword).

                shells.append({
                    "title": title,
                    "booking_url": full_url,
                    "start_date": start_d.isoformat() if start_d else None,
                    "category": category,
                    "description_hint": description_hint or None,
                })

            if not page_had_new:
                # Drupal keeps serving the last page's content past the real
                # end for some views configs — stop once a page contributes
                # nothing new rather than trusting card count alone.
                break

        logger.info(f"RCPCH: {len(shells)} upcoming shells from listing")
        return shells or None

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
            logger.warning(f"RCPCH: detail fetch failed for {url}")
            return result

        try:
            page.set_content(detail_html, timeout=15000)
        except Exception as e:
            logger.warning(f"RCPCH: page.set_content failed for {url}: {e}")
            # Page is still parked on the real URL from the scraper's
            # navigate() — evaluate() below still works against the live DOM.

        h1 = (page.evaluate(r"""() => {
            const h = document.querySelector('h1');
            return h ? h.textContent.trim() : '';
        }""") or "").strip()
        if h1:
            result["conference_name"] = h1
        title = h1 or shell.get("title")

        fields = self._read_fields(page)

        # Dates — prefer the on-page Views EVA date block (has both
        # start/end for multi-day events); fall back to the shell's
        # listing-derived start_date.
        start_date, end_date = self._parse_dates(fields.get("date_times", []), shell)
        if start_date:
            result["start_date"] = start_date
        if end_date:
            result["end_date"] = end_date
        result["start_time"] = self._parse_start_time(fields.get("time_times", []))

        # Venue / city / region / format
        result.update(self._extract_venue(fields.get("location_text"), fields.get("body_text", "")))

        # Availability -> sold-out flag
        avail = (fields.get("availability_text") or "").strip()
        result["is_sold_out"] = bool(re.search(r"fully booked|sold out|no (?:places|spaces) left|\bfull\b", avail, re.I))

        # Pricing (deterministic)
        result["pricing_tiers"] = self._extract_pricing(fields.get("fee_html", ""), detail_html)

        # Booking URL — prefer the on-page one, fall back to the detail URL itself.
        result["booking_url"] = fields.get("booking_url") or url

        # CPD — RCPCH doesn't publish a numeric points count on any probed
        # page; only mark accredited when the BODY content (not site nav)
        # mentions CPD.
        body_text = fields.get("body_text", "") or ""
        cpd_m = re.search(r"(\d+)\s*(?:CPD\s*)?(?:points?|credits?)", body_text, re.I)
        if cpd_m:
            result["cpd_points"] = int(cpd_m.group(1))
            result["cpd_accredited"] = True
        elif re.search(r"\bCPD\b", body_text, re.I):
            result["cpd_points"] = None
            result["cpd_accredited"] = True
        else:
            result["cpd_points"] = None
            result["cpd_accredited"] = False

        # Abstract / poster submission info (deterministic)
        is_open, deadline = extract_abstract_info(body_text)
        result["abstract_open"] = is_open
        result["abstract_deadline"] = deadline.isoformat() if deadline else None

        # Description + specialty (topic-tag backstop, then LLM, then shared classifier)
        result.update(self._extract_soft_fields(body_text, title, fields.get("topics", []), llm_call))

        return result

    # ------------------------------------------------------------------ #
    # Read all the field--name-field-(cs|ev)-* blocks in one evaluate() call.
    # ------------------------------------------------------------------ #
    @staticmethod
    def _read_fields(page: Page) -> Dict[str, Any]:
        try:
            return page.evaluate(r"""() => {
                const pick = (suffix) =>
                    document.querySelector(`.field--name-field-cs-${suffix}, .field--name-field-ev-${suffix}`);

                const locEl = pick('location');
                const availEl = pick('availability');
                const feeEl = pick('fee');
                const bookEl = pick('booking');
                const bodyEl = document.querySelector('.field--name-field-sh-body');

                const dateView = document.querySelector(
                    '.view-display-id-course_date_eva, .view-display-id-event_date_eva'
                );
                const timeView = document.querySelector(
                    '.view-display-id-course_time_eva, .view-display-id-event_time_eva'
                );

                const times = (el) => el
                    ? Array.from(el.querySelectorAll('time[datetime]')).map(t => t.getAttribute('datetime'))
                    : [];

                const topicLinks = Array.from(document.querySelectorAll('.tags a[href^="/topic/"]'))
                    .map(a => (a.textContent || '').trim())
                    .filter(Boolean);

                const bookLink = bookEl ? bookEl.querySelector('a[href]') : null;

                const addrEl = locEl ? locEl.querySelector('.address') : null;

                return {
                    location_text: (addrEl || locEl) ? (addrEl || locEl).textContent.replace(/\s+/g, ' ').trim() : null,
                    availability_text: availEl ? (availEl.textContent || '').trim() : null,
                    fee_html: feeEl ? feeEl.innerHTML : '',
                    booking_url: bookLink ? bookLink.getAttribute('href') : null,
                    body_text: bodyEl ? (bodyEl.textContent || '').replace(/\s+/g, ' ').trim() : '',
                    date_times: times(dateView),
                    time_times: times(timeView),
                    topics: topicLinks,
                };
            }""") or {}
        except Exception as e:
            logger.warning(f"RCPCH field read failed: {e}")
            return {}

    # ------------------------------------------------------------------ #
    # Dates from the Views EVA date block's <time datetime> tags.
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_dates(iso_times: List[str], shell: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        dates: List[date] = []
        for raw in iso_times:
            try:
                dates.append(datetime.fromisoformat(raw.replace("Z", "+00:00")).date())
            except ValueError:
                continue
        if not dates:
            return shell.get("start_date"), None
        dates.sort()
        start = dates[0].isoformat()
        end = dates[-1].isoformat() if len(dates) > 1 and dates[-1] != dates[0] else None
        return start, end

    @staticmethod
    def _parse_start_time(iso_times: List[str]) -> Optional[str]:
        if not iso_times:
            return None
        try:
            dt = datetime.fromisoformat(iso_times[0].replace("Z", "+00:00"))
            return dt.strftime("%H:%M")
        except ValueError:
            return None

    # ------------------------------------------------------------------ #
    # Venue / city / region / format
    # ------------------------------------------------------------------ #
    def _extract_venue(self, location_text: Optional[str], body_text: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        loc = (location_text or "").strip()

        if not loc:
            # No address field at all — the only signal left is whether the
            # body/fee prose says it's online. If neither says anything,
            # leave format null (self-healing re-fetch picks it up later).
            if _ONLINE_RE.search(body_text or ""):
                out["event_format"] = "online"
            else:
                out["event_format"] = None
            out["venue_name"] = None
            out["city"] = None
            out["region"] = None
            return out

        out["event_format"] = "in_person"
        # Drupal address field renders as "Org Name Address line Locality Postcode Country"
        # concatenated with no separators once flattened to textContent — but
        # postcode and country are reliably at the tail, so strip a UK
        # postcode then peel off a trailing "United Kingdom".
        addr = re.sub(r"\bUnited Kingdom\b\s*$", "", loc, flags=re.I).strip()
        addr = re.sub(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b\s*$", "", addr, flags=re.I).strip()

        city = None
        region = None
        for key, val in _UK_REGIONS.items():
            if re.search(rf"\b{re.escape(key)}\b", addr, re.I):
                city = key.title()
                region = val
                break

        # The city name can also appear earlier in the organisation/venue
        # name (e.g. "Stirling Court Hotel ... Stirling") — the locality
        # span is always the LAST occurrence (it comes right before the
        # postcode/country, which we've already stripped), so split on the
        # last match rather than the first.
        venue = addr
        if city:
            matches = list(re.finditer(rf"\b{re.escape(city)}\b", addr, re.I))
            if matches:
                cut = addr[: matches[-1].start()].strip(" ,")
                venue = cut or addr

        out["venue_name"] = venue[:200] if venue else None
        out["city"] = city
        out["region"] = region
        return out

    # ------------------------------------------------------------------ #
    # Pricing — `.field--name-field-(cs|ev)-fee` inner HTML: <p> section
    # headers + <ul><li>Label - £NNN</li></ul> / <li>Label: £NNN</li> lists,
    # OR free-form "This is a free ... event" prose, OR the field is
    # entirely absent (no fee published — stays []).
    # ------------------------------------------------------------------ #
    def _extract_pricing(self, fee_html: str, full_detail_html: str) -> List[Dict[str, Any]]:
        if not fee_html or not fee_html.strip():
            return []

        tiers: List[Dict[str, Any]] = []
        current_header = ""

        # Fee blocks come in two shapes on RCPCH pages: <ul><li>Label - £NNN</li></ul>
        # lists, and a single <p> with <br>-separated "Label - £NNN" lines. Both
        # can carry a plain-text "Section header:" line (no price) that groups
        # the lines under it. Normalise everything to one line per <p>/<li>/<br>
        # boundary so both shapes are handled by the same loop, in document order
        # so a header line only applies to the lines that follow it.
        normalized = re.sub(r"<h[1-6][^>]*>.*?</h[1-6]>", "\n", fee_html, flags=re.S)
        normalized = re.sub(r"<(?:p|li)[^>]*>", "", normalized)
        normalized = re.sub(r"</(?:p|li)>|<br\s*/?>", "\n", normalized)
        lines = [_strip_tags(l).strip() for l in normalized.split("\n")]
        lines = [l for l in lines if l]

        for line in lines:
            price_m = re.search(r"£\s*[0-9][0-9,]*(?:\.[0-9]+)?", line)
            if not price_m:
                header_text = line.rstrip(":").strip()
                if header_text and header_text.lower() not in ("fees", "fee"):
                    current_header = header_text
                continue

            price = self.parse_gbp(line)
            if price is None:
                continue
            label = line[: price_m.start()].rstrip(" -:–").strip()
            if not label:
                label = current_header or "Fee"
            tier_label = f"{current_header} · {label}" if current_header and current_header != label else label
            tiers.append({
                "tier_label": tier_label[:120],
                "price_gbp": price,
                "is_early_bird": False,
                "early_bird_deadline": None,
            })

        if not tiers:
            fee_text = _strip_tags(fee_html)
            if re.search(r"\bfree\b", fee_text, re.I) and not re.search(r"£\s*[1-9]", fee_text):
                tiers.append({
                    "tier_label": "Standard",
                    "price_gbp": 0.0,
                    "is_early_bird": False,
                    "early_bird_deadline": None,
                })
            else:
                # Belt-and-braces: in case a future page swaps to a plain
                # <table> fee layout the shared helper recognises.
                tiers = parse_pricing_tables(full_detail_html, default_currency="GBP")

        # Dedupe (defends against responsive shadow markup).
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
    # Description + specialty. Topic taxonomy tags are the most reliable
    # backstop for this source (deterministic, curated by RCPCH editors) —
    # tried before the shared keyword classifier.
    # ------------------------------------------------------------------ #
    def _extract_soft_fields(
        self,
        body_text: str,
        title: Optional[str],
        topics: List[str],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        text = (body_text or "")[:3000]

        prompt = f"""You are summarising a single medical CPD event/course detail page. Extract ONLY two fields.

EVENT TITLE: {title}

PAGE BODY:
{text}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the page text" or null,
  "specialty": "primary clinical/topic area (e.g. Paediatrics, Safeguarding, Endocrinology, Medical Education)" or null
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
                logger.warning(f"RCPCH soft-fields JSON parse failed: {e}; raw[:200]={raw[:200]!r}")

        if not result.get("specialty"):
            topic_hint = next(
                (t for t in topics if t.strip().lower() not in _GENERIC_TOPICS),
                None,
            )
            result["specialty"] = (
                topic_hint
                or classify_specialty(title, body_text)
                or "Paediatrics"
            )

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
