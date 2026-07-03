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
import html as _html
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

# Junk external hosts to never follow (site dev credits, social, etc)
JUNK_EXTERNAL_HOSTS = (
    "rouge-media.com", "facebook.com", "twitter.com", "x.com",
    "linkedin.com", "youtube.com", "instagram.com", "tiktok.com",
    "google.com", "doubleclick.net", "googletagmanager.com",
    "wordpress.com", "wp.org", "wpengine.com", "cloudflare.com",
    "addthis.com", "sharethis.com",
)

# Link text keywords that suggest "the real event page is here"
EXTERNAL_FOLLOW_TEXT_RE = re.compile(
    r"(register|book\s+now|book\s+here|more\s+info|find\s+out\s+more|"
    r"learn\s+more|view\s+course|course\s+(?:details?|page)|module\s+details?|"
    r"official(?:\s+(?:website|page))?|programme\s+(?:details?|page)|"
    r"event\s+(?:page|website)|conference\s+website|"
    r"visit\s+(?:the\s+)?(?:event|conference)|hosted\s+by)",
    re.I,
)


def find_external_event_links(
    html: str, base_url: str, limit: int = 3,
) -> list[tuple[str, str]]:
    """External (cross-domain) anchors whose link TEXT suggests they lead
    to the official event page. Returns (url, link_text) tuples.

    Used as a Tier 3 fallback when same-domain exploration found no fees
    (typical for aggregator sites that list 3rd-party events and link
    out to the actual course host for details — e.g. BOPA listing a
    Royal Marsden module). Caller MUST still apply identity-token +
    LLM event-match gates before extracting from these pages.
    """
    host = urlparse(base_url).netloc.lower()
    candidates: list[tuple[str, str]] = []
    seen: set = set()
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{1,120})</a>', html):
        href = m.group(1).strip()
        text = re.sub(r"\s+", " ", m.group(2)).strip()
        if not href or not text or href.startswith("#") or href.startswith("javascript:"):
            continue
        if not href.startswith("http"):
            continue
        parsed = urlparse(href)
        if not parsed.netloc:
            continue
        ext_host = parsed.netloc.lower()
        # Skip same-domain (handled by find_same_domain_anchors)
        if ext_host == host or ext_host.endswith("." + host) or host.endswith("." + ext_host):
            continue
        # Skip junk hosts
        if any(j in ext_host for j in JUNK_EXTERNAL_HOSTS):
            continue
        # Link text must look like an "official event page" pointer
        if not EXTERNAL_FOLLOW_TEXT_RE.search(text):
            continue
        clean = href.split("#")[0]
        if clean in seen:
            continue
        seen.add(clean)
        candidates.append((clean, text[:80]))
        if len(candidates) >= limit:
            break
    return candidates


def find_same_domain_anchors(html: str, base_url: str, limit: int = 25) -> list[str]:
    """Extract candidate same-domain URLs from HTML that LOOK relevant.

    Two passes:
      1. Direct keyword match: fee/abstract/programme/registration/cost
      2. Conference-subsite shapes: "latest-conference", "annual",
         "conference-YYYY" — these often host year-specific event sub-sites
         with rich fee + abstract content (e.g. BOPA's /latest-conference-2026/).
    """
    host = urlparse(base_url).netloc.lower()
    keywords_rx = re.compile(
        r"(fees?|tickets?|abstract|programme|agenda|registration|prices?|cost|"
        r"submission|booking|cpd|latest[-/]conference|annual[-/]conference|"
        r"conference[-/]\d{4}|symposium[-/]\d{4}|congress[-/]\d{4}|"
        r"\d{4}[-/]conference|"
        r"-latest|/latest|annual|summit)",
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


def llm_classify_anchors(
    *, html: str, base_url: str, field: str,
    event_title: str, llm_call: Callable[[str], Optional[str]],
    limit: int = 10,
) -> list[str]:
    """Safety-net anchor discovery for unusual URL shapes. Ask the LLM to
    pick same-domain anchors most likely to host {field} content,
    including link TEXT (e.g. "Latest Conference 2026" → /latest-conference-2026/).
    Returns absolute URLs."""
    host = urlparse(base_url).netloc.lower()
    anchors: list[tuple[str, str]] = []
    seen: set = set()
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{1,120})</a>', html):
        href = m.group(1).strip()
        text = re.sub(r"\s+", " ", m.group(2)).strip()
        if not href or not text or href.startswith("#") or href.startswith("javascript:"):
            continue
        try:
            absolute = urljoin(base_url, href)
        except Exception:
            continue
        parsed = urlparse(absolute)
        if parsed.netloc and parsed.netloc.lower() != host:
            continue
        clean = absolute.split("#")[0].split("?")[0]
        if clean in seen or clean == base_url:
            continue
        seen.add(clean)
        anchors.append((clean, text[:80]))
        if len(anchors) >= 80:
            break
    if not anchors:
        return []
    lines = "\n".join(f"{u}  ←  {t}" for u, t in anchors[:80])
    prompt = (
        f"You're locating {field} information for a medical event titled "
        f"\"{event_title}\". From these same-domain links, pick AT MOST {limit} "
        f"URLs most likely to contain {field} (e.g. registration fees, abstract "
        f"deadlines). Reply with one URL per line, no commentary.\n\n{lines}"
    )
    raw = llm_call(prompt)
    if not raw:
        return []
    chosen: list[str] = []
    for line in raw.splitlines():
        url = line.strip().split()[0] if line.strip() else ""
        if url.startswith("http") and url in seen:
            chosen.append(url)
        if len(chosen) >= limit:
            break
    return chosen


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


