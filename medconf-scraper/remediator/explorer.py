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
import os
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
    image_selections: list = field(default_factory=list)  # {src, rule(s), size} per image sent to vision
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
    # Tier 3: external page the value was found on (organiser/booking URL patch)
    external_url: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "value": self.value,
            "method": self.method,
            "found": self.found,
            "external_url": self.external_url,
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
    r"visit\s+(?:the\s+)?(?:event|conference)|hosted\s+by|"
    r"book\s+(?:online|event|tickets?|your|a\s+place|your\s+place)|"
    r"(?:further|full|more)\s+(?:details|information)|buy\s+tickets?|get\s+tickets?|"
    r"tickets?\s+(?:here|available)|reserve\s+(?:a\s+)?(?:place|seat))",
    re.I,
)
# Hosts whose anchors are event-registration links even with generic text.
TICKETING_HOST_RE = re.compile(
    r"(eventbrite|cvent|eventsair|regonline|ticketsource|oxfordabstracts|"
    r"ticketlight|tickettailor|eventzilla|bookwhen|gotowebinar|zoom\.us/webinar|"
    r"onlineregistrationform|congressbooking|conferencecare|cmevents)", re.I)


# Generic anchor text ("here", "this link", a bare URL...) that says nothing
# on its own; only followed when the SURROUNDING sentence is about
# registration / fees / the organiser (BSH: "Further details and
# registration can be found <a>here</a>").
GENERIC_ANCHOR_RE = re.compile(
    r"^\s*(?:click\s+)?(?:here|this\s+(?:link|page|website|site)|"
    r"(?:the\s+)?(?:event\s+|conference\s+|organiser'?s?\s+)?(?:website|web\s*page|page|site|link)|"
    r"(?:visit\s+)?(?:the\s+)?website|link|read\s+more|visit|"
    r"(?:https?://|www\.)\S+|[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:/\S*)?)\s*[.:>»]*\s*$",
    re.I,
)
EXTERNAL_CONTEXT_RE = re.compile(
    r"(register|registration|book|booking|fees?|prices?|cost|tickets?|programme|"
    r"further\s+details|more\s+information|organis(?:ed|er)|hosted\s+by)",
    re.I,
)
_CHROME_BLOCK_RE = re.compile(
    r"<(nav|header|footer|aside|script|style)\b.*?</\1\s*>", re.I | re.S,
)
_ANCHOR_RE = re.compile(r"""<a\b[^>]*?href=["']([^"']+)["'][^>]*>(.{0,400}?)</a>""", re.I | re.S)
_CONTEXT_CHARS = 200
_MARK = "\x00LINK\x00"


def _anchor_context(html: str, start: int, end: int) -> str:
    """Tag-stripped text within +-_CONTEXT_CHARS of the anchor at html[start:end]."""
    window = html[max(0, start - 800): end + 800]
    rel = start - max(0, start - 800)
    window = window[:rel] + _MARK + window[rel + (end - start):]
    # Block-level tags are hard boundaries: context stays inside the same
    # paragraph / list item / cell as the anchor.
    window = re.sub(r"</?(?:p|li|ul|ol|div|br|h[1-6]|tr|td|th|section|article)\b[^>]*>",
                    "\x01", window, flags=re.I)
    text = _html.unescape(re.sub(r"<[^>]+>", " ", window))
    text = re.sub(r"[ \t\r\n]+", " ", text)
    i = text.find(_MARK)
    if i < 0:
        return ""
    before = text[max(0, i - _CONTEXT_CHARS): i].split("\x01")[-1]
    after = text[i + len(_MARK): i + len(_MARK) + _CONTEXT_CHARS].split("\x01")[0]
    return before + " " + after


def find_external_event_links(
    html: str, base_url: str, limit: int = 4,
) -> list[tuple[str, str]]:
    """External (cross-domain) anchors that probably lead to the official
    event page. Returns (url, link_text) tuples, best first.

    Two ways to qualify:
      1. The anchor TEXT matches EXTERNAL_FOLLOW_TEXT_RE (register, more info...)
         -- highest priority.
      2. The anchor text is generic ("here", "this link", a bare URL, the
         external domain) AND the surrounding +-200 chars mention
         registration / fees / organiser -- lower priority. Anchors inside
         nav/header/footer/aside blocks are ignored for this rule.

    Used as a Tier 3 fallback when same-domain exploration found no fees
    (aggregator sites linking out to the real host, e.g. BOPA -> Royal
    Marsden, BSH -> RCPSG). Caller MUST still apply identity-token +
    LLM event-match gates before extracting from these pages.
    """
    host = urlparse(base_url).netloc.lower()
    # Spans of site chrome: generic anchors inside them never qualify.
    chrome_spans = [(m.start(), m.end()) for m in _CHROME_BLOCK_RE.finditer(html)]

    def in_chrome(pos: int) -> bool:
        return any(a <= pos < b for a, b in chrome_spans)

    explicit: list[tuple[str, str]] = []
    contextual: list[tuple[str, str]] = []
    seen: set = set()
    for m in _ANCHOR_RE.finditer(html):
        href = m.group(1).strip()
        text = _html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))
        text = re.sub(r"\s+", " ", text).strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        href = _html.unescape(href)
        if href.startswith("//"):
            href = "https:" + href
        if not href.startswith("http"):
            continue
        parsed = urlparse(href)
        # Image-only buttons have no text: only a ticketing-platform host
        # makes them worth following.
        if not text and not TICKETING_HOST_RE.search(parsed.netloc or ""):
            continue
        if not parsed.netloc:
            continue
        ext_host = parsed.netloc.lower()
        # Skip same-domain (handled by find_same_domain_anchors)
        if ext_host == host or ext_host.endswith("." + host) or host.endswith("." + ext_host):
            continue
        # Skip junk hosts
        if any(j in ext_host for j in JUNK_EXTERNAL_HOSTS):
            continue
        clean = href.split("#")[0]
        if clean in seen:
            continue
        if EXTERNAL_FOLLOW_TEXT_RE.search(text) or (
                TICKETING_HOST_RE.search(ext_host) and not in_chrome(m.start())):
            seen.add(clean)
            explicit.append((clean, text[:80]))
        elif (GENERIC_ANCHOR_RE.match(text) or ext_host.replace("www.", "") in text.lower()):
            if in_chrome(m.start()):
                continue
            ctx = _anchor_context(html, m.start(), m.end())
            if EXTERNAL_CONTEXT_RE.search(ctx):
                seen.add(clean)
                contextual.append((clean, text[:80]))
    return (explicit + contextual)[:limit]


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


