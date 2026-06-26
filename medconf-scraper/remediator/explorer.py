"""Tier 2 adaptive explorer — exhaustive page exploration when quick fixers
return null.

Mission: never declare "source genuinely missing" without proof. Tier 1
fixers are fast heuristics (regex, known patterns). When they fail, we
escalate here. The explorer:

  1. INVENTORY — enumerate the page surface
       - all tabs found via shadow-DOM walk (already in fetcher)
       - all same-domain anchor links (programme/registration/venue/etc)
       - all images near "fee" / "price" / "£" / "$" / "€" text
  2. WALK every surface — collect tab snapshots, sub-page text, image OCR
  3. EXTRACT — LLM with the full multi-surface context
  4. AUDIT TRAIL — record WHERE we looked so the verdict is provable

The verdict shape:
  {
    "field": "pricing",
    "value": <extracted value> | None,
    "method": "tab:Fees" | "subpage:/fees" | "image_ocr" | "llm_full_context" | "not_found",
    "audit_trail": {
        "tabs_visited": ["Overview","Fees","CPD"],
        "subpages_fetched": ["/fees", "/programme"],
        "images_ocred": 4,
        "total_text_chars": 18432,
        "llm_reasoning": "Found '£190 RCR members' under tab 'Fees' on main page."
    }
  }

A None value with audit_trail = AUDITABLE failure. A future Claude session
can re-verify by walking the same trail.
"""

from __future__ import annotations
import json
import logging
import re
from dataclasses import dataclass, asdict, field
from typing import Any, Callable, Optional
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)


@dataclass
class AuditTrail:
    tabs_visited: list = field(default_factory=list)
    subpages_fetched: list = field(default_factory=list)
    images_ocred: int = 0
    total_text_chars: int = 0
    llm_reasoning: str = ""
    notes: list = field(default_factory=list)


@dataclass
class ExploreResult:
    field: str
    value: Any
    method: str
    audit_trail: AuditTrail
    found: bool

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "value": self.value,
            "method": self.method,
            "found": self.found,
            "audit_trail": asdict(self.audit_trail),
        }


# Sub-pages worth trying for fee/abstract/cpd info, ordered by typical hit rate
COMMON_SUBPAGE_SUFFIXES = (
    "/fees", "/pages/fees", "/fees-and-how-to-book",
    "/tickets", "/registration", "/registration-and-fees",
    "/abstracts", "/pages/abstracts", "/call-for-abstracts",
    "/pages/Late-Abstracts", "/abstract-submission",
    "/programme", "/agenda", "/sessions",
)

# Hosts where sub-page guessing is a waste (Salesforce LWC, plain WordPress events)
SKIP_SUBPAGE_GUESS_DOMAINS = (
    "my.rcr.ac.uk",
    "engage.rcgp.org.uk",
    "rcem.ac.uk",
)


def find_same_domain_anchors(html: str, base_url: str, limit: int = 25) -> list[str]:
    """Extract candidate same-domain URLs from HTML that LOOK relevant
    (contain fee/abstract/programme/registration keywords)."""
    host = urlparse(base_url).netloc.lower()
    keywords_rx = re.compile(
        r"(fees?|tickets?|abstract|programme|agenda|registration|prices?|cost)",
        re.I,
    )
    candidates: list[str] = []
    seen: set = set()
    for m in re.finditer(r'href="([^"]+)"', html):
        href = m.group(1).strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        try:
            absolute = urljoin(base_url, href)
        except Exception:
            continue
        parsed = urlparse(absolute)
        if parsed.netloc and parsed.netloc.lower() != host:
            continue
        clean = absolute.split("#")[0].split("?")[0]
        if clean in seen:
            continue
        if not keywords_rx.search(clean):
            continue
        seen.add(clean)
        candidates.append(clean)
        if len(candidates) >= limit:
            break
    return candidates


def find_money_images(html: str, base_url: str, limit: int = 8) -> list[str]:
    """Find <img> URLs near money/fee text. Returns absolute URLs."""
    from urllib.parse import urljoin
    urls: list[str] = []
    seen: set = set()
    for m in re.finditer(r'<img[^>]*src=["\']([^"\']+)["\']', html, re.I):
        src = m.group(1).strip()
        if src.startswith("//"):
            src = "https:" + src
        elif not src.lower().startswith("http"):
            src = urljoin(base_url, src)
        sl = src.lower()
        if any(k in sl for k in ("logo", "/brand/", "icon", "favicon", ".svg")):
            continue
        if src in seen:
            continue
        seen.add(src)
        urls.append(src)
        if len(urls) >= limit:
            break
    return urls


