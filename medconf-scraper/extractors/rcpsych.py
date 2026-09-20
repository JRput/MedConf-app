"""
Royal College of Psychiatrists (RCPsych) — events extractor.

Site is a Sitecore-style CMS. Listing page
(https://www.rcpsych.ac.uk/events/conferences) renders ALL ~70 upcoming
events on ONE page — no pagination. Detail URLs encode the event date:

    /events/conferences/detail/YYYY/MM/DD/default-calendar/<slug>

CloudFront WAF gotcha: the site's edge (AWS CloudFront) 403s any request
whose User-Agent string contains "HeadlessChrome" — which is exactly what
Playwright's default `chromium.launch(headless=True)` sends. That means the
shared BrowserController (browser.py, not editable here) gets a 403 error
page on both the listing and every detail navigate(). We work around this
entirely inside this module: `list_shells_override()` fetches the listing
via httpx with a normal desktop Chrome UA, and `extract_detail()` ignores
the (blocked) `page` content and re-fetches the detail URL via httpx too,
then loads that HTML into the Playwright `page` with `page.set_content()`
so the existing page.evaluate() DOM-reading patterns still work.

Detail-page shapes observed (3 probed):
  1. Multi-day priced conference — `.ttl` date chips per day, `.table-block`
     table with Location/CPD rows, `.fees` table with member/grade tiers
     (plus an extra "Conference dinner" add-on row), `.faq-accordion`
     Overview/Programme panels.
  2. Course, fees TBC — `.table-block` table has only "Timings"/"Location"
     rows, no `.fees` block, no `.ttl` day chips. Only date signal is the
     URL. No accordion. There's a plain `<address>` "Event Location" block
     near the bottom as a second venue source.
  3. Online single-fee workshop — Location value is literally "Online
     event"; `.fees` table has one flat "Standard fee" row.

Fees table cells: `<td>label</td><th>&pound;NNN ...</th>` — label in <td>,
price in <th> (reversed vs a typical fee row, note the tag swap).
"""

from __future__ import annotations

import re
import html as html_lib
from datetime import date, datetime
from typing import Dict, Any, Optional, Callable, List
from urllib.parse import urljoin

import httpx
from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from .abstract_classifier import extract_abstract_info
from .pricing_tables import parse_pricing_tables
from logger import logger