_REG_LINK_RE = re.compile(
    r"\b(?:registration|register|fees?|pricing|prices?|rates?|tickets?|book(?:ing)?|"
    r"how\s+to\s+(?:book|register))\b", re.I)
_REG_LINK_NEG_RE = re.compile(r"newsletter|subscribe|unsubscribe|log\s?in|sign\s?in|privacy|cookie", re.I)


def find_registration_links(html: str, base_url: str, limit: int = 3) -> list[tuple[str, str]]:
    """Same-host links whose anchor text OR href says registration/fees/
    pricing/tickets/booking, nav links included (flagship microsites keep
    "Registration" in the nav). Returns [(absolute_url, link_text)], deduped,
    capped. Other-host links are never returned (external follow is a
    separate, identity-gated tier)."""
    host = urlparse(base_url).netloc.lower().removeprefix("www.")
    self_url = base_url.split("#")[0].split("?")[0].rstrip("/")
    out: list[tuple[str, str]] = []
    seen: set = set()
    for m in re.finditer(r'<a\b[^>]*?href=["\']([^"\']+)["\'][^>]*>(.*?)</a\s*>', html or "", re.I | re.S):
        href = m.group(1).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        text = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        absolute = urljoin(base_url, href)
        pu = urlparse(absolute)
        if pu.scheme not in ("http", "https") or pu.netloc.lower().removeprefix("www.") != host:
            continue
        clean = absolute.split("#")[0].split("?")[0]
        if clean.rstrip("/") == self_url or clean in seen:
            continue
        if _REG_LINK_NEG_RE.search(text) or _REG_LINK_NEG_RE.search(pu.path):
            continue
        if not (_REG_LINK_RE.search(text[:80]) or _REG_LINK_RE.search(pu.path.replace("-", " ").replace("_", " "))):
            continue
        seen.add(clean)
        out.append((clean, text[:60]))
        if len(out) >= limit:
            break
    return out


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


# Per-process budget for vision calls. 2026-09-26: on ACPGBI (no fee tables
# anywhere) the pricing explorer sent every sponsor logo / photo on every
# event page to the vision model — 489 calls in one run, 40+ min, and a
# rate-limit hazard for the nightly --all run. Fee tables are rare images;
# a source that needs more than this per run is being fed the wrong images.
VISION_IMAGE_BUDGET = int(os.environ.get("REMEDIATOR_VISION_BUDGET", "15"))
# Wall-clock cap as well: a hanging vision call costs a full timeout even
# at one attempt, and 2026-09-29/30 showed image count alone doesn't bound
# the run. Once exceeded, no more images are sent this process.
VISION_TIME_BUDGET_S = int(os.environ.get("REMEDIATOR_VISION_TIME_BUDGET_S", "720"))
_vision_images_sent = 0
_vision_seconds = 0.0


def vision_time_left() -> bool:
    return _vision_seconds < VISION_TIME_BUDGET_S


def _note_vision_time(seconds: float) -> None:
    global _vision_seconds
    _vision_seconds += seconds

def find_money_images(html: str, base_url: str, limit: int = 8, *,
                      strict: bool = False, trail: Optional["AuditTrail"] = None) -> list[str]:
    """Find <img> sources that plausibly show a fee table (see
    remediator/image_scan.py for the rules): images under a fee/registration
    heading block, images with money words within ~600 chars, or substantial
    images whose alt/src mention fee|price|rate|regist. `data:image/*;base64,`
    sources pass through unchanged (vision takes data URLs). Images under 120px
    are skipped, larger images come first, and sponsor logos/photos/icons are
    skipped by name. Capped by `limit` and the process-wide vision budgets.
    strict=True keeps only fee-heading images (main event page). The rule that
    selected each image is recorded in `trail.image_selections`."""
    global _vision_images_sent
    from .image_scan import select_fee_images
    remaining = VISION_IMAGE_BUDGET - _vision_images_sent
    if not vision_time_left():
        logger.warning(
            f"vision time budget exhausted ({VISION_TIME_BUDGET_S}s this run) — "
            f"skipping image pricing for {base_url}"
        )
        return []
    if remaining <= 0:
        logger.warning(
            f"vision budget exhausted ({VISION_IMAGE_BUDGET} images this run) — "
            f"skipping image pricing for {base_url}"
        )
        return []
    chosen = select_fee_images(html, base_url, strict=strict)[: min(limit, remaining)]
    for c in chosen:
        info = {"image": c.label(), "page": base_url, "rules": list(c.rules),
                "size": f"{c.width or '?'}x{c.height or '?'}"}
        logger.info(f"explorer: vision candidate {info}")
        if trail is not None:
            trail.image_selections.append(info)
    _vision_images_sent += len(chosen)
    return [c.src for c in chosen]