def fetch_page_text_and_html(url: str, *, timeout: float = 25.0) -> tuple[Optional[str], Optional[str]]:
    """Return (text_only, raw_html) — text stripped of tags, html for anchor scanning."""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (MedConf explorer)"}) as c:
            r = c.get(url)
            r.raise_for_status()
            html = r.text
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:25000], html
    except Exception as e:
        logger.warning(f"explorer: fetch failed for {url}: {e}")
        return None, None


def explore_for_pricing(
    *,
    row: dict,
    page_text: str,
    page_html: Optional[str],
    base_url: str,
    llm_call: Callable[[str], Optional[str]],
) -> ExploreResult:
    """Pricing-specific exploration. Returns ExploreResult."""
    trail = AuditTrail()
    trail.total_text_chars = len(page_text or "")
    accumulated_text = page_text or ""
    accumulated_tiers: list = []

    # 1. Inventory: tabs already in page_text (fetcher expanded them).
    # If text contains £/$/€, try regex sweep first
    from .fixers.pricing import _text_pricing_sweep
    tiers = _text_pricing_sweep(page_text or "")
    if tiers:
        trail.llm_reasoning = "Found prices via text regex sweep on main page (tabs already expanded by fetcher)."
        trail.notes.append(f"regex_sweep_main: {len(tiers)} tiers")
        return ExploreResult(
            field="pricing", value=tiers, method="tab_text_regex",
            audit_trail=trail, found=True,
        )

    # 2. Walk same-domain sub-pages if HTML available
    parsed = urlparse(base_url)
    host = parsed.netloc.lower()
    if page_html and not any(d in host for d in SKIP_SUBPAGE_GUESS_DOMAINS):
        # Discover relevant sub-pages via anchor scanning (smarter than fixed guesses)
        anchors = find_same_domain_anchors(page_html, base_url, limit=15)
        # Also try common suffixes off the base URL
        seed = base_url.split("?")[0].rstrip("/")
        for suffix in COMMON_SUBPAGE_SUFFIXES[:6]:
            anchors.append(seed + suffix)
        seen: set = set()
        for url in anchors:
            if url in seen or url == base_url:
                continue
            seen.add(url)
            sub_text, sub_html = fetch_page_text_and_html(url)
            if not sub_text:
                continue
            trail.subpages_fetched.append(url)
            trail.total_text_chars += len(sub_text)
            tiers = _text_pricing_sweep(sub_text)
            if tiers:
                trail.llm_reasoning = f"Found prices on sub-page {url} via text regex sweep."
                trail.notes.append(f"regex_sweep_subpage: {len(tiers)} tiers from {url}")
                return ExploreResult(
                    field="pricing", value=tiers, method=f"subpage_text:{urlparse(url).path}",
                    audit_trail=trail, found=True,
                )
            # No text prices — collect fee images
            if sub_html:
                images = find_money_images(sub_html, url, limit=6)
                if images:
                    try:
                        from vision import extract_pricing_from_images
                        vtiers = extract_pricing_from_images(images)
                        trail.images_ocred += len(images)
                        if vtiers:
                            trail.llm_reasoning = f"Found prices via vision LLM on {len(images)} image(s) at {url}."
                            trail.notes.append(f"vision_subpage: {len(vtiers)} tiers from {url}")
                            return ExploreResult(
                                field="pricing", value=vtiers, method=f"vision_subpage:{urlparse(url).path}",
                                audit_trail=trail, found=True,
                            )
                    except Exception as e:
                        trail.notes.append(f"vision_failed_on_{url}: {e}")

    # 3. Try vision LLM on images on the main page
    if page_html:
        images = find_money_images(page_html, base_url, limit=6)
        if images:
            try:
                from vision import extract_pricing_from_images
                vtiers = extract_pricing_from_images(images)
                trail.images_ocred += len(images)
                if vtiers:
                    trail.llm_reasoning = f"Found prices via vision LLM on {len(images)} main-page image(s)."
                    trail.notes.append(f"vision_main: {len(vtiers)} tiers")
                    return ExploreResult(
                        field="pricing", value=vtiers, method="vision_main",
                        audit_trail=trail, found=True,
                    )
            except Exception as e:
                trail.notes.append(f"vision_main_failed: {e}")

    # 4. LLM with full context: ask if anywhere we've collected mentions money
    title = row.get("conference_name") or ""
    context = accumulated_text[:8000]
    if not context:
        trail.llm_reasoning = "No page text available."
        return ExploreResult(
            field="pricing", value=None, method="not_found",
            audit_trail=trail, found=False,
        )
    prompt = f"""You are looking for REGISTRATION FEES for a medical event.

EVENT: {title}

I have searched the main event page (with all tabs expanded) and {len(trail.subpages_fetched)} sub-page(s). The accumulated text follows.

If there is ANY registration-fee information (member rates, non-member rates, day passes, etc), extract it as JSON:
{{"tiers": [{{"tier_label": "...", "price": <number>, "currency": "GBP|USD|EUR", "is_early_bird": false, "early_bird_deadline": null}}, ...], "reasoning": "where you found it"}}

If you genuinely see NO fee information anywhere, respond with:
{{"tiers": [], "reasoning": "what you DID see — be specific about what sections were present (e.g. 'page has Overview, Programme, Speakers tabs but no Fees section')"}}

Do not invent prices. If a price is approximate or ranged, capture both bounds.

PAGE TEXT:
{context}
"""
    raw = llm_call(prompt)
    if not raw:
        trail.llm_reasoning = "LLM call failed (rate limit or 5xx)."
        return ExploreResult(
            field="pricing", value=None, method="not_found",
            audit_trail=trail, found=False,
        )
    try:
        # Strip code fences
        s = raw.strip()
        if s.startswith("```"):
            parts = s.split("```")
            if len(parts) >= 3:
                s = parts[1]
                if s.startswith("json"):
                    s = s[4:]
                s = s.strip()
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if m:
            s = m.group(0)
        parsed = json.loads(s)
    except Exception as e:
        trail.llm_reasoning = f"LLM JSON parse failed: {e}"
        return ExploreResult(
            field="pricing", value=None, method="not_found",
            audit_trail=trail, found=False,
        )
    trail.llm_reasoning = parsed.get("reasoning", "")[:300]
    parsed_tiers = parsed.get("tiers", [])
    if not parsed_tiers:
        return ExploreResult(
            field="pricing", value=None, method="not_found",
            audit_trail=trail, found=False,
        )
    # Convert LLM tiers to our schema
    out_tiers: list = []
    for t in parsed_tiers:
        try:
            price = float(t.get("price"))
        except (TypeError, ValueError):
            continue
        label = str(t.get("tier_label", "")).strip()[:200]
        if not label or price <= 0:
            continue
        out_tiers.append({
            "tier_label": label,
            "price_gbp": price,
            "currency": str(t.get("currency", "GBP")).upper()[:3],
            "is_early_bird": bool(t.get("is_early_bird")),
            "early_bird_deadline": t.get("early_bird_deadline"),
        })
    if not out_tiers:
        return ExploreResult(
            field="pricing", value=None, method="not_found",
            audit_trail=trail, found=False,
        )
    return ExploreResult(
        field="pricing", value=out_tiers, method="llm_full_context",
        audit_trail=trail, found=True,
    )


