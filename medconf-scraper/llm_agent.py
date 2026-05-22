# llm_agent.py
"""LLM orchestration engine - the reasoning loop that drives the scraper."""

import json
import hashlib
import re
from openai import OpenAI
from config import KIMI_API_KEY, KIMI_BASE_URL, KIMI_MODEL, SCRAPER_MAX_STEPS
from browser import BrowserController
from extractors import get_extractor
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse
from logger import logger


class AgentLoop:
    """
    The agentic loop that uses an LLM to navigate websites and extract conference data.
    
    At each step, the LLM receives the current page content and decides:
    - 'navigate': Go to a different URL
    - 'extract': Extract conference data from current page
    - 'done': Task complete
    """
    
    def __init__(self, source: Dict[str, Any]):
        self.source = source
        # Kimi K2 Instruct via NVIDIA's OpenAI-compatible API.
        # max_retries=5 lets the client auto-retry 429s with exponential backoff
        # — addresses the rate-limit failures we saw in the multi-source test.
        self.client = OpenAI(
            api_key=KIMI_API_KEY,
            base_url=KIMI_BASE_URL,
            max_retries=5,
        )
        self.browser = BrowserController()
        self.step_count = 0
        self.extracted_data: List[Dict[str, Any]] = []
        self.history: List[str] = []  # Tracks actions taken so far
        # Per-source detail-page extractor (RSMExtractor for source_id=3, etc.).
        # Defaults to FallbackExtractor (LLM-only) for sources without a registered file.
        self.extractor = get_extractor(source)

    # ------------------------------------------------------------------ #
    # Phase A — listing walk (no LLM, no detail navigation)
    # ------------------------------------------------------------------ #
    def list_shells(self) -> List[Dict[str, Any]]:
        """
        Walk the listing page(s) for this source and return event-card shells.

        Uses pagination config from scraper_sources (pagination_type,
        pagination_template, max_pages_hint). Returns shells with
        title/booking_url/is_sold_out/start_date/start_time/location_hint/
        description_hint/page_index. Deterministic — no LLM calls here.

        Caller is responsible for launching/closing the browser before/after.
        """
        try:
            shells = self.browser.get_event_cards_paginated(self.source)
        except Exception as e:
            logger.warning(f"DOM card extraction failed: {e}")
            return []
        logger.info(f"Listing phase: {len(shells)} cards extracted across all pages")
        return shells

    # ------------------------------------------------------------------ #
    # Phase B — detail enrichment for a SINGLE shell
    # ------------------------------------------------------------------ #
    def extract_detail_for_shell(self, shell: Dict[str, Any]) -> Dict[str, Any]:
        """
        Navigate to one event's detail URL and run the per-source extractor.
        Returns a fully merged conference dict ready for validation + upsert.

        Caller is responsible for browser lifecycle.
        """
        title_short = (shell.get("title") or "")[:60]
        booking_url = shell.get("booking_url")
        if not booking_url:
            logger.warning(f"  No booking_url for '{title_short}' — using listing data only")
            return self._merge_shell_only(shell)
        try:
            self.browser.navigate(booking_url)
            detail = self.extractor.extract_detail(
                page=self.browser.page,
                shell=shell,
                llm_call=self._llm_call,
            )
            return self._merge_shell_and_detail(shell, detail)
        except Exception as e:
            logger.warning(f"  Detail extraction failed for '{title_short}': {e}")
            return self._merge_shell_only(shell)

    # ------------------------------------------------------------------ #
    # Browser lifecycle helpers (called explicitly by scraper.py now)
    # ------------------------------------------------------------------ #
    def open_browser(self) -> None:
        self.browser.launch()

    def close_browser(self) -> None:
        try:
            self.browser.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Legacy run() — kept for compatibility with non-incremental callers
    # (e.g. run_rcgp_source.py). Performs the full list-then-detail flow.
    # ------------------------------------------------------------------ #
    def run(self) -> Dict[str, Any]:
        try:
            self.open_browser()
            shells = self.list_shells()
            if not shells:
                logger.info("No structured cards; using legacy LLM fallback")
                return self._run_legacy_fallback()
            for i, shell in enumerate(shells):
                self.step_count += 1
                logger.info(f"Detail {i+1}/{len(shells)}: {(shell.get('title') or '')[:60]}")
                self.extracted_data.append(self.extract_detail_for_shell(shell))
            return {
                "data": self.extracted_data,
                "steps_taken": self.step_count,
                "error": None if self.extracted_data else "No data extracted",
            }
        except Exception as e:
            return {"data": self.extracted_data, "steps_taken": self.step_count, "error": str(e)}
        finally:
            self.close_browser()

    def _merge_shell_and_detail(self, shell: Dict[str, Any], detail: Dict[str, Any]) -> Dict[str, Any]:
        """Combine deterministic shell data (trustworthy) with LLM detail (enriched)."""
        booking_url = shell.get("booking_url")
        location_hint = shell.get("location_hint")

        # Prefer detail-page event_format; if absent and listing said "Online", use that
        event_format = detail.get("event_format")
        if event_format is None and location_hint and location_hint.lower() == "online":
            event_format = "online"

        # Prefer detail-page city; if absent and location_hint is a real city (not "Online"), use it
        city = detail.get("city")
        if not city and location_hint and location_hint.lower() != "online":
            city = location_hint

        # Date precedence: listing card is usually canonical, but for multi-page
        # micro-sites (e.g. rcgpac.org.uk) the listing card may only carry the
        # end date or no date at all — fall back to detail-extracted dates then.
        start_date = shell.get("start_date") or detail.get("start_date")
        end_date = detail.get("end_date") or shell.get("start_date") or detail.get("start_date")

        return {
            # Deterministic from listing
            "conference_name": shell["title"],
            "booking_url": booking_url,
            "is_sold_out": shell.get("is_sold_out", False),
            "start_date": start_date,
            "start_time": shell.get("start_time"),
            # LLM-derived from detail page
            "end_date": end_date,  # default end=start for single-day
            "description": detail.get("description"),
            "specialty": detail.get("specialty"),
            "venue_name": detail.get("venue_name"),
            "city": city,
            "region": detail.get("region"),
            "event_format": event_format,
            "cpd_points": detail.get("cpd_points"),
            "cpd_accredited": bool(detail.get("cpd_accredited", False)),
            "abstract_open": bool(detail.get("abstract_open", False)),
            "abstract_deadline": detail.get("abstract_deadline"),
            "pricing_tiers": detail.get("pricing_tiers", []) or [],
            # Identity
            "organiser_url": booking_url,
            "source_url": booking_url or self._fallback_source_url(shell["title"]),
        }

    def _merge_shell_only(self, shell: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback when detail extraction fails — use only the listing-level data."""
        booking_url = shell.get("booking_url")
        location_hint = shell.get("location_hint")
        is_online = bool(location_hint and location_hint.lower() == "online")
        return {
            "conference_name": shell["title"],
            "booking_url": booking_url,
            "is_sold_out": shell.get("is_sold_out", False),
            "start_date": shell.get("start_date"),
            "start_time": shell.get("start_time"),
            "end_date": shell.get("start_date"),
            "city": None if is_online else location_hint,
            "event_format": "online" if is_online else None,
            "pricing_tiers": [],
            "organiser_url": booking_url,
            "source_url": booking_url or self._fallback_source_url(shell["title"]),
        }

    def _fallback_source_url(self, title: str) -> str:
        """Generate a deterministic synthetic URL when no booking_url is available."""
        h = hashlib.md5(title.encode()).hexdigest()[:8]
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:40].strip("-")
        return f"{self.source['base_url']}#{slug}-{h}"

    def _extract_detail(self, shell: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run the per-source extractor against the currently loaded detail page.

        Each source has its own extractor module under extractors/ that knows
        the HTML structure of that source's event pages (CSS selectors for
        pricing tables, venue blocks, etc). The extractor decides which fields
        to derive deterministically vs which to send to the LLM.

        Sources without a registered extractor fall through to FallbackExtractor
        which calls the LLM for everything (the previous default behaviour).
        """
        return self.extractor.extract_detail(
            page=self.browser.page,
            shell=shell,
            llm_call=self._llm_call,
        )

    def _llm_call(self, prompt: str) -> Optional[str]:
        """
        Helper passed to per-source extractors: runs a single chat completion
        against Kimi and returns the raw response text. Centralises model
        config (model name, temperature, max_tokens) and lets the OpenAI client's
        built-in retry policy (max_retries=5) handle transient 429s.
        """
        try:
            response = self.client.chat.completions.create(
                model=KIMI_MODEL,
                max_tokens=4096,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}],
                extra_body={"chat_template_kwargs": {"thinking": False}},
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.warning(f"  LLM call failed: {e}")
            return None

    def _run_legacy_fallback(self) -> Dict[str, Any]:
        """Original single-page LLM extract — used when DOM card extraction fails."""
        page_text = self.browser.get_page_text()
        self.step_count += 1
        logger.info(f"Legacy fallback: single LLM extract on listing page")
        decision = self._get_llm_decision(page_text)
        if decision.get("action") == "extract":
            data = decision.get("data", []) or []
            self.extracted_data.extend(data)
        return {
            "data": self.extracted_data,
            "steps_taken": self.step_count,
            "error": None if self.extracted_data else "Legacy fallback found no data"
        }

    def _get_llm_decision(self, page_text: str) -> Dict[str, Any]:
        """Send the current state to the LLM and parse its JSON response."""
        
        # Truncate page text if very long to stay within token limits
        truncated_text = page_text[:8000]
        
        # Get page links (limited to 50)
        links = self.browser.get_page_links()[:50]
        
        prompt = f"""You are a web scraping agent. Your task is to extract medical conference data from websites.

ORIGINAL INSTRUCTIONS:
{self.source['extraction_instructions']}

CURRENT PAGE URL: {self.browser.get_current_url()}

CURRENT PAGE CONTENT:
{truncated_text}

AVAILABLE LINKS ON PAGE:
{json.dumps(links, indent=2)}

ACTIONS TAKEN SO FAR:
{chr(10).join(self.history)}

CONFERENCES EXTRACTED SO FAR: {len(self.extracted_data)}

INSTRUCTIONS:
Based on the page content and your extraction instructions, decide your next action.

DATA FIDELITY RULES (HIGHEST PRIORITY — never violate):
A. Extract ONLY values that are explicitly visible in CURRENT PAGE CONTENT above. Do NOT use prior knowledge, training-data memory, or plausible guesses.
B. If a field is not on the page, set it to null (for strings, numbers, dates) or [] (for pricing_tiers). NEVER fabricate. NEVER fall back to a generic value.
C. Pricing: if no GBP amount (£N) appears on the page for a specific conference, that conference's "pricing_tiers" MUST be []. Marketing copy like "free for members" alone is NOT a tier — leave it empty.
D. Dates (start_date / end_date / abstract_deadline): null if no calendar date is shown for that event. Do not infer from event names, "annual" labels, or training data.
E. organiser_url: pick the per-event booking/detail link from AVAILABLE LINKS ON PAGE that corresponds to THIS specific conference. Match by proximity in the page text and by recognisable event slug. If you cannot confidently identify the right link for this event, use null. Do NOT use the listing URL as a fallback.
F. cpd_points: integer if a number is explicitly shown (e.g. "6 CPD points"). Otherwise null. Do not estimate.
G. region / city / venue_name: only what is printed on the page. Use null if absent. Do not infer "United Kingdom" or similar generics.
H. cpd_accredited: true only if the page explicitly says CPD-accredited / CPD-approved / shows a CPD points number. Otherwise false.

PAGINATION RULES:
1. Extract from each page ONLY ONCE. If you've already extracted from this page (check ACTIONS TAKEN SO FAR), navigate to the next page.
2. After extracting from a page, if pagination shows more pages (Next, Page 3, etc.), you MUST navigate to the next page.
3. Do NOT extract from the same page multiple times - this wastes steps and doesn't get new data.

Decision logic:
- If this is the FIRST time seeing conference data on this page, use action 'extract' and return ALL conferences found.
- If you've ALREADY extracted from this page, use action 'navigate' to go to the next page (check pagination links).
- If there are pagination links showing more pages (Next, Page 3, 4, etc.), navigate to the next unvisited page.
- If you see links to individual conference detail pages that might have more info, navigate to them.
- Only use action 'done' when you have visited ALL pages and extracted ALL available conferences.

CRITICAL: Respond ONLY with valid JSON. No text before or after. Use this exact structure:
{{
    "action": "navigate" | "extract" | "done",
    "url": "<only if navigating>",
    "data": [<only if extracting — array of conference objects>],
    "reasoning": "<brief explanation>"
}}

Conference object structure (apply DATA FIDELITY RULES — use null / [] when a field is not visible on the page):
{{
    "conference_name": string (required — the event title as printed),
    "specialty": string or null,
    "start_date": "YYYY-MM-DD" or null,
    "end_date": "YYYY-MM-DD" or null,
    "venue_name": string or null,
    "city": string or null,
    "region": string or null,
    "cpd_accredited": boolean (false unless explicitly stated, see rule H),
    "cpd_points": integer or null (MUST be whole number — null if not stated),
    "abstract_open": boolean (false unless the page explicitly mentions abstract submission is open),
    "abstract_deadline": "YYYY-MM-DD" or null,
    "organiser_url": string or null (per-event link from AVAILABLE LINKS — null if not identifiable, see rule E),
    "description": string or null (a short summary built ONLY from text on this page),
    "pricing_tiers": [{{"tier_label": string, "price_gbp": number}}] (EMPTY ARRAY [] if no GBP prices are shown on the page for this event, see rule C)
}}"""

        # Call Kimi K2.5 API - disable thinking mode for direct JSON output
        response = self.client.chat.completions.create(
            model=KIMI_MODEL,
            max_tokens=16384,
            temperature=0.7,
            messages=[{"role": "user", "content": prompt}],
            extra_body={"chat_template_kwargs": {"thinking": False}}  # Disable thinking mode
        )

        # Handle response - Kimi may return content in different places
        message = response.choices[0].message
        raw = message.content
        
        # If content is None, check for reasoning_content (Kimi's thinking mode output)
        if raw is None:
            # Check model_extra for reasoning content
            if hasattr(message, 'model_extra') and message.model_extra:
                raw = message.model_extra.get('reasoning_content') or message.model_extra.get('reasoning')
            # Also check direct attributes
            if raw is None and hasattr(message, 'reasoning_content'):
                raw = message.reasoning_content
            if raw is None and hasattr(message, 'reasoning'):
                raw = message.reasoning
        
        if raw is None:
            raise ValueError(f"No content in LLM response: {message}")
        
        # Ensure raw is a string before calling strip()
        if not isinstance(raw, str):
            raw = str(raw) if raw is not None else ""
        
        if not raw:
            raise ValueError(f"Empty content in LLM response: {message}")
        
        raw = raw.strip()
        
        # Strip markdown code fences if present
        if raw.startswith("```"):
            parts = raw.split("```")
            if len(parts) >= 2:
                raw = parts[1]
                if raw.startswith("json"):
                    raw = raw[4:].strip()
        
        # Try to find JSON in the response
        if not raw.startswith("{"):
            # Look for JSON object in the text
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start != -1 and end > start:
                raw = raw[start:end]
        
        return json.loads(raw)
