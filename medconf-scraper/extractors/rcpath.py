"""
Royal College of Pathologists (RCPath) — events extractor.

Preside CMS (ColdFusion), fully server-rendered, no JS required for either
listing or detail pages.

LISTING (https://www.rcpath.org/profession/conferences/events.html):
The single listing page renders ~506 `/event/<slug>.html` cards grouped into
year `<div class="events" id="events-YYYY">` blocks. Crucially, the site
itself already separates past from upcoming: a block whose id ends in
`-past` (e.g. `events-2025-past`, `events-2026-past`) holds already-happened
events, while a plain `events-YYYY` block (e.g. `events-2026`, `events-2027`)
holds only *upcoming* events for that year. We exploit this directly in
`list_shells_override()` instead of trying to infer "upcoming" from a
day-badge with no month attached (the `<span class="day">18</span>` cards
carry NO month/year — only the enclosing year-block id and the site's own
past/future bucketing tell you which side of "today" an event falls on).
Each `<li>` card also carries a CPD-credit line and 0-2 `<span
class="category">` badges ("External Event" / "College conference" /
"Webinar") which we surface into `shell["category"]` for the 3-way
event_type merge.

DETAIL (https://www.rcpath.org/event/<slug>.html):
Two shapes observed, both server-rendered (verified via plain httpx GET —
no JS needed):

  A) Externally-hosted events (booking on a 3rd-party site, e.g.
     diagnexia.com or a Zoom registration link): `.banner-info-box` gives
     h1/date/CPD; NO tab structure in main content; venue/price info, if
     any, lives directly in `<aside class="sidebar">` as a bare `<h3>` +
     `<p>` pair right after the "Book a Place" widget (e.g. `<h3>Zoom</h3>`).
     Sample: computational-pathology-fundamentals.html (External Event, no
     price, no venue — booking on diagnexia.com); liver-pathology-bitesize-
     webinars-11.html (External→actually College, Zoom, Free banner badge).

  B) College-run events with a Bootstrap tab UI in the main content
     (`.tab-content > .tab-pane#tab-N`, nav labels via `[role=tab]`):
     Overview / Programme / "Registration Fees" (or "Registration fees") /
     Location (or Zoom) / etc. Registration Fees tab content is NOT an HTML
     `<table>` — it's `<p><strong>Label</strong>: £NNN</p>` or
     `<p><strong>Label</strong> - £NNN</p>` / `- FREE` lines mixed with
     unrelated cancellation-policy prose we must filter out. Location tab
     (in-person) is a free-text address paragraph + embedded Google Maps
     iframe, e.g. "Postgraduate Medical Centre, Belfast City Hospital, 51
     Lisburn Road, Belfast BT9 7AB". Samples: medical-examiner-training-
     virtual-8.html (single flat fee), new-consultants-day-2026-virtual.html
     (member FREE / non-member £103 — two tiers), northern-ireland-
     symposium-2026-...html (in-person, free, Location tab with address).

Banner also sometimes carries a `<span class="side-note orange">Free</span>`
badge — but ONLY when the whole event is free (never appears alongside a
mixed fee table), so it's a safe signal to synthesise a single £0 tier when
no Registration Fees tab exists at all.
"""

from __future__ import annotations

import re
import html as html_lib
from datetime import date
from typing import Dict, Any, Optional, Callable, List

import httpx
from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from .abstract_classifier import extract_abstract_info
from .pricing_tables import parse_pricing_tables
from logger import logger


LISTING_URL = "https://www.rcpath.org/profession/conferences/events.html"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

UK_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
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
    "belfast": "Northern Ireland",
    "cambridge": "East of England",
    "norwich": "East of England",
    "oxford": "South East England",
    "brighton": "South East England",
    "leicester": "East Midlands",
    "nottingham": "East Midlands",
}

# Whole-region hints used only when no city-level address text is found
# (e.g. banner hint "To be held in Northern Ireland").
_REGION_ONLY_HINTS = {
    "northern ireland": "Northern Ireland",
    "scotland": "Scotland",
    "wales": "Wales",
}

# Category badges on listing cards -> shell["category"] used by the 3-way
# event_type merge in llm_agent._merge_shell_and_detail.
_CATEGORY_MAP = {
    "webinar": "workshop",
    "college conference": "conference",
    # "External Event" deliberately unmapped — too mixed (courses, symposia,
    # workshops all show this badge); let the title heuristic decide.
}

