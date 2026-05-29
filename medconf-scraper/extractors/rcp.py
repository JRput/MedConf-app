# extractors/rcp.py
"""
Royal College of Physicians (RCP) — detail-page extractor.

RCP event detail pages (https://www.rcp.ac.uk/events-and-education/events/<slug>/)
have a very clean, consistent structured sidebar panel we exploit:

  - Key-info panel: <div class="event-panel__item"> blocks, each with
        <div class="event-panel__item-title"><h4>LABEL</h4></div>
        <p>VALUE</p>
    Labels seen: "Date", "Price", "CPD credits", "Location".

  - Pricing: <div class="event-panel__price [event-panel__price--member]">
        "Tier label : £125"
    Member tiers carry the --member modifier class. Prices live in the DOM even
    when shown behind a "Multiple price options" modal, so textContent reads them
    regardless of modal state.

  - Location values are either an online keyword ("Zoom", "Online", "Microsoft
    Teams") or a flattened UK address ("2 Paddington Village Liverpool L7 3FA").

  - Date values are "11 June 2026" (single day) or "4-5 June 2026" (range).

  - Description + specialty come from the .event-details__tab prose via the LLM,
    with the heuristic specialty classifier as a backstop.

External online events hosted on player.rcplondon.ac.uk have NO event-panel; for
those the extractor returns the little it can and the caller falls back to the
listing shell.
"""

import json
import re
from typing import Dict, Any, Optional, Callable, List
from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from .abstract_classifier import extract_abstract_info
from logger import logger


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