def usable_vision_tiers(vtiers: list, trail: Optional["AuditTrail"] = None) -> list:
    """Drop vision tiers whose currency could not be determined (null) —
    never guess GBP. Logged and noted on the trail."""
    keep = [t for t in (vtiers or []) if t.get("currency")]
    dropped = len(vtiers or []) - len(keep)
    if dropped:
        msg = f"vision: dropped {dropped} tier(s) with unknown currency (not guessing GBP)"
        logger.warning(msg)
        if trail is not None:
            trail.notes.append(msg)
    return keep


EXPLORER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)


# --- Run-level fetch layer -------------------------------------------------
# Profiling sources 33/37 (2026-10-03): every event re-fetched the site
# homepage and the same handful of "membership / awards / cpd" anchors, plus
# 6 guessed per-event suffixes (almost all 404), with a 25 s timeout each and
# no memory of failures. All fetches now go through one per-process cache
# (successes AND failures), a per-host circuit breaker for hosts that keep
# timing out, and a hard deadline the runner sets for the current source.
FETCH_CACHE: dict = {}
_host_slow_hits: dict = {}
HOST_BREAKER_THRESHOLD = int(os.environ.get("REMEDIATOR_HOST_BREAKER", "3"))
# Max network fetches (cache misses) one explorer call may make.
EXPLORE_MAX_FETCHES = int(os.environ.get("REMEDIATOR_EXPLORE_MAX_FETCHES", "10"))
# Max wall-clock seconds one explorer call may spend.
EXPLORE_MAX_SECONDS = float(os.environ.get("REMEDIATOR_EXPLORE_MAX_SECONDS", "90"))
# Max LLM event-identity checks one explorer call may make. Profiled on
# source 33: 56 of 53+ text calls (81 s of 206 s) were these checks, mostly
# re-judging the same site-wide pages (membership, awards, CPD) per event.
EXPLORE_MAX_LLM_CHECKS = int(os.environ.get("REMEDIATOR_EXPLORE_MAX_LLM_CHECKS", "2"))
# Separate fetch allowance for the external-link tier (page + registration hop).
EXPLORE_EXTERNAL_FETCHES = int(os.environ.get("REMEDIATOR_EXPLORE_EXTERNAL_FETCHES", "5"))
EVENT_MATCH_CACHE: dict = {}
FETCH_TIMEOUT_S = float(os.environ.get("REMEDIATOR_FETCH_TIMEOUT_S", "12"))

_source_deadline: Optional[float] = None  # epoch seconds; None = unlimited
fetch_stats = {"network": 0, "cache_hits": 0, "network_seconds": 0.0, "breaker_skips": 0}


def set_source_deadline(deadline: Optional[float]) -> None:
    """Runner sets this at the start of each source (and clears it after)."""
    global _source_deadline
    _source_deadline = deadline


def get_source_deadline() -> Optional[float]:
    return _source_deadline


def source_time_up() -> bool:
    import time as _t
    return _source_deadline is not None and _t.time() >= _source_deadline


def reset_fetch_state() -> None:
    FETCH_CACHE.clear()
    EVENT_MATCH_CACHE.clear()
    _host_slow_hits.clear()
    for k in fetch_stats:
        fetch_stats[k] = 0 if k != "network_seconds" else 0.0


class ExploreBudget:
    """Per-explorer-call cap on network fetches and wall-clock time."""

    def __init__(self, max_fetches: Optional[int] = None):
        import time as _t
        self._t = _t
        self.started = _t.time()
        self.fetches = 0
        self.llm_checks = 0
        self.max_fetches = EXPLORE_MAX_FETCHES if max_fetches is None else max_fetches

    def exhausted(self) -> bool:
        return (
            source_time_up()
            or self.fetches >= self.max_fetches
            or (self._t.time() - self.started) >= EXPLORE_MAX_SECONDS
        )

    def fetch(self, url: str, **kw) -> tuple[Optional[str], Optional[str]]:
        """Budget-aware fetch. Cache hits are free; misses count."""
        if url in FETCH_CACHE:
            return fetch_page_text_and_html(url, **kw)
        if self.exhausted():
            return None, None
        self.fetches += 1
        return fetch_page_text_and_html(url, **kw)