# Noise lines inside a Registration Fees tab that must never be read as a
# price row even though they may contain a £ amount (e.g. cancellation fee).
_FEE_NOISE_RE = re.compile(
    r"cancellation|administrative charge|payments? (?:are|must)|"
    r"contact us|non[- ]transferrable|forfeited|please note that an",
    re.I,
)

_FEE_LINE_RE = re.compile(
    r"^(?P<label>.+?)[\s:\u2013\u2014-]+\s*"
    r"(?:£\s*(?P<price>[0-9][0-9,]*(?:\.[0-9]{1,2})?)|(?P<free>free)\b)\.?\s*$",
    re.I,
)


def _http_get(url: str) -> Optional[str]:
    try:
        with httpx.Client(
            timeout=30.0, follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        logger.warning(f"RCPath httpx GET failed for {url}: {e}")
        return None


class RCPathExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing phase — bypass the shared DOM walker so we can exploit the
    # site's own past/upcoming year-block split.
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = _http_get(LISTING_URL)
        if not html:
            logger.warning("RCPath: listing fetch failed, no shells")
            return None

        # Locate every year-block start (`events-YYYY` or `events-YYYY-past`)
        # in document order, then slice the HTML between consecutive
        # boundaries so each segment holds exactly one block's <li> cards.
        block_starts = [
            (m.start(), m.group(1))
            for m in re.finditer(
                r'<div class="events[^"]*"\s+id="(events-\d{4}(?:-past)?)"', html
            )
        ]
        if not block_starts:
            logger.warning("RCPath: no year blocks found in listing HTML")
            return None

        shells: List[Dict[str, Any]] = []
        seen_urls = set()
        for i, (start, block_id) in enumerate(block_starts):
            if block_id.endswith("-past"):
                continue  # already-happened events — skip entirely
            end = block_starts[i + 1][0] if i + 1 < len(block_starts) else len(html)
            segment = html[start:end]

            for li_m in re.finditer(r"<li>(.*?)</li>", segment, re.S):
                li_html = li_m.group(1)
                title_m = re.search(
                    r'<h3>\s*<a href="([^"]+)">([^<]*)</a>', li_html
                )
                if not title_m:
                    continue
                url = html_lib.unescape(title_m.group(1)).strip()
                title = html_lib.unescape(title_m.group(2)).strip()
                if not url or not title or url in seen_urls:
                    continue
                seen_urls.add(url)

                cats = [
                    html_lib.unescape(c).strip()
                    for c in re.findall(r'<span class="category">([^<]+)</span>', li_html)
                ]
                category = None
                for c in cats:
                    mapped = _CATEGORY_MAP.get(c.strip().lower())
                    if mapped:
                        category = mapped
                        break

                shells.append({
                    "title": title,
                    "booking_url": url,
                    "category": category,
                })

        logger.info(f"RCPath: {len(shells)} upcoming shells from listing (of {len(seen_urls)} unique links)")
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

        # 1. Conference name from h1 — never trust the listing shell title.
        # The page renders more than one <h1> (site logo + cookie banner);
        # the real title lives inside .banner-info-box.
        h1 = page.evaluate(
            "() => { const el = document.querySelector('.banner-info-box h1'); "
            "return el ? el.textContent.trim() : null; }"
        )
        if h1:
            result["conference_name"] = h1

        # 2. Banner: date range + CPD + Free badge + optional location hint
        banner = self._extract_banner(page)

        start_date, end_date = self._parse_dates(banner.get("date_text"))
        if start_date:
            result["start_date"] = start_date
        if end_date:
            result["end_date"] = end_date

        cpd_points = self._parse_cpd(banner.get("credits_text"))
        result["cpd_points"] = cpd_points
        result["cpd_accredited"] = bool(cpd_points) or bool(
            re.search(r"CPD[- ]accredit|CPD[- ]approv", page.evaluate("() => document.body.textContent || ''") or "", re.I)
        )

        # 3. Pricing — Registration Fees tab (bespoke <p> parser) first,
        # then the shared plain-table parser as a supplementary catch,
        # then the Free-badge fallback.
        tiers = self._extract_pricing(page)
        if not tiers:
            html = page.content()
            tiers = parse_pricing_tables(html, default_currency="GBP")
        if not tiers and banner.get("is_free"):
            tiers = [{
                "tier_label": "Standard",
                "price_gbp": 0.0,
                "is_early_bird": False,
                "early_bird_deadline": None,
            }]
        result["pricing_tiers"] = tiers

        # 4. Venue / city / region / format
        result.update(self._extract_venue(page, banner.get("location_hint")))

        # 5. Abstract / poster submission info (deterministic)
        page_text = page.evaluate("() => document.body.textContent || ''") or ""
        is_open, deadline = extract_abstract_info(page_text)
        result["abstract_open"] = is_open
        result["abstract_deadline"] = deadline.isoformat() if deadline else None

        # 6. Description + specialty (LLM, small prompt, heuristic fallback)
        result.update(self._extract_soft_fields(page, shell, llm_call))

        return result

    # ------------------------------------------------------------------ #
    # Banner: .banner-info-box h1 / p.date / p.credits / Free badge / hint
    # ------------------------------------------------------------------ #
    def _extract_banner(self, page: Page) -> Dict[str, Any]:
        try:
            return page.evaluate(r"""() => {
                const box = document.querySelector('.banner-info-box');
                if (!box) return {};
                const dateEl = box.querySelector('p.date');
                const creditsEl = box.querySelector('p.credits');
                const freeEl = box.querySelector('.side-note');
                // Location hint: any <p> in the banner that is neither
                // .date nor .credits nor containing a .side-note badge.
                let hint = null;
                for (const p of box.querySelectorAll('p')) {
                    if (p === dateEl || p === creditsEl) continue;
                    if (p.querySelector('.side-note')) continue;
                    const t = (p.textContent || '').replace(/\s+/g, ' ').trim();
                    if (t) { hint = t; break; }
                }
                return {
                    date_text: dateEl ? dateEl.textContent.replace(/\s+/g, ' ').trim() : null,
                    credits_text: creditsEl ? creditsEl.textContent.replace(/\s+/g, ' ').trim() : null,
                    is_free: freeEl ? /free/i.test(freeEl.textContent) : false,
                    location_hint: hint,
                };
            }""") or {}
        except Exception as e:
            logger.warning(f"RCPath banner extraction failed: {e}")
            return {}

    # ------------------------------------------------------------------ #
    # Dates — "18–19, August 2026" / "1 September 2026" / cross-month range
    # ------------------------------------------------------------------ #
    def _parse_dates(self, date_text: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        if not date_text:
            return None, None
        text = date_text.strip()

        # Cross-month range: "29 June - 2 July 2026"
        m = re.search(
            r"(\d{1,2})\s+([A-Za-z]+)\s*[\u2013\u2014-]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
            text,
        )
        if m:
            d1, mon1, d2, mon2, year = m.groups()
            return self._iso(year, mon1, d1), self._iso(year, mon2, d2)

        # Same-month range: "18–19, August 2026" / "18-19 August 2026"
        m = re.search(r"(\d{1,2})\s*[\u2013\u2014-]\s*(\d{1,2}),?\s+([A-Za-z]+)\s+(\d{4})", text)
        if m:
            d1, d2, mon, year = m.groups()
            return self._iso(year, mon, d1), self._iso(year, mon, d2)

        # Single day: "1 September 2026"
        m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text)
        if m:
            d1, mon, year = m.groups()
            return self._iso(year, mon, d1), None

        return None, None

    @staticmethod
    def _iso(year: str, month_name: str, day: str) -> Optional[str]:
        mon = _MONTHS.get(month_name.lower()[:3])
        if not mon:
            return None
        try:
            return f"{int(year):04d}-{mon:02d}-{int(day):02d}"
        except ValueError:
            return None

    # ------------------------------------------------------------------ #
    # CPD — "14 CPD Credits" / "1 CPD Credit"
    # ------------------------------------------------------------------ #
    def _parse_cpd(self, credits_text: Optional[str]) -> Optional[int]:
        if not credits_text:
            return None
        m = re.search(r"(\d+)\s*CPD\s*Credits?", credits_text, re.I)
        return int(m.group(1)) if m else None

    # ------------------------------------------------------------------ #
    # Pricing — Registration Fees tab: "<p><strong>Label</strong>: £X</p>"
    # or "<p><strong>Label</strong> - FREE</p>", cancellation-policy prose
    # filtered out by _FEE_NOISE_RE.
    # ------------------------------------------------------------------ #
    def _extract_pricing(self, page: Page) -> List[Dict[str, Any]]:
        try:
            lines = page.evaluate(r"""() => {
                const panes = Array.from(document.querySelectorAll('.tab-pane'));
                const feePane = panes.find(p => {
                    const header = p.querySelector('.mobile-accordion-header');
                    return header && /registration fee/i.test(header.textContent);
                });
                if (!feePane) return [];
                const content = feePane.querySelector('.page-content');
                if (!content) return [];
                return Array.from(content.querySelectorAll('p'))
                    .map(p => (p.textContent || '').replace(/\s+/g, ' ').trim())
                    .filter(t => t.length > 0);
            }""") or []
        except Exception as e:
            logger.warning(f"RCPath pricing extraction failed: {e}")
            return []

        tiers: List[Dict[str, Any]] = []
        for line in lines:
            if _FEE_NOISE_RE.search(line):
                continue
            m = _FEE_LINE_RE.match(line)
            if not m:
                continue
            label = m.group("label").strip(" :-\u2013\u2014")
            if not label or _FEE_NOISE_RE.search(label):
                continue
            if m.group("free"):
                price = 0.0
            else:
                try:
                    price = float(m.group("price").replace(",", ""))
                except (TypeError, ValueError):
                    continue
            tiers.append({
                "tier_label": label[:120],
                "price_gbp": price,
                "is_early_bird": bool(re.search(r"early[- ]?bird", label, re.I)),
                "early_bird_deadline": None,
            })

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
    # Venue / city / region / format
    # ------------------------------------------------------------------ #
    _ONLINE_RE = re.compile(
        r"\b(zoom|webinar|virtual|online|microsoft teams|ms teams|teams|"
        r"livestream|live stream|held via)\b", re.I,
    )

    def _extract_venue(self, page: Page, banner_hint: Optional[str]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}

        loc_text = None
        try:
            loc_text = page.evaluate(r"""() => {
                // 1. A tab-pane whose header matches Location/Venue/Zoom
                const panes = Array.from(document.querySelectorAll('.tab-pane'));
                const pane = panes.find(p => {
                    const header = p.querySelector('.mobile-accordion-header');
                    return header && /location|venue|zoom/i.test(header.textContent);
                });
                if (pane) {
                    const content = pane.querySelector('.page-content');
                    if (content) {
                        const clone = content.cloneNode(true);
                        clone.querySelectorAll('iframe, script, style').forEach(n => n.remove());
                        const t = (clone.textContent || '').replace(/\s+/g, ' ').trim();
                        if (t) return t;
                    }
                }
                // 2. Sidebar h3 + adjacent text (non-tabbed simple pages).
                // Only h3 elements that are DIRECT children of the sidebar
                // qualify — unrelated "More events" / "Featured" promo
                // panels (e.g. "World Patient Safety Day") wrap their own
                // h3 inside a nested .widget/.featured-panel div and must
                // be excluded, or they get misread as the venue name.
                const aside = document.querySelector('aside.sidebar');
                if (aside) {
                    const h3s = Array.from(aside.children).filter(el => el.tagName === 'H3');
                    const h3 = h3s.find(h => {
                        const t = (h.textContent || '').trim();
                        return t && !/book a place|more events/i.test(t);
                    });
                    if (h3) {
                        let collected = h3.textContent.trim() + ' ';
                        let cursor = h3.nextElementSibling;
                        let hops = 0;
                        while (cursor && hops < 3 && cursor.tagName !== 'H3') {
                            collected += (cursor.textContent || '').replace(/\s+/g, ' ').trim() + ' ';
                            cursor = cursor.nextElementSibling;
                            hops++;
                        }
                        return collected.trim();
                    }
                }
                return null;
            }""")
        except Exception as e:
            logger.warning(f"RCPath venue extraction failed: {e}")

        # Extra online signal: the "Book a Place" button often links straight
        # to a Zoom/Teams/Webex registration URL even when no Location/Zoom
        # tab or sidebar note exists at all.
        booking_href = ""
        try:
            booking_href = page.evaluate(
                "() => { const a = document.querySelector('.booking-widget a'); "
                "return a ? a.href : ''; }"
            ) or ""
        except Exception:
            pass

        combined_for_online_check = (loc_text or "") + " " + (banner_hint or "") + " " + booking_href
        if self._ONLINE_RE.search(combined_for_online_check) or re.search(
            r"zoom\.us|teams\.microsoft\.com|webex\.com", booking_href, re.I
        ):
            out["event_format"] = "online"
            out["venue_name"] = None
            out["city"] = None
            out["region"] = None
            return out

        # In-person: prefer the detail-page location text; fall back to the
        # banner hint ("To be held in Northern Ireland" — region only, no
        # street address, so venue_name stays null rather than fabricated).
        address = loc_text or None
        if not address and banner_hint:
            for key, region in _REGION_ONLY_HINTS.items():
                if key in banner_hint.lower():
                    out["event_format"] = "in_person"
                    out["venue_name"] = None
                    out["city"] = None
                    out["region"] = region
                    return out
            # Unrecognised banner hint text — leave everything null so the
            # next scrape run retries once the detail page publishes more.
            return out

        if not address:
            return out

        out["event_format"] = "in_person"
        clean_address = UK_POSTCODE_RE.sub("", address).strip(" ,")
        # Strip common lead-in phrases the Location tab prose uses before
        # the actual venue name ("Event to be held at X", "This event will
        # take place at X", "Venue: X").
        clean_address = re.sub(
            r"^(?:event to be held at|this event will (?:be held|take place) at|"
            r"the (?:event|symposium|meeting|course) will (?:be held|take place) at|"
            r"venue\s*:)\s*",
            "", clean_address, flags=re.I,
        ).strip(" ,")

        city = None
        region = None
        for key in _UK_REGIONS:
            if re.search(rf"\b{re.escape(key)}\b", clean_address, re.I):
                city = key.title()
                region = _UK_REGIONS[key]
                break
        if not city:
            for key, reg in _REGION_ONLY_HINTS.items():
                if key in clean_address.lower():
                    region = reg
                    break

        venue_name = clean_address
        if city:
            cut = re.split(rf"\b{re.escape(city)}\b", clean_address, flags=re.I)[0].strip(" ,")
            venue_name = cut or clean_address

        out["venue_name"] = venue_name[:200] if venue_name else None
        out["city"] = city
        out["region"] = region
        return out

    # ------------------------------------------------------------------ #
    # Description + specialty (LLM, small prompt, heuristic fallback)
    # ------------------------------------------------------------------ #
    def _extract_soft_fields(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        # Prefer the Overview tab / intro-text prose; fall back to main body.
        text = page.evaluate(r"""() => {
            const panes = Array.from(document.querySelectorAll('.tab-pane'));
            const overview = panes.find(p => {
                const header = p.querySelector('.mobile-accordion-header');
                return header && /overview/i.test(header.textContent);
            });
            const source = overview ? overview.querySelector('.page-content') : null;
            if (source) {
                const clone = source.cloneNode(true);
                clone.querySelectorAll('script, style, iframe').forEach(n => n.remove());
                const t = clone.textContent.replace(/\s+/g, ' ').trim();
                if (t.length > 40) return t;
            }
            const intro = document.querySelector('.intro-text');
            if (intro) {
                const t = intro.textContent.replace(/\s+/g, ' ').trim();
                if (t.length > 40) return t;
            }
            const main = document.querySelector('.main-content') || document.querySelector('main') || document.body;
            const clone = main.cloneNode(true);
            clone.querySelectorAll('nav, footer, script, style, noscript, header, .tab-content').forEach(n => n.remove());
            return clone.textContent.replace(/\s+/g, ' ').trim();
        }""")[:5000]

        prompt = f"""You are summarising a single medical event detail page. Extract ONLY two fields.

EVENT TITLE: {shell.get('title')}

PAGE BODY:
{text}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the page text" or null,
  "specialty": "primary clinical/topic area (e.g. Histopathology, Haematology, Microbiology, Cytopathology)" or null
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
                logger.warning(f"RCPath soft-fields JSON parse failed: {e}; raw[:200]={raw[:200]!r}")

        # Heuristic specialty backstop — always runs when LLM yielded none
        if not result.get("specialty"):
            heuristic = classify_specialty(shell.get("title"), text)
            if heuristic:
                result["specialty"] = heuristic

        # Description fallback — first clean chunk of Overview/intro text.
        if not result.get("description") and text:
            first_chunk = text.strip()
            if len(first_chunk) > 40:
                result["description"] = self._truncate_to_sentence(first_chunk, 320)

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
