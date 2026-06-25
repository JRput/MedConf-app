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


# ----------------------------------------------------------------------
# event_type classifiers — used by the merge layer when the per-source
# extractor doesn't return an explicit event_type.
# ----------------------------------------------------------------------

def _event_type_from_category(cat: Optional[str]) -> Optional[str]:
    """Map a source-provided listing-card category badge to event_type.

    RCP exposes 'Conference' / 'Workshop' / 'Webinar' / 'Social' / 'Ceremony'.
    Most other sources don't expose this — they pass None and we fall through
    to the title heuristic.
    """
    if not cat:
        return None
    c = cat.strip().lower()
    if c in ("workshop", "webinar"):
        return "workshop"
    if c in ("course",):
        return "course"
    if c in ("conference",):
        return "conference"
    # 'social' / 'ceremony' fall through to None → title heuristic / default
    return None


# Title-keyword rules. Order matters — more-specific terms first.
# Each entry is (regex, event_type).
_TITLE_RULES = [
    # "Course" is overloaded — "ATLS Provider course" is a course, but "Trauma
    # Symposium 2026" is a conference. We trust the word when it appears.
    (re.compile(r"\b(?:masterclass|workshop|webinar|seminar|short course|study day|training day|teaching day|skills lab|simulation)\b", re.I), "workshop"),
    (re.compile(r"\b(?:course|programme|cpd|certification|fellowship programme|training programme)\b", re.I), "course"),
    (re.compile(r"\b(?:conference|congress|symposium|summit|annual meeting|forum|expo)\b", re.I), "conference"),
]


def _event_type_from_title(title: Optional[str]) -> Optional[str]:
    """Title keyword heuristic. Returns None when nothing matches confidently
    — caller falls through to 'conference' as the safe default."""
    if not title:
        return None
    for rx, kind in _TITLE_RULES:
        if rx.search(title):
            return kind
    return None


# Flagship = international or national-level major conference. These are
# the once-a-year flagship events of a Royal College / specialty society
# (RCEM Annual Conference, RCOG World Congress, RCP Annual Conference,
# RCGP Annual Conference, etc). Distinct from regional / local events.
_FLAGSHIP_TITLE_RE = re.compile(
    r"\b("
    r"world\s+congress"
    r"|international\s+congress"
    r"|international\s+conference"
    r"|annual\s+conference"
    r"|annual\s+congress"
    r"|annual\s+meeting"
    r"|annual\s+symposium"
    r"|annual\s+scientific\s+(?:meeting|conference)"
    r"|national\s+conference"
    r"|national\s+congress"
    r")\b",
    re.I,
)


_JUNK_TITLE_RE = re.compile(
    r"^("
    r"there are no results"
    r"|no results"
    r"|no events"
    r"|no upcoming events"
    r"|loading"
    r"|page not found"
    r"|sorry,?\s*(?:something|we)"
    r"|search results"
    r"|select a"
    r"|\.\.\."
    r")",
    re.I,
)


def _is_junk_title(title: Optional[str]) -> bool:
    """True when the listing-card title is an empty-state / loading / error
    message that slipped in because a JS-rendered listing rendered its
    not-found view at the moment of harvest. These are NEVER real event
    titles and should never reach `conferences.conference_name`."""
    if not title:
        return True
    t = title.strip()
    return bool(_JUNK_TITLE_RE.match(t))


def _is_flagship_from_title(title: Optional[str]) -> bool:
    """Detect international/national flagship conferences from the title.

    Used as the merge-layer default. Per-source extractors can force-set
    is_flagship=True (RCEM source 8, RCOG source 10) when the source IS
    the flagship event and don't need to round-trip through this regex.

    Also used against the description as a secondary check — many
    flagships use a tagline as their title (e.g. "Defining the future
    of general practice…") but then say "RCGP Annual Conference" inside
    the description body.
    """
    if not title:
        return False
    return bool(_FLAGSHIP_TITLE_RE.search(title))


# Dedicated subsites for known flagship events. The detail URL is the
# most reliable signal when the visible title is a marketing tagline.
_FLAGSHIP_URL_HOSTS = (
    "rcgpac.org.uk",      # RCGP Annual Conference subsite
    "rcem-events.uk",     # RCEM conference registration domain (annual conf etc.)
)