def fetch_page_text_and_html(url: str, *, timeout: float = FETCH_TIMEOUT_S) -> tuple[Optional[str], Optional[str]]:
    """Return (text_only, raw_html) — text stripped of tags, html for anchor scanning.
    Cached per process (failures included), host-circuit-broken, and
    refused once the source deadline has passed."""
    import time as _t
    if url in FETCH_CACHE:
        fetch_stats["cache_hits"] += 1
        return FETCH_CACHE[url]
    if source_time_up():
        return None, None
    host = urlparse(url).netloc.lower()
    if _host_slow_hits.get(host, 0) >= HOST_BREAKER_THRESHOLD:
        fetch_stats["breaker_skips"] += 1
        return None, None
    t0 = _t.time()
    result: tuple[Optional[str], Optional[str]] = (None, None)
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
            result = (text[:200000], html)
    except httpx.HTTPStatusError as e:
        # A 404/403 is a fast, definitive answer — not a slow host.
        logger.warning(f"explorer: fetch failed for {url}: HTTP {e.response.status_code}")
    except Exception as e:
        # Timeouts / connection errors: these are what burn the clock.
        _host_slow_hits[host] = _host_slow_hits.get(host, 0) + 1
        logger.warning(f"explorer: fetch failed for {url}: {type(e).__name__}")
    fetch_stats["network"] += 1
    fetch_stats["network_seconds"] += _t.time() - t0
    FETCH_CACHE[url] = result
    return result


# --- External-page fee extraction (flat text) -------------------------------
# Fetched text is whitespace-collapsed, so the line-based sweep only sees
# "label-word £N" shapes. External registration pages typically render
# "Medical Students - £10 Nurses - £35 ..." or "Regular $ 799 Price Until ...".
_FLAT_PRICE_RE = re.compile(r"([£$€])\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?")
_FLAT_FEE_CTX_RE = re.compile(
    r"(registration|register|pricing|prices?|fees?|tickets?|delegate|rates?|early\s*bird|book\s+your)", re.I)
_FLAT_LABEL_JUNK_RE = re.compile(
    r"\b(budget|under|over|refund|holding|sponsor\w*|exhibit\w*|donat\w*|up\s+to|"
    r"administrative|charge|deposit|subscription)\b", re.I)
_FLAT_NOISE_RE = re.compile(
    r"(price\s+until\b[^A-Za-z]*(?:[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})?|\bselect\b|\bpay\s+now\b|"
    r"\badd\s+to\s+(?:cart|basket)\b|\bper\s+(?:person|delegate)\b)", re.I)


_FLAT_ROLE_RE = re.compile(
    r"(member|student|delegate|consultant|trainee|nurse|doctor|registrar|fellow|resident|"
    r"early|standard|regular|concession|industry|speaker|listener|visitor|attendee|physician)", re.I)
_PRICE_FIRST_RE = re.compile(r"^\s*[-\u2013\u2014]\s*[A-Za-z]")


def _flat_text_price_sweep(text: str, max_tiers: int = 40) -> list:
    """Tiers from flattened text where each price is preceded by its label
    ("Label - £N", "Label $ N"). Needs >=2 distinct labelled prices and a
    fee-context word shortly before the first one; sponsor budgets, refunds
    and holding fees are rejected. Never guesses a currency: the symbol
    decides (£/$/€)."""
    if not text or len(text) < 20:
        return []
    tiers: list = []
    seen: set = set()
    prev_end = 0
    first_start = None
    for m in _FLAT_PRICE_RE.finditer(text):
        raw = text[max(prev_end, m.start() - 120): m.start()]
        prev_end = m.end()
        label = _FLAT_NOISE_RE.sub(" ", raw)
        # a sentence / heading boundary ends the previous context
        label = re.split(r"[:.!?]\s+|\s{2,}", label)[-1] if re.search(r"[:.!?]\s", label) else label
        # leading deadline dates ("Ends: April 5, 2027 Speaker ...") are not part of the label
        label = re.sub(r"^\W*(?:(?:ends?|until|by|before|from|valid)\b\W*)?(?:[A-Z][a-z]{2,8}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}|\d{1,2}(?:st|nd|rd|th)?\s+[A-Z][a-z]{2,8}\.?,?\s+\d{4})\W*", "", label)
        label = re.sub(r"\s+", " ", label).strip(" -\u2013\u2014:|,/*$\u00a3\u20ac")
        if not re.fullmatch(r"[A-Za-z0-9 ,/&()'\u2019.+\-\u2013]+", label):
            continue  # script/JSON residue, not a fee label
        # leading digits-only/price residue e.g. "- Medic / Nurse" is price-first: skip
        if len(label) < 3 or len(label) > 90 or not re.search(r"[A-Za-z]{3}", label):
            continue
        if _FLAT_LABEL_JUNK_RE.search(label):
            continue
        # "Day pass £20 - Medic / Nurse": the label FOLLOWS the price. Mixed
        # label orders mislabel tiers, so refuse the whole page.
        if (_PRICE_FIRST_RE.match(text[m.end(): m.end() + 6])
                and not re.search(r"[-\u2013\u2014:|]\s*$", raw)):
            return []
        try:
            price = float(m.group(2).replace(",", "") + ("." + m.group(3) if m.group(3) else ""))
        except ValueError:
            continue
        if price <= 0 or price > 50000:
            continue
        if first_start is None:
            first_start = m.start()
        key = (label.lower(), price)
        if key in seen:
            continue
        seen.add(key)
        tiers.append({
            "tier_label": label[:200], "price_gbp": price,
            "currency": {"£": "GBP", "$": "USD", "\u20ac": "EUR"}[m.group(1)],
            "is_early_bird": "early" in label.lower(), "early_bird_deadline": None,
        })
        if len(tiers) > max_tiers:
            return []
    if len(tiers) < 2 or first_start is None:
        return []
    role_hits = sum(1 for t in tiers if _FLAT_ROLE_RE.search(t["tier_label"]))
    if not (_FLAT_FEE_CTX_RE.search(text[max(0, first_start - 1500): first_start + 300]) or role_hits >= 2):
        return []
    return tiers