EXPLORER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)


def fetch_page_text_and_html(url: str, *, timeout: float = 25.0) -> tuple[Optional[str], Optional[str]]:
    """Return (text_only, raw_html) — text stripped of tags, html for anchor scanning."""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": EXPLORER_UA, "Accept": "text/html,application/xhtml+xml"}) as c:
            r = c.get(url)
            r.raise_for_status()
            html = r.text
            # Order matters: unescape BEFORE whitespace normalization so
            # &nbsp;/&pound; entities become \xa0/£ and \s+ can collapse
            # \xa0 into normal spaces. Doing whitespace normalize first
            # would leave \xa0 embedded and break downstream regex.
            text = re.sub(r"<[^>]+>", " ", html)
            text = _html.unescape(text)
            text = re.sub(r"\s+", " ", text).strip()
            # Cap at 200k — matches the fetcher's cap. 25k truncation
            # broke abstract detection on BTOG (content at offset 148k).
            return text[:200000], html
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
        # Walk homepage too — many sites put fees on a dedicated sub-site
        # (e.g. /latest-conference-2026/) that isn't linked from the
        # individual event page but IS on the homepage.
        try:
            home_url = f"https://{host}/"
            _, home_html = fetch_page_text_and_html(home_url)
            if home_html:
                home_anchors = find_same_domain_anchors(home_html, home_url, limit=10)
                anchors.extend(home_anchors)
        except Exception:
            pass
        # If keyword filter found very few anchors, ask LLM to classify
        if len(anchors) < 3:
            try:
                llm_anchors = llm_classify_anchors(
                    html=page_html, base_url=base_url, field="registration fees",
                    event_title=row.get("conference_name") or "",
                    llm_call=llm_call, limit=6,
                )
                anchors.extend(llm_anchors)
                trail.notes.append(f"llm_classified_anchors: {len(llm_anchors)}")
            except Exception as e:
                trail.notes.append(f"llm_classify_failed: {e}")
        # Also try common suffixes off the base URL
        seed = base_url.split("?")[0].rstrip("/")
        for suffix in COMMON_SUBPAGE_SUFFIXES[:6]:
            anchors.append(seed + suffix)
        # CRITICAL: gate to verify any sub-page is actually about THIS event
        # before extracting pricing. Prevents cross-contamination across
        # events on the same domain (e.g. a Geriatric Oncology module
        # accidentally getting fees from a different /latest-conference-2026/
        # sub-site that happens to contain the words "oncology" and "royal").
        event_name = (row.get("conference_name") or "").lower()
        STOPWORDS = {
            "the","a","an","of","and","or","to","for","in","on","at","with",
            "by","from","as","is","are","be","this","that","these","those",
            "course","event","conference","training","module","webinar",
            "study","day","programme","program","update","session","online",
            "uk","london","england","british","national","royal","royale",
            # Society / topic-wide words — these appear on every page of the
            # domain regardless of which event the page is about
            "oncology","pharmacy","medicine","medical","clinical","health",
            "healthcare","school","hospital","trust","nhs","association",
            "society","college","institute","centre","center","faculty",
            "department","group","network","council","board",
            # Year tokens are too common
            "2024","2025","2026","2027","2028",
        }
        identity_tokens = {
            t for t in re.findall(r"[a-z]{4,}", event_name)
            if t not in STOPWORDS
        }
        if not identity_tokens:
            identity_tokens = {t for t in re.findall(r"[a-z]{3,}", event_name)
                               if t not in STOPWORDS}

        def page_matches_event(sub_text: str, url: str) -> bool:
            """Two-stage match. First check ≥1 distinctive token is present —
            cheap rejection. If at least one matches but it's ambiguous,
            ask the LLM to verify."""
            if not identity_tokens:
                return True
            sub_l = sub_text.lower()
            matched = [t for t in identity_tokens if t in sub_l]
            if not matched:
                trail.notes.append(f"skipped_unrelated_zero_tokens: {url}")
                return False
            # If most identity tokens match, accept without LLM call
            if len(matched) >= max(2, len(identity_tokens) // 2):
                return True
            # Ambiguous: 1 of several tokens matched. Ask the LLM —
            # cheap insurance against cross-event contamination.
            sample = sub_text[:3000]
            prompt = (
                f"You are checking if a web page is about a specific event.\n\n"
                f"EVENT TITLE: {row.get('conference_name')}\n"
                f"EVENT DATE: {row.get('start_date')}\n\n"
                f"Is the page below DESCRIBING that exact event (not a "
                f"different one that shares a domain)? Reply with one word: "
                f"yes or no.\n\n"
                f"PAGE TEXT:\n{sample}"
            )
            raw = llm_call(prompt) or ""
            verdict = raw.strip().lower()[:3]
            ok = verdict.startswith("yes")
            trail.notes.append(
                f"llm_event_match {url}: matched={matched} verdict={verdict!r} ok={ok}"
            )
            return ok

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
            # Event-identity gate — skip if this sub-page isn't about our event
            if not page_matches_event(sub_text, url):
                continue
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

    # Note: We deliberately do NOT run vision LLM on the main event page's
    # images here. Doing so picks up unrelated site-wide promo banners (e.g.
    # an org's flagship-conference reg-fee.jpeg appearing as a "register now"
    # banner on every event detail page). Image-based fees only make sense
    # on DEDICATED event sub-pages (handled by vision_subpage above, where
    # the identity-token gate ensures the sub-page is about THIS event).

    # 3. TIER 3 — External-link follow for aggregator sites
    # If the event page links out to an external "Register" / "More info"
    # page (typical when a society lists 3rd-party events — e.g. BOPA
    # listing a Royal Marsden School module), follow it. Same identity
    # gate applies on the external page text.
    if page_html and identity_tokens:
        externals = find_external_event_links(page_html, base_url, limit=3)
        for ext_url, link_text in externals:
            if ext_url in (trail.subpages_fetched):
                continue
            sub_text, sub_html = fetch_page_text_and_html(ext_url)
            if not sub_text:
                trail.notes.append(f"external_fetch_failed: {ext_url}")
                continue
            trail.subpages_fetched.append(ext_url)
            trail.total_text_chars += len(sub_text)
            trail.notes.append(f"external_followed: {ext_url} (link text: {link_text!r})")
            if not page_matches_event(sub_text, ext_url):
                continue
            # External text regex sweep
            tiers = _text_pricing_sweep(sub_text)
            if tiers:
                trail.llm_reasoning = (
                    f"Followed external link {link_text!r} to {ext_url} "
                    f"(aggregator-style listing). Found prices via text regex."
                )
                trail.notes.append(f"external_text: {len(tiers)} tiers from {ext_url}")
                return ExploreResult(
                    field="pricing", value=tiers,
                    method=f"external_text:{urlparse(ext_url).netloc}",
                    audit_trail=trail, found=True,
                )
            # External page might also have fee images
            if sub_html:
                images = find_money_images(sub_html, ext_url, limit=4)
                if images:
                    try:
                        from vision import extract_pricing_from_images
                        vtiers = extract_pricing_from_images(images)
                        trail.images_ocred += len(images)
                        if vtiers:
                            trail.llm_reasoning = (
                                f"Followed external link {link_text!r} to {ext_url}. "
                                f"Found prices via vision LLM on {len(images)} image(s)."
                            )
                            trail.notes.append(
                                f"external_vision: {len(vtiers)} tiers from {ext_url}"
                            )
                            return ExploreResult(
                                field="pricing", value=vtiers,
                                method=f"external_vision:{urlparse(ext_url).netloc}",
                                audit_trail=trail, found=True,
                            )
                    except Exception as e:
                        trail.notes.append(f"external_vision_failed: {e}")

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