class RCPExtractor(BaseExtractor):

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        # 1. Structured key-info panel (Date / Price / CPD credits / Location)
        panel = self._extract_panel(page)

        # 2. Pricing tiers (deterministic)
        result["pricing_tiers"] = self._extract_pricing(page)

        # 3. Venue / city / region / format (from Location panel value)
        result.update(self._extract_venue(panel.get("Location")))

        # 3b. Title fallback when the page didn't publish a Location panel item.
        # Common case: "Update in medicine – Exeter 2026" — RCP hasn't yet
        # posted the venue on the detail page, but the city is right in the
        # title. Also detect online/webinar/virtual in title.
        if not result.get("event_format"):
            title_l = (shell.get("title") or "").lower()
            if re.search(r"\b(online|webinar|virtual|livestream|live stream)\b", title_l):
                result["event_format"] = "online"
                result["venue_name"] = None
                result["city"] = None
                result["region"] = None
            else:
                for key, region in self._UK_REGIONS.items():
                    if re.search(rf"\b{re.escape(key)}\b", title_l):
                        result["city"] = key.title()
                        result["region"] = region
                        result["event_format"] = "in_person"
                        break

        # 4. CPD points (panel "CPD credits" → fallback to body text)
        cpd_points, cpd_accredited = self._extract_cpd(panel.get("CPD credits"), page)
        result["cpd_points"] = cpd_points
        result["cpd_accredited"] = cpd_accredited

        # 5. Dates (panel "Date" → start_date + optional end_date for ranges)
        start_date, end_date = self._extract_dates(panel.get("Date"))
        if start_date:
            result["start_date"] = start_date
        if end_date:
            result["end_date"] = end_date

        # 6. Abstract / poster submission info (deterministic)
        page_text = page.evaluate("() => document.body.textContent || ''")
        is_open, deadline = extract_abstract_info(page_text)
        result["abstract_open"] = is_open
        result["abstract_deadline"] = deadline.isoformat() if deadline else None

        # 7. Description + specialty (LLM, small prompt, heuristic fallback)
        result.update(self._extract_soft_fields(page, shell, llm_call))

        return result

    # ------------------------------------------------------------------ #
    # Structured panel: {label -> value}
    # ------------------------------------------------------------------ #
    def _extract_panel(self, page: Page) -> Dict[str, str]:
        """Read the .event-panel__item label/value pairs into a dict."""
        try:
            return page.evaluate(r"""() => {
                const out = {};
                document.querySelectorAll('.event-panel__item').forEach(it => {
                    const titleEl = it.querySelector('.event-panel__item-title h4, .event-panel__item-title');
                    const valEl = it.querySelector('p');
                    if (!titleEl || !valEl) return;
                    const label = (titleEl.textContent || '').trim();
                    const value = (valEl.textContent || '').replace(/\s+/g, ' ').trim();
                    if (label && value && !(label in out)) out[label] = value;
                });
                return out;
            }""") or {}
        except Exception as e:
            logger.warning(f"RCP panel extraction failed: {e}")
            return {}

    # ------------------------------------------------------------------ #
    # Pricing
    # ------------------------------------------------------------------ #
    def _extract_pricing(self, page: Page) -> List[Dict[str, Any]]:
        """
        Parse .event-panel__price rows. Each looks like
            "RCP subscribing members and fellows (consultant / SAS) : £125"
        Member tiers carry the event-panel__price--member modifier class.
        """
        try:
            rows = page.evaluate(r"""() => {
                return Array.from(document.querySelectorAll('.event-panel__price')).map(e => ({
                    text: (e.textContent || '').replace(/\s+/g, ' ').trim(),
                    isMember: /event-panel__price--member/.test(e.className),
                }));
            }""") or []
        except Exception as e:
            logger.warning(f"RCP pricing extraction failed: {e}")
            return []

        tiers: List[Dict[str, Any]] = []
        for row in rows:
            text = (row.get("text") or "").strip()
            price = self.parse_gbp(text)
            if price is None:
                continue
            # Label is everything before the price marker (" : £" or "£")
            label = re.split(r"\s*:?\s*£", text)[0].strip(" :–-")
            if not label:
                label = "Member" if row.get("isMember") else "Standard"
            tiers.append({
                "tier_label": label[:120],
                "price_gbp": price,
                "is_early_bird": False,
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
    UK_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)

    def _extract_venue(self, location_value: Optional[str]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        loc = (location_value or "").strip()
        if not loc:
            return out

        # Online / virtual events
        if re.search(r"\b(online|webinar|virtual|zoom|microsoft teams|ms teams|teams|livestream|live stream)\b", loc, re.I):
            out["event_format"] = "online"
            out["venue_name"] = None
            out["city"] = None
            out["region"] = None
            return out

        out["event_format"] = "in_person"

        # Strip the postcode out of the flattened address string
        address = self.UK_POSTCODE_RE.sub("", loc).strip(" ,")

        # Try to locate a known UK city anywhere in the address (most robust)
        city = None
        region = None
        for key in self._UK_REGIONS:
            if re.search(rf"\b{re.escape(key)}\b", address, re.I):
                # Title-case the matched city
                city = key.title()
                region = self._UK_REGIONS[key]
                break

        # Fallback: take the last word before the (removed) postcode as the city
        if not city:
            tokens = [t for t in re.split(r"[\s,]+", address) if t]
            if tokens:
                city = tokens[-1][:80]
                region = self._infer_uk_region(city)

        # Venue name = the address text preceding the city token
        venue = address
        if city:
            cut = re.split(rf"\b{re.escape(city)}\b", address, flags=re.I)[0].strip(" ,")
            venue = cut or address
        out["venue_name"] = venue[:200] if venue else None
        out["city"] = city
        out["region"] = region
        return out

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
        "belfast": "Northern Ireland",
        "cambridge": "East of England",
        "norwich": "East of England",
        "oxford": "South East England",
        "brighton": "South East England",
        "leicester": "East Midlands",
        "nottingham": "East Midlands",
    }

    @classmethod
    def _infer_uk_region(cls, city: str) -> Optional[str]:
        c = (city or "").lower()
        for key, val in cls._UK_REGIONS.items():
            if key in c:
                return val
        return None

    # ------------------------------------------------------------------ #
    # CPD
    # ------------------------------------------------------------------ #
    def _extract_cpd(self, cpd_value: Optional[str], page: Page) -> tuple[Optional[int], bool]:
        """Panel "CPD credits" value is like "6 credits". Fall back to body text."""
        if cpd_value:
            m = re.search(r"(\d+)\s*(?:CPD\s*)?(?:credits?|points?)", cpd_value, re.I)
            if m:
                return int(m.group(1)), True
        text = page.evaluate("() => document.body.textContent || ''")
        m = re.search(r"\b(\d+)\s*(?:CPD\s*)?(?:credits?|points?)\b", text, re.I)
        if m:
            return int(m.group(1)), True
        if re.search(r"\bCPD[- ]accredited|CPD[- ]approved\b", text, re.I):
            return None, True
        return None, False

    # ------------------------------------------------------------------ #
    # Dates
    # ------------------------------------------------------------------ #
    def _extract_dates(self, date_value: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        """
        Parse the panel "Date" value. Handles:
          - single day:   "11 June 2026"
          - same-month range: "4-5 June 2026" / "4 - 5 June 2026"
          - cross-month range: "29 June - 2 July 2026"
        Returns (start_iso, end_iso). end is None for single-day.
        """
        if not date_value:
            return None, None
        text = date_value.strip()

        # Cross-month range: "29 June - 2 July 2026"
        m = re.search(
            r"(\d{1,2})\s+([A-Za-z]+)\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
            text,
        )
        if m:
            d1, mon1, d2, mon2, year = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
            start = self._iso(year, mon1, d1)
            end = self._iso(year, mon2, d2)
            return start, end

        # Same-month range: "4-5 June 2026"
        m = re.search(r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text)
        if m:
            d1, d2, mon, year = m.group(1), m.group(2), m.group(3), m.group(4)
            return self._iso(year, mon, d1), self._iso(year, mon, d2)

        # Single day: "11 June 2026"
        m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text)
        if m:
            d1, mon, year = m.group(1), m.group(2), m.group(3)
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
    # Description + specialty (LLM, small prompt, heuristic fallback)
    # ------------------------------------------------------------------ #
    def _extract_soft_fields(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        # Prefer the description tab prose; fall back to main body text
        text = page.evaluate(r"""() => {
            const tabs = Array.from(document.querySelectorAll('.event-details__tab'))
                .map(t => (t.textContent || '').replace(/\s+/g, ' ').trim())
                .filter(t => t.length > 40);
            if (tabs.length) return tabs.join(' \n ');
            const main = document.querySelector('main, article, [role="main"]') || document.body;
            const clone = main.cloneNode(true);
            clone.querySelectorAll('nav, footer, script, style, noscript, header').forEach(n => n.remove());
            return clone.textContent.replace(/\s+/g, ' ').trim();
        }""")[:5000]

        prompt = f"""You are summarising a single medical event detail page. Extract ONLY two fields.

EVENT TITLE: {shell.get('title')}

PAGE BODY:
{text}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the page text" or null,
  "specialty": "primary clinical/topic area (e.g. Cardiology, Geriatric Medicine, Respiratory Medicine, Medical Leadership)" or null
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
                logger.warning(f"RCP soft-fields JSON parse failed: {e}; raw[:200]={raw[:200]!r}")

        # Heuristic specialty backstop — always runs when LLM yielded none
        if not result.get("specialty"):
            heuristic = classify_specialty(shell.get("title"), text)
            if heuristic:
                result["specialty"] = heuristic
        return result
