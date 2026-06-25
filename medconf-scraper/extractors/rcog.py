# extractors/rcog.py
"""
Royal College of Obstetricians and Gynaecologists (RCOG) — extractor.

Two RCOG sources share this module:

  - source 9:  upcoming events & courses listing → 25+ events whose detail
               pages live at rcog.eventsair.com/<slug>/. Pricing is on a
               separate /fees-and-how-to-book sub-page that the extractor
               walks after loading the main detail page.
  - source 10: RCOG World Congress 2027 — single international flagship
               event with a multi-page subsite under rcog.org.uk. Prices
               are in USD (currency='USD' on the tiers).

Key listing-page shape (eventsair.com detail pages):
  - <h1> is the event title.
  - The first 1-2 <h2> blocks carry date / format / venue. They can be:
      * Simple single-format: "Monday 22 June 2026" + "Online"
      * Multi-format with pipes:
          "Lectures | Online | 8-9 September 2026"
          "Practical workshops | In-person | RCOG, London | 15 OR 16 September 2026"
  - "Make use of our early bird rates and book by <DATE>" → early bird deadline
  - Pricing on /fees-and-how-to-book — single <table> with rows like
        "Standard rate | £293.00"
    grouped under <h2> headings: "Early bird rate | Until 4 May 2026"
                                 "Standard rate | From 5 May 2026"

Specialty is always "Obstetrics & Gynaecology" (RCOG is the O&G college).
"""

import json
import re
from datetime import datetime
from typing import Dict, Any, Optional, Callable, List, Tuple

from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from .abstract_classifier import extract_abstract_info
from logger import logger

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}

_TEXTUAL_DATE_RE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b")
_TEXTUAL_RANGE_RE = re.compile(
    r"\b(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b"
)
_CROSS_MONTH_RE = re.compile(
    r"\b(\d{1,2})\s+([A-Za-z]+)\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b"
)
_EARLY_BIRD_BY_RE = re.compile(
    r"early bird[^.\n]*?book by\s+(?:[A-Za-z]+\s+)?(\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})",
    re.I,
)