LISTING_URL = "https://www.rcpsych.ac.uk/events/conferences"
BASE_URL = "https://www.rcpsych.ac.uk"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DETAIL_LINK_RE = re.compile(
    r'href="(/events/conferences/detail/(\d{4})/(\d{2})/(\d{2})/[^"]+)"'
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


# The shared specialty_classifier.py's generic "General Practice" catch-all
# (keyed on "annual conference"/"general practice") was built around GP-heavy
# sources (RCGP/RCP) and false-positives on RCPsych faculty conference titles
# that don't happen to contain "psychiatr" (e.g. "Faculty of Medical
# Psychotherapy Annual Conference"). Since virtually every RCPsych event is
# psychiatry/mental-health-related, we check these source-specific faculty
# keywords FIRST, before falling through to the shared classifier. This is a
# per-source fix, not a change to the shared file.
_RCPSYCH_SPECIALTY_HINTS: List[tuple[str, str]] = [
    ("psychotherap", "Medical Psychotherapy"),
    ("neuropsychiatry", "Neuropsychiatry"),
    ("child and adolescent", "Child & Adolescent Psychiatry"),
    ("old age psychiatry", "Old Age Psychiatry"),
    ("intellectual disability", "Psychiatry of Intellectual Disability"),
    ("liaison psychiatry", "Liaison Psychiatry"),
    ("forensic", "Forensic Psychiatry"),
    ("rehabilitation and social psychiatry", "Rehabilitation & Social Psychiatry"),
    ("addiction", "Addiction Psychiatry"),
    ("perinatal", "Perinatal Psychiatry"),
    ("eating disorder", "Eating Disorders"),
    ("digital psychiatry", "Digital Psychiatry"),
    ("general adult psychiatry", "General Adult Psychiatry"),
    ("neurodivergen", "Neurodevelopmental Psychiatry"),
]


def _rcpsych_specialty_hint(title: Optional[str], text: Optional[str]) -> Optional[str]:
    combined = f"{title or ''} {text or ''}".lower()
    for kw, label in _RCPSYCH_SPECIALTY_HINTS:
        if kw in combined:
            return label
    return None


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
        logger.warning(f"RCPsych httpx GET failed for {url}: {e}")
        return None


class RCPsychExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Listing phase — bypass the shared (CloudFront-blocked) browser walk.
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        html = _http_get(LISTING_URL)
        if not html:
            logger.warning("RCPsych: listing fetch failed, no shells")
            return None

        shells: List[Dict[str, Any]] = []
        seen_urls = set()
        today = date.today()

        for m in DETAIL_LINK_RE.finditer(html):
            href, y, mo, d = m.group(1), m.group(2), m.group(3), m.group(4)
            url = urljoin(BASE_URL, html_lib.unescape(href))
            if url in seen_urls:
                continue
            seen_urls.add(url)

            try:
                url_date = date(int(y), int(mo), int(d))
            except ValueError:
                url_date = None

            # Only keep upcoming (today or later) — the listing page itself
            # is already filtered to upcoming events, but be defensive.
            if url_date and url_date < today:
                continue

            # Find the <h3> title inside the surrounding <li> card so we can
            # filter [CANCELLED] entries before the detail fetch. Search a
            # window around the match rather than the whole doc.
            window_start = max(0, m.start() - 1600)
            window = html[window_start:m.start()]
            h3m = re.findall(r"<h3>(.*?)</h3>", window, re.S)
            title = html_lib.unescape(re.sub(r"<[^>]+>", "", h3m[-1])).strip() if h3m else None

            if title and "[CANCELLED]" in title.upper():
                continue

            shells.append({
                "title": title,
                "booking_url": url,
                "start_date": url_date.isoformat() if url_date else None,
            })

        logger.info(f"RCPsych: {len(shells)} upcoming shells from listing (of {len(seen_urls)} links)")
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
        detail_html = _http_get(url) if url else None
        if not detail_html:
            logger.warning(f"RCPsych: detail fetch failed for {url}")
            return result

        # Load the httpx-fetched HTML into the (already-blocked) Playwright
        # page so we can reuse page.evaluate() DOM-reading patterns instead
        # of hand-rolling regex-based HTML parsing (no bs4/lxml available).
        try:
            page.set_content(detail_html, timeout=15000)
        except Exception as e:
            logger.warning(f"RCPsych: page.set_content failed for {url}: {e}")
            return result

        # 1. Conference name from h1 — never trust the listing shell title.
        # NOTE: the page renders TWO <h1> tags (a hidden/empty one in the
        # site chrome, then the real event title) — pick the first
        # non-empty one, not just document.querySelector('h1').
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

        # 2. Key-info table (Location / CPD / Timings)
        panel = self._extract_panel(page)

        # 3. Pricing (deterministic)
        tiers = self._extract_pricing(page)
        if not tiers:
            # Fallback to the shared plain-number table parser in case a
            # page uses a differently-classed fee table we haven't seen.
            tiers = parse_pricing_tables(detail_html, default_currency="GBP")
        result["pricing_tiers"] = tiers

        # 4. Venue / city / region / format
        result.update(self._extract_venue(panel.get("Location"), page))

        # 5. CPD points
        cpd_points, cpd_accredited = self._extract_cpd(panel.get("CPD"), page)
        result["cpd_points"] = cpd_points
        result["cpd_accredited"] = cpd_accredited

        # 6. Dates — try the `.ttl` day chips (multi-day), else URL fallback
        start_date, end_date = self._extract_dates(page, shell)
        if start_date:
            result["start_date"] = start_date
        if end_date:
            result["end_date"] = end_date

        # 7. Abstract / poster submission info (deterministic)
        page_text = page.evaluate("() => document.body.textContent || ''") or ""
        is_open, deadline = extract_abstract_info(page_text)
        result["abstract_open"] = is_open
        result["abstract_deadline"] = deadline.isoformat() if deadline else None

        # 8. Description + specialty (LLM w/ deterministic fallback)
        result.update(self._extract_soft_fields(page, h1 or shell.get("title"), llm_call))

        return result

    # ------------------------------------------------------------------ #
    # Key-info table: {label -> value}
    # ------------------------------------------------------------------ #
    def _extract_panel(self, page: Page) -> Dict[str, str]:
        try:
            return page.evaluate(r"""() => {
                const out = {};
                document.querySelectorAll('.table-block table tr').forEach(tr => {
                    const cells = tr.querySelectorAll('td');
                    if (cells.length < 2) return;
                    const label = (cells[0].textContent || '').replace(/\s+/g, ' ').trim();
                    const value = (cells[1].textContent || '').replace(/\s+/g, ' ').trim();
                    if (label && value && !(label in out)) out[label] = value;
                });
                return out;
            }""") or {}
        except Exception as e:
            logger.warning(f"RCPsych panel extraction failed: {e}")
            return {}

    # ------------------------------------------------------------------ #
    # Pricing — `.fees table tr` rows: <td>label</td><th>£price</th>
    # ------------------------------------------------------------------ #
    def _extract_pricing(self, page: Page) -> List[Dict[str, Any]]:
        try:
            rows = page.evaluate(r"""() => {
                return Array.from(document.querySelectorAll('.fees table tr')).map(tr => {
                    const td = tr.querySelector('td');
                    const th = tr.querySelector('th');
                    return {
                        label: (td ? td.textContent : '').replace(/\s+/g, ' ').trim(),
                        priceText: (th ? th.textContent : '').replace(/\s+/g, ' ').trim(),
                    };
                });
            }""") or []
        except Exception as e:
            logger.warning(f"RCPsych pricing extraction failed: {e}")
            return []

        tiers: List[Dict[str, Any]] = []
        for row in rows:
            label = (row.get("label") or "").strip()
            price_text = (row.get("priceText") or "").strip()
            if not label or not price_text:
                continue

            # A cell can hold multiple price variants separated by "/",
            # e.g. "£490 whole event/£265 per single day". Split on "/"
            # and pair each price with its trailing description as the
            # timeframe portion of the composite label.
            segments = [s.strip() for s in price_text.split("/") if s.strip()]
            if not segments:
                segments = [price_text]

            for seg in segments:
                price = self.parse_gbp(seg)
                if price is None:
                    continue
                # Strip the £NNN prefix to get the timeframe qualifier, e.g.
                # "£490 whole event" -> "whole event"
                qualifier = re.sub(r"^\s*£?\s*[\d,.]+\s*", "", seg).strip()
                tier_label = f"{label} · {qualifier}" if qualifier else label
                tiers.append({
                    "tier_label": tier_label[:120],
                    "price_gbp": price,
                    "is_early_bird": False,
                    "early_bird_deadline": None,
                })

        # Dedupe by (label, price) — defends against responsive shadow copies
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
    def _extract_venue(self, location_value: Optional[str], page: Page) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        loc = (location_value or "").strip()

        # Fallback: the standalone <address> "Event Location" block seen on
        # course-type pages that don't publish a table Location row.
        if not loc:
            try:
                loc = (page.evaluate(
                    "() => (document.querySelector('address')||{}).textContent || ''"
                ) or "").replace("Location:", "").strip()
            except Exception:
                loc = ""

        if not loc:
            return out

        if re.search(r"\b(online|webinar|virtual|zoom|microsoft teams|ms teams|teams|livestream|live stream)\b", loc, re.I):
            out["event_format"] = "online"
            out["venue_name"] = None
            out["city"] = None
            out["region"] = None
            return out

        out["event_format"] = "in_person"

        address = UK_POSTCODE_RE.sub("", loc).strip(" ,")

        city = None
        region = None
        for key in _UK_REGIONS:
            if re.search(rf"\b{re.escape(key)}\b", address, re.I):
                city = key.title()
                region = _UK_REGIONS[key]
                break

        if not city:
            # Take the last comma-separated segment as a best-guess city
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
    # CPD
    # ------------------------------------------------------------------ #
    def _extract_cpd(self, cpd_value: Optional[str], page: Page) -> tuple[Optional[int], bool]:
        if cpd_value:
            m = re.search(r"(\d+)\s*(?:CPD\s*)?(?:points?|credits?)", cpd_value, re.I)
            if m:
                return int(m.group(1)), True
            # "1 point per hour of eligible content" — no fixed total, but
            # the page explicitly discusses CPD, so mark it accredited.
            if re.search(r"\bCPD\b", cpd_value, re.I) or re.search(r"\bpoint\b", cpd_value, re.I):
                return None, True
        text = page.evaluate("() => document.body.textContent || ''") or ""
        m = re.search(r"\b(\d+)\s*(?:CPD\s*)?(?:points?|credits?)\b", text, re.I)
        if m:
            return int(m.group(1)), True
        if re.search(r"\bCPD[- ]accredited|CPD[- ]approved\b", text, re.I):
            return None, True
        return None, False

    # ------------------------------------------------------------------ #
    # Dates — `.ttl` day chips give day-of-month + month abbrev for
    # multi-day events; single/URL-derived date is the deterministic
    # fallback for everything else.
    # ------------------------------------------------------------------ #
    def _extract_dates(self, page: Page, shell: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        url_date = shell.get("start_date")  # already ISO from list_shells_override

        try:
            chips = page.evaluate(r"""() => {
                return Array.from(document.querySelectorAll('.ttl .date')).map(e =>
                    (e.textContent || '').replace(/\s+/g, ' ').trim()
                );
            }""") or []
        except Exception:
            chips = []

        if not chips:
            return url_date, None

        # Each chip looks like "03Sep" ("num" span + month text concatenated).
        # We know the year from the URL date (or default to it if parse fails).
        year = None
        if url_date:
            try:
                year = datetime.fromisoformat(url_date).year
            except ValueError:
                year = None

        parsed_dates = []
        for chip in chips:
            m = re.match(r"(\d{1,2})\s*([A-Za-z]{3,})", chip)
            if not m:
                continue
            day, mon_text = m.group(1), m.group(2)
            mon = _MONTHS.get(mon_text.lower()[:3])
            if not mon:
                continue
            y = year or (datetime.fromisoformat(url_date).year if url_date else datetime.now().year)
            try:
                parsed_dates.append(date(y, mon, int(day)))
            except ValueError:
                continue

        if not parsed_dates:
            return url_date, None

        parsed_dates.sort()
        start = parsed_dates[0].isoformat()
        end = parsed_dates[-1].isoformat() if len(parsed_dates) > 1 else None
        return start, end

    # ------------------------------------------------------------------ #
    # Description + specialty (LLM, small prompt, heuristic fallback)
    # ------------------------------------------------------------------ #
    def _extract_soft_fields(
        self,
        page: Page,
        title: Optional[str],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        # Prefer the accordion Overview/Programme panel text; RCPsych wraps
        # this markup in .faq-accordion .panel-body — often HIDDEN via CSS
        # collapse, so we must read via textContent (not innerText).
        text = page.evaluate(r"""() => {
            const panels = Array.from(document.querySelectorAll('.faq-accordion .panel'));
            const chunks = [];
            for (const p of panels) {
                const heading = (p.querySelector('.panel-title') || {}).textContent || '';
                if (!/overview|programme|about|description/i.test(heading)) continue;
                const body = (p.querySelector('.panel-body') || {}).textContent || '';
                const cleaned = body.replace(/\s+/g, ' ').trim();
                if (cleaned.length > 40) chunks.push(cleaned);
            }
            if (chunks.length) return chunks.join(' \n ');
            // No Overview/Programme panel on this page (common on course
            // pages with fees still TBC) — fall back to the main content
            // area, stripped of nav/breadcrumb/contact chrome. If nothing
            // substantial remains, return '' so the caller leaves
            // description null rather than fabricating from nav junk.
            const main = document.querySelector('main') || document.body;
            const clone = main.cloneNode(true);
            clone.querySelectorAll(
                'nav, footer, script, style, noscript, header, .breadcrumbs, ' +
                '.btn-back, .contact-info, address, .table-block, .fees, figure'
            ).forEach(n => n.remove());
            return clone.textContent.replace(/\s+/g, ' ').trim();
        }""")[:5000]

        prompt = f"""You are summarising a single medical event detail page. Extract ONLY two fields.

EVENT TITLE: {title}

PAGE BODY:
{text}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the page text" or null,
  "specialty": "primary clinical/topic area (e.g. Psychiatry, Mental Health, Child and Adolescent Psychiatry, Medical Leadership)" or null
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
                logger.warning(f"RCPsych soft-fields JSON parse failed: {e}; raw[:200]={raw[:200]!r}")

        if not result.get("specialty"):
            heuristic = (
                _rcpsych_specialty_hint(title, text)
                or classify_specialty(title, text)
                or "Mental Health"
            )
            result["specialty"] = heuristic

        if not result.get("description") and text:
            first_chunk = text.split(" \n ", 1)[0].strip()
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
