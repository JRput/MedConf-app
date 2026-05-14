# extractors/fallback.py
"""
Generic LLM-only extractor — used for sources that don't yet have a dedicated
per-source extractor. Mirrors the previous default _extract_detail behaviour.
"""

import json
import re
from typing import Dict, Any, Callable, Optional
from playwright.sync_api import Page

from .base import BaseExtractor
from logger import logger


_MULTIPAGE_ALLOWLIST = ["programme", "ticket", "venue", "location", "abstract",
                       "poster", "overview", "speakers", "registration", "register",
                       "whats-on", "faqs", "agenda", "schedule", "about", "info",
                       "highlights"]
_MULTIPAGE_BLOCKLIST = ["cookie", "privacy", "terms", "accessibility",
                       "sustainability", "sponsor", "exhibit", "phishing",
                       "contact", "press", "media", "policy", "covid"]


class FallbackExtractor(BaseExtractor):

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        # If this source is flagged as multi-page (its "detail page" is a small
        # subsite), walk same-domain sub-pages and concatenate text first.
        if self.source.get("detail_is_multipage"):
            page_text = self._collect_multipage_text(page)[:8000]
        else:
            # Standard single-page text grab (main content area, no nav/footer)
            page_text = page.evaluate("""() => {
                const main = document.querySelector('main, article, [role="main"]') || document.body;
                const clone = main.cloneNode(true);
                clone.querySelectorAll('nav, footer, script, style, noscript, header').forEach(n => n.remove());
                return clone.textContent.replace(/\\s+/g, ' ').trim();
            }""")[:8000]
        current_url = page.url

        prompt = f"""You are extracting structured data from a single medical event detail page.

LISTING-LEVEL DATA (already collected — do NOT re-extract these):
- Title: {shell.get('title')}
- Date: {shell.get('start_date')} {shell.get('start_time') or ''}
- Sold out: {shell.get('is_sold_out')}
- Location hint from listing: {shell.get('location_hint')}

DETAIL PAGE URL: {current_url}

DETAIL PAGE CONTENT:
{page_text}

DATA FIDELITY RULES (highest priority — never violate):
- Extract ONLY values explicitly stated on the detail page above.
- Use null / [] when a field is not on the page. NEVER fabricate or guess.
- Pricing: if no GBP amount (e.g. £150) is shown for this event, "pricing_tiers" MUST be [].
  Marketing copy like "free for members" without a stated tier price is NOT a tier.
- Dates: only use end_date if a multi-day end date is explicitly shown.
- event_format: "online" only if the page says webinar/online/virtual; "in_person" if
  it shows a physical venue and is not described as online; "hybrid" if explicitly hybrid;
  null if unclear.
- cpd_accredited: true ONLY if the page explicitly says CPD-accredited / CPD-approved / shows a CPD points number.

Respond ONLY with valid JSON, no text before or after, no markdown fences:
{{
  "description": "concise ~30-50 word summary built only from page text" | null,
  "specialty": "clinical/topic area (e.g. Dermatology, Minor Surgery, Exam Preparation)" | null,
  "end_date": "YYYY-MM-DD" | null,
  "venue_name": "named venue or building" | null,
  "city": "explicit city or town" | null,
  "region": "UK region if explicitly stated" | null,
  "event_format": "in_person" | "online" | "hybrid" | null,
  "cpd_points": integer | null,
  "cpd_accredited": boolean,
  "abstract_open": boolean,
  "abstract_deadline": "YYYY-MM-DD" | null,
  "pricing_tiers": [{{"tier_label": "Member | Non-member | Trainee | etc", "price_gbp": number}}]
}}"""

        raw = llm_call(prompt)
        if not raw:
            return {}

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
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning(f"FallbackExtractor JSON parse failed: {e}; raw[:200]={raw[:200]!r}")
            return {}

    def _collect_multipage_text(self, page: Page, max_pages: int = 8) -> str:
        """Visit same-domain event-relevant sub-pages, return combined textContent."""
        try:
            start_url = page.url
            buf = [page.evaluate("() => document.body.textContent || ''") or ""]

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
                            if (clean === startPath || seen.has(clean)) return;
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
                {"allowlist": _MULTIPAGE_ALLOWLIST, "blocklist": _MULTIPAGE_BLOCKLIST},
            ) or []

            for url in candidates[:max_pages - 1]:
                try:
                    page.goto(url, wait_until="load", timeout=15000)
                    page.wait_for_timeout(1200)
                    txt = page.evaluate("() => document.body.textContent || ''") or ""
                    if txt.strip():
                        buf.append(txt)
                except Exception as e:
                    logger.warning(f"  multipage sub-page nav failed for {url}: {e}")
                    continue

            try:
                page.goto(start_url, wait_until="load", timeout=15000)
                page.wait_for_timeout(800)
            except Exception:
                pass

            return "\n\n".join(buf)
        except Exception as e:
            logger.warning(f"_collect_multipage_text failed: {e}")
            try:
                return page.evaluate("() => document.body.textContent || ''") or ""
            except Exception:
                return ""