class RCOGExtractor(BaseExtractor):

    EVENTS_CALENDAR_ID = 9
    WORLD_CONGRESS_2027_ID = 10

    WC2027_BASE = "https://www.rcog.org.uk/careers-and-training/training/courses-and-events/rcog-world-congress/rcog-world-congress-2027/"
    WC2027_SUBPAGES = [
        "",
        "registration/",
        "abstracts/",
        "visit-kuala-lumpur/",
        "about-the-congress/",
    ]

    # ------------------------------------------------------------------ #
    # Listing override
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        import httpx

        if self.source_id == self.WORLD_CONGRESS_2027_ID:
            return [{
                "title": "RCOG World Congress 2027",
                "booking_url": self.WC2027_BASE,
                "category": "conference",
            }]

        if self.source_id != self.EVENTS_CALENDAR_ID:
            return None

        listing_url = self.source["base_url"]
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True,
                              headers={"User-Agent": "Mozilla/5.0 (MedConf scraper)"}) as client:
                resp = client.get(listing_url)
                resp.raise_for_status()
                html = resp.text
        except Exception as e:
            logger.warning(f"RCOG source {self.source_id}: listing fetch failed: {e}")
            return None

        # Detail pages always live at rcog.eventsair.com/<slug>/. Some pages
        # use the slug alone; some include an extra path segment we strip
        # ("…/sso", "…/fees-and-how-to-book" never appear at the listing).
        link_re = re.compile(
            r'href="(https://rcog\.eventsair\.com/[a-z0-9-]+/?)"'
        )
        seen: set = set()
        shells: List[Dict[str, Any]] = []
        for m in link_re.finditer(html):
            href = m.group(1).rstrip("/") + "/"
            if href in seen:
                continue
            seen.add(href)
            slug = href.rstrip("/").rsplit("/", 1)[-1]
            shells.append({
                "title": slug.replace("-", " ").strip().title(),
                "booking_url": href,
                "category": None,
            })
        logger.info(f"RCOG source {self.source_id}: harvested {len(shells)} listing shells")
        return shells

    # ------------------------------------------------------------------ #
    # Detail extraction
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        if self.source_id == self.WORLD_CONGRESS_2027_ID:
            return self._extract_world_congress(page, shell, llm_call)
        return self._extract_eventsair_event(page, shell, llm_call)

    # ------------------------------------------------------------------ #
    # eventsair.com event detail extraction (source 9)
    # ------------------------------------------------------------------ #
    def _extract_eventsair_event(
        self, page: Page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        # eventsair.com is JS-rendered — wait for content to settle
        try:
            page.wait_for_timeout(3500)
        except Exception:
            pass

        h1 = (page.evaluate("() => (document.querySelector('h1')||{}).textContent || ''") or "").strip()
        result: Dict[str, Any] = {"specialty": "Obstetrics & Gynaecology"}
        if h1:
            result["conference_name"] = h1

        # Headline h2s carry date + format + venue
        h2_blocks = self._headline_h2_blocks(page)
        date_info, fmt_info, venue_info = self._parse_eventsair_h2_blocks(h2_blocks)
        result.update(date_info)
        result.update(fmt_info)
        result.update(venue_info)

        # Body text for early-bird detection + abstract sniffing
        body_text = page.evaluate("() => document.body.innerText || ''") or ""
        early_bird_deadline = self._find_early_bird_deadline(body_text)

        # Capture the Overview-section prose NOW, before walking to the
        # fees sub-page. _extract_fees_page navigates the same page away,
        # and we'd lose the description content otherwise.
        overview_text = self._extract_overview_text(page)

        # Walk to /fees-and-how-to-book for pricing
        fees_url = shell.get("booking_url", "").rstrip("/") + "/fees-and-how-to-book"
        result["pricing_tiers"] = self._extract_fees_page(page, fees_url, early_bird_deadline)

        # CPD points are inconsistently published on eventsair pages — sniff
        # the body text but don't fail when missing.
        cpd_m = re.search(r"\b(\d+)\s*CPD\s*(?:credit|point)s?\b", body_text, re.I)
        if cpd_m:
            result["cpd_points"] = int(cpd_m.group(1))
            result["cpd_accredited"] = True
        else:
            result["cpd_accredited"] = "cpd" in body_text.lower()

        # Abstracts on eventsair pages: rare. Conservatively leave closed
        # unless a real deadline is present.
        is_open, deadline = extract_abstract_info(body_text)
        result["abstract_open"] = is_open
        result["abstract_deadline"] = deadline.isoformat() if deadline else None

        # Booking / sold-out detection
        if re.search(r"\b(fully booked|sold out|waiting list)\b", body_text, re.I):
            result["is_sold_out"] = True
        # The "Register today" / "Book now" anchor on the page is the booking URL
        action_href = page.evaluate(r"""() => {
            const anchors = [...document.querySelectorAll('a[href]')];
            const a = anchors.find(a => /register|book|sso/i.test(a.textContent || '') || /sso/i.test(a.href || ''));
            return a ? a.href : null;
        }""")
        if action_href:
            result["booking_url"] = action_href

        # Soft fields (LLM + heuristic fallback). We use the Overview text
        # captured BEFORE the fees-page navigation rather than reading
        # raw body innerText now — the eventsair page leads with the
        # title, nav menu links, date and venue lines BEFORE the actual
        # prose, so a naive 320-char truncate would produce all junk.
        result.update(self._extract_soft_fields(page, shell, llm_call,
                                                pre_text=overview_text[:5000]))
        # Always force specialty to O&G — RCOG is the college
        result["specialty"] = "Obstetrics & Gynaecology"

        return result

    def _headline_h2_blocks(self, page: Page) -> List[str]:
        try:
            return page.evaluate(r"""() => {
                return [...document.querySelectorAll('h1 ~ h2, h2')]
                    .slice(0, 6)
                    .map(h => (h.textContent || '').replace(/\s+/g, ' ').trim())
                    .filter(t => t.length > 3);
            }""") or []
        except Exception:
            return []

    def _extract_overview_text(self, page: Page) -> str:
        """Return the clean human-readable description from an eventsair page.

        These pages are structured: <h1>Title</h1>, a nav list, <h2>date</h2>,
        <h2>Location | …</h2>, <h2>Overview</h2>, then paragraphs, then more
        <h2>s for "Key reasons to attend", "Agenda" etc. We harvest the prose
        between the <h2>Overview</h2> and the next major <h2>, which is the
        canonical "about this event" copy. Falls back to all paragraph text
        inside the article if no Overview heading is present.
        """
        try:
            return page.evaluate(r"""() => {
                // Find the Overview / About heading.
                const headings = [...document.querySelectorAll('h2, h3')];
                const overview = headings.find(h => /^(overview|about(?:\s+(?:this|the))?(?:\s+(?:event|conference|course|congress|day))?)$/i.test((h.textContent || '').trim()));

                const NOISE = /^(register|view programme|book |fees|waiting list|key reasons|agenda|join the conversation|news \||t \+44|w rcog\.org\.uk|disclaimer|cookies|venue\s*\||contact|email\s|tel\s|^\s*\+\d|^\s*[a-z]+@)/i;
                const collect = (startEl) => {
                    const parts = [];
                    let total = 0;
                    let n = startEl ? startEl.nextElementSibling : null;
                    while (n && total < 1500) {
                        const tag = n.tagName ? n.tagName.toLowerCase() : '';
                        // Stop at the next major heading
                        if (tag === 'h2' || tag === 'h3') break;
                        const t = (n.textContent || '').replace(/\s+/g, ' ').trim();
                        if (t && t.length > 20 && !NOISE.test(t)) {
                            parts.push(t);
                            total += t.length;
                        }
                        n = n.nextElementSibling;
                    }
                    return parts.join('\n\n');
                };

                if (overview) {
                    const got = collect(overview);
                    if (got.length > 60) return got;
                }

                // Fallback: take all <p> elements inside the article body, in order.
                const main = document.querySelector('article, main, [role="main"]') || document.body;
                const ps = [...main.querySelectorAll('p')]
                    .map(p => (p.textContent || '').replace(/\s+/g, ' ').trim())
                    .filter(t => t.length > 40
                        && !/^(register|view programme|book|fees|waiting list|join the conversation|disclaimer|cookies)/i.test(t));
                return ps.slice(0, 8).join('\n\n');
            }""") or ""
        except Exception:
            return ""

    def _parse_eventsair_h2_blocks(
        self, blocks: List[str],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """Return (dates, format, venue) dicts. Each piece is best-effort.

        Date precedence: earliest single/range date across all blocks.
        Format: "Online" → online; "In-person" → in_person; both → hybrid.
        Venue: a piece that looks like a city or "X, Y" address.
        """
        all_pieces: List[str] = []
        for b in blocks:
            for p in b.split("|"):
                p = p.strip()
                if p:
                    all_pieces.append(p)
            # blocks themselves can also be a single piece (no pipes)
            if "|" not in b:
                all_pieces.append(b.strip())

        # de-dupe preserving order
        seen = set()
        pieces = []
        for p in all_pieces:
            if p in seen:
                continue
            seen.add(p)
            pieces.append(p)

        # ---- Date(s) ------------------------------------------------------
        dates_found: List[Tuple[str, Optional[str]]] = []
        for p in pieces:
            # cross-month range
            m = _CROSS_MONTH_RE.search(p)
            if m:
                start = self._iso(m.group(5), m.group(2), m.group(1))
                end = self._iso(m.group(5), m.group(4), m.group(3))
                dates_found.append((start, end))
                continue
            # same-month range
            m = _TEXTUAL_RANGE_RE.search(p)
            if m:
                d1, d2, month, year = m.group(1), m.group(2), m.group(3), m.group(4)
                dates_found.append(
                    (self._iso(year, month, d1), self._iso(year, month, d2))
                )
                continue
            # "OR" alternatives ("15 OR 16 September 2026")
            m = re.search(r"\b(\d{1,2})\s+OR\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b", p, re.I)
            if m:
                d1, d2, month, year = m.group(1), m.group(2), m.group(3), m.group(4)
                dates_found.append(
                    (self._iso(year, month, d1), self._iso(year, month, d2))
                )
                continue
            # single textual date
            m = _TEXTUAL_DATE_RE.search(p)
            if m:
                iso = self._iso(m.group(3), m.group(2), m.group(1))
                dates_found.append((iso, None))

        date_out: Dict[str, Any] = {}
        if dates_found:
            # Earliest start date wins (event "begins" on the soonest of its
            # multiple sub-events). End_date = the matching end OR the latest
            # end across all pieces.
            valid = [(s, e) for s, e in dates_found if s]
            if valid:
                valid.sort(key=lambda x: x[0])
                start = valid[0][0]
                ends = [e or s for s, e in valid]
                end = max(ends)
                date_out["start_date"] = start
                if end and end != start:
                    date_out["end_date"] = end
                else:
                    date_out["end_date"] = start

        # ---- Format -------------------------------------------------------
        joined_lower = " ".join(pieces).lower()
        is_online = bool(re.search(r"\bonline\b|\bvirtual\b|\bwebinar\b", joined_lower))
        is_inperson = bool(re.search(r"\bin[- ]person\b", joined_lower))
        fmt_out: Dict[str, Any] = {}
        if is_online and is_inperson:
            fmt_out["event_format"] = "hybrid"
        elif is_online:
            fmt_out["event_format"] = "online"
        elif is_inperson:
            fmt_out["event_format"] = "in_person"

        # ---- Venue --------------------------------------------------------
        venue_out: Dict[str, Any] = {}

        # Strategy 1 — explicit "Location | <X>" or "Venue | <X>" h2 block.
        # ROBuST host-trust events and BPS courses publish the venue this
        # way, often without naming a known UK city ("Good Hope Hospital,
        # B75 7RR", "Pembury Hospital Education Centre", "ERC RCOG Office,
        # Cairo, Egypt"). Take the value verbatim as venue_name; try to
        # find a city/region inside it but don't require one.
        for raw_block in blocks:
            m = re.match(r"^\s*(?:Location|Venue)\s*\|\s*(.+)$", raw_block, re.I)
            if m:
                venue_text = m.group(1).strip(" ,.")
                venue_out["venue_name"] = venue_text[:200] or None
                for city_key, region in self._UK_REGIONS.items():
                    if re.search(rf"\b{re.escape(city_key)}\b", venue_text, re.I):
                        venue_out["city"] = city_key.title()
                        venue_out["region"] = region
                        break
                break

        # Strategy 2 — "RCOG, London" literal anywhere in the pieces.
        if not venue_out:
            for p in pieces:
                pl = p.lower()
                if "rcog" in pl and "london" in pl:
                    venue_out["venue_name"] = "RCOG, London"
                    venue_out["city"] = "London"
                    venue_out["region"] = "London"
                    break

        # Strategy 3 — known UK city found anywhere in a piece.
        if not venue_out:
            for p in pieces:
                for city_key, region in self._UK_REGIONS.items():
                    if re.search(rf"\b{re.escape(city_key)}\b", p, re.I):
                        venue_out["city"] = city_key.title()
                        venue_out["region"] = region
                        venue_text = re.sub(rf"\b{re.escape(city_key)}\b", "", p, flags=re.I).strip(" ,|")
                        venue_out["venue_name"] = venue_text[:200] or None
                        break
                if venue_out:
                    break

        # If we have any venue info but no explicit format keyword, the
        # event is in-person — eventsair listings only call out "Online"
        # when the event truly is, and host-trust workshops never label
        # themselves explicitly.
        if "event_format" not in fmt_out and (venue_out.get("city") or venue_out.get("venue_name")):
            fmt_out["event_format"] = "in_person"

        # If the format was "online" but no venue, blank the city/venue
        if fmt_out.get("event_format") == "online":
            venue_out = {}

        return date_out, fmt_out, venue_out

    _UK_REGIONS = {
        "london": "London",
        "manchester": "North West England",
        "liverpool": "North West England",
        "chorley": "North West England",
        "leeds": "Yorkshire and the Humber",
        "sheffield": "Yorkshire and the Humber",
        "york": "Yorkshire and the Humber",
        "hull": "Yorkshire and the Humber",
        "bradford": "Yorkshire and the Humber",
        "newcastle": "North East England",
        "birmingham": "West Midlands",
        "bristol": "South West England",
        "exeter": "South West England",
        "plymouth": "South West England",
        "southampton": "South East England",
        "brighton": "South East England",
        "oxford": "South East England",
        "portsmouth": "South East England",
        "maidstone": "South East England",
        "tunbridge wells": "South East England",
        "cardiff": "Wales",
        "edinburgh": "Scotland",
        "glasgow": "Scotland",
        "belfast": "Northern Ireland",
        "cambridge": "East of England",
        "norwich": "East of England",
        "norfolk": "East of England",
        "lancashire": "North West England",
    }

    def _find_early_bird_deadline(self, body: str) -> Optional[str]:
        m = _EARLY_BIRD_BY_RE.search(body)
        if not m:
            return None
        date_str = m.group(1)
        tm = _TEXTUAL_DATE_RE.search(date_str)
        if tm:
            return self._iso(tm.group(3), tm.group(2), tm.group(1))
        return None

    # ------------------------------------------------------------------ #
    # Fees page extraction
    # ------------------------------------------------------------------ #
    def _extract_fees_page(
        self, page: Page, fees_url: str, early_bird_deadline: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Navigate to /fees-and-how-to-book and parse the pricing table.

        Pricing table format (consistent across RCOG eventsair events):
            <h2>Early bird rate | Until 4 May 2026</h2>
            Band A including UK
            Standard rate | £293.00
            ...
            <h2>Standard rate | From 5 May 2026</h2>
            ...
        Each row is "<label> | £<price>". Section <h2>s carry the band name
        (Early bird / Standard) and its deadline.
        """
        try:
            page.goto(fees_url, timeout=20000, wait_until="domcontentloaded")
        except Exception as e:
            logger.warning(f"RCOG fees page nav failed for {fees_url}: {e}")
            return []

        # Wait for either a populated <table> OR any £-price to appear in the
        # body — eventsair.com is a SPA so the markup hydrates after the
        # initial DOMContentLoaded fires. Bail after ~10s if neither shows up.
        try:
            page.wait_for_function(
                r"""() => {
                    const t = document.querySelector('table');
                    if (t && /£/.test(t.innerText || '')) return true;
                    return /£\s*\d/.test(document.body.innerText || '');
                }""",
                timeout=10000,
            )
        except Exception:
            # No price content surfaced — page may genuinely have no fees yet.
            pass

        try:
            table_text = page.evaluate(r"""() => {
                const t = document.querySelector('table');
                return t ? (t.innerText || '').trim() : '';
            }""") or ""
        except Exception:
            table_text = ""

        if not table_text:
            # Non-table layout (ROBuST host-trust pages): parse the body text
            # for a "Course fee" / "Fee" / "Price" heading followed by £NNN.
            try:
                body = page.evaluate("() => document.body.innerText || ''") or ""
            except Exception:
                body = ""
            return self._extract_fees_from_body(body, early_bird_deadline)

        # Parse line-by-line. Lines like
        #   "Standard rate | £293.00"
        # produce a (label, price) tuple; headings like
        #   "Early bird rate | Until 4 May 2026"
        # update the current band + deadline.
        tiers: List[Dict[str, Any]] = []
        current_band = ""
        current_subband = ""
        current_band_is_early = False
        current_deadline: Optional[str] = early_bird_deadline

        for raw_line in table_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            # Band heading "Early bird rate | Until 4 May 2026"
            lower = line.lower()
            if lower.startswith("early bird") and "|" in line:
                current_band = "Early bird"
                current_band_is_early = True
                # Pull deadline from the heading itself if present
                m = _TEXTUAL_DATE_RE.search(line)
                if m:
                    current_deadline = self._iso(m.group(3), m.group(2), m.group(1))
                continue
            if lower.startswith("standard rate") and "|" in line and "£" not in line:
                current_band = "Standard"
                current_band_is_early = False
                current_deadline = None
                continue
            # Sub-section heading like "Band A including UK", "Band B and C",
            # "Low resources countries:" — anything without a £ that isn't a
            # rate row.
            if "£" not in line:
                current_subband = re.sub(r":$", "", line).strip()
                continue
            # Rate row: "Label | £XXX.XX"
            m = re.search(r"^(.*?)\|\s*£\s*([\d,]+(?:\.\d+)?)\s*$", line)
            if not m:
                # Sometimes the row is "Label | £XXX.XX  " with extra cells
                m = re.search(r"^(.+?)\s+£\s*([\d,]+(?:\.\d+)?)", line)
                if not m:
                    continue
            label_raw = m.group(1).strip(" |")
            price = float(m.group(2).replace(",", ""))
            # Build descriptive label: "<band> · <subband> · <label>"
            label_parts = [p for p in [current_band, current_subband, label_raw] if p]
            tier_label = " · ".join(label_parts)[:200]
            tiers.append({
                "tier_label": tier_label,
                "price_gbp": price,
                "currency": "GBP",
                "is_early_bird": current_band_is_early,
                "early_bird_deadline": current_deadline if current_band_is_early else None,
            })

        # Dedupe identical (label, price) — defends against responsive shadow copies
        seen = set()
        out: List[Dict[str, Any]] = []
        for t in tiers:
            key = (t["tier_label"], t["price_gbp"])
            if key in seen:
                continue
            seen.add(key)
            out.append(t)
        return out

    def _extract_fees_from_body(
        self, body: str, early_bird_deadline: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Body-text fallback when the fees page has no <table>.

        Common case: ROBuST courses hosted by NHS trusts publish a free-form
        section like:
            "Course fee
             £250 + VAT"
        We capture the (heading, price) pair near "Course fee" / "Fees" /
        "Price" / "Cost" headings. The £NNN value can be a plain or VAT-suffixed
        amount; we strip "+ VAT" wording so the price is the headline GBP value.
        """
        tiers: List[Dict[str, Any]] = []
        if not body:
            return tiers

        # Strategy 1 — line-form tier rows: "<label> | £NNN" or "<label>: £NNN".
        # Catches pages like India Day where the price grid is rendered as
        # text lines outside a <table>.
        for line in body.splitlines():
            line = line.strip()
            if "£" not in line:
                continue
            m = re.search(r"^(.*?)[|:]\s*£\s*([\d,]+(?:\.\d+)?)\s*$", line)
            if not m:
                continue
            label_raw = m.group(1).strip()
            if not label_raw or len(label_raw) > 200:
                continue
            # Skip noise like "Deadline | 15 June 2026" — the price branch
            # requires a £ so this is already filtered.
            price = float(m.group(2).replace(",", ""))
            tiers.append({
                "tier_label": label_raw,
                "price_gbp": price,
                "currency": "GBP",
                "is_early_bird": False,
                "early_bird_deadline": None,
            })

        # Strategy 2 — bare-heading fallback: "Course fee" / "Fee" / "Price"
        # followed within ~80 chars by a £NNN value. Catches host-trust
        # ROBuST pages with a single fee listed under a heading.
        if not tiers:
            for m in re.finditer(
                r"(course fee|fees?|price|cost|registration fee)[\s:]*\n?[\s\S]{0,80}?£\s*([\d,]+(?:\.\d+)?)",
                body,
                re.I,
            ):
                label_raw = m.group(1).title()
                price = float(m.group(2).replace(",", ""))
                tiers.append({
                    "tier_label": label_raw,
                    "price_gbp": price,
                    "currency": "GBP",
                    "is_early_bird": False,
                    "early_bird_deadline": None,
                })

        # Dedupe (label, price)
        seen = set()
        out: List[Dict[str, Any]] = []
        for t in tiers:
            key = (t["tier_label"], t["price_gbp"])
            if key in seen:
                continue
            seen.add(key)
            out.append(t)
        return out

    # ------------------------------------------------------------------ #
    # World Congress 2027 — multi-page subsite (source 10)
    # ------------------------------------------------------------------ #
    def _extract_world_congress(
        self, page: Page, shell: Dict[str, Any], llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        # Walk sub-pages to collect text for description
        combined_text_parts: List[str] = []
        for sub in self.WC2027_SUBPAGES:
            url = self.WC2027_BASE + sub
            try:
                if sub:
                    page.goto(url, timeout=15000, wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)
                body = page.evaluate(r"""() => {
                    const main = document.querySelector('main, article, [role="main"]') || document.body;
                    const clone = main.cloneNode(true);
                    clone.querySelectorAll('nav, footer, script, style, noscript, header, .menu').forEach(n => n.remove());
                    return (clone.textContent || '').replace(/\s+/g, ' ').trim();
                }""") or ""
                combined_text_parts.append(body)
            except Exception as e:
                logger.warning(f"RCOG WC2027 sub-page {url} failed: {e}")

        combined_text = "\n\n".join(combined_text_parts)

        result: Dict[str, Any] = {
            "conference_name": "RCOG World Congress 2027",
            "start_date": "2027-04-22",
            "end_date": "2027-04-24",
            "venue_name": "Kuala Lumpur Convention Centre",
            "city": "Kuala Lumpur",
            "region": "Malaysia",
            "event_format": "in_person",
            "event_type": "conference",
            "is_flagship": True,
            "specialty": "Obstetrics & Gynaecology",
            "cpd_accredited": True,
            "cpd_points": None,
            "booking_url": self.WC2027_BASE + "registration/",
            "organiser_url": self.WC2027_BASE,
            "pricing_tiers": self._world_congress_2027_pricing(),
            "abstract_open": True,
            "abstract_deadline": "2026-09-01",
        }

        # LLM-driven description + heuristic fallback
        result.update(self._extract_soft_fields(
            page, {"title": result["conference_name"]}, llm_call,
            pre_text=combined_text[:5000],
        ))
        result["specialty"] = "Obstetrics & Gynaecology"
        return result

    # ------------------------------------------------------------------ #
    # World Congress 2027 — pricing (USD rates, encoded from the website)
    # ------------------------------------------------------------------ #
    # Source: rcog.org.uk/.../rcog-world-congress-2027/registration/
    # Four time-banded categories. Onsite rates apply once the event starts.
    _WC2027_BANDS = [
        ("Super early bird", "2026-10-31", True),
        ("Early bird", "2027-01-09", True),
        ("Standard", None, False),
        ("Onsite", None, False),
    ]
    _WC2027_RATES = [
        ("Consultant – UK / Band A",                          808,  950, 1188, 1425),
        ("Host Country (Malaysia)",                            485,  570,  713,  855),
        ("Trainee",                                             565,  665,  831,  998),
        ("Midwife / Nurse",                                     404,  475,  594,  713),
        ("Allied Healthcare Professional",                      485,  570,  713,  855),
        ("Low Resource (Band B)",                               646,  760,  950, 1140),
        ("Low Resource (Band C)",                               363,  428,  534,  641),
        ("Medical Student",                                     323,  380,  475,  570),
        ("Charity",                                             404,  475,  594,  713),
        ("Industry",                                            969, 1140, 1425, 1710),
    ]

    def _world_congress_2027_pricing(self) -> List[Dict[str, Any]]:
        tiers: List[Dict[str, Any]] = []
        for cat_label, super_eb, eb, std, onsite in self._WC2027_RATES:
            prices = [super_eb, eb, std, onsite]
            for (band_label, deadline, is_early), price in zip(self._WC2027_BANDS, prices):
                tiers.append({
                    "tier_label": f"{band_label} · {cat_label}",
                    "price_gbp": float(price),  # storing the USD value here; currency='USD'
                    "currency": "USD",
                    "is_early_bird": is_early,
                    "early_bird_deadline": deadline,
                })
        return tiers

    # ------------------------------------------------------------------ #
    # Soft fields — description + specialty via LLM + heuristic fallback
    # ------------------------------------------------------------------ #
    def _extract_soft_fields(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
        pre_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        if pre_text is None:
            try:
                text = page.evaluate(r"""() => {
                    const main = document.querySelector('main, article, [role="main"]') || document.body;
                    const clone = main.cloneNode(true);
                    clone.querySelectorAll('nav, footer, script, style, noscript, header, .menu').forEach(n => n.remove());
                    return (clone.textContent || '').replace(/\s+/g, ' ').trim();
                }""")[:5000]
            except Exception:
                text = ""
        else:
            text = pre_text

        title = shell.get("title") or ""
        prompt = f"""You are summarising a single medical event detail page. Extract ONLY two fields.

EVENT TITLE: {title}

PAGE BODY:
{text}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the page text" or null,
  "specialty": "primary clinical/topic area (e.g. Obstetrics & Gynaecology, Maternal Medicine, Gynaecological Surgery)" or null
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
                parsed = json.loads(raw)
                result = {
                    "description": parsed.get("description"),
                    "specialty": parsed.get("specialty"),
                }
            except json.JSONDecodeError as e:
                logger.warning(f"RCOG soft-fields JSON parse failed: {e}; raw[:200]={raw[:200]!r}")

        # Always keep RCOG specialty O&G — the college is single-discipline.
        result["specialty"] = "Obstetrics & Gynaecology"

        if not result.get("description") and text:
            chunk = text[:320].rstrip()
            cut = chunk.rfind(". ")
            if cut > 100:
                chunk = chunk[: cut + 1]
            else:
                chunk = chunk + "…"
            result["description"] = chunk

        return result

    # ------------------------------------------------------------------ #
    # Date helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _iso(year: str, month_name: str, day: str) -> Optional[str]:
        key = month_name.lower()
        mon = _MONTHS.get(key) or _MONTHS.get(key[:3])
        if not mon:
            return None
        try:
            return f"{int(year):04d}-{mon:02d}-{int(day):02d}"
        except ValueError:
            return None
