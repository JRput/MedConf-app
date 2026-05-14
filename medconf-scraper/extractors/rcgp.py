# extractors/rcgp.py
"""
Royal College of General Practitioners — detail-page extractor.

RCGP listing cards link to TWO different detail-page domains:

  1. engage.rcgp.org.uk/event/<id>  (most events)
       - Salesforce-rendered booking widget
       - Body is THIN (~3-7K chars) — title + sessions + speakers + 2 prices
       - Pricing as inline <p><span>Member rate: £99</span></p>
       - No CPD info on detail page
       - No description, no venue/format info — these come from the listing

  2. www.rcgpac.org.uk  (Annual Conference flagship — once a year)
       - Standalone marketing site, completely different markup
       - <strong>Location</strong><p>SEC Glasgow</p> pattern
       - <strong>Conference and Exhibition dates</strong><p>29-30 October 2026</p>
       - Pricing hidden behind a "Ticket options" button (skipped — would need click-flow)

Because RCGP detail pages are thin, the listing card's `description_hint` and
`location_hint` are MORE valuable than the detail page for descriptive fields.
The detail page primarily contributes pricing.
"""

import json
import re
from typing import Dict, Any, Optional, Callable, List
from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from logger import logger


# Heuristic keyword sets
ONLINE_TITLE_KEYS = ("online", "webinar", "virtual", "remote")
IN_PERSON_TITLE_KEYS = ()  # rare to see explicit; default by venue presence