def explore_for_abstract_status(
    *,
    row: dict,
    page_text: str,
    page_html: Optional[str],
    base_url: str,
    llm_call: Callable[[str], Optional[str]],
) -> ExploreResult:
    """Abstract-specific exploration. Same pattern: heuristics first, then
    sub-page walk, then LLM with full context."""
    trail = AuditTrail()
    trail.total_text_chars = len(page_text or "")
    from .fixers.abstract import fix_abstract_status

    # 1. Standard fixer on the main page
    val, method = fix_abstract_status(row, page_text or "", llm_call)
    if val:
        trail.llm_reasoning = f"Main-page abstract fixer succeeded via {method}."
        trail.notes.append(f"main_fixer: {method}")
        return ExploreResult(
            field="abstract_status", value=val, method=f"main:{method}",
            audit_trail=trail, found=True,
        )

    # 2. Walk same-domain sub-pages
    parsed = urlparse(base_url)
    host = parsed.netloc.lower()
    if page_html and not any(d in host for d in SKIP_SUBPAGE_GUESS_DOMAINS):
        anchors = find_same_domain_anchors(page_html, base_url, limit=15)
        seed = base_url.split("?")[0].rstrip("/")
        for suffix in ("/abstracts", "/pages/abstracts", "/call-for-abstracts",
                       "/pages/Late-Abstracts", "/abstract-submission",
                       "/abstract-info"):
            anchors.append(seed + suffix)
        seen: set = set()
        for url in anchors:
            if url in seen or url == base_url:
                continue
            seen.add(url)
            sub_text, _ = fetch_page_text_and_html(url)
            if not sub_text:
                continue
            trail.subpages_fetched.append(url)
            trail.total_text_chars += len(sub_text)
            if "abstract" not in sub_text.lower():
                continue
            val, method = fix_abstract_status(row, sub_text, llm_call)
            if val:
                trail.llm_reasoning = f"Sub-page abstract fixer succeeded at {url} via {method}."
                trail.notes.append(f"subpage_fixer: {url} → {method}")
                return ExploreResult(
                    field="abstract_status", value=val,
                    method=f"subpage:{urlparse(url).path}", audit_trail=trail, found=True,
                )

    # 3. LLM with full context for explicit-closed wording
    title = row.get("conference_name") or ""
    context = (page_text or "")[:8000]
    if "abstract" not in context.lower():
        trail.llm_reasoning = "No 'abstract' mention in fetched text — likely no abstract programme."
        # Confidently set closed
        return ExploreResult(
            field="abstract_status", value={"abstract_open": False},
            method="no_abstract_anywhere", audit_trail=trail, found=True,
        )

    prompt = f"""You are looking for abstract-submission status for a medical conference.

EVENT: {title}

Read the page text. Determine:
- Is there an abstract submission programme at all?
- If yes: are submissions OPEN or CLOSED right now?
- If OPEN: what is the deadline date? (Format YYYY-MM-DD)

Reply ONLY with JSON:
{{"status": "open" | "closed" | "no_programme", "deadline": "YYYY-MM-DD" | null, "reasoning": "where you found it"}}

PAGE TEXT:
{context}
"""
    raw = llm_call(prompt)
    if not raw:
        trail.llm_reasoning = "LLM call failed."
        return ExploreResult(
            field="abstract_status", value=None, method="not_found",
            audit_trail=trail, found=False,
        )
    try:
        s = raw.strip()
        if s.startswith("```"):
            parts = s.split("```")
            if len(parts) >= 3:
                s = parts[1].lstrip("json").strip()
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if m:
            s = m.group(0)
        parsed = json.loads(s)
    except Exception as e:
        trail.llm_reasoning = f"LLM parse failed: {e}"
        return ExploreResult(
            field="abstract_status", value=None, method="not_found",
            audit_trail=trail, found=False,
        )
    trail.llm_reasoning = parsed.get("reasoning", "")[:300]
    status = parsed.get("status", "")
    deadline = parsed.get("deadline")
    if status == "no_programme":
        return ExploreResult(
            field="abstract_status", value={"abstract_open": False},
            method="llm_no_programme", audit_trail=trail, found=True,
        )
    if status == "closed":
        result = {"abstract_open": False}
        if deadline and re.match(r"^\d{4}-\d{2}-\d{2}$", deadline):
            result["abstract_deadline"] = deadline
        return ExploreResult(
            field="abstract_status", value=result,
            method="llm_closed", audit_trail=trail, found=True,
        )
    if status == "open":
        result = {"abstract_open": True}
        if deadline and re.match(r"^\d{4}-\d{2}-\d{2}$", deadline):
            from datetime import date
            if deadline < date.today().isoformat():
                result["abstract_open"] = False
            result["abstract_deadline"] = deadline
        else:
            result["abstract_deadline_note"] = "see event page for details"
        return ExploreResult(
            field="abstract_status", value=result,
            method="llm_open", audit_trail=trail, found=True,
        )
    return ExploreResult(
        field="abstract_status", value=None, method="not_found",
        audit_trail=trail, found=False,
    )


EXPLORERS = {
    "pricing": explore_for_pricing,
    "abstract_status": explore_for_abstract_status,
}
