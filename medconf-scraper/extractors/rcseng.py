# extractors/rcseng.py
"""
Royal College of Surgeons of England — detail-page extractor.

RCSEng event detail pages (rcseng.ac.uk/news-and-events/events/calendar/<slug>/)
have a clean, server-rendered HTML structure. Pricing and CPD are in a
"highlights" sidebar with deterministic selectors:

  <div class="itemDetailsInfo-highlights">
    <ul class="noList">
      <li><span><i class="fa fa-gbp"></i> £0 - £15</span></li>
      <li><span><i class="rosette"></i>1 CPD Point</span></li>
    </ul>
  </div>

The price text is a "Member to Non-Member" range (e.g. "£0 - £15") which we
split into two tiers. Mobile-shadow duplicates (.itemHighlightMobile) are
deduplicated downstream.

Description + specialty still use a small LLM call.
"""

import json
import re
from typing import Dict, Any, Optional, Callable, List
from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from .abstract_classifier import extract_abstract_info
from logger import logger


class RCSEngExtractor(BaseExtractor):

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        # Canonical title from the detail page's <h1>. The listing scrape
        # can pick up empty-state copy ("There are no results matching your
        # search criteria.") when the RCSEng calendar's JS layer briefly
        # renders a no-results state during shell harvesting. Reading h1
        # from the real detail page guarantees the right title.
        try:
            h1 = (page.evaluate(
                "() => (document.querySelector('h1')||{}).textContent || ''"
            ) or "").strip()
            if h1 and len(h1) < 200:
                result["conference_name"] = h1
        except Exception:
            pass

        # Pricing tiers (deterministic — split "£0 - £15" range into Member/Non-Member)
        result["pricing_tiers"] = self._extract_pricing(page)

        # CPD points (deterministic — "1 CPD Point" pattern)
        cpd_pts, cpd_acc = self._extract_cpd(page)
        result["cpd_points"] = cpd_pts
        result["cpd_accredited"] = cpd_acc

        # Format / venue (most RCSEng events are webinars)
        venue_info = self._extract_format_and_venue(page, shell)
        result.update(venue_info)

        # End date for multi-day events
        end_date = self._extract_end_date(page)
        if end_date:
            result["end_date"] = end_date

        # Abstract / poster submission info (deterministic — no LLM)
        page_text = page.evaluate("() => document.body.textContent || ''")
        is_open, deadline = extract_abstract_info(page_text)
        result["abstract_open"] = is_open
        result["abstract_deadline"] = deadline.isoformat() if deadline else None

        # Description + specialty via small LLM call (RCSEng detail pages have
        # rich event-info prose)
        soft = self._extract_soft_fields(page, shell, llm_call)
        result.update(soft)

        return result

    # ------------------------------------------------------------------ #
    # Pricing
    # ------------------------------------------------------------------ #
    def _extract_pricing(self, page: Page) -> List[Dict[str, Any]]:
        """
        Walk .itemDetailsInfo-highlights to find the £-prefixed pricing line.
        Format is typically "£0 - £15" representing Member - Non-Member.
        Returns a list of pricing tiers split out into Member / Non-Member.
        """
        try:
            text = page.evaluate(r"""() => {
                // Prefer the desktop highlights section over the mobile shadow
                const desktop = document.querySelector('.itemDetailsInfo-highlights');
                if (desktop) {
                    return Array.from(desktop.querySelectorAll('li')).map(li => (li.textContent || '').trim()).join('\n');
                }
                // Fallback: any element with our typical highlight class
                const mob = document.querySelector('.itemHighlightMobile');
                if (mob) return (mob.textContent || '').trim();
                return '';
            }""")
        except Exception as e:
            logger.warning(f"RCSEng pricing extraction failed: {e}")
            return []

        if not text:
            return []

        # Find the £ line. Could be "£0 - £15" or "£15" or "£0 - £45 - £75"
        # Multiple prices separated by hyphens
        gbp_matches = re.findall(r"£\s*([0-9]+(?:\.[0-9]+)?)", text)
        if not gbp_matches:
            return []

        prices = [float(p) for p in gbp_matches]

        # Common patterns:
        #   single price → one tier (typically free)
        #   two prices    → Member / Non-Member
        #   three+ prices → Member / Non-Member / Trainee or similar — label sequentially
        if len(prices) == 1:
            return [{"tier_label": "Standard", "price_gbp": prices[0],
                     "is_early_bird": False, "early_bird_deadline": None}]
        if len(prices) == 2:
            return [
                {"tier_label": "Member",     "price_gbp": prices[0], "is_early_bird": False, "early_bird_deadline": None},
                {"tier_label": "Non-Member", "price_gbp": prices[1], "is_early_bird": False, "early_bird_deadline": None},
            ]
        # 3+ prices — generic labels
        labels = ["Member", "Non-Member", "Trainee", "Student", "Other"]
        return [
            {"tier_label": labels[i] if i < len(labels) else f"Tier {i+1}",
             "price_gbp": p, "is_early_bird": False, "early_bird_deadline": None}
            for i, p in enumerate(prices)
        ]

    # ------------------------------------------------------------------ #
    # CPD
    # ------------------------------------------------------------------ #
    def _extract_cpd(self, page: Page) -> tuple[Optional[int], bool]:
        """Look for 'N CPD Point(s)' / 'N CPD Credit(s)' anywhere on the page."""
        text = page.evaluate("() => document.body.textContent || ''")
        m = re.search(r"\b(\d+)\s*(?:CPD|cpd)\s*(?:Point|Credit)s?\b", text)
        if m:
            return int(m.group(1)), True
        # Implicit accreditation
        if re.search(r"\bCPD[- ]accredited|CPD[- ]approved\b", text, re.I):
            return None, True
        return None, False

    # ------------------------------------------------------------------ #
    # Format / venue
    # ------------------------------------------------------------------ #
    def _extract_format_and_venue(self, page: Page, shell: Dict[str, Any]) -> Dict[str, Any]:
        """
        RCSEng events are typically:
          - Webinars (most common) — title starts with "Webinar:" → online
          - In-person events at RCSEng, Lincoln's Inn Fields, London
          - Hybrid events (less common)
        """
        title = (shell.get("title") or "").lower()
        text = page.evaluate("() => document.body.textContent || ''")
        lower_text = text.lower()

        # Strong signals first
        if title.startswith("webinar:") or " webinar " in lower_text[:5000]:
            return {"event_format": "online", "venue_name": None, "city": None, "region": None}
        if re.search(r"\bhybrid\s+event\b", lower_text) or re.search(r"\bonline and in[- ]person\b", lower_text):
            return {"event_format": "hybrid"}
        # Look for "At The Royal College of Surgeons" or RCS England venue
        if re.search(r"\bRoyal College of Surgeons of England\b|\bLincoln['']s Inn Fields\b", text):
            return {
                "event_format": "in_person",
                "venue_name": "Royal College of Surgeons of England",
                "city": "London",
                "region": "London",
            }
        # Default: unknown — leave for shell merge to fill from listing hint
        return {}

    # ------------------------------------------------------------------ #
    # Date utilities
    # ------------------------------------------------------------------ #
    def _extract_end_date(self, page: Page) -> Optional[str]:
        """Look for date ranges like '20-21 May 2026' on the page."""
        text = page.evaluate("() => document.body.textContent || ''")
        m = re.search(r"\b(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text)
        if not m:
            return None
        end_day = int(m.group(2))
        mon_key = m.group(3).lower()[:3]
        year = int(m.group(4))
        months = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
                  "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
        if mon_key not in months:
            return None
        return f"{year:04d}-{months[mon_key]:02d}-{end_day:02d}"

    # ------------------------------------------------------------------ #
    # Description + specialty (LLM)
    # ------------------------------------------------------------------ #
    def _extract_soft_fields(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        text = page.evaluate("""() => {
            const main = document.querySelector('main, article, [role="main"]') || document.body;
            const clone = main.cloneNode(true);
            clone.querySelectorAll('nav, footer, script, style, noscript, header').forEach(n => n.remove());
            return clone.textContent.replace(/\\s+/g, ' ').trim();
        }""")[:5000]

        prompt = f"""You are summarising a single Royal College of Surgeons of England event detail page.

EVENT TITLE: {shell.get('title')}

PAGE BODY:
{text}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the page text" or null,
  "specialty": "primary clinical/topic area (e.g. Surgery, Dentistry, Exam Preparation, Oncology)" or null
}}"""
        # Always try the heuristic, even when the LLM call returned None.
        # (Fixed regression: previous code had an early return on llm_call=None
        # that bypassed the heuristic — leaving cloud-worker rows null when
        # NVIDIA rate-limited the LLM call.)
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
                logger.warning(f"RCSEng soft-fields JSON parse failed: {e}")

        # Specialty heuristic ALWAYS runs as fallback when LLM didn't yield one
        if not result.get("specialty"):
            heuristic = classify_specialty(shell.get("title"), text)
            if heuristic:
                result["specialty"] = heuristic
        return result