class RCGPExtractor(BaseExtractor):

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        url = page.url
        if "rcgpac.org.uk" in url:
            return self._extract_rcgpac(page, shell, llm_call)
        return self._extract_engage(page, shell, llm_call)

    # ================================================================== #
    # Path A — engage.rcgp.org.uk (most RCGP events)
    # ================================================================== #
    def _extract_engage(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        # 1. Pricing — inline <span>Member rate: £99</span> patterns
        result["pricing_tiers"] = self._extract_engage_pricing(page)

        # 2. Format & venue inferred from title + listing hints
        result.update(self._infer_format_from_listing(shell))

        # 3. CPD: detail page rarely has it — listing card text might mention "CPD"
        result["cpd_accredited"] = self._infer_cpd_from_shell(shell)
        result["cpd_points"] = None  # Detail page doesn't carry numeric CPD

        # 4. End date for multi-day events: try regex on title or shell description
        end_date = self._extract_end_date_from_shell_or_page(shell, page)
        if end_date:
            result["end_date"] = end_date

        # 5. Description: prefer listing description_hint (much richer than thin
        # engage detail page), fall back to LLM
        soft = self._extract_soft_fields_engage(page, shell, llm_call)
        result.update(soft)

        return result

    def _extract_engage_pricing(self, page: Page) -> List[Dict[str, Any]]:
        """
        Pricing on engage pages is rendered as <p><span>Member rate: £99</span></p>
        across two patterns:
          "Members - £525" / "Non-member - £625"
          "Member rate: £99" / "Non member rate: £149"
        Sometimes more tiers (Trainee, Group) appear too.
        """
        try:
            text = page.evaluate("() => document.body.textContent || ''")
        except Exception as e:
            logger.warning(f"RCGP engage pricing extraction failed: {e}")
            return []

        # Capture all "<label> [-:] £<amount>" pairs.
        # Engage page DOM concatenates adjacent <p> textContent without whitespace
        # ("Members - £525Non-member - £625"), so we cannot rely on a leading \b.
        # The alternation order (Non-member tried after Members?) means we must
        # also use a leading lookbehind that allows digits/letters/start-of-string
        # but PREFERS the longer "Non-member" alternative when present.
        # The trailing \b plus the ":/-/£" suffix is enough to avoid false positives.
        pattern = re.compile(
            r"(Non[- ]?members?|Members?|Trainees?|Students?|Group|Standard)\b"
            r"(?:\s+rate)?\s*[-:]?\s*£\s*([0-9]+(?:\.[0-9]+)?)",
            re.I,
        )

        seen = set()
        tiers: List[Dict[str, Any]] = []
        for m in pattern.finditer(text):
            raw_label = m.group(1).strip()
            price = float(m.group(2))
            # Normalise label
            label = self._normalise_tier_label(raw_label)
            key = (label, price)
            if key in seen:
                continue
            seen.add(key)
            tiers.append({
                "tier_label": label,
                "price_gbp": price,
                "is_early_bird": False,
                "early_bird_deadline": None,
            })
        return tiers

    @staticmethod
    def _normalise_tier_label(raw: str) -> str:
        """Map varied source labels to a small canonical set."""
        r = raw.lower().replace(" ", "").replace("-", "")
        if r.startswith("nonmember"):
            return "Non-Member"
        if r.startswith("member"):
            return "Member"
        if r.startswith("trainee"):
            return "Trainee"
        if r.startswith("student"):
            return "Student"
        if r == "group":
            return "Group"
        if r == "standard":
            return "Standard"
        return raw.title()

    def _infer_format_from_listing(self, shell: Dict[str, Any]) -> Dict[str, Any]:
        """
        RCGP listings expose location hints — "Online" for webinars, a city
        name (Middlesbrough / Manchester / etc.) for in-person events.

        Where the listing card doesn't make format explicit (many RCGP webinars
        don't), fall through to keyword inference on title + description_hint.
        """
        hint = (shell.get("location_hint") or "").strip()
        title_lower = (shell.get("title") or "").lower()
        desc_lower = (shell.get("description_hint") or "").lower()

        # Strong online signals
        if hint.lower() == "online" or any(k in title_lower for k in ONLINE_TITLE_KEYS):
            return {"event_format": "online", "venue_name": None, "city": None, "region": None}
        # Inference from listing description
        for kw in ("online webinar", "live webinar", "online event", "online course",
                  "via zoom", "via teams", "virtual event"):
            if kw in desc_lower:
                return {"event_format": "online", "venue_name": None, "city": None, "region": None}
        # Standalone "webinar" / "online" in description (less strong but usable)
        if "webinar" in desc_lower or " online " in f" {desc_lower} ":
            return {"event_format": "online", "venue_name": None, "city": None, "region": None}

        # In-person hints
        if hint:
            return {
                "event_format": "in_person",
                "venue_name": None,         # detail page doesn't reliably state venue
                "city": hint,
                "region": self._infer_uk_region(hint),
            }
        return {"event_format": None}

    @staticmethod
    def _infer_uk_region(city: str) -> Optional[str]:
        c = (city or "").lower()
        regions = {
            "london": "London", "manchester": "North West England",
            "liverpool": "North West England", "leeds": "Yorkshire and the Humber",
            "sheffield": "Yorkshire and the Humber", "york": "Yorkshire and the Humber",
            "newcastle": "North East England", "middlesbrough": "North East England",
            "birmingham": "West Midlands", "bristol": "South West England",
            "exeter": "South West England", "cardiff": "Wales",
            "edinburgh": "Scotland", "glasgow": "Scotland",
            "belfast": "Northern Ireland", "cambridge": "East of England",
            "norwich": "East of England", "oxford": "South East England",
            "doncaster": "Yorkshire and the Humber", "warrington": "North West England",
            "reigate": "South East England",
        }
        for key, val in regions.items():
            if key in c:
                return val
        return None

    @staticmethod
    def _infer_cpd_from_shell(shell: Dict[str, Any]) -> bool:
        """RCGP detail pages don't show CPD — check listing description for it."""
        for src in (shell.get("description_hint"), shell.get("title")):
            if not src:
                continue
            if re.search(r"\bCPD[- ]accredited|CPD[- ]approved|\d+\s*CPD\s*point", src, re.I):
                return True
        # Best signal: course types (Minor Surgery / Diabetes / etc.) ARE CPD-eligible.
        # We default false to be honest — the dashboard can show "CPD: unspecified" rather than fabricate.
        return False

    def _extract_end_date_from_shell_or_page(
        self, shell: Dict[str, Any], page: Page,
    ) -> Optional[str]:
        """RCGP detail pages don't show date ranges. Best signal is the event title for multi-day courses."""
        title = shell.get("title") or ""
        # "3-day", "Two-day" hints
        m = re.search(r"\b(\d+)[- ]day\b", title, re.I)
        if m and shell.get("start_date"):
            n_days = int(m.group(1))
            if 2 <= n_days <= 14:
                from datetime import datetime, timedelta
                try:
                    start = datetime.strptime(shell["start_date"], "%Y-%m-%d")
                    return (start + timedelta(days=n_days - 1)).strftime("%Y-%m-%d")
                except ValueError:
                    return None
        return None

    def _extract_soft_fields_engage(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        """
        For engage pages, prefer the listing description_hint (richer than the
        thin detail page). Use LLM only to compress it and to classify specialty.
        """
        # Prefer listing description; fall back to detail page text
        text_for_llm = (shell.get("description_hint") or "").strip()
        if not text_for_llm:
            text_for_llm = page.evaluate("""() => {
                const main = document.querySelector('main, article, [role="main"]') || document.body;
                const clone = main.cloneNode(true);
                clone.querySelectorAll('nav, footer, script, style, noscript, header').forEach(n => n.remove());
                return clone.textContent.replace(/\\s+/g, ' ').trim();
            }""")[:3000]

        prompt = f"""You are summarising an RCGP medical event from its listing description.

EVENT TITLE: {shell.get('title')}

LISTING DESCRIPTION:
{text_for_llm}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the description above" or null,
  "specialty": "clinical/topic area (e.g. General Practice, Minor Surgery, Exam Preparation, Dermatology)" or null
}}"""
        raw = llm_call(prompt)
        parsed = self._parse_soft_json(raw) if raw else {}

        # Heuristic fallback for specialty — runs even when the LLM call fails
        # (common when cloud workers hit NVIDIA rate limits). Title + listing
        # description usually contain enough signal to classify deterministically.
        if not parsed.get("specialty"):
            heuristic = classify_specialty(shell.get("title"), text_for_llm)
            if heuristic:
                parsed["specialty"] = heuristic

        return parsed

    # ================================================================== #
    # Path B — rcgpac.org.uk (Annual Conference)
    # ================================================================== #
    def _extract_rcgpac(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        # Date + venue from <strong>Label</strong><p>Value</p> pattern
        meta = self._extract_rcgpac_metadata(page)
        result.update(meta)

        # Pricing on the public homepage is hidden behind "Ticket options" button.
        # Skip — annual conf pricing varies and is best left as TBC until they
        # publish a dedicated tickets page we can target.
        result["pricing_tiers"] = []

        # CPD — page mentions "CPD credits" via image alt text
        text = page.evaluate("() => document.body.textContent || ''")
        if re.search(r"\bCPD\s+credit", text, re.I):
            result["cpd_accredited"] = True
        else:
            result["cpd_accredited"] = False
        result["cpd_points"] = None

        # Description + specialty
        soft = self._extract_soft_fields_rcgpac(page, shell, llm_call)
        result.update(soft)

        return result

    def _extract_rcgpac_metadata(self, page: Page) -> Dict[str, Any]:
        """
        Walk <strong>Label</strong> → next sibling text. RCGPAC uses this for
        Conference dates, Location, View the programme, etc.
        """
        try:
            data = page.evaluate(r"""() => {
                const labels = {};
                document.querySelectorAll('strong, b, h2, h3, h4').forEach(el => {
                    const label = (el.textContent || '').trim();
                    if (!label) return;
                    // The value is the immediate next sibling's text content
                    let next = el.nextElementSibling;
                    if (!next) {
                        // try parent's nextSibling
                        next = el.parentElement?.nextElementSibling || null;
                    }
                    if (next) {
                        const value = (next.textContent || '').trim().slice(0, 200);
                        if (value) labels[label] = value;
                    }
                });
                return labels;
            }""")
        except Exception as e:
            logger.warning(f"RCGPAC metadata extraction failed: {e}")
            return {}

        out: Dict[str, Any] = {}
        # Find the venue
        for label_key, value in data.items():
            if re.match(r"^location$", label_key.strip(), re.I):
                # value e.g. "SEC Glasgow"
                venue = value.split(",")[0].strip()
                out["venue_name"] = venue[:200]
                # Try to derive city
                if "glasgow" in venue.lower():
                    out["city"] = "Glasgow"
                    out["region"] = "Scotland"
                elif "london" in venue.lower():
                    out["city"] = "London"
                    out["region"] = "London"
                elif "," in value:
                    parts = [p.strip() for p in value.split(",") if p.strip()]
                    if len(parts) >= 2:
                        out["city"] = parts[1][:80]
                out["event_format"] = "in_person"
                break

        # Find the dates
        for label_key, value in data.items():
            if re.match(r".*(?:dates?)\s*$", label_key.strip(), re.I):
                # e.g. "29-30 October 2026"
                m = re.search(r"\b(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", value)
                if m:
                    months = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
                              "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
                    mon = months.get(m.group(3).lower()[:3])
                    if mon:
                        out["start_date"] = f"{int(m.group(4)):04d}-{mon:02d}-{int(m.group(1)):02d}"
                        out["end_date"]   = f"{int(m.group(4)):04d}-{mon:02d}-{int(m.group(2)):02d}"
                break

        return out

    def _extract_soft_fields_rcgpac(
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

        prompt = f"""You are summarising the RCGP Annual Conference homepage.

EVENT TITLE: {shell.get('title')}

PAGE BODY:
{text}

Respond with valid JSON only:
{{
  "description": "30-50 word summary built only from the page text" or null,
  "specialty": "General Practice"
}}"""
        raw = llm_call(prompt)
        if not raw:
            return {"specialty": "General Practice"}
        return self._parse_soft_json(raw)

    # ================================================================== #
    # Shared
    # ================================================================== #
    @staticmethod
    def _parse_soft_json(raw: str) -> Dict[str, Any]:
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
            return {
                "description": parsed.get("description"),
                "specialty": parsed.get("specialty"),
            }
        except json.JSONDecodeError as e:
            logger.warning(f"RCGP soft-fields JSON parse failed: {e}")
            return {}
