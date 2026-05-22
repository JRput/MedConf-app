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
from .abstract_classifier import extract_abstract_info
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

        # 5. Abstract / poster submission info (deterministic — no LLM)
        # For RCGP engage pages the detail body is thin, so we ALSO scan the
        # listing-card description_hint where calls for abstracts sometimes appear.
        combined_text = ((shell.get("description_hint") or "") + " " +
                          page.evaluate("() => document.body.textContent || ''"))
        is_open, deadline = extract_abstract_info(combined_text)
        result["abstract_open"] = is_open
        result["abstract_deadline"] = deadline.isoformat() if deadline else None

        # 6. Description: prefer listing description_hint (much richer than thin
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
    #
    # This is a small standalone website rather than a single page. Info is
    # split across /tickets, /programme, /programme/poster-abstract-submissions,
    # /overview/why-attend, etc. We use browser.fetch_multi_page_text() to walk
    # the relevant sub-pages and concatenate them, then apply our classifiers
    # to the combined text.
    # ================================================================== #
    def _extract_rcgpac(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        # 1. Multi-page crawl — walk the rcgpac.org.uk subsite
        # We use page.url here so logging / debug paths can see which start URL
        # triggered the crawl.
        from browser import BrowserController  # local import to avoid circular
        # The Page object's parent browser controller does the crawling. We
        # access it via a small trick — the AgentLoop owns the BrowserController
        # but the extractor only gets the Page. We grab the BrowserController
        # via a passthrough on the page's context. Simpler: just re-import and
        # use the page directly with our own multi-page logic.
        # In practice, the agent passes us page; we need to call
        # fetch_multi_page_text. Easiest is to construct a thin wrapper around
        # the same page. But since the agent's browser owns the page and we
        # already have it, let's just inline the walk here.
        all_text = self._collect_rcgpac_text(page, max_pages=8)
        text = "\n\n".join(all_text.values())

        # 2. Sidebar metadata still works on the homepage (the <strong>Location</strong>
        # pattern). We try the homepage first; if it lacks data, we'll have a
        # broader fallback via the combined text.
        meta = self._extract_rcgpac_metadata(page)
        result.update(meta)

        # 3. If metadata didn't catch a date range, try a regex on combined text
        if not result.get("start_date") or not result.get("end_date"):
            date_range = self._parse_date_range_from_text(text)
            if date_range:
                start_iso, end_iso = date_range
                # Don't overwrite an existing start_date with weaker data
                if start_iso and not result.get("start_date"):
                    result["start_date"] = start_iso
                if end_iso and not result.get("end_date"):
                    result["end_date"] = end_iso

        # 4. Pricing — parse from the combined text (/tickets sub-page typically
        # has Members/Non-members lines in £-amount format)
        result["pricing_tiers"] = self._parse_rcgpac_pricing(text)

        # 5. CPD — combined text has more chance of mentioning CPD credits
        if re.search(r"\b(\d+)\s*CPD\s*(?:point|credit)s?\b", text, re.I) \
                or re.search(r"\bCPD\s+(?:credit|accredit|approved)", text, re.I):
            result["cpd_accredited"] = True
            cpd_match = re.search(r"\b(\d+)\s*CPD\s*(?:point|credit)s?\b", text, re.I)
            if cpd_match:
                result["cpd_points"] = int(cpd_match.group(1))
        else:
            result["cpd_accredited"] = False
            result["cpd_points"] = None

        # 6. Abstract / poster submission info from combined text — much more
        # likely to find the deadline on /programme/poster-abstract-submissions
        is_open, deadline = extract_abstract_info(text)
        result["abstract_open"] = is_open
        result["abstract_deadline"] = deadline.isoformat() if deadline else None

        # 7. Description + specialty — LLM gets richer context now
        soft = self._extract_soft_fields_rcgpac_multi(text, shell, llm_call)
        result.update(soft)

        return result

    def _collect_rcgpac_text(self, page: Page, max_pages: int = 8) -> Dict[str, str]:
        """Walk same-domain sub-pages of the current rcgpac.org.uk page."""
        # The BrowserController owns navigation; reach it via the page's owning
        # browser if available — but the AgentLoop wires us with the page, not
        # the controller. Simpler approach: drive navigation directly on the page.
        try:
            start_url = page.url
            pages: Dict[str, str] = {}
            pages[start_url] = page.evaluate("() => document.body.textContent || ''") or ""

            # Discover candidate sub-pages on the homepage
            candidates = page.evaluate(
                """({allowlist, blocklist}) => {
                    const out = [];
                    const seen = new Set();
                    const start = new URL(document.location.href);
                    const startPath = start.origin + start.pathname;
                    document.querySelectorAll('a[href]').forEach(a => {
                        try {
                            const u = new URL(a.href);
                            if (u.hostname !== start.hostname) return;
                            const clean = u.origin + u.pathname;
                            if (clean === startPath) return;
                            if (seen.has(clean)) return;
                            const path = u.pathname.toLowerCase();
                            if (blocklist.some(kw => path.includes(kw))) return;
                            if (allowlist.some(kw => path.includes(kw))) {
                                seen.add(clean);
                                out.push(clean);
                            }
                        } catch (e) {}
                    });
                    return out;
                }""",
                {
                    "allowlist": ["programme", "ticket", "venue", "location", "abstract",
                                  "poster", "overview", "speakers", "registration",
                                  "register", "whats-on", "faqs", "agenda", "schedule",
                                  "about", "info", "highlights"],
                    "blocklist": ["cookie", "privacy", "terms", "accessibility",
                                  "sustainability", "sponsor", "exhibit", "phishing",
                                  "contact", "press", "media", "policy", "covid",
                                  "social-and-networking"],
                },
            ) or []

            budget = max_pages - 1
            for url in candidates[:budget]:
                try:
                    page.goto(url, wait_until="load", timeout=15000)
                    page.wait_for_timeout(1500)
                    txt = page.evaluate("() => document.body.textContent || ''") or ""
                    if txt.strip():
                        pages[url] = txt
                except Exception as e:
                    logger.warning(f"  rcgpac sub-page nav failed for {url}: {e}")
                    continue

            # Return to start URL
            try:
                page.goto(start_url, wait_until="load", timeout=15000)
                page.wait_for_timeout(1000)
            except Exception:
                pass

            return pages
        except Exception as e:
            logger.warning(f"  _collect_rcgpac_text failed: {e}")
            try:
                return {page.url: page.evaluate("() => document.body.textContent || ''") or ""}
            except Exception:
                return {}

    @staticmethod
    def _parse_rcgpac_pricing(text: str) -> List[Dict[str, Any]]:
        """
        Parse ticket-style pricing lines from rcgpac.org.uk's tickets page.
        Common patterns:
          'Member £495'
          'Member rate: £495'
          'Members - £525'
          'Non-member £575'
          'Early bird £395'
          'Trainee £200'
        """
        if not text:
            return []
        # Reuse the engage-style regex but slightly more permissive (some sites use 'Early bird')
        pattern = re.compile(
            r"(Non[- ]?members?|Members?|Early\s+bird|Standard|Trainees?|Students?|Group)\b"
            r"(?:\s+rate)?\s*[-:]?\s*£\s*([0-9]+(?:\.[0-9]+)?)",
            re.I,
        )
        seen = set()
        tiers: List[Dict[str, Any]] = []
        for m in pattern.finditer(text):
            raw_label = m.group(1).strip()
            price = float(m.group(2))
            label = RCGPExtractor._normalise_tier_label(raw_label)
            key = (label, price)
            if key in seen:
                continue
            seen.add(key)
            tiers.append({
                "tier_label": label,
                "price_gbp": price,
                "is_early_bird": "early" in raw_label.lower(),
                "early_bird_deadline": None,
            })
        return tiers

    @staticmethod
    def _parse_date_range_from_text(text: str) -> Optional[tuple[Optional[str], Optional[str]]]:
        """Find '29-30 October 2026' or '5-6 March 2026' style date ranges."""
        if not text:
            return None
        # "DD-DD Month YYYY" or "DD – DD Month YYYY"
        # Note: no leading \b — textContent can concatenate adjacent elements with
        # no whitespace ("dates29-30 October 2026"), and \b between letter↔digit
        # word chars would never match in that case.
        m = re.search(
            r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
            text,
        )
        if not m:
            return None
        months = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
                  "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
        mon = months.get(m.group(3).lower()[:3])
        if not mon:
            return None
        d1, d2, year = int(m.group(1)), int(m.group(2)), int(m.group(4))
        try:
            return (f"{year:04d}-{mon:02d}-{d1:02d}",
                    f"{year:04d}-{mon:02d}-{d2:02d}")
        except ValueError:
            return None

    def _extract_soft_fields_rcgpac_multi(
        self,
        combined_text: str,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        """LLM call for description + specialty using the combined multi-page text."""
        # Truncate to a reasonable size for the prompt — combined text can be 30K+ chars
        text_for_llm = combined_text[:6000]

        prompt = f"""You are summarising a multi-page medical conference website.

EVENT TITLE: {shell.get('title')}

CONTENT FROM SEVERAL PAGES OF THE CONFERENCE WEBSITE:
{text_for_llm}

Respond with valid JSON only:
{{
  "description": "30-50 word summary built only from the page text above" or null,
  "specialty": "General Practice"
}}"""
        raw = llm_call(prompt)
        if not raw:
            return {"specialty": "General Practice"}
        parsed = self._parse_soft_json(raw)
        if not parsed.get("specialty"):
            parsed["specialty"] = "General Practice"
        return parsed

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
