# extractors/rsm.py
"""
Royal Society of Medicine — detail-page extractor.

RSM event detail pages have these reliable structural patterns we exploit:
  - Pricing table: <table class="m-price-table"> nested inside
                   <details> (role accordion) inside .o-tabs__tab (Member tab).
  - Each price cell: <div class="m-price-table__item"> with text "£N.NN"
                     and <small class="m-price-table__label"> for the line item.
  - Tabs: Member / Non-Member, distinguished by .o-tabs__tab position
                     and the tab navigation links.
  - Venue: typically "Location" + address block in a sidebar / sticky aside.
  - Online events: page text contains "online" / "webinar" with no physical venue.
  - CPD: phrasing like "X CPD points" appears in the agenda or programme summary.

Description + specialty still use the LLM (kept small; ~2K token prompt).
"""

import json
import re
from typing import Dict, Any, Optional, Callable, List
from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from .abstract_classifier import extract_abstract_info
from logger import logger


class RSMExtractor(BaseExtractor):

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        # --- 1. Pricing tiers (deterministic HTML parsing) ---
        result["pricing_tiers"] = self._extract_pricing(page)

        # --- 2. Venue / location / format (deterministic with regex fallbacks) ---
        venue_info = self._extract_venue(page)
        result.update(venue_info)

        # --- 3. CPD points (regex) ---
        result["cpd_points"], result["cpd_accredited"] = self._extract_cpd(page)

        # --- 4. End date for multi-day events (regex) ---
        end_date = self._extract_end_date(page, shell)
        if end_date:
            result["end_date"] = end_date

        # --- 5. Abstract / poster submission info (deterministic — no LLM) ---
        page_text = page.evaluate("() => document.body.textContent || ''")
        is_open, deadline = extract_abstract_info(page_text)
        result["abstract_open"] = is_open
        result["abstract_deadline"] = deadline.isoformat() if deadline else None

        # --- 6. Description + specialty (LLM — small prompt) ---
        soft = self._extract_soft_fields(page, shell, llm_call)
        result.update(soft)

        return result

    # ------------------------------------------------------------------ #
    # Pricing — handles BOTH layouts RSM uses across event types
    # ------------------------------------------------------------------ #
    def _extract_pricing(self, page: Page) -> List[Dict[str, Any]]:
        """
        Walk every .m-price-table in the page DOM. RSM uses TWO different
        internal layouts depending on event type:

          Layout A — multi-day events (e.g. Trauma Symposium):
            <td>
              <div class="m-price-table__item">£0<small class="__label">Day 1</small></div>
              <div class="m-price-table__item">£35.75<small class="__label">Lunch</small></div>
            </td>
            (Headers = Day 1 / Day 2; line items = Day fee, Lunch, Dinner, etc.)

          Layout B — single-fee events (e.g. Cybersecurity, Stevens Lecture):
            <td data-th="RSM Associate">£0.00</td>
            <td data-th="RSM Fellow">£0.00</td>
            (Headers = role names; one price per role; NO __item wrappers)

        For each table, we determine tab + role context and extract every price.
        """
        try:
            raw = page.evaluate("""() => {
                const tables = Array.from(document.querySelectorAll('.m-price-table'));
                return tables.map(t => {
                    // Role context: nearest <details><summary>. None for Layout B
                    // because the role is encoded per-column instead.
                    const detailsAnc = t.closest('details');
                    const accordionRole = detailsAnc?.querySelector('summary')?.textContent.trim() || null;

                    // Tab context: nearest .o-tabs__tab; map back to its tab-link
                    const tabAnc = t.closest('.o-tabs__tab');
                    let tabName = null;
                    if (tabAnc) {
                        const tabsContainer = tabAnc.closest('.o-tabs');
                        if (tabsContainer) {
                            const tabLinks = Array.from(tabsContainer.querySelectorAll('.o-tabs__link, [role="tab"], button'));
                            for (const link of tabLinks) {
                                if (link.getAttribute('aria-controls') === tabAnc.id) {
                                    tabName = link.textContent.trim();
                                    break;
                                }
                            }
                            if (!tabName) {
                                const allTabs = Array.from(tabsContainer.querySelectorAll('.o-tabs__tab'));
                                const idx = allTabs.indexOf(tabAnc);
                                tabName = idx === 0 ? 'Member' : (idx === 1 ? 'Non-Member' : `Tab${idx}`);
                            }
                        }
                    }

                    const headers = Array.from(t.querySelectorAll('thead th')).map(th => th.textContent.trim());

                    // --- Layout A: items wrapped in .m-price-table__item ---
                    const itemsA = Array.from(t.querySelectorAll('.m-price-table__item')).map(item => {
                        const labelEl = item.querySelector('.m-price-table__label');
                        const label = labelEl ? labelEl.textContent.replace(/\\s+/g, ' ').trim() : '';
                        let priceText = item.textContent.replace(/\\s+/g, ' ').trim();
                        if (label) priceText = priceText.replace(label, '').trim();
                        const td = item.closest('td');
                        let columnIdx = null;
                        if (td) {
                            const tr = td.parentElement;
                            columnIdx = Array.from(tr.children).indexOf(td);
                        }
                        return {
                            layout: 'A',
                            price_text: priceText,
                            label,
                            columnHeader: columnIdx !== null ? (headers[columnIdx] || '') : ''
                        };
                    });

                    // --- Layout B: <td data-th="RoleName">£X</td> directly ---
                    let itemsB = [];
                    if (itemsA.length === 0) {
                        itemsB = Array.from(t.querySelectorAll('tbody td')).map(td => {
                            const role = td.getAttribute('data-th') || '';
                            const text = td.textContent.replace(/\\s+/g, ' ').trim();
                            return {
                                layout: 'B',
                                price_text: text,
                                label: role,                    // role IS the line-item label here
                                columnHeader: role,
                            };
                        }).filter(it => it.label);
                    }

                    return {
                        accordionRole,
                        tabName,
                        layoutDetected: itemsA.length > 0 ? 'A' : (itemsB.length > 0 ? 'B' : 'empty'),
                        items: itemsA.length > 0 ? itemsA : itemsB,
                    };
                });
            }""")
        except Exception as e:
            logger.warning(f"RSM pricing extraction failed: {e}")
            return []

        tiers: List[Dict[str, Any]] = []
        for table in raw:
            accordion_role = (table.get("accordionRole") or "").strip()
            tab = (table.get("tabName") or "").strip()
            tab_norm = re.sub(r"\s*-\s*", "-", tab)  # "Non - Member" → "Non-Member"
            layout = table.get("layoutDetected", "empty")

            for it in table["items"]:
                price = self.parse_gbp(it.get("price_text") or "")
                if price is None:
                    continue

                label = (it.get("label") or "").strip()
                col = (it.get("columnHeader") or "").strip()

                if layout == "A":
                    # Use accordion role + line-item label (e.g. Member - RSM Associate - Lunch)
                    role = accordion_role or "Unknown"
                    line_item = label if label else col
                    parts = [tab_norm, role, line_item]
                elif layout == "B":
                    # Role IS the column header / data-th. No accordion needed.
                    role = label or col or "Unknown"
                    parts = [tab_norm, role]
                else:
                    parts = [tab_norm, accordion_role, label or col]

                tier_label = " - ".join(p for p in parts if p)

                tiers.append({
                    "tier_label": tier_label[:120],
                    "price_gbp": price,
                    "is_early_bird": False,
                    "early_bird_deadline": None,
                })

        # Deduplicate (tier_label, price_gbp) — responsive shadow tables can duplicate cells
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
    # Venue / location / format
    # ------------------------------------------------------------------ #
    UK_POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$")

    def _extract_venue(self, page: Page) -> Dict[str, Any]:
        """
        RSM detail pages have a "Location" heading near the top of the booking
        sidebar. Walking forward from that heading is far more reliable than
        regex on flattened textContent (where the word "Location" appears in
        multiple semantic contexts).
        """
        info = page.evaluate(r"""() => {
            // Find the <h*> element whose text is exactly "Location"
            const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4, h5, h6'));
            for (const h of headings) {
                if (!/^location$/i.test((h.textContent || '').trim())) continue;
                // Walk forward through siblings, collecting text until we hit
                // another heading or run out of siblings.
                let cursor = h.nextElementSibling;
                let collected = '';
                while (cursor && !/^H[1-6]$/.test(cursor.tagName) && collected.length < 600) {
                    collected += (cursor.textContent || '').trim() + ' ';
                    cursor = cursor.nextElementSibling;
                }
                // Walk up if direct siblings empty — sometimes location is in a child of next section
                if (!collected.trim()) {
                    const parent = h.parentElement;
                    if (parent) {
                        // Take everything in the parent after the heading
                        const all = (parent.textContent || '').trim();
                        const idx = all.indexOf('Location');
                        if (idx >= 0) collected = all.slice(idx + 'Location'.length, idx + 600);
                    }
                }
                return { locationText: collected.trim().replace(/\s+/g, ' ') };
            }
            return { locationText: null };
        }""")

        loc = (info.get("locationText") or "").strip()
        out: Dict[str, Any] = {}

        if not loc:
            return out

        # Online / webinar detection — explicit keywords win
        if re.search(r"\bonline\b|\bwebinar\b|\bvirtual\b", loc, re.I):
            out["event_format"] = "online"
            out["venue_name"] = None
            out["city"] = None
            out["region"] = None
            return out

        # Address parsing: "Royal Society of Medicine, 1 Wimpole St, Marylebone, London, W1G 0AE, United Kingdom"
        parts = [p.strip() for p in loc.split(",") if p.strip()]
        if not parts:
            return out

        # Filter postcodes upfront — they're never the venue/city/region
        non_postcode = [p for p in parts if not self.UK_POSTCODE_RE.match(p)]
        if not non_postcode:
            return out

        # First non-postcode element is the venue
        out["venue_name"] = non_postcode[0][:200]
        out["event_format"] = "in_person"

        # City heuristic: second-to-last non-postcode part is usually city
        # (last part is typically country: "United Kingdom" / "UK")
        if len(non_postcode) >= 3:
            # venue, [street, area, ...,] city, country
            out["city"] = non_postcode[-2][:80]
            # Region: detect from "London", "Manchester", etc. — for UK, set
            # broadly based on city
            out["region"] = self._infer_uk_region(non_postcode[-2])
        elif len(non_postcode) == 2:
            # Just venue + city/country
            out["city"] = non_postcode[1][:80]

        return out

    @staticmethod
    def _infer_uk_region(city: str) -> Optional[str]:
        """Map common UK cities to broad regions used in our schema."""
        c = (city or "").lower()
        regions = {
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
            "cardiff": "Wales",
            "swansea": "Wales",
            "edinburgh": "Scotland",
            "glasgow": "Scotland",
            "belfast": "Northern Ireland",
            "cambridge": "East of England",
            "norwich": "East of England",
            "oxford": "South East England",
            "brighton": "South East England",
        }
        for key, val in regions.items():
            if key in c:
                return val
        return None

    # ------------------------------------------------------------------ #
    # CPD
    # ------------------------------------------------------------------ #
    def _extract_cpd(self, page: Page) -> tuple[Optional[int], bool]:
        """
        Pull explicit CPD point counts from page text. Patterns RSM uses:
          'X CPD points', 'X CPD credits', 'CPD: X points'
        """
        text = page.evaluate("() => document.body.textContent || ''")
        m = re.search(r"\b(\d+)\s*(?:CPD\s*(?:points?|credits?))", text, re.I)
        if m:
            return int(m.group(1)), True
        # Implicit CPD-accredited if the page mentions CPD-accredited/approved
        if re.search(r"\bCPD[- ]accredited|CPD[- ]approved\b", text, re.I):
            return None, True
        return None, False

    # ------------------------------------------------------------------ #
    # End-date for multi-day events
    # ------------------------------------------------------------------ #
    def _extract_end_date(self, page: Page, shell: Dict[str, Any]) -> Optional[str]:
        """
        RSM detail pages show "Date" sections like "18 May 2026" (single day) or
        "18-19 May 2026" / "18 - 19 May 2026" (range). If a range is present,
        return the end day in ISO. Otherwise return None (caller defaults end=start).
        """
        text = page.evaluate("() => document.body.textContent || ''")
        # "18-19 May 2026" or "18 - 19 May 2026"
        m = re.search(r"\b(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text)
        if not m:
            return None
        end_day = int(m.group(2))
        month_name = m.group(3).lower()[:3]
        year = int(m.group(4))
        months = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
        if month_name not in months:
            return None
        return f"{year:04d}-{months[month_name]:02d}-{end_day:02d}"

    # ------------------------------------------------------------------ #
    # Description + specialty (LLM, small prompt)
    # ------------------------------------------------------------------ #
    def _extract_soft_fields(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        """
        Tight prompt, ~5K chars input — much cheaper / smaller than the full
        all-fields LLM path used by the FallbackExtractor.
        """
        # Get a focused chunk: skip nav/footer, take main body
        text = page.evaluate("""() => {
            const main = document.querySelector('main, article, [role="main"]') || document.body;
            const clone = main.cloneNode(true);
            clone.querySelectorAll('nav, footer, script, style, noscript, header').forEach(n => n.remove());
            return clone.textContent.replace(/\\s+/g, ' ').trim();
        }""")[:5000]

        prompt = f"""You are summarising a single medical event detail page. Extract ONLY two fields.

EVENT TITLE: {shell.get('title')}

PAGE BODY:
{text}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the page text" or null,
  "specialty": "primary clinical/topic area (e.g. Orthopaedics, Cardiology, Sleep Medicine, Public Health)" or null
}}"""
        # Try the LLM, but ALWAYS fall through to the heuristic classifier.
        # The earlier bug here: an early `return {}` on llm_call=None skipped the
        # heuristic entirely, so cloud-worker rate-limit failures produced rows
        # with both description AND specialty null. Now the heuristic runs
        # whether the LLM succeeded or not.
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
                logger.warning(f"RSM soft-fields JSON parse failed: {e}; raw[:200]={raw[:200]!r}")

        # Specialty heuristic — ALWAYS runs as a fallback when LLM didn't yield one
        if not result.get("specialty"):
            heuristic = classify_specialty(shell.get("title"), text)
            if heuristic:
                result["specialty"] = heuristic
        return result