def _external_page_tiers(text: Optional[str], html: Optional[str],
                         trail: Optional["AuditTrail"] = None) -> tuple[list, str]:
    """Fee tiers from a fetched external/registration page: line sweep, then
    plain fee tables, then the flat-text sweep. Returns (tiers, method)."""
    from .fixers.pricing import _text_pricing_sweep
    t = _text_pricing_sweep(text or "")
    flat = _flat_text_price_sweep(text or "")
    # The inline sweep can glue several prices into one junk label; the
    # flat sweep wins when it recovers more (cleanly labelled) tiers.
    if t and len(flat) <= len(t):
        return t, "text"
    tt = _plain_table_tiers(html, trail)
    if tt:
        return tt, "table"
    if flat:
        return flat, "flat"
    return [], ""


_DATE_FMT = ("%-d %B %Y", "%d %B %Y", "%B %-d", "%-d %B", "%B %-d, %Y", "%-d %b %Y")


def external_identity_ok(row: dict, text: str) -> bool:
    """Loose identity gate for an external page that the event's OWN page
    linked explicitly (the link is the main identity evidence): accept on any
    distinctive title token (>=4 letters, or an acronym/number token such as
    "crsm" / "2026 annual") or on the event start date written out."""
    low = (text or "").lower()
    if not low:
        return False
    title = (row.get("conference_name") or "").lower()
    weak = {"the", "and", "for", "with", "from", "event", "course", "conference", "training",
            "annual", "meeting", "online", "live", "webinar", "series", "international"}
    toks = {t for t in re.findall(r"[a-z0-9]{4,}", title) if t not in weak and not t.isdigit()}
    toks |= {t for t in re.findall(r"\b[a-z]{3}\b", title) if t not in weak and t.isalpha()
             and re.search(rf"\b{t.upper()}\b", row.get("conference_name") or "")}
    if any(t in low for t in toks):
        return True
    sd = (row.get("start_date") or "")[:10]
    if sd:
        try:
            import datetime as _dt
            d = _dt.date.fromisoformat(sd)
            for f in _DATE_FMT:
                try:
                    if d.strftime(f).lower() in low:
                        return True
                except ValueError:
                    pass
        except ValueError:
            pass
    return False


def _plain_table_tiers(html: Optional[str], trail: Optional["AuditTrail"] = None) -> list:
    """Plain-number <table> fee grids (pricing_tables parser). Currency must
    be detected from the table/heading; tiers without one are dropped, never
    defaulted to GBP."""
    if not html:
        return []
    try:
        from extractors.pricing_tables import parse_pricing_tables
        return usable_vision_tiers(parse_pricing_tables(html, default_currency="", max_tiers=40), trail)
    except Exception as e:
        logger.debug(f"explorer: pricing_tables pass failed: {e}")
        return []


PDF_FETCH_TIMEOUT_S = float(os.environ.get("REMEDIATOR_PDF_TIMEOUT_S", "15"))
PDF_MAX_TIERS = 40
_PLAIN_FEE_LINE_RE = re.compile(r"^(?P<label>[A-Za-z][^\d$£€|]{2,100}?)[\s.:|\-]*(?P<price>\d{1,3}(?:[,.]\d{3})+|\d{2,5})(?:[.,]\d{2})?\s*$")
PDF_CACHE: dict = {}


def _fetch_document_text(url: str, trail: "AuditTrail") -> Optional[str]:
    """Download a PDF/DOCX (15 s timeout, 8 MB cap, cached) and return its text."""
    from .pdf_text import document_to_text, PDF_MAX_BYTES
    if url in PDF_CACHE:
        return PDF_CACHE[url]
    text: Optional[str] = None
    try:
        with httpx.Client(timeout=PDF_FETCH_TIMEOUT_S, follow_redirects=True,
                          headers={"User-Agent": EXPLORER_UA}) as c:
            r = c.get(url)
            r.raise_for_status()
            if len(r.content) > PDF_MAX_BYTES:
                trail.notes.append(f"pdf_skipped_too_large: {url}")
            else:
                text = document_to_text(r.content, url)
    except Exception as e:
        trail.notes.append(f"pdf_fetch_failed: {url} ({type(e).__name__})")
    PDF_CACHE[url] = text
    return text


