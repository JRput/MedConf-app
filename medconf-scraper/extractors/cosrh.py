# extractors/cosrh.py
"""
College of Sexual and Reproductive Healthcare (CoSRH, formerly FSRH) —
detail-page extractor.

iMIS Cloud (ASI/Telerik .aspx) site. The listing at

    https://www.cosrh.org/Public/Events

is a client-side "iPart" widget — raw httpx returns only the header/footer
shell, so a real browser (Playwright) is required for both the listing and
detail pages (no `fetch_html` httpx path works here; recon confirmed the
`/api/Event` REST endpoint returns 401 anonymously, so we don't use it).

Listing cards:

    <li class="psc-cb-dyncontent-content psc-cb-card">
      <div class="dynamichead">...</div>
      <div class="dynamicbody">
        <div class="psc-cb-dynamic-titlebar">
          <div class="auxbar"><span>29 Sep</span><span>Manchester</span></div>
          <h5>CoSRH Conference 2026: Healthy Futures | Manchester and Online</h5>
        </div>
      </div>
      <div class="dynamicfoot">
        <a href="/Public/Event_Display.aspx?EventKey=FACX290926" class="psc-cb-button">
          View Event Details</a>
      </div>
    </li>

The `auxbar` date has no year and is unreliable for multi-day events (it
only shows the first day), so the listing override captures ONLY title +
booking_url + EventKey; every real field is read off the detail page, which
publishes an unambiguous DD/MM/YYYY "When" field.

Detail pages (`/Public/Event_Display.aspx?EventKey=...`) are the standard
iMIS "ciEventDisplay" web part — the same block IDs appear on every event:

    <span id="..._WhenCaption">When</span>
    <span id="..._WhenData">29/09/2026  10:00 - 30/09/2026  16:30<br>GMT ...</span>
    <span id="..._WhereCaption">Where</span>
    <span id="..._AddressData">Mercure Manchester Piccadilly Hotel
Portland St
MANCHESTER
M1 4PH
UNITED KINGDOM</span>

`WhereDiv` is entirely ABSENT for online-only events (AGM, Trainer
Conference) — its presence is itself the in-person/hybrid signal.

The free-text "AdditionalInfoHtmlData" div holds the actual event copy
(overview, pricing, entry requirements, FAQs, cancellation policy) as
whatever HTML each event organiser pasted in — three pricing shapes seen
across the 9 live events, all handled by `_extract_pricing`:
  1. A matrix `<table>` with a header row (blank/label first cell, then
     "In-Person" / "Online" columns) and EITHER (a) `colspan` section rows
     ("Members" / "Concessions") splitting groups of ticket rows, or
     (b) no groups at all — just category rows straight under the header.
  2. A plain 2-column `<table>` with no header row (label | £price), no
     In-Person/Online split (e.g. the DCSRH Assessment Half Day).
  3. No `<table>` at all — inline prose "Pricing:" followed by
     "Label: £NNN[ per X]" lines (Postpartum Contraception Training), or a
     flat "free of charge" statement (Trainer Conference -> one £0 tier).
  4. No pricing section published at all (member-login-required booking,
     e.g. the Menopause Care course, the AGM, the Trainer Conference
     registration flow) -> `pricing_tiers = []`, never fabricated.

CPD points are NOT part of the standard block IDs — when published, they
appear as a plain "Gain 3 CPD points" / "up to 3 CPD points" sentence in
the free-text body, so `_extract_cpd` regexes the cleaned body text rather
than a fixed selector.

Booking requires an account sign-in for every event (no anonymous "sold
out" state is ever rendered) -> `is_sold_out` cannot be determined
deterministically and is left False (flagged in concerns).

Event type: none of the 9 live events recur across multiple dates (course
titles like "Essentials of Menopause Care course" and "Postpartum
Contraception Training Course" each get their OWN EventKey per date, same
pattern as RCPE's Evening Medical Updates) — so this source never emits
`sessions[]`; instead each row is classified individually as
conference/workshop by `_classify_event_type` on the title.
"""