def _is_flagship_from_url(url: Optional[str]) -> bool:
    if not url:
        return False
    u = url.lower()
    return any(host in u for host in _FLAGSHIP_URL_HOSTS)


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
        # timeout=90s: NVIDIA's gateway only returns its own 504 after ~300s, so
        # without an explicit client timeout a hung request burns ~5 min before we
        # even retry. Failing fast at 90s lets the retry hit a (possibly healthier)
        # backend node sooner. max_retries=5 still covers transient 429s/504s.
        self.client = OpenAI(
            api_key=KIMI_API_KEY,
            base_url=KIMI_BASE_URL,
            max_retries=5,
            timeout=90.0,
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
        # Per-source extractors may bypass the DOM walker when they have a
        # more reliable listing (e.g. sitemap.xml for course catalogues).
        try:
            override = self.extractor.list_shells_override()
        except Exception as e:
            logger.warning(f"Extractor.list_shells_override failed: {e}")
            override = None

        if override is not None:
            logger.info(f"Listing phase: {len(override)} shells from extractor override")
            return override

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

        # Description fallback: if the detail page's description is null
        # (typical when the LLM call timed out / 504'd), fall back to the
        # listing card's description_hint. RCGP and many other listing
        # cards already carry a rich human-written summary — far better
        # than a null. Per-source extractors that have their own
        # deterministic fallback (e.g. RCP's Overview-tab paragraph) will
        # have set detail.description before this point, so they're
        # unaffected by this fallback.
        description = detail.get("description") or shell.get("description_hint")

        # Course extractors pull the proper course title from the detail
        # page's h1 (slug-derived titles in the sitemap-listed shell are
        # ugly). For conferences, shell["title"] from the listing card is
        # canonical. Prefer detail's value when present.
        #
        # Safety net: reject obvious empty-state shell titles ("There are
        # no results matching…", "No events found", "Loading…"). These
        # happen when a JS-rendered listing page briefly shows its empty
        # / loading state during shell harvesting. When the shell title
        # looks junk and the extractor didn't supply a real one, fall
        # back to a URL-slug-derived placeholder so the row is at least
        # identifiable until the next scrape repairs it.
        shell_title = (shell.get("title") or "").strip()
        if _is_junk_title(shell_title):
            slug = (shell.get("booking_url") or "").rstrip("/").rsplit("/", 1)[-1]
            shell_title = slug.replace("-", " ").strip().title() if slug else shell_title
        conference_name = detail.get("conference_name") or shell_title

        # event_type chain:
        #   1. detail extractor's explicit value (highest priority — e.g. RCSEng
        #      courses always set 'course'; RCP sets from category badge)
        #   2. shell.category badge text (RCP captures this via .event-results__first-tag)
        #   3. title-keyword heuristic (covers RCGP/RSM/RCSEng-events whose listing
        #      cards don't expose a category)
        #   4. fallback to 'conference'
        event_type = (
            detail.get("event_type")
            or _event_type_from_category(shell.get("category"))
            or _event_type_from_title(conference_name)
            or "conference"
        )

        # Sessions array is course-specific. Pass through to the upsert layer.
        sessions = detail.get("sessions")

        return {
            # Deterministic from listing
            "conference_name": conference_name,
            "event_type": event_type,
            "is_sold_out": shell.get("is_sold_out", False),
            "start_date": start_date,
            "start_time": shell.get("start_time"),
            # LLM-derived from detail page
            "end_date": end_date,  # default end=start for single-day
            "description": description,
            "sessions": sessions,
            "specialty": detail.get("specialty"),
            "venue_name": detail.get("venue_name"),
            "city": city,
            "region": detail.get("region"),
            "event_format": event_format,
            "cpd_points": detail.get("cpd_points"),
            "cpd_accredited": bool(detail.get("cpd_accredited", False)),
            "abstract_open": bool(detail.get("abstract_open", False)),
            "abstract_deadline": detail.get("abstract_deadline"),
            "abstract_deadline_note": detail.get("abstract_deadline_note"),
            "pricing_tiers": detail.get("pricing_tiers", []) or [],
            # On-demand catch-up flag (RCEM source 7). When True, start_date
            # holds the "available until" deadline rather than a live date.
            "is_on_demand": bool(detail.get("is_on_demand", False)),
            "on_demand_original_date": detail.get("on_demand_original_date"),
            # Flagship = international/national major LIVE conference. Detection chain:
            #   1. Per-source extractor set detail["is_flagship"] directly
            #      (RCEM source 8, RCOG source 10) — highest priority.
            #   2. Dedicated-subsite URL — `rcgpac.org.uk` is the RCGP
            #      Annual Conference's standalone marketing site; the
            #      title there is typically the year's tagline (e.g.
            #      "Defining the future of general practice…") and won't
            #      hit the title regex, so the URL is the safer signal.
            #   3. Title regex — matches "Annual Conference", "World
            #      Congress", etc.
            # Deliberately NOT matched against `description` — descriptions
            # often reference OTHER flagships ("ahead of RCGP Annual
            # Conference") or use "national" generically, producing too
            # many false positives.
            # Only fires when event_type is conference AND the row isn't
            # an on-demand recording (past-flagship recordings live on
            # the On-Demand chip).
            "is_flagship": bool(detail.get("is_flagship") or (
                event_type == "conference"
                and not detail.get("is_on_demand", False)
                and (
                    _is_flagship_from_url(booking_url)
                    or _is_flagship_from_title(conference_name)
                )
            )),
            # Identity — prefer the extractor's explicit organiser/booking_url
            # (some sources distinguish the rcem.ac.uk landing page from the
            # third-party registration form) and fall back to the shell.
            "organiser_url": detail.get("organiser_url") or booking_url,
            "booking_url": detail.get("booking_url") or booking_url,
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
            # max_tokens=512: the soft-fields prompt only needs a ~50-word
            # description + a specialty (~120 tokens). The old 4096 ceiling let
            # the model hold the connection long enough to trip NVIDIA's ~300s
            # gateway timeout (the 504s). A tight cap finishes generation in
            # seconds and makes 504s rare.
            response = self.client.chat.completions.create(
                model=KIMI_MODEL,
                max_tokens=512,
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