def _tiers_from_document_text(text: str, trail: "AuditTrail") -> list:
    """Run the text sweep and the plain-number parser over extracted document
    text. Every tier needs a label and a detected currency; years/page numbers
    are not prices; capped at PDF_MAX_TIERS."""
    from .fixers.pricing import _text_pricing_sweep
    # "Consultant: £40 + VAT" -> drop the tax/unit suffix so line patterns match.
    text = re.sub(r"(?im)([£$€]\s*[\d,]+(?:\.\d+)?)\s*(?:\+|plus|incl?\.?|excl?\.?|ex\.?)?\s*(?:VAT|GST|tax)\b.*$", r"\1", text)
    tiers = []
    for t in _text_pricing_sweep(text):
        # Inline sweep can span a line break; keep only the label's own line.
        label = (t.get("tier_label") or "").split("\n")[-1].strip()
        if len(re.findall(r"[A-Za-z]", label)) >= 3 and not any(
                x["tier_label"].lower() == label.lower() and x["price_gbp"] == t["price_gbp"] for x in tiers):
            tiers.append({**t, "tier_label": label})
    if not tiers:
        # Plain-number fee lines ("Member  450") -> pseudo table for the
        # shared parser. Needs a currency word/code somewhere in the document.
        from extractors.pricing_tables import _detect_currency, parse_pricing_tables
        currency = _detect_currency(text[:20000], "")
        rows = []
        for line in text.splitlines():
            m = _PLAIN_FEE_LINE_RE.match(line.strip())
            if not m:
                continue
            label, price = m.group("label").strip(" .:|-"), m.group("price")
            if re.fullmatch(r"(19|20)\d\d", price) or len(re.findall(r"[A-Za-z]", label)) < 3:
                continue  # year / page-number-ish
            if re.search(r"(?i)\b(page|tel|phone|fax|postcode|room|floor)\b", label):
                continue
            rows.append(f"<tr><td>{_html.escape(label)}</td><td>{price}</td></tr>")
        if currency and rows:
            tiers = parse_pricing_tables(
                f"<h3>Registration fees {currency}</h3><table>{''.join(rows)}</table>",
                default_currency="", max_tiers=PDF_MAX_TIERS)
    tiers = [t for t in usable_vision_tiers(tiers, trail)
             if (t.get("tier_label") or "").strip() and t.get("price_gbp")]
    return tiers[:PDF_MAX_TIERS]


def _follow_fee_document(html: Optional[str], base_url: str, budget: "ExploreBudget",
                         trail: "AuditTrail"):
    """At most one fee-ish PDF/DOCX per event. Returns (tiers, url, method) or None.
    Records `pdf_followed: <url>` in the trail."""
    if not html or any(str(n).startswith("pdf_followed:") for n in trail.notes):
        return None
    from .pdf_text import find_fee_documents
    for url, _text in find_fee_documents(html, base_url, limit=2):
        if budget.exhausted():
            return None
        budget.fetches += 1
        text = _fetch_document_text(url, trail)
        trail.notes.append(f"pdf_followed: {url}")
        if not text or len(text.strip()) < 40:
            trail.notes.append(f"pdf_no_text_layer (scanned?): {url}")
            continue
        trail.total_text_chars += len(text)
        tiers = _tiers_from_document_text(text, trail)
        if tiers:
            from urllib.parse import unquote
            name = unquote(urlparse(url).path.rsplit("/", 1)[-1])
            trail.notes.append(f"pdf_tiers: {len(tiers)} from {url}")
            return tiers, url, f"pdf:{name}"
        return None  # one document per event
    return None