import re
import html as _htmlmod
import json as _json
from datetime import date
from typing import Dict, Any, Optional, Callable, List, Tuple
from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from .abstract_classifier import extract_abstract_info
from .pricing_tables import _parse_price as parse_price_generic
from logger import logger


LISTING_URL = "https://www.cosrh.org/Public/Events"
BASE_URL = "https://www.cosrh.org"

UK_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)
_NON_UK_TRAILERS = {"united kingdom", "uk", "england", "scotland", "wales", "northern ireland"}

_UK_REGIONS = {
    "edinburgh": "Scotland", "glasgow": "Scotland", "aberdeen": "Scotland", "dundee": "Scotland",
    "london": "London", "manchester": "North West England", "liverpool": "North West England",
    "leeds": "Yorkshire and the Humber", "sheffield": "Yorkshire and the Humber",
    "york": "Yorkshire and the Humber", "newcastle": "North East England",
    "birmingham": "West Midlands", "bristol": "South West England", "exeter": "South West England",
    "cardiff": "Wales", "swansea": "Wales", "belfast": "Northern Ireland",
    "cambridge": "East of England", "norwich": "East of England",
    "oxford": "South East England", "brighton": "South East England",
    "leicester": "East Midlands", "nottingham": "East Midlands", "southampton": "South East England",
}


def _infer_uk_region(city: Optional[str]) -> Optional[str]:
    c = (city or "").lower()
    for key, val in _UK_REGIONS.items():
        if key in c:
            return val
    return None


def _clean(html_frag: str) -> str:
    if not html_frag:
        return ""
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html_frag, flags=re.DOTALL | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = _htmlmod.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


class CoSRHExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing — client-side iMIS iPart, browser-first (recon: js_required)
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        browser = getattr(self, "browser", None)
        page = getattr(browser, "page", browser)
        if page is None:
            logger.warning("CoSRH: no browser page available for listing")
            return None

        shells: List[Dict[str, Any]] = []
        try:
            page.goto(LISTING_URL, wait_until="load", timeout=30000)
            try:
                page.wait_for_selector("li.psc-cb-dyncontent-content.psc-cb-card", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(2000)
            html = page.content()
        except Exception as e:
            logger.warning(f"CoSRH: listing navigation failed: {e}")
            return None

        cards = re.findall(
            r'<li class="psc-cb-dyncontent-content psc-cb-card">.*?</li>', html, re.DOTALL,
        )
        seen_urls = set()
        for card_html in cards:
            href_m = re.search(r'href="([^"]+)"\s+class="psc-cb-button"', card_html)
            title_m = re.search(r"<h5>(.*?)</h5>", card_html, re.DOTALL)
            if not href_m or not title_m:
                continue
            href = href_m.group(1).strip()
            booking_url = href if href.startswith("http") else BASE_URL + href
            if booking_url in seen_urls:
                continue
            seen_urls.add(booking_url)
            title = _clean(title_m.group(1))
            if not title:
                continue
            key_m = re.search(r"EventKey=([A-Za-z0-9]+)", booking_url)
            shells.append({
                "title": title,
                "booking_url": booking_url,
                "event_key": key_m.group(1) if key_m else None,
                "is_sold_out": False,
            })

        if not shells:
            logger.warning("CoSRH listing override found 0 shells; falling back to DOM walker")
            return None

        logger.info(f"CoSRH: {len(shells)} shells found on listing page")
        return shells

    # ------------------------------------------------------------------ #
    # Detail page
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        try:
            page.wait_for_selector(".EventDisplay", timeout=15000)
        except Exception:
            pass
        try:
            page.wait_for_timeout(1500)
            html = page.content()
        except Exception as e:
            logger.warning(f"CoSRH: page.content() failed for {shell.get('booking_url')}: {e}")
            html = ""

        result: Dict[str, Any] = {}

        # Real title — the <title> tag (H1 isn't used on this template), never
        # trust the listing shell text in case the SPA briefly rendered an
        # empty/error state during shell harvesting.
        title_m = re.search(r"<title>\s*(.*?)\s*(?:\|\s*CoSRH\s*)?</title>", html, re.DOTALL | re.I)
        result["conference_name"] = _clean(title_m.group(1)) if title_m else shell.get("title")

        # --- When ---
        when_m = re.search(r'_WhenData"[^>]*>(.*?)</span>', html, re.DOTALL)
        when_text = _clean(when_m.group(1)) if when_m else ""
        start_date, end_date, start_time = self._parse_when(when_text)
        result["start_date"] = start_date
        result["end_date"] = end_date or start_date
        result["start_time"] = start_time

        # --- Where (absent entirely for online-only events) ---
        where_present = "_WhereDiv" in html
        address_m = re.search(r'_AddressData"[^>]*>(.*?)</span>', html, re.DOTALL)
        address_text = _clean(address_m.group(1).replace("<br>", "\n").replace("<br/>", "\n")) if address_m else ""
        # Re-extract with real newlines preserved (the _clean above collapses
        # them) — pull the raw fragment and normalise <br> tags to \n first.
        if address_m:
            raw_addr = address_m.group(1)
            raw_addr = re.sub(r"<br\s*/?>", "\n", raw_addr)
            address_text = _htmlmod.unescape(re.sub(r"<[^>]+>", "", raw_addr)).strip()

        # Body text (everything in the free-text info block) used for
        # online/hybrid detection, CPD points, abstracts, soft fields.
        body_m = re.search(r'AdditionalInfoHtmlData"[^>]*>(.*?)</span>\s*</div>\s*</div>\s*</div>', html, re.DOTALL)
        body_html = body_m.group(1) if body_m else ""
        body_text = _clean(body_html)

        online_mentioned = bool(re.search(r"\bonline\b|\bvirtual\b|\bzoom\b|\bwebinar\b", body_text, re.I))

        venue_name, city = self._parse_address(address_text) if where_present and address_text else (None, None)
        if where_present and venue_name:
            result["venue_name"] = venue_name
            result["city"] = city
            result["region"] = _infer_uk_region(city)
            result["event_format"] = "hybrid" if online_mentioned else "in_person"
        elif online_mentioned:
            result["venue_name"] = None
            result["city"] = None
            result["region"] = None
            result["event_format"] = "online"
        else:
            result["venue_name"] = None
            result["city"] = None
            result["region"] = None
            result["event_format"] = None

        # --- Event type (title heuristic — no source recurs into sessions) ---
        result["event_type"] = self._classify_event_type(result["conference_name"] or shell.get("title") or "")

        # --- CPD (free-text mention only; no structured field on this template) ---
        cpd_m = re.search(r"(\d+)\s*CPD\s*points?", body_text, re.I)
        result["cpd_points"] = int(cpd_m.group(1)) if cpd_m else None
        result["cpd_accredited"] = bool(cpd_m) or bool(re.search(r"\bCPD\b", body_text))

        # --- Sold out: never observable anonymously (booking requires sign-in) ---
        result["is_sold_out"] = False

        # --- Pricing ---
        result["pricing_tiers"] = self._extract_pricing(body_html, body_text)

        # --- Abstracts ---
        if re.search(r"abstract|poster|call for papers", body_text, re.I):
            is_open, deadline = extract_abstract_info(body_text)
            result["abstract_open"] = is_open
            result["abstract_deadline"] = deadline.isoformat() if deadline else None
        else:
            result["abstract_open"] = False
            result["abstract_deadline"] = None

        # --- Soft fields ---
        result.update(self._extract_soft_fields(body_text, result["conference_name"] or shell.get("title") or "", llm_call))

        return result

    # ------------------------------------------------------------------ #
    # When / date parsing
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_when(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """'29/09/2026  10:00 - 30/09/2026  16:30 GMT Daylight Time' ->
        ('2026-09-29','2026-09-30','10:00'). Single-day form
        '14/10/2026  09:00 - 13:00 ...' -> ('2026-10-14','2026-10-14','09:00')."""
        if not text:
            return None, None, None

        two_day = re.search(
            r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2})\s*-\s*(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2})",
            text,
        )
        if two_day:
            d1, m1, y1, t1, d2, m2, y2, t2 = two_day.groups()
            try:
                start = date(int(y1), int(m1), int(d1)).isoformat()
                end = date(int(y2), int(m2), int(d2)).isoformat()
                return start, end, t1
            except ValueError:
                pass

        one_day = re.search(
            r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})", text,
        )
        if one_day:
            d, m, y, t1, _t2 = one_day.groups()
            try:
                dt = date(int(y), int(m), int(d)).isoformat()
                return dt, dt, t1
            except ValueError:
                pass

        # Bare date, no time range (defensive — not seen live).
        bare = re.search(r"(\d{2})/(\d{2})/(\d{4})", text)
        if bare:
            d, m, y = bare.groups()
            try:
                dt = date(int(y), int(m), int(d)).isoformat()
                return dt, dt, None
            except ValueError:
                pass

        return None, None, None

    # ------------------------------------------------------------------ #
    # Event type classification (title heuristic)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _classify_event_type(title: str) -> str:
        t = (title or "").lower()
        if re.search(r"\bassessment\b|\bagm\b|annual general meeting|\bcourse\b|\btraining\b", t):
            return "workshop"
        return "conference"

    # ------------------------------------------------------------------ #
    # Venue address parsing
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_address(address_text: str) -> Tuple[Optional[str], Optional[str]]:
        lines = [l.strip(" ,") for l in address_text.split("\n") if l.strip(" ,")]
        if lines and lines[-1].strip().lower() in _NON_UK_TRAILERS:
            lines = lines[:-1]
        if not lines:
            return None, None

        last = lines[-1]
        pc_m = UK_POSTCODE_RE.search(last)
        if pc_m:
            before = UK_POSTCODE_RE.sub("", last).strip(" ,")
            if before:
                city = before
                venue_lines = lines[:-1]
            else:
                city = lines[-2] if len(lines) >= 2 else None
                venue_lines = lines[:-2] if len(lines) >= 2 else []
        else:
            city = last
            venue_lines = lines[:-1]

        venue_name = venue_lines[0] if venue_lines else None
        if city and city.isupper():
            city = city.title()
        return venue_name, city

    # ------------------------------------------------------------------ #
    # Pricing — matrix table / plain table / prose colon-lines / "free"
    # ------------------------------------------------------------------ #
    def _extract_pricing(self, body_html: str, body_text: str) -> List[Dict[str, Any]]:
        # Isolate the Pricing section: from a "Pricing" heading/label to the
        # next h1-h4 heading (or end of body if it's the last section).
        section_m = re.search(
            r"(?is)(<h[1-4][^>]*>\s*(?:<[^>]+>\s*)*pricing\s*:?\s*(?:</[^>]+>\s*)*</h[1-4]>|"
            r"pricing\s*:\s*</span>)(.*?)(?=<h[1-4][^>]*>|$)",
            body_html,
        )
        section_html = section_m.group(2) if section_m else ""
        if not section_html and "pricing" not in body_text.lower():
            return []
        if not section_html:
            # "Pricing" mentioned only as plain inline text (no heading tag) —
            # fall back to scanning from that point in the raw body.
            idx = body_html.lower().find("pricing")
            section_html = body_html[idx:idx + 4000] if idx >= 0 else ""

        tiers: List[Dict[str, Any]] = []

        table_m = re.search(r"<table[^>]*>(.*?)</table>", section_html, re.DOTALL)
        if table_m:
            tiers = self._parse_pricing_table(table_m.group(1))

        if not tiers:
            # Prose "Label: £NNN[ per X]" lines, e.g.
            # "CoSRH members: £350 per ticket".
            section_text = _clean(section_html)
            for m in re.finditer(
                r"([A-Za-z][A-Za-z &/()'’,-]{2,60}?):\s*£\s*([\d,]+(?:\.\d{1,2})?)(?:\s*per\s+\w+)?",
                section_text,
            ):
                label = m.group(1).strip()
                price = parse_price_generic(m.group(2))
                if price is None:
                    continue
                tiers.append({
                    "tier_label": label[:120],
                    "price_gbp": price,
                    "is_early_bird": bool(re.search(r"early[- ]?bird", label, re.I)),
                    "early_bird_deadline": None,
                })

        if not tiers and re.search(r"free of charge|completely free|no charge|no cost", body_text, re.I):
            tiers.append({
                "tier_label": "Standard",
                "price_gbp": 0.0,
                "is_early_bird": False,
                "early_bird_deadline": None,
            })

        # Dedupe (label, price)
        seen = set()
        deduped = []
        for t in tiers:
            key = (t["tier_label"], t["price_gbp"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(t)
        return deduped

    @staticmethod
    def _parse_pricing_table(table_html: str) -> List[Dict[str, Any]]:
        rows_raw = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL)
        rows: List[List[str]] = []
        for row_html in rows_raw:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.DOTALL)
            rows.append([_clean(c) for c in cells])
        rows = [r for r in rows if any(c for c in r)]
        if not rows:
            return []

        def cell_price(c: str) -> Optional[float]:
            return parse_price_generic(c) if re.search(r"[£\d]", c or "") else None

        # Header row: first row where none of cells[1:] parse as a price
        # (they're column captions like "In-Person" / "Online").
        header_cols: Optional[List[str]] = None
        data_rows = rows
        first_row = rows[0]
        if len(first_row) >= 2 and all(cell_price(c) is None for c in first_row[1:]):
            header_cols = [c or None for c in first_row[1:]]
            data_rows = rows[1:]

        tiers: List[Dict[str, Any]] = []
        current_group: Optional[str] = None
        for row in data_rows:
            non_empty = [c for c in row if c]
            # Section/group header: a single non-empty cell (colspan), no price.
            if len(non_empty) == 1 and cell_price(non_empty[0]) is None:
                current_group = non_empty[0]
                continue
            if len(row) < 2:
                continue
            label = row[0]
            if not label:
                continue
            if label.lower() in {"category", "type", "rate", "amount", "price", "cost", "fee", "membership category"}:
                continue

            if header_cols:
                for i, col in enumerate(header_cols, start=1):
                    if i >= len(row):
                        break
                    price = cell_price(row[i])
                    if price is None:
                        continue
                    parts = [p for p in (current_group, col, label) if p]
                    tiers.append({
                        "tier_label": " · ".join(parts)[:120],
                        "price_gbp": price,
                        "is_early_bird": bool(re.search(r"early[- ]?bird", label, re.I)),
                        "early_bird_deadline": None,
                    })
            else:
                price = None
                for c in reversed(row[1:]):
                    price = cell_price(c)
                    if price is not None:
                        break
                if price is None:
                    continue
                parts = [p for p in (current_group, label) if p]
                tiers.append({
                    "tier_label": " · ".join(parts)[:120],
                    "price_gbp": price,
                    "is_early_bird": bool(re.search(r"early[- ]?bird", label, re.I)),
                    "early_bird_deadline": None,
                })

        return tiers

    # ------------------------------------------------------------------ #
    # Description + specialty (LLM, small prompt, heuristic fallback)
    # ------------------------------------------------------------------ #
    def _extract_soft_fields(
        self,
        body_text: str,
        title: str,
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        # Cut the free-text body off before the Pricing/Entry
        # requirements/FAQs/Cancellation boilerplate so the LLM only sees
        # the genuine overview prose.
        overview = re.split(
            r"(?i)\b(pricing|entry requirements|faqs?|cancellation and refund policy|how to book)\b",
            body_text, maxsplit=1,
        )[0].strip()
        text = overview[:3000] if overview else body_text[:3000]

        prompt = f"""You are summarising a single medical conference/event detail page. Extract ONLY two fields.

EVENT TITLE: {title}

PAGE BODY:
{text}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the page text" or null,
  "specialty": "primary clinical specialty (e.g. Cardiology, Infectious Disease, Respiratory)" or null
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
                logger.warning(f"CoSRH soft-fields JSON parse failed: {e}; raw[:200]={raw[:200]!r}")

        if not result.get("specialty"):
            heuristic = classify_specialty(title, text)
            if heuristic:
                result["specialty"] = heuristic
            else:
                # Site-wide default — every CoSRH event is sexual/reproductive
                # healthcare even when the title/body don't say so explicitly
                # (e.g. "CoSRH Trainer Conference").
                result["specialty"] = "Sexual & Reproductive Health"

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