def _follow_registration_subpages(html: str, base_url: str, budget: "ExploreBudget",
                                  trail: "AuditTrail", limit: int = 2):
    """On an external event site, fetch up to `limit` same-host registration/
    fees links and run the text sweep then the (budgeted) image pass on each.
    Returns (tiers, url, method) or None. Records `external_subpage_followed`."""
    from .fixers.pricing import _text_pricing_sweep as _sweep
    for url, text in find_registration_links(html, base_url, limit=limit):
        if budget.exhausted():
            trail.notes.append("explore_budget_exhausted: stopped external sub-page walk")
            return None
        sub_text, sub_html = budget.fetch(url)
        if not sub_text:
            continue
        trail.subpages_fetched.append(url)
        trail.total_text_chars += len(sub_text)
        trail.notes.append(f"external_subpage_followed: {url} ({text})")
        tiers = _sweep(sub_text)
        if tiers:
            trail.notes.append(f"external_subpage_text: {len(tiers)} tiers from {url}")
            return tiers, url, "text"
        tt = _plain_table_tiers(sub_html, trail)
        if tt:
            trail.notes.append(f"external_subpage_table: {len(tt)} tiers from {url}")
            return tt, url, "table"
        _pdf = _follow_fee_document(sub_html, url, budget, trail)
        if _pdf:
            return _pdf
        if sub_html and vision_time_left() and not source_time_up():
            images = find_money_images(sub_html, url, limit=4, trail=trail)
            if images:
                try:
                    from vision import extract_pricing_from_images
                    import time as _t
                    _t0 = _t.time()
                    vt = usable_vision_tiers(
                        extract_pricing_from_images(images, stop_at=get_source_deadline()), trail)
                    _note_vision_time(_t.time() - _t0)
                    trail.images_ocred += len(images)
                    if vt:
                        trail.notes.append(f"external_subpage_vision: {len(vt)} tiers from {url}")
                        return vt, url, "vision"
                except Exception as e:
                    trail.notes.append(f"external_subpage_vision_failed: {e}")
    return None


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
    budget = ExploreBudget()
    identity_tokens: set = set()  # filled by the sub-page block; Tier 3 must not NameError without it
    external_seen: Optional[str] = None  # last external page fetched (organiser_url retry hint)

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

    # 1b. Main-page fee image: only an image sitting under this page's own
    # fee/registration heading (strict) — not site-wide promo banners.
    if page_html and vision_time_left() and not source_time_up():
        images = find_money_images(page_html, base_url, limit=2, strict=True, trail=trail)
        if images:
            try:
                from vision import extract_pricing_from_images
                import time as _t
                _t0 = _t.time()
                vtiers = usable_vision_tiers(
                    extract_pricing_from_images(images, stop_at=_source_deadline), trail)
                _note_vision_time(_t.time() - _t0)
                trail.images_ocred += len(images)
                if vtiers:
                    trail.llm_reasoning = (
                        f"Found prices via vision LLM on {len(images)} fee-heading image(s) "
                        f"on the main event page.")
                    trail.notes.append(f"vision_main_page: {len(vtiers)} tiers")
                    return ExploreResult(
                        field="pricing", value=vtiers, method="vision_main_page",
                        audit_trail=trail, found=True,
                    )
            except Exception as e:
                trail.notes.append(f"vision_main_page_failed: {e}")

    # 1c. Fee PDF/DOCX linked from the main page.
    _pdf = _follow_fee_document(page_html, base_url, budget, trail)
    if _pdf:
        ptiers, purl, pmethod = _pdf
        trail.llm_reasoning = f"Found prices in linked fee document {purl}."
        return ExploreResult(field="pricing", value=ptiers, method=pmethod,
                             audit_trail=trail, found=True, external_url=purl)

    # 2. Walk same-domain sub-pages if HTML available
    parsed = urlparse(base_url)
    host = parsed.netloc.lower()
    if page_html and not any(d in host for d in SKIP_SUBPAGE_GUESS_DOMAINS):
        # Discover relevant sub-pages via anchor scanning (smarter than fixed guesses)
        # Explicit registration/fees links on the page (nav included) go
        # BEFORE any guessed suffix or loosely-matched anchor.
        reg_links = find_registration_links(page_html, base_url, limit=3)
        reg_link_text = {u: t for u, t in reg_links}
        anchors = [u for u, _ in reg_links] + find_same_domain_anchors(page_html, base_url, limit=15)
        # Walk homepage too — many sites put fees on a dedicated sub-site
        # (e.g. /latest-conference-2026/) that isn't linked from the
        # individual event page but IS on the homepage.
        try:
            home_url = f"https://{host}/"
            _, home_html = budget.fetch(home_url)
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
        # Guessed suffixes are the lowest-value candidates (many CMSs answer 200
        # for any path, each then costing a vision call). When the page links
        # out explicitly (register / book online / ticketing host) the Tier 3
        # external follow is the better use of the budget, so skip the guesses.
        _has_explicit_external = bool(find_external_event_links(page_html, base_url, limit=1))
        seed = base_url.split("?")[0].rstrip("/")
        for suffix in ([] if _has_explicit_external else COMMON_SUBPAGE_SUFFIXES[:6]):
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
            cache_key = (url, frozenset(matched))
            if cache_key in EVENT_MATCH_CACHE:
                return EVENT_MATCH_CACHE[cache_key]
            if budget.llm_checks >= EXPLORE_MAX_LLM_CHECKS or source_time_up():
                trail.notes.append(f"llm_event_match_skipped (cap) {url}: treated as no match")
                return False
            budget.llm_checks += 1
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
            if raw:  # don't cache LLM outages as "no"
                EVENT_MATCH_CACHE[cache_key] = ok
            return ok

        seen: set = set()
        for url in anchors:
            if url in seen or url == base_url:
                continue
            seen.add(url)
            if budget.exhausted():
                trail.notes.append("explore_budget_exhausted: stopped sub-page walk")
                break
            sub_text, sub_html = budget.fetch(url)
            if not sub_text:
                continue
            trail.subpages_fetched.append(url)
            if url in reg_link_text:
                trail.notes.append(f"subpage_followed: {url} ({reg_link_text[url]})")
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
            ttiers = _plain_table_tiers(sub_html, trail)
            if ttiers:
                trail.llm_reasoning = f"Found prices in a fee table on sub-page {url}."
                trail.notes.append(f"table_subpage: {len(ttiers)} tiers from {url}")
                return ExploreResult(
                    field="pricing", value=ttiers, method=f"subpage_table:{urlparse(url).path}",
                    audit_trail=trail, found=True,
                )
            _pdf = _follow_fee_document(sub_html, url, budget, trail)
            if _pdf:
                ptiers, purl, pmethod = _pdf
                trail.llm_reasoning = f"Found prices in fee document {purl} linked from {url}."
                return ExploreResult(field="pricing", value=ptiers, method=pmethod,
                                     audit_trail=trail, found=True, external_url=purl)
            # No text prices — collect fee images
            if sub_html:
                images = find_money_images(sub_html, url, limit=6, trail=trail)
                if images:
                    try:
                        from vision import extract_pricing_from_images
                        import time as _t
                        _t0 = _t.time()
                        vtiers = usable_vision_tiers(extract_pricing_from_images(images, stop_at=_source_deadline), trail)
                        _note_vision_time(_t.time() - _t0)
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
    organiser = (row.get("organiser_url") or "").strip()
    has_organiser = bool(organiser) and organiser.split("#")[0].rstrip("/") != (row.get("source_url") or base_url).split("#")[0].rstrip("/")
    if page_html or has_organiser:
        # The same-domain walk above routinely burns the whole fetch budget on
        # guessed sub-pages (survey P12: 40+ of 50 rows never reached their
        # external link). Tier 3 gets its own small allowance, still bounded
        # by the per-source deadline.
        budget = ExploreBudget(max_fetches=EXPLORE_EXTERNAL_FETCHES)
        externals = find_external_event_links(page_html or "", base_url, limit=4)
        if has_organiser and organiser not in [u for u, _ in externals]:
            externals.insert(0, (organiser, "organiser_url"))
        for ext_url, link_text in externals:
            if ext_url in (trail.subpages_fetched):
                continue
            if budget.exhausted():
                break
            sub_text, sub_html = budget.fetch(ext_url)
            if not sub_text:
                trail.notes.append(f"external_fetch_failed: {ext_url}")
                continue
            trail.subpages_fetched.append(ext_url)
            trail.total_text_chars += len(sub_text)
            trail.notes.append(f"external_followed: {ext_url} (link text: {link_text!r})")
            # The event's own page linked here explicitly, so the link is the
            # identity evidence: a loose token/date match is enough. Fall back
            # to the strict gate only when that fails.
            if not (external_identity_ok(row, sub_text)
                    or (identity_tokens and page_matches_event(sub_text, ext_url))):
                trail.notes.append(f"external_identity_rejected: {ext_url}")
                continue
            external_seen = external_seen or ext_url
            # External text regex sweep + fee tables + flat "Label - £N" text
            tiers, _how = _external_page_tiers(sub_text, sub_html, trail)
            if tiers:
                trail.llm_reasoning = (
                    f"Followed external link {link_text!r} to {ext_url} "
                    f"(aggregator-style listing). Found prices via {_how} extraction."
                )
                trail.notes.append(f"external_{_how}: {len(tiers)} tiers from {ext_url}")
                return ExploreResult(
                    field="pricing", value=tiers,
                    method=f"external_{'text' if _how == 'text' else _how}:{urlparse(ext_url).netloc}",
                    audit_trail=trail, found=True, external_url=ext_url,
                )
            # External page might also have fee images
            if sub_html:
                images = find_money_images(sub_html, ext_url, limit=4, trail=trail)
                if images:
                    try:
                        from vision import extract_pricing_from_images
                        import time as _t
                        _t0 = _t.time()
                        vtiers = usable_vision_tiers(extract_pricing_from_images(images, stop_at=_source_deadline), trail)
                        _note_vision_time(_t.time() - _t0)
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
                                audit_trail=trail, found=True, external_url=ext_url,
                            )
                    except Exception as e:
                        trail.notes.append(f"external_vision_failed: {e}")
            _pdf = _follow_fee_document(sub_html, ext_url, budget, trail)
            if _pdf:
                ptiers, purl, pmethod = _pdf
                trail.llm_reasoning = f"Followed external link to {ext_url}; fees in linked document {purl}."
                return ExploreResult(field="pricing", value=ptiers, method=pmethod,
                                     audit_trail=trail, found=True, external_url=ext_url)
            # Two-hop: the external congress site keeps fees on its own
            # "Registration" sub-page. Same-host, max 2, shared fetch caps.
            if sub_html:
                hop = _follow_registration_subpages(sub_html, ext_url, budget, trail, limit=2)
                if hop:
                    htiers, hop_url, hop_method = hop
                    trail.llm_reasoning = (
                        f"Followed external link {link_text!r} to {ext_url}, then its "
                        f"registration sub-page {hop_url}. Found prices via {hop_method}.")
                    return ExploreResult(
                        field="pricing", value=htiers,
                        method=(hop_method if hop_method.startswith("pdf:")
                                else f"external_subpage_{hop_method}:{urlparse(hop_url).netloc}"),
                        audit_trail=trail, found=True, external_url=ext_url,
                    )

    # 4. LLM with full context: ask if anywhere we've collected mentions money
    title = row.get("conference_name") or ""
    context = accumulated_text[:8000]
    if not context:
        trail.llm_reasoning = "No page text available."
        return ExploreResult(
            field="pricing", value=None, method="not_found",
            audit_trail=trail, found=False, external_url=external_seen,
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
            audit_trail=trail, found=False, external_url=external_seen,
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
            audit_trail=trail, found=False, external_url=external_seen,
        )
    trail.llm_reasoning = parsed.get("reasoning", "")[:300]
    parsed_tiers = parsed.get("tiers", [])
    if not parsed_tiers:
        return ExploreResult(
            field="pricing", value=None, method="not_found",
            audit_trail=trail, found=False, external_url=external_seen,
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
            audit_trail=trail, found=False, external_url=external_seen,
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
    budget = ExploreBudget()
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
            if budget.exhausted():
                trail.notes.append("explore_budget_exhausted: stopped sub-page walk")
                break
            sub_text, _ = budget.fetch(url)
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
