# extractors/discovery.py
"""Scrape-time sub-page discovery (ticket X3, mission "cross-source coverage").

The per-source extractor reads the event's own page. Fees, venue and abstract
info often live one click away ("Registration", "Travel", "Call for papers"), in
a fee PDF, or in a fee image. This engine follows those links DURING the scrape,
for every source, with no per-extractor code:

    discover(row, page_html, page_text, base_url, hints=..., budget=...)

For each field still MISSING on `row` (pricing_tiers / venue_name+city / abstract
info) it
  1. reads the page the caller already has (no refetch),
  2. picks candidate same-site links with the remediator's pickers (imported
     lazily and defensively by name; a small local matcher is the fallback),
     hints first, plus ONE external hop to `row["organiser_url"]`,
  3. fetches at most `budget.max_html` (2) HTML pages (10 s each),
  4. follows ONE PDF (<= 8 MB, <= 20 pages, `%PDF` header, parsed in a child
     process by `remediator.pdf_text`),
  5. reads money-adjacent images with the vision chain inside a per-source,
     per-run ledger (<= 5 images, <= 120 s); beyond it the image is DEFERRED
     (`result.deferred` gets "fee_image_pending"),
  6. parses with the shared parsers only: `pricing_tables` -> `fee_matrix` ->
     `money.find_amounts` fee-context sweep; `abstract_classifier`;
     `location_evidence` (via the explorer's place extractor when present).

Hard rules: never calls a text LLM, never fabricates (a tier without a currency
is dropped, a zero amount is not a fee), wall clock 20 s without vision / 140 s
with vision on a monotonic clock checked between steps, never raises.

`apply_to_row()` merges a result into EMPTY fields only.
"""

from __future__ import annotations

import html as _html
import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from logger import logger

import money

__all__ = [
    "DiscoveryHints", "DiscoveryBudget", "VisionLedger", "DiscoveryResult",
    "discover", "apply_to_row", "missing_fields", "page_identity", "own_page_scope", "own_paths", "row_years",
    "STRONG", "WEAK", "REJECTED",
]

FIELD_FEES, FIELD_VENUE, FIELD_ABSTRACT = "fees", "venue", "abstract"
_FIELD_ORDER = (FIELD_FEES, FIELD_VENUE, FIELD_ABSTRACT)
_HINT_ATTR = {FIELD_FEES: "fees", FIELD_VENUE: "venue", FIELD_ABSTRACT: "abstracts"}
MAX_TIERS = 40
PDF_MAX_BYTES = 8_000_000
PDF_MIN_FETCH = 2.0      # a PDF step starts only when the clock allows at least this much fetch ...
PDF_MIN_PARSE = 3.0      # ... plus this much for the child-process parse


# ── public types ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class DiscoveryHints:
    """What an extractor knows about where its sub-pages live. All optional.

    *_suffixes: appended to the event page URL ("/registration", "?tab=fees").
    *_urls: templates formatted with {url} (event page, no query/fragment),
            {base} (scheme://host), {year} (start year), {slug} (last path part).
    anchor_words: {"fees"|"venue"|"abstracts": ("delegate rates", ...)} extra
            words matched against same-site anchor TEXT.
    The engine tries hints first; a wrong hint costs one of the 2 fetches.
    """
    fees_suffixes: Tuple[str, ...] = ()
    abstracts_suffixes: Tuple[str, ...] = ()
    venue_suffixes: Tuple[str, ...] = ()
    fees_urls: Tuple[str, ...] = ()
    abstracts_urls: Tuple[str, ...] = ()
    venue_urls: Tuple[str, ...] = ()
    anchor_words: Dict[str, Tuple[str, ...]] = field(default_factory=dict)


@dataclass
class VisionLedger:
    """Per-source, per-run vision allowance, shared by every row of the source."""
    max_images: int = 5
    max_seconds: float = 120.0
    images_used: int = 0
    seconds_used: float = 0.0

    def images_left(self) -> int:
        return max(0, self.max_images - self.images_used)

    def seconds_left(self) -> float:
        return max(0.0, self.max_seconds - self.seconds_used)


@dataclass
class DiscoveryBudget:
    max_html: int = 2
    html_timeout: float = 10.0
    max_pdf: int = 1
    pdf_timeout: float = 15.0
    wall_seconds: float = 20.0            # without vision
    wall_seconds_vision: float = 140.0    # when the vision step runs
    vision: VisionLedger = field(default_factory=VisionLedger)
    clock: Callable[[], float] = time.monotonic


@dataclass
class DiscoveryResult:
    tiers: List[Dict[str, Any]] = field(default_factory=list)
    venue_name: Optional[str] = None
    city: Optional[str] = None
    abstract_open: Optional[bool] = None
    abstract_deadline: Optional[str] = None
    abstract_deadline_note: Optional[str] = None
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    deferred: List[str] = field(default_factory=list)

    def has_abstract(self) -> bool:
        return bool(self.abstract_deadline or self.abstract_deadline_note or self.abstract_open)

    def found_fields(self) -> List[str]:
        out = []
        if self.tiers:
            out.append("pricing_tiers")
        if self.venue_name or self.city:
            out.append("venue")
        if self.has_abstract():
            out.append("abstract")
        return out


# ── seams (monkeypatched by tests; real network lives only here) ──────────────────
HTML_MAX_BYTES = 2_000_000


def _hard_cap(fn: Callable[[], Any], seconds: float) -> Any:
    """fn() in a daemon thread, abandoned after `seconds` of WALL-CLOCK time (returns
    None then). httpx timeouts are per socket operation: a server that trickles bytes or
    stalls one read can outlast them; this cap is the total read deadline."""
    import threading
    box: Dict[str, Any] = {}

    def _run():
        try:
            box["v"] = fn()
        except Exception as e:  # noqa: BLE001
            box["e"] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(max(0.1, seconds))
    if t.is_alive():
        logger.debug(f"discovery: fetch abandoned after {seconds:.1f}s (total read deadline)")
        return None
    if "e" in box:
        raise box["e"]
    return box.get("v")


def _stream_body(url: str, timeout: float, max_bytes: int, headers: Optional[dict] = None):
    """(status, body_bytes, encoding) streamed with a per-chunk deadline + size check; None
    when the body passes `max_bytes` or the deadline. Callers also wrap it in _hard_cap."""
    import httpx
    end = time.monotonic() + timeout
    buf = bytearray()
    with httpx.Client(timeout=httpx.Timeout(min(timeout, 10.0), connect=min(timeout, 5.0)), follow_redirects=True,
                      headers=headers or {"User-Agent": "Mozilla/5.0 (compatible; MedConfBot)"}) as c:
        with c.stream("GET", url) as r:
            try:
                if int((r.headers or {}).get("content-length") or 0) > max_bytes:
                    return None
            except ValueError:
                pass
            for chunk in r.iter_bytes():
                buf.extend(chunk)
                if len(buf) > max_bytes or time.monotonic() > end:
                    return None
            return r.status_code, bytes(buf), getattr(r, "encoding", None)


def _get_capped(url: str, timeout: float, max_bytes: int, headers: Optional[dict] = None):
    """(status, body, encoding) or None, inside a total read deadline of `timeout` s and a
    hard size cap. Safe-fetch mode goes through the hop-validated client (its own deadline)."""
    import safe_fetch
    if safe_fetch.enabled():
        got = _hard_cap(lambda: safe_fetch.fetch_validated(
            url, safe_fetch.check_url_safe, max_bytes=max_bytes + 1,
            deadline=time.monotonic() + timeout), timeout)
        if not got or got[0] != "ok":
            return None
        return got[4] or 200, got[2], got[3]
    return _hard_cap(lambda: _stream_body(url, timeout, max_bytes, headers), timeout)


def _fetch_html(url: str, timeout: float) -> Optional[str]:
    """HTML body or None: total read deadline `timeout`, body <= HTML_MAX_BYTES, error and
    bot-block pages refused (extractors.http_fetch's detector), safe-fetch honoured, never
    launches Playwright."""
    try:
        from extractors import http_fetch
        got = _get_capped(url, timeout, HTML_MAX_BYTES, dict(getattr(http_fetch, "DEFAULT_HEADERS", {}) or {}) or None)
        if not got:
            return None
        status, body, enc = got
        if body is None or len(body) > HTML_MAX_BYTES or (status or 0) >= 400:
            return None
        try:
            text = body.decode(enc or "utf-8", errors="replace")
        except LookupError:
            text = body.decode("utf-8", errors="replace")
        looks = getattr(http_fetch, "_looks_blocked", None)
        if looks and looks(status, text):
            return None
        return text
    except Exception as e:  # noqa: BLE001
        logger.debug(f"discovery: fetch failed {url}: {type(e).__name__}")
        return None


def _fetch_bytes(url: str, timeout: float, max_bytes: int = PDF_MAX_BYTES) -> Optional[bytes]:
    """PDF bytes (<= max_bytes, `%PDF` header) or None, inside a total read deadline."""
    try:
        got = _get_capped(url, timeout, max_bytes)
        if not got:
            return None
        status, data, _enc = got
        if (status or 0) >= 400 or not data or len(data) > max_bytes or not data.startswith(b"%PDF"):
            return None
        return data
    except Exception as e:  # noqa: BLE001
        logger.debug(f"discovery: pdf fetch failed {url}: {type(e).__name__}")
        return None


def _pdf_text(data: bytes, timeout: float = 20.0) -> str:
    """Child-process parse under remediator.pdf_text limits (<= 20 pages); the child
    is killed after `timeout` seconds (the caller passes what is left of the wall clock)."""
    try:
        from remediator.pdf_text import pdf_to_text_isolated, PDF_MAX_PAGES
        return pdf_to_text_isolated(data, max_pages=PDF_MAX_PAGES, timeout=max(1.0, timeout)) or ""
    except Exception as e:  # noqa: BLE001
        logger.debug(f"discovery: pdf parse failed: {type(e).__name__}")
        return ""


def _vision_pricing(image_urls: List[str], stop_at: float, timeout: Optional[float] = None) -> List[Dict[str, Any]]:
    """The remaining budget is BOTH the per-image download timeout and the hard call
    timeout inside vision, and the whole call is hard-capped at it here as well."""
    import vision
    limit = max(1.0, timeout if timeout is not None else stop_at - time.time())
    return vision.call_with_hard_timeout(
        lambda: vision.extract_pricing_from_images(image_urls, stop_at=stop_at,
                                                   fetch_timeout=limit, call_timeout=limit),
        limit) or []


def _vision_allowed() -> bool:
    try:
        import safe_fetch
        return not safe_fetch.enabled()
    except Exception:  # noqa: BLE001
        return True


# ── explorer access (defensive: X2 edits explorer.py concurrently) ────────────────
def _explorer():
    try:
        from remediator import explorer
        return explorer
    except Exception as e:  # noqa: BLE001
        logger.debug(f"discovery: explorer unavailable ({type(e).__name__}); local matchers only")
        return None


def _call(name: str, *args, **kw):
    """explorer.<name>(*args, **kw), or None when the name is absent / raises."""
    ex = _explorer()
    fn = getattr(ex, name, None) if ex else None
    if fn is None:
        return None
    try:
        return fn(*args, **kw)
    except TypeError:
        try:
            return fn(*args)
        except Exception:  # noqa: BLE001
            return None
    except Exception:  # noqa: BLE001
        return None


# ── small helpers ────────────────────────────────────────────────────────────────
def _host(url: str) -> str:
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def _page_key(url: str) -> str:
    return (url or "").split("#")[0].rstrip("/")


def _to_text(html: str, limit: Optional[int] = 250_000) -> str:
    """Visible text. `limit=None` returns ALL of it (FV8: the own-page sibling checks must
    not be blind past 250 k characters); every other caller keeps the 250 k cap."""
    h = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1\s*>", " ", html or "")
    t = _html.unescape(re.sub(r"<[^>]+>", " ", h))
    t = re.sub(r"\s+", " ", t).strip()
    return t if limit is None else t[:limit]


_SUPSUB_RE = re.compile(r"(?is)<(sup|sub)\b[^>]*>.*?</\1\s*>")


def _to_lines(html: str) -> str:
    html = _SUPSUB_RE.sub(" ", html or "")      # footnote markers ("EUR<sup>1</sup>") are not amounts
    try:
        from remediator.fee_matrix import html_to_lines
        return html_to_lines(html)
    except Exception:  # noqa: BLE001
        h = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1\s*>", " ", html or "")
        h = re.sub(r"(?i)</?(?:p|div|li|ul|ol|tr|td|th|table|h[1-6]|br|section|article)\b[^>]*>", "\n", h)
        return _html.unescape(re.sub(r"<[^>]+>", " ", h))


def _is_date(s: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


_ANCHOR_RE = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a\s*>", re.I | re.S)
_BAD_LINK_RE = re.compile(r"newsletter|subscribe|log\s?in|sign\s?in|privacy|cookie|\.(?:png|jpe?g|gif|svg|webp|css|js|ics|zip)(?:\?|$)", re.I)

_LOCAL_RX = {
    FIELD_FEES: re.compile(r"\b(?:registration|register|fees?|pricing|prices?|rates?|tickets?|book(?:ing)?|costs?|attend)\b", re.I),
    FIELD_VENUE: re.compile(r"\b(?:venue|location|travel|getting\s+there|directions?|how\s+to\s+find|accommodation|hotel|map)\b", re.I),
    FIELD_ABSTRACT: re.compile(r"\b(?:abstracts?|call\s+for\s+(?:papers|abstracts|posters|proposals)|submissions?|submit|posters?)\b", re.I),
}


def _local_links(html: str, base_url: str, rx: "re.Pattern[str]", *, limit: int = 3) -> List[Tuple[str, str]]:
    """Same-host anchors whose text or path matches rx (fallback picker)."""
    host, me = _host(base_url), _page_key(base_url)
    out, seen = [], set()
    for m in _ANCHOR_RE.finditer(html or ""):
        href = m.group(1).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        text = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        absolute = urljoin(base_url, href)
        pu = urlparse(absolute)
        if pu.scheme not in ("http", "https") or _host(absolute) != host:
            continue
        clean = absolute.split("#")[0]
        if _page_key(clean) == me or clean in seen or _BAD_LINK_RE.search(text) or _BAD_LINK_RE.search(pu.path):
            continue
        if not (rx.search(text[:80]) or rx.search(pu.path.replace("-", " ").replace("_", " "))):
            continue
        seen.add(clean)
        out.append((clean, text[:60]))
        if len(out) >= limit:
            break
    return out


def _pairs(res: Any) -> List[Tuple[str, str]]:
    out = []
    for x in res or []:
        if isinstance(x, str):
            out.append((x, ""))
        elif isinstance(x, (tuple, list)) and x:
            out.append((str(x[0]), str(x[1]) if len(x) > 1 else ""))
    return out


# ── candidate selection ──────────────────────────────────────────────────────────
def _hint_candidates(fieldname: str, page_url: str, row: dict, hints: Optional[DiscoveryHints]) -> List[Tuple[str, Optional[str]]]:
    """(url, declared_host) per hint. Suffixes live on the event page's host; a URL
    template declares the host written in it, or None when a placeholder builds the host."""
    if not hints:
        return []
    attr = _HINT_ATTR[fieldname]
    clean = page_url.split("#")[0].split("?")[0].rstrip("/")
    pu = urlparse(page_url)
    ctx = {"url": clean, "base": f"{pu.scheme}://{pu.netloc}",
           "year": (str(row.get("start_date") or "")[:4] or ""),
           "slug": clean.rsplit("/", 1)[-1]}
    out: List[Tuple[str, Optional[str]]] = []
    for suf in getattr(hints, f"{attr}_suffixes", ()) or ():
        out.append((clean + suf, _host(page_url)))
    for tpl in getattr(hints, f"{attr}_urls", ()) or ():
        try:
            url = tpl.format(**ctx)
            probe = tpl.format(url="http://\x00/", base="http://\x00", year="0", slug="\x00")
        except (KeyError, IndexError, ValueError):
            continue
        declared = _host(probe)
        out.append((url, None if (not declared or "\x00" in declared) else declared))
    return out


_NON_HTML_PATH_RE = re.compile(r"\.(?:pdf|docx?|xlsx?|pptx?|zip|png|jpe?g|gif|svg|webp|css|js|json|xml|ico|woff2?|ttf|map)$", re.I)
# A page OUTSIDE the event's own section (site-wide: awards, membership, training...)
# must say the field word itself; loose words like "cost", "info", "attend" do not count.
_STRONG_RX = {
    FIELD_FEES: re.compile(r"\b(?:registration|register|fees?|pricing|tickets?|booking|book\s+now|rates?)\b", re.I),
    FIELD_VENUE: re.compile(r"\b(?:venue|location|travel|directions?|getting\s+there|how\s+to\s+find)\b", re.I),
    FIELD_ABSTRACT: re.compile(r"\b(?:abstracts?|call\s+for\s+(?:papers|abstracts|posters)|submit)\b", re.I),
}
_SITEWIDE_NEG_RE = re.compile(
    r"award|grant|scholar|training|trainee|patient|member(?:ship)?|career|job|news|blog|policy|"
    r"technology|cost-of|journal|publication|about|contact|donate|exhibitor|sponsor", re.I)
_WEAK_TITLE_TOKENS = {"annual", "meeting", "conference", "congress", "course", "international", "symposium",
                      "update", "updates", "training", "workshop", "series", "online", "webinar", "event"}


def _title_tokens(row: dict) -> set:
    return {t for t in re.findall(r"[a-z0-9]{5,}", (row.get("conference_name") or "").lower())
            if t not in _WEAK_TITLE_TOKENS and not t.isdigit()}


_TICKETING_RE = re.compile(
    r"(eventbrite|cvent|eventsair|regonline|ticketsource|oxfordabstracts|tickettailor|eventzilla|bookwhen|"
    r"congressbooking|conferencecare|cmevents|exordo|eventsforce|conftool|whova|eventscase|bizzabo|trybooking|humanitix)", re.I)


def _is_ticketing_host(url: str) -> bool:
    rx = getattr(_explorer(), "TICKETING_HOST_RE", None) or _TICKETING_RE
    return bool(rx.search(urlparse(url).netloc))


def _external_by_slug(html: str, page_url: str, row: dict) -> List[str]:
    """Cross-host anchors whose URL path carries >= 2 distinct title tokens of THIS
    event ("camls-us.org/programs/minimally-invasive-gynecologic-surgery-course-..."):
    the link's own address is the identity evidence. Further gated by the page-text
    identity check after the fetch."""
    toks = _title_tokens(row)
    out, seen = [], set()
    for m in _ANCHOR_RE.finditer(html or ""):
        url = urljoin(page_url, _html.unescape(m.group(1).strip()))
        pu = urlparse(url)
        if pu.scheme not in ("http", "https") or _host(url) == _host(page_url) or url in seen:
            continue
        if _NON_HTML_PATH_RE.search(pu.path) or _call("is_junk_external", url):
            continue
        low = pu.path.lower()
        hit = len({t for t in toks if t in low})
        if _is_ticketing_host(url) or (hit >= 3 or (hit >= 2 and hit >= 0.6 * len(toks))):
            seen.add(url)
            out.append(url)
        if len(out) >= 2:
            break
    return out


def _candidates(fieldname: str, html: str, page_url: str, row: dict,
                hints: Optional[DiscoveryHints], skip: set) -> List[Dict[str, Any]]:
    """Ordered candidates for one field. Priority: hints, in-event-path pickers,
    the organiser_url (external), same-site pages outside the event's section that
    name the field outright, an external link whose address names this event."""
    seen = set(skip) | {_page_key(page_url)}
    buckets: Dict[int, List[Dict[str, Any]]] = {0: [], 1: [], 2: [], 3: [], 4: []}

    def add(url: str, why: str, prio: int, external: bool = False, text: str = "") -> None:
        k = _page_key(url)
        if not url or k in seen or urlparse(url).scheme not in ("http", "https"):
            return
        if _NON_HTML_PATH_RE.search(urlparse(url).path):
            return                      # documents go through the PDF step, not the HTML fetch
        if not external and _host(url) != _host(page_url):
            return
        if prio == 1 and not _in_event_path(page_url, url):
            label = (text + " " + urlparse(url).path.rstrip("/").rsplit("/", 1)[-1].replace("-", " "))
            if not _STRONG_RX[fieldname].search(label) or _SITEWIDE_NEG_RE.search(label):
                return                  # site-wide page that never names the field
        seen.add(k)
        buckets[prio].append({"url": url, "why": why, "field": fieldname, "external": external})

    for u, declared in _hint_candidates(fieldname, page_url, row, hints):
        # a hint is fetched only on the event page's host or the host the hint itself declares
        if _host(u) == _host(page_url):
            add(u, "hint", 0)
        elif declared and _host(u) == declared:
            add(u, "hint", 0, external=True)
    words = ((hints.anchor_words or {}).get(_HINT_ATTR[fieldname]) or ()) if hints else ()
    if words:
        rx = re.compile("|".join(re.escape(w) for w in words), re.I)
        for u, _t in _local_links(html, page_url, rx):
            add(u, "hint_anchor", 0)

    picked: List[Tuple[str, str]] = []
    if fieldname == FIELD_FEES:
        picked += _pairs(_call("find_registration_links", html, page_url, 3))
        nav = _call("static_nav_links", html, page_url)
        if nav:
            pri = _call("prioritise_nav_links", nav, page_url, need_abstract=False) or []
            picked += [(t[0], t[1]) for t in pri if len(t) > 2 and t[2] == "fees"]
        if not picked:
            picked += _local_links(html, page_url, _LOCAL_RX[FIELD_FEES])
    elif fieldname == FIELD_VENUE:
        got = _call("find_venue_links", html, page_url)
        picked += _pairs(got) if got is not None else _local_links(html, page_url, _LOCAL_RX[FIELD_VENUE])
    else:
        got = _call("find_abstract_links", html, page_url)
        picked += _pairs(got) if got is not None else []
        nav = _call("static_nav_links", html, page_url)
        if nav:
            pri = _call("prioritise_nav_links", nav, page_url, need_abstract=True) or []
            picked += [(t[0], t[1]) for t in pri if len(t) > 2 and t[2] == "abstract"]
        if not picked:
            picked += _local_links(html, page_url, _LOCAL_RX[FIELD_ABSTRACT])
    for u, t in picked:
        add(u, "picker", 1, text=t)

    org = str(row.get("organiser_url") or "").strip()
    if org.startswith(("http://", "https://")) and _host(org) != _host(page_url) and not _call("is_junk_external", org):
        add(org, "organiser_url", 2, external=True)
    for u in _external_by_slug(html, page_url, row):
        add(u, "linked_event_site", 4, external=True)
    return [c for p in sorted(buckets) for c in buckets[p]]


# ── parsers ──────────────────────────────────────────────────────────────────────
_FEE_CTX_RE = re.compile(r"\b(?:fees?|registration|prices?|pricing|rates?|tariff|tickets?|cost|delegates?)\b", re.I)
_SIDE_CHARGE_RE = re.compile(
    r"cancell?ation|no[- ]?show|non[- ]?attendance|penalt|parking|deposit|late[- ]payment|"
    r"administrat\w*\s+(?:charge|fee)|admin\s+(?:charge|fee)|refund|holding\s+fee|"
    r"sponsor|exhibit|booth|donat|bursar|scholarship|prize|award|per\s+night|hotel|accommodation|"
    r"salary|stipend|grant\b", re.I)


def _clean_tiers(tiers: Iterable[dict]) -> List[Dict[str, Any]]:
    """Currency mandatory (never guessed), amount > 0 and plausible, label required, deduped."""
    out, seen = [], set()
    for t in tiers or []:
        cur = money.normalize_currency(t.get("currency"))
        try:
            price = float(t.get("price_gbp"))
        except (TypeError, ValueError):
            continue
        label = re.sub(r"\s+", " ", str(t.get("tier_label") or "")).strip()
        if not cur or price <= 0 or not money.plausible(price, cur) or len(re.findall(r"[A-Za-z]", label)) < 3:
            continue
        key = (label.lower(), price, cur)
        if key in seen:
            continue
        seen.add(key)
        out.append({"tier_label": label[:200], "price_gbp": price, "currency": cur,
                    "is_early_bird": bool(t.get("is_early_bird")) or "early" in label.lower(),
                    "early_bird_deadline": t.get("early_bird_deadline")})
        if len(out) >= MAX_TIERS:
            break
    return out


def _tidy_label(x: str) -> str:
    x = re.sub(r"^[\s\-\u2013\u2014:|,/*()]+", "", x)
    return re.sub(r"[\s\-\u2013\u2014:|,/*]+$", "", x)


_FEELIKE_RE = re.compile(
    r"member|student|delegate|early|late|standard|regular|trainee|fellow|nurse|consultant|resident|"
    r"physician|doctor|registrar|on-?site|advance|concession|industry|speaker|visitor|attendee", re.I)
_BARE_TIMEFRAME_RE = re.compile(
    r"^(?:super\s+)?(?:early(?:[\s-]*bird)?|late|standard|regular|on-?site|advance)(?:\s*(?:fee|rate|price|registration))?$", re.I)
_CATEGORY_TAIL_RE = re.compile(
    r"\s*(?:super\s+)?(?:early(?:[\s-]*bird)?|late|standard|regular|on-?site|advance)?\s*(?:fee|rate|price|registration)?"
    r"\s*[-\u2013\u2014:]*\s*$", re.I)


def _label_for(lines: List[str], i: int, mny: "money.Money", head: str) -> Optional[str]:
    """Label of the amount on lines[i]: the words between the previous amount (or line
    start) and this one ("Member: £120"; for a 2nd amount on a line the line's
    category is prefixed: "Physicians · Late Fee"), else the words after it on the
    same line, else a neighbouring short amount-free line that reads like a fee
    category. Anything else is not a label (None)."""
    line = lines[i]
    try:
        prior = [m for m in money.find_amounts(line, context=head) if m.span[1] <= mny.span[0]]
    except Exception:  # noqa: BLE001
        prior = []
    start = prior[-1].span[1] if prior else 0
    seg = _tidy_label(re.sub(r"^\s*(?:and|&|or|;|,)\s+", "", line[start:mny.span[0]], flags=re.I))
    if prior and len(re.findall(r"[A-Za-z]", seg)) >= 3:
        first = prior[0]
        cat = _tidy_label(_CATEGORY_TAIL_RE.sub("", line[:first.span[0]]))
        if len(re.findall(r"[A-Za-z]", cat)) < 3 and i > 0 and len(lines[i - 1]) <= 80 \
                and not money.find_amounts(lines[i - 1], context=head):
            cat = _tidy_label(lines[i - 1])
        if len(re.findall(r"[A-Za-z]", cat)) >= 3 and cat.lower() not in seg.lower() and not _SIDE_CHARGE_RE.search(cat):
            seg = f"{cat} \u00b7 {seg}"
    after = _tidy_label(line[mny.span[1]:])
    if _BARE_TIMEFRAME_RE.match(seg) and i > 0:
        # "Early Fee $2,699 / Late Fee $2,999" under a category line ("Physicians - Main Course only")
        prev = _tidy_label(lines[i - 1])
        if (len(lines[i - 1]) <= 80 and len(re.findall(r"[A-Za-z]", prev)) >= 3
                and not money.find_amounts(lines[i - 1], context=head) and not _SIDE_CHARGE_RE.search(prev)):
            seg = f"{prev} \u00b7 {seg}"
    if len(re.findall(r"[A-Za-z]", seg)) >= 3 and len(seg) <= 120:
        return seg
    if len(re.findall(r"[A-Za-z]", after)) >= 3 and len(after) <= 120:
        return after
    for j in (i + 1, i - 1):
        if 0 <= j < len(lines) and len(lines[j]) <= 80 and not money.find_amounts(lines[j], context=head):
            c = _tidy_label(lines[j])
            if len(re.findall(r"[A-Za-z]", c)) >= 3 and (_FEE_CTX_RE.search(c) or _FEELIKE_RE.search(c)) \
                    and not _SIDE_CHARGE_RE.search(c):
                return c
    return None


_BAD_SWEEP_LABEL_RE = re.compile(r"(?i)^\s*\d+\s*\)|indicative|billed\s+in|charged\s+in")
_CODES_ONLY_RE = re.compile(r"^[\s/|,;:.\-\u2013\u2014()*\u20ac$\u00a3A-Z]{0,12}$")
_SWEEP_MIN_AMOUNT = 5.0


def _bad_sweep_label(label: str) -> bool:
    """A label that is only currency codes / symbols / slashes, a footnote ("1) ..."), or a
    billing note is no fee category."""
    if _BAD_SWEEP_LABEL_RE.search(label):
        return True
    letters = re.sub(r"[^A-Za-z]", "", label)
    return not letters or (len(letters) <= 12 and _CODES_ONLY_RE.match(label) is not None
                           and all(c in money.KNOWN_CODES for c in re.findall(r"[A-Za-z]{2,}", label)))


def _dual_groups(line: str, found: list) -> list:
    """Runs of amounts in different currencies joined by / or | ("8 400 SEK / 795 EUR")."""
    groups, i = [], 0
    while i < len(found):
        grp = [found[i]]
        while i + 1 < len(found) and re.fullmatch(r"\s*[/|]\s*", line[found[i].span[1]:found[i + 1].span[0]]) \
                and found[i + 1].currency != grp[-1].currency:
            grp.append(found[i + 1])
            i += 1
        groups.append(grp)
        i += 1
    return groups


def _dual_filter(line: str, found: list, billing: Optional[str]) -> list:
    """Two amounts in different currencies joined by / or | are ONE price in two currencies:
    keep the billing currency's, else the first. The kept amount's span starts at the GROUP's
    start so its label is read from the text before the group, not from the dropped amount."""
    keep = []
    for grp in _dual_groups(line, found):
        pick = next((g for g in grp if billing and g.currency == billing), grp[0])
        if pick is not grp[0]:
            pick = money.Money(amount=pick.amount, currency=pick.currency, high=pick.high,
                               span=(grp[0].span[0], pick.span[1]))
        keep.append(pick)
    return keep


def _money_sweep(lines_text: str) -> List[Dict[str, Any]]:
    """Fee-context sweep: every line with a currency-bearing amount under fee
    context (a fee word in the label or the 12 lines above), side charges and
    sponsor/hotel amounts excluded, ranges skipped. One tier needs a fee word on
    its own line; otherwise >= 1 labelled tier under a fee heading."""
    lines = [re.sub(r"[ \t\xa0]+", " ", l).strip() for l in (lines_text or "").split("\n")]
    lines = [l for l in lines if l]
    head = (lines_text or "")[:4000]
    billing: Optional[str] = None
    offset = 0
    joined = "\n".join(lines)
    for line in lines:
        try:
            grps = [g for g in _dual_groups(line, money.find_amounts(line, context=head)) if len(g) > 1]
        except Exception:  # noqa: BLE001
            grps = []
        if grps:
            # the billing sentence must sit within 1,500 characters after the first dual line
            bm = re.search(r"(?i)\b(?:billed|charged|invoiced|payable|prices?)\s+(?:are\s+)?in\s+([A-Z]{3})\b",
                           joined[offset:offset + 1500])
            billing = bm.group(1) if bm and bm.group(1) in money.KNOWN_CODES else None
            break
        offset += len(line) + 1
    tiers: List[Dict[str, Any]] = []
    for i, line in enumerate(lines):
        if _SIDE_CHARGE_RE.search(line):
            continue
        try:
            found = _dual_filter(line, money.find_amounts(line, context=head), billing)
        except Exception:  # noqa: BLE001
            continue
        for mny in found:
            if mny.high is not None or mny.currency is None or mny.amount < _SWEEP_MIN_AMOUNT:
                continue
            label = _label_for(lines, i, mny, head)
            if label is None or _bad_sweep_label(label):
                continue
            ctx = " ".join(lines[max(0, i - 12): i]) + " " + label
            if not _FEE_CTX_RE.search(ctx):
                continue
            tiers.append({"tier_label": label, "price_gbp": mny.amount, "currency": mny.currency})
    clean = _drop_conflicts(_clean_tiers(tiers))
    if len(clean) == 1 and not _FEE_CTX_RE.search(clean[0]["tier_label"]):
        return []
    return clean


def _norm_label(label: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\b(?:19|20)\d\d\b|[^a-z ]", " ", label.lower())).strip()


def _drop_conflicts(tiers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The same fee label (year ignored) at different prices means the page lists several
    editions / sessions and we cannot tell which one is this event: keep none of them."""
    prices: Dict[str, set] = {}
    for t in tiers:
        prices.setdefault(_norm_label(t["tier_label"]), set()).add((t["price_gbp"], t["currency"]))
    return [t for t in tiers if len(prices[_norm_label(t["tier_label"])]) == 1]


def _fees_from(html: str, lines_text: str) -> Tuple[List[Dict[str, Any]], str]:
    """pricing_tables -> fee_matrix -> money sweep. Returns (tiers, method)."""
    if html:
        try:
            from extractors.pricing_tables import parse_pricing_tables
            t = _clean_tiers(parse_pricing_tables(html, default_currency="", max_tiers=MAX_TIERS))
            if t:
                return t, "pricing_tables"
        except Exception as e:  # noqa: BLE001
            logger.debug(f"discovery: pricing_tables failed: {e}")
    try:
        from remediator.fee_matrix import parse_fee_matrix
        t = _clean_tiers(parse_fee_matrix(lines_text))
        if t:
            return t, "fee_matrix"
    except Exception as e:  # noqa: BLE001
        logger.debug(f"discovery: fee_matrix failed: {e}")
    t = _money_sweep(lines_text)
    return (t, "money_sweep") if t else ([], "")


def _city_guess(parts: List[str]) -> Optional[str]:
    parts = [p.strip() for p in parts if p.strip() and not re.search(r"\d", p)]
    if len(parts) >= 3:
        return parts[-2]
    return parts[-1] if len(parts) == 2 else None


_BANNER_DATE_PREFIX_RE = re.compile(
    r"^\s*(?:[A-Z][a-z]+\.?\s+\d{1,2}(?:\s*[-\u2013\u2014]\s*(?:[A-Z][a-z]+\.?\s+)?\d{1,2})?,?\s+\d{4}|"
    r"\d{1,2}(?:\s*[-\u2013\u2014]\s*\d{1,2})?\s+[A-Z][a-z]+\.?\s+\d{4})\s*[-\u2013\u2014|,:]?\s*")


def _split_banner(val: str) -> Optional[Dict[str, Any]]:
    """"<date> <Venue words> <City>, <State/Country>" -> venue + city, ONLY when the
    split is unambiguous: the city is the 1-2 words before the comma AND that same
    phrase already appears inside the venue name ("JW Marriott Los Angeles L.A. Live
    Los Angeles, California"). Otherwise None (never guess a split)."""
    rest = _BANNER_DATE_PREFIX_RE.sub("", val or "", count=1).strip()
    if "," not in rest:
        return None
    head, _, tail = rest.rpartition(",")
    if not head.strip() or not tail.strip() or len(tail.split()) > 3:
        return None
    words = head.split()
    for n in (2, 1):
        if len(words) > n:
            city = " ".join(words[-n:])
            venue = " ".join(words[:-n])
            if re.search(r"[A-Za-z]{3}", city) and city in venue and len(venue.split()) >= 2:
                return {"venue_name": venue, "city": city, "method": "banner_split"}
    return None


def _place_from(html: str, text: str, base_url: str) -> Optional[Dict[str, Any]]:
    """{"venue_name","city"} from ONE page, no network."""
    if html:
        got = _call("extract_place_from_html", html, base_url, text)
        if got and (got.get("venue_name") or got.get("city")):
            return {"venue_name": got.get("venue_name"), "city": got.get("city"),
                    "method": got.get("method") or "explorer_place"}
    try:
        from extractors import location_evidence as le
        if html:
            m = re.search(r"maps[^\"'>]*[?&](?:q|query)=([^&\"'>]+)", html, re.I)
            if m:
                from urllib.parse import unquote_plus
                q = unquote_plus(_html.unescape(m.group(1)))
                parts = [p.strip() for p in q.split(",")]
                if len(parts) >= 2 and not re.search(r"\d", parts[0]):
                    return {"venue_name": parts[0], "city": _city_guess(parts), "method": "maps_embed"}
        ev = le.find_location_evidence(html or "", text or "")
        if ev:
            kind, _, val = ev.partition(": ")
            parts = [p.strip() for p in val.split(",")]
            if kind == "date/venue banner":
                pl = _split_banner(val)
                if pl:
                    return pl
            if kind == "address block" and len(parts) >= 2:
                if re.search(r"\d", parts[0]):      # "12 Queen Street, Leeds, LS1 4AB": a street, not a venue
                    city = next((x for x in parts[1:] if x and not re.search(r"\d", x)), None)
                    if city:
                        return {"venue_name": None, "city": city, "method": "address_block"}
                elif len(parts) >= 3:
                    return {"venue_name": parts[0], "city": _city_guess(parts), "method": "address_block"}
            if kind in ("venue line", "line under h1") and parts and not re.search(r"\d", parts[0]):
                return {"venue_name": parts[0], "city": _city_guess(parts) if len(parts) > 1 else None,
                        "method": kind.replace(" ", "_")}
    except Exception as e:  # noqa: BLE001
        logger.debug(f"discovery: location_evidence failed: {e}")
    return None


# ── identity of a fetched page: FAIL-CLOSED three-valued gate (FV4) ─────────────────
# STRONG   -> the page's data (and its links) may be used.
# WEAK     -> recorded in evidence (reason "weak_identity"); NOTHING from it is used.
# REJECTED -> recorded (reason "identity_mismatch"); NOTHING from it is used.
#
# Level-2 lists (recorded on MISSION_BOARD_COVERAGE.md):
SECTION_PHRASES = ("call for abstracts", "call for papers", "registration", "register", "fees", "pricing",
                   "prices", "tickets", "booking", "venue", "location", "travel", "abstracts", "programme")
EVENT_TYPE_WORDS = frozenset({"workshop", "masterclass", "course", "webinar", "symposium", "congress",
                              "conference", "meeting", "summit", "day", "forum", "lecture", "series"})
_NORM_STOP = frozenset({"the", "and", "of"})
STRONG, WEAK, REJECTED = "strong", "weak", "rejected"

_ID_WEAK = {"annual", "meeting", "conference", "congress", "course", "international", "symposium",
            "update", "updates", "training", "workshop", "series", "online", "webinar", "event", "events",
            "with", "from", "that", "this", "your", "live", "scientific", "national", "global", "world"}
_HEAD_GENERIC = {"registration", "register", "fees", "pricing", "prices", "tickets", "booking", "venue",
                 "location", "travel", "directions", "abstract", "abstracts", "submission", "submissions",
                 "programme", "program", "information", "details", "delegate", "delegates", "accommodation",
                 "welcome", "about", "home", "overview", "contact", "speakers", "sponsors", "exhibitors",
                 "schedule", "agenda", "general", "important", "dates", "call", "papers", "posters"}
_EVENT_NOUN_RE = re.compile(
    r"\b(?:conference|congress|course|masterclass|summit|symposium|meeting|workshop|webinar|forum|"
    r"update|annual|study\s+day|school|academy|convention|colloquium|seminar|bootcamp|assembly)\b|\b20\d\d\b",
    re.I)
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,}[0-9]*\b")
_TITLE_SEP_RE = re.compile(r"\s+[|–—-]\s+|\s*\|\s*")


def _norm(s: Any) -> str:
    """Identity normal form: case, punctuation, whitespace and the stop words the/and/of
    removed ("The Cardio Update & Co. 2027" -> "cardio update co 2027")."""
    t = _html.unescape(str(s or "")).lower().replace("&", " and ")
    return " ".join(w for w in re.sub(r"[\W_]+", " ", t).split() if w not in _NORM_STOP)


def _has(hay: str, needle: str) -> bool:
    return bool(needle) and f" {needle} " in f" {hay} "


def _cut(hay: str, needle: str) -> str:
    """hay with every whole-phrase occurrence of needle replaced by a barrier."""
    return f" {hay} ".replace(f" {needle} ", " | ").strip() if needle else hay


def _strip_tags(x: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", x or ""))).strip()


def _main_headings(html: str) -> List[str]:
    """The page's own heading: its first non-empty <h1>; else <title> minus the site
    suffix (or prefix) segment."""
    for m in re.finditer(r"<h1\b[^>]*>(.*?)</h1\s*>", html or "", re.I | re.S):
        h = _strip_tags(m.group(1))
        if h:
            return [h]
    m = re.search(r"<title\b[^>]*>(.*?)</title\s*>", html or "", re.I | re.S)
    if not m:
        return []
    t = _strip_tags(m.group(1))
    segs = [x for x in _TITLE_SEP_RE.split(t) if x.strip()]
    if len(segs) >= 2:
        return [" ".join(segs[:-1]), " ".join(segs[1:])]
    return [t] if t else []


def _all_headings(html: str) -> List[str]:
    out = [_strip_tags(m.group(1)) for m in re.finditer(r"<h[1-4]\b[^>]*>(.*?)</h[1-4]\s*>", html or "", re.I | re.S)]
    m = re.search(r"<title\b[^>]*>(.*?)</title\s*>", html or "", re.I | re.S)
    if m:
        out.append(_strip_tags(m.group(1)))
    return [h for h in out if h]


def _own_path(url: str) -> Optional[Tuple[str, str]]:
    """(host, "/a/b") of an event URL; None for a bare host (a homepage owns nothing)."""
    pu = urlparse(url or "")
    path = "/".join(x for x in pu.path.lower().split("/") if x)
    if pu.scheme not in ("http", "https") or not path:
        return None
    return _host(url), "/" + path


def _under_own_path(url: str, own: Iterable[Tuple[str, str]]) -> bool:
    """True only when `url` sits strictly UNDER one of the event's own URL paths
    (/events/<slug>/registration for /events/<slug>). The parent directory, a sibling
    slug sharing a prefix (/events/<slug>-workshop) and the page itself do not count."""
    pu = urlparse(url or "")
    path = "/" + "/".join(x for x in pu.path.lower().split("/") if x)
    return any(_host(url) == h and path.startswith(p + "/") for h, p in own)


def _in_event_path(base_url: str, url: str) -> bool:
    o = _own_path(base_url)
    return bool(o) and _under_own_path(url, [o])


def _heading_names_other_event(row: dict, heading: str) -> bool:
    """The heading reads like an EVENT name (an event noun or a year plus at least one
    distinctive word) and shares no distinctive word with this row's title."""
    name = row.get("conference_name") or ""
    toks = {t for t in re.findall(r"[a-z0-9]{4,}", name.lower()) if t not in _ID_WEAK and not t.isdigit()}
    toks |= {t.lower() for t in re.findall(r"\b[A-Z]{3}\b", name)}
    if not heading or not toks:
        return False
    low = heading.lower()
    if any(t in low for t in toks):
        return False
    words = {w for w in re.findall(r"[a-z]{4,}", low) if w not in _ID_WEAK and w not in _HEAD_GENERIC}
    return bool(words) and bool(_EVENT_NOUN_RE.search(heading))


def _only_section_words(rest: List[str], year: str) -> bool:
    """True when the leftover heading tokens are ONLY allow-listed section phrases (and
    the row's own start year)."""
    phrases = sorted((p.split() for p in SECTION_PHRASES), key=len, reverse=True)
    i = 0
    while i < len(rest):
        if rest[i] == "|" or (year and rest[i] == year):
            i += 1
            continue
        for ph in phrases:
            if rest[i:i + len(ph)] == ph:
                i += len(ph)
                break
        else:
            return False
    return True


def _heading_relation(title_n: str, heading_n: str, year: str) -> str:
    """"equal" | "section" (title + allow-listed section words only) | "extends_event"
    (title + an event-type word the title does not have) | "contains" | "absent"."""
    if not title_n or not heading_n:
        return "absent"
    if heading_n == title_n:
        return "equal"
    if not _has(heading_n, title_n):
        return "absent"
    rest = _cut(heading_n, title_n).split()
    title_words = set(title_n.split())
    if any(w in EVENT_TYPE_WORDS and w not in title_words for w in rest):
        return "extends_event"
    return "section" if _only_section_words(rest, year) else "contains"


def _norm_shell_titles(row: dict, titles: Iterable[str]) -> List[str]:
    me = _norm(row.get("conference_name"))
    out = []
    for t in titles or ():
        n = _norm(t)
        if n and n != me and len(n) >= 8 and len(n.split()) >= 2 and n not in out:
            out.append(n)
    return out


def _names_other_shell(title_n: str, text_n: str, others: List[str]) -> bool:
    """A sibling shell title occurs in text_n. A sibling that CONTAINS the row title is
    searched as is; a shorter one only outside occurrences of the row's own title."""
    if not others or not text_n:
        return False
    cut = _cut(text_n, title_n) if title_n else text_n
    for o in others:
        if _has(cut if not (title_n and _has(o, title_n)) else text_n, o):
            return True
    return False


_YEAR_RE = re.compile(r"(?<![0-9])(20\d\d)(?![0-9])")
_HEADING_RE = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1\s*>", re.I | re.S)


def row_years(row: dict) -> set:
    """The years that belong to this row: its start and end year, plus any 20xx year
    written in its own title ("Annual Meeting 2027" held in early 2028 keeps 2027)."""
    out = set()
    for k in ("start_date", "end_date"):
        y = str(row.get(k) or "")[:4]
        if y.isdigit() and y.startswith("20"):
            out.add(y)
    out.update(_YEAR_RE.findall(str(row.get("conference_name") or "")))
    return out


_DEADLINE_WORD_RE = re.compile(
    r"\b(?:by|before|until|till|deadline|ends?|closes?|prior\s+to|early[\s-]*bird|"
    r"book(?:ings?)?\s+by|register\s+by)\b", re.I)
_MONTH_NUM = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
              "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_MON = (r"(january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|"
        r"september|sept|sep|october|oct|november|nov|december|dec)\b\.?")
_DATE_FORMS = (   # each anchored at the END of the text before the year; groups -> (day, month)
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + _MON + r",?\s*$", re.I), lambda g: (g[0], g[1])),
    (re.compile(r"\b" + _MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*$", re.I), lambda g: (g[1], g[0])),
    (re.compile(r"\b" + _MON + r",?\s*$", re.I), lambda g: ("1", g[0])),
    (re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-]$"), lambda g: (g[0], g[1])),
)
DEADLINE_WINDOW_MONTHS = 9      # Level 2 (FV8): early-bird deadlines sit within 9 months of the start


def _deadline_date(before: str, year: str) -> Optional[date]:
    """The date written right before `year` ("31 December", "December 31,", "Dec", "31/12/");
    a missing day is the 1st; d/m order. None when there is no parseable date."""
    for rx, pick in _DATE_FORMS:
        m = rx.search(before)
        if not m:
            continue
        day, mon = pick(m.groups())
        try:
            month = int(mon) if mon.isdigit() else _MONTH_NUM[mon.lower()[:3]]
            return date(int(year), month, int(day))
        except (ValueError, KeyError):
            return None
    return None


def _months_back(d: date, n: int) -> date:
    import calendar
    y, m = d.year, d.month - n
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _is_prior_year_deadline(s: str, start: int, year: str, years: set, start_date: Any = None) -> bool:
    """FV7/FV8: exactly one year before the row's earliest year, written as a DATE right
    before it, a deadline word in the ~40 characters before, AND that date falls within
    DEADLINE_WINDOW_MONTHS before the row's start_date (strictly before it). No parseable
    start_date -> no exemption. An early-bird / booking deadline, not another edition."""
    try:
        if int(year) != min(int(y) for y in years) - 1:
            return False
    except ValueError:
        return False
    begins = _is_date(start_date)
    if begins is None:
        return False
    before = s[max(0, start - 40):start]
    if not _DEADLINE_WORD_RE.search(before):
        return False
    when = _deadline_date(before, year)
    return when is not None and _months_back(begins, DEADLINE_WINDOW_MONTHS) <= when < begins


def _foreign_year(s: str, years: set, start_date: Any = None) -> Optional[str]:
    for m in _YEAR_RE.finditer(s or ""):
        y = m.group(1)
        if y not in years and not _is_prior_year_deadline(s, m.start(), y, years, start_date):
            return y
    return None


ARCHIVE_SEGMENTS = frozenset({"past", "previous", "archive", "archives", "history"})   # Level 2 (FV8)


_TOKEN_SPLIT_RE = re.compile(r"[-_.]+")


def _path_tokens(path: str) -> set:
    """Every segment of a lower-cased URL path, whole AND split on - _ . (FV9)."""
    out = set()
    for seg in (x for x in path.split("/") if x):
        out.add(seg)
        out.update(t for t in _TOKEN_SPLIT_RE.split(seg) if t)
    return out


def url_edition_reason(row: dict, url: str) -> Optional[str]:
    """FV8/FV9: a prior edition's page under the event's own path.
    "other_year_path": the URL path (segments, filename) or QUERY string (keys and values)
        carries a 20xx year that is not the row's; years anywhere in the row's own
        booking/source URL (path or query) count as the row's.
    "archive_path": a path segment, or a token of one split on - _ . (filename stem
        included), EQUALS past / previous / archive / archives / history; tokens that also
        occur in the row's own tokenised booking/source path stay allowed.
    Two-digit years ("cu26") are deliberately not detected (too broad)."""
    pu = urlparse(url or "")
    path, query = pu.path.lower(), pu.query.lower()
    if not path and not query:
        return None
    own_tokens, own_years = set(), set()
    for u in (row.get("booking_url"), row.get("source_url")):
        ou = urlparse(str(u or ""))
        own_tokens |= _path_tokens(ou.path.lower())
        own_years.update(_YEAR_RE.findall(ou.path.lower() + "?" + ou.query.lower()))
    allowed = row_years(row) | own_years
    if any(y not in allowed for y in _YEAR_RE.findall(path + "?" + query)):
        return "other_year_path"
    if any(t in ARCHIVE_SEGMENTS and t not in own_tokens for t in _path_tokens(path)):
        return "archive_path"
    return None


def _has_money(text: str) -> bool:
    try:
        return any(m.currency and m.amount and m.amount > 0 for m in money.find_amounts(text, context=text))
    except Exception:  # noqa: BLE001
        return False


def _fee_heading(html: str) -> Optional[str]:
    """The heading (h1-h6) immediately above the first currency amount on the page."""
    hs = list(_HEADING_RE.finditer(html or ""))
    for i, m in enumerate(hs):
        end = hs[i + 1].start() if i + 1 < len(hs) else len(html)
        if _has_money(_to_text(html[m.end():end])[:20_000]):
            return _strip_tags(m.group(2))
    return None


def page_identity(row: dict, url: str, html: str, text: str, *, own: Iterable[Tuple[str, str]],
                  via_hint: bool = False, shell_titles: Iterable[str] = ()) -> Tuple[str, str]:
    """(verdict, reason) for one FETCHED page. Decision order (first match wins):
      1. any heading (h1-h4, <title>) names another shell title of the source  -> REJECTED other_shell_in_heading
      1a. URL path carries a 20xx year not the row's / an archive segment     -> REJECTED other_year_path / archive_path (FV8)
      1b. main heading, or the heading right above the first fee amount, names a
          20xx year that is not the row's (start / end / title year)            -> REJECTED other_year
          (own-path pages included; FV6)
      2. main heading = row title + an event-type word the title lacks        -> REJECTED extends_title_with_event_word
      3. main heading reads like another event (no shared distinctive word)    -> REJECTED heading_names_other_event
                                                    (acronym row: WEAK acronym_row)
      4. body / nav text names another shell title                             -> WEAK other_shell_in_body
      5. url strictly under the event's own URL path                           -> STRONG own_path
      6. main heading == row title (+ only allow-listed section words)         -> STRONG heading_equals_title
      7. url came from an extractor DISCOVERY_HINTS entry (host checked)       -> STRONG hint
      8. otherwise                                                             -> WEAK no_strong_identity"""
    title_n = _norm(row.get("conference_name"))
    others = _norm_shell_titles(row, shell_titles)
    year = str(row.get("start_date") or "")[:4]
    year = year if year.isdigit() else ""
    for h in _all_headings(html):
        if _names_other_shell(title_n, _norm(h), others):
            return REJECTED, "other_shell_in_heading"
    mains = _main_headings(html)
    edition = url_edition_reason(row, url)          # FV8: before any year exemption
    if edition:
        return REJECTED, edition
    years = row_years(row)
    if years and any(_foreign_year(h, years, row.get("start_date")) for h in mains + [_fee_heading(html) or ""]):
        return REJECTED, "other_year"
    rels = [_heading_relation(title_n, _norm(h), year) for h in mains]
    if "extends_event" in rels and not any(r in ("equal", "section") for r in rels):
        return REJECTED, "extends_title_with_event_word"
    if mains and _heading_names_other_event(row, mains[0]):
        if _ACRONYM_RE.search(row.get("conference_name") or ""):
            return WEAK, "acronym_row"
        return REJECTED, "heading_names_other_event"
    if _names_other_shell(title_n, _norm((text or "")[:250_000]), others):
        return WEAK, "other_shell_in_body"
    if _under_own_path(url, own):
        return STRONG, "own_path"
    if any(r in ("equal", "section") for r in rels):
        return STRONG, "heading_equals_title"
    if via_hint:
        return STRONG, "hint"
    return WEAK, "no_strong_identity"


# ── money-adjacent images and PDF links ──────────────────────────────────────────
def _fee_images(html: str, page_url: str, strict: bool) -> List[str]:
    """Image sources worth vision. Uses the selection core of
    explorer.find_money_images (remediator.image_scan) without that function's
    process-global image/time counters: the per-source ledger here is the budget."""
    try:
        from remediator.image_scan import select_fee_images
        return [c.src for c in select_fee_images(html, page_url, strict=strict)]
    except Exception as e:  # noqa: BLE001
        logger.debug(f"discovery: image scan failed: {e}")
        return []


_PDF_ANCHOR_RE = re.compile(r"<a\b[^>]*?href=[\"']([^\"']+?\.pdf)(?:[?#][^\"']*)?[\"'][^>]*>(.{0,400}?)</a>", re.I | re.S)
_PDF_KIND_RX = {
    FIELD_FEES: re.compile(r"fee|price|pricing|cost|registration|brochure|rates?\b|tariff|programme|program\b", re.I),
    FIELD_ABSTRACT: re.compile(r"abstract|call[-_ ]for|submission|poster|guidelines?\s+for\s+authors", re.I),
    FIELD_VENUE: re.compile(r"venue|travel|location|getting|directions|programme|general[-_ ]info", re.I),
}
_PDF_NEG_RE = re.compile(r"endorse|application|sponsor|exhibit|terms|conditions|privacy|cancellation|policy|visa", re.I)


def _pdf_links(html: str, page_url: str) -> List[Tuple[str, str]]:
    out, seen = [], set()
    for m in _PDF_ANCHOR_RE.finditer(html or ""):
        url = urljoin(page_url, _html.unescape(m.group(1).strip()))
        if urlparse(url).scheme not in ("http", "https") or url in seen:
            continue
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(2))).strip()
        label = f"{urlparse(url).path.rsplit('/', 1)[-1]} {text}"
        seen.add(url)
        out.append((url, label))
    return out


# ── engine ───────────────────────────────────────────────────────────────────────
def missing_fields(row: dict) -> List[str]:
    """Which of fees / venue / abstract the row still lacks."""
    out = []
    if not row.get("pricing_tiers"):
        out.append(FIELD_FEES)
    fmt = (row.get("event_format") or "").lower()
    if fmt != "online" and not (row.get("venue_name") and row.get("city")):
        out.append(FIELD_VENUE)
    if not (row.get("abstract_deadline") or row.get("abstract_deadline_note")
            or row.get("abstract_open") is True):
        out.append(FIELD_ABSTRACT)
    return out


class _Run:
    def __init__(self, row, budget, hints, own=(), shell_titles=()):
        self.row, self.budget, self.hints = row, budget, hints
        self.own = [o for o in own if o]
        self.shell_titles = list(shell_titles or ())
        self.res = DiscoveryResult()
        self.t0 = budget.clock()
        self.wall = budget.wall_seconds
        self.missing = set(missing_fields(row))
        self.today = date.today()
        self.start = _is_date(row.get("start_date"))
        self.images: List[str] = []
        self.pdfs: List[Tuple[str, str]] = []

    # clock
    def left(self) -> float:
        return self.wall - (self.budget.clock() - self.t0)

    def need(self, f: str) -> bool:
        if f not in self.missing:
            return False
        if f == FIELD_FEES:
            return not self.res.tiers
        if f == FIELD_VENUE:
            return not ((self.res.venue_name or self.row.get("venue_name"))
                        and (self.res.city or self.row.get("city")))
        return not self.res.has_abstract()

    def any_needed(self) -> bool:
        return any(self.need(f) for f in _FIELD_ORDER)

    def log(self, step: str, url: str, found: List[str], t_start: float) -> None:
        self.res.evidence.append({"step": step, "url": url, "found": found,
                                  "elapsed_ms": int((self.budget.clock() - t_start) * 1000)})

    # parsing one body of text/html
    def parse(self, html: str, text: str, lines_text: str, url: str, *, external: bool,
              step: str, t_start: float, allow_images: bool = True, verify: bool = False,
              via_hint: bool = False) -> bool:
        """Parse one body. `verify=True` (every FETCHED page) runs the fail-closed identity
        gate first: only a STRONG page contributes data, images, PDFs or links; a WEAK or
        REJECTED page is recorded in evidence and contributes NOTHING. Returns False then."""
        found: List[str] = []
        ident: Optional[Tuple[str, str]] = None
        if verify:
            ident = page_identity(self.row, url, html, text, own=self.own, via_hint=via_hint,
                                  shell_titles=self.shell_titles)
            if ident[0] != STRONG:
                reason = "weak_identity" if ident[0] == WEAK else "identity_mismatch"
                self.res.evidence.append({"step": step, "url": url, "found": [reason], "reason": reason,
                                          "identity": ident[0], "detail": ident[1],
                                          "elapsed_ms": int((self.budget.clock() - t_start) * 1000)})
                return False
        if self.need(FIELD_FEES):
            if external and _is_ticketing_host(url):
                # identity + same-date gated, holding fees / deposits removed (explorer)
                tiers, how = _clean_tiers(_call("ticketing_host_tiers", self.row, text, html) or []), "ticketing_host"
            else:
                tiers, how = _fees_from(html, lines_text)
            if tiers:
                self.res.tiers = tiers
                found.append(f"fees:{len(tiers)} via {how}")
        if self.need(FIELD_VENUE):
            pl = _place_from(html, text, url)
            if pl:
                if pl.get("venue_name") and not self.res.venue_name and not self.row.get("venue_name"):
                    self.res.venue_name = pl["venue_name"]
                if pl.get("city") and not self.res.city and not self.row.get("city"):
                    self.res.city = pl["city"]
                found.append(f"venue:{pl.get('method')}")
        if self.need(FIELD_ABSTRACT):
            try:
                from extractors.abstract_classifier import classify_submission
                is_open, deadline, note = classify_submission(text, self.today, self.start)
                if deadline or note or is_open:
                    self.res.abstract_open = bool(is_open)
                    self.res.abstract_deadline = deadline.isoformat() if deadline else None
                    self.res.abstract_deadline_note = note
                    found.append(f"abstract:{'deadline' if deadline else 'note'}")
            except Exception as e:  # noqa: BLE001
                logger.debug(f"discovery: abstract classify failed: {e}")
        if html:
            if allow_images and self.need(FIELD_FEES):
                for src in _fee_images(html, url, strict=(step == "page")):
                    if src not in self.images:
                        self.images.append(src)
            for u, label in _pdf_links(html, url):
                if all(u != p[0] for p in self.pdfs):
                    self.pdfs.append((u, label))
        self.log(step, url, found, t_start)
        if ident:
            self.res.evidence[-1].update(identity=ident[0], detail=ident[1])
        return True


def own_paths(row: dict) -> List[Tuple[str, str]]:
    """The event's own URL paths: booking_url and source_url (fragments ignored); a stored
    URL that is a strict ANCESTOR of the other one is a listing, not the event's own path."""
    own = [o for o in (_own_path(u) for u in (row.get("booking_url"), row.get("source_url")) if u) if o]
    return [o for o in own if not any(x != o and x[0] == o[0] and x[1].startswith(o[1] + "/") for x in own)]


def under_own_paths(url: str, row: dict) -> bool:
    """`url` sits strictly under one of the row's own URL paths."""
    return _under_own_path(url, own_paths(row))


def is_shared_page(row: dict, base_url: str, shared: bool = False) -> bool:
    """A page that may carry several events: the caller says so (base URL shared by >= 2
    shells), or the page / the row's booking URL carries a #fragment."""
    if shared:
        return True
    return any("#" in str(u or "") for u in (base_url, row.get("booking_url")))   # incl. a bare "#" (SCCM)


# ── the event's own page: other-shell checks (FV6) ───────────────────────────────
# FV7 (ReDoS): every character has exactly ONE way to be consumed. A tag never spans another
# "<"; a "<" / "&" that does not open a tag / entity falls to the single-character branch
# only then. Possessive quantifiers (Python >= 3.11; CI pins 3.11) stop any re-split on a
# failed match. Separators are still: tags, entities, any non-word character, "_".
_RAW_SEP = (r"(?:<[^<>]*>|&[A-Za-z#0-9]+;|[^\w<&]|_|<(?![^<>]*>)|&(?![A-Za-z#0-9]+;))++")
_RAW_STOP = r"(?:(?:the|and|of)" + _RAW_SEP + r")*+"
SIBLING_SCAN_CHARS = 400_000   # Level 2 (FV7): raw-html window scanned per call after `after`


def _phrase_rx(norm_phrase: str) -> "re.Pattern[str]":
    """Matches a _norm()-form phrase in RAW html (tags, entities, punctuation and the
    stop words the/and/of allowed between its words)."""
    words = norm_phrase.split()
    body = (_RAW_SEP + _RAW_STOP).join(re.escape(w) for w in words)
    return re.compile(r"(?<![^\W_])" + body + r"(?![^\W_])", re.I)


def _blank_scripts(html: str) -> str:
    """script/style/noscript bodies replaced by spaces of the same length (offsets kept)."""
    return re.sub(r"(?is)<(script|style|noscript)\b.*?</\1\s*>", lambda m: " " * len(m.group(0)), html or "")


def _first_sibling_offset(html: str, title_n: str, others: List[str], after: int = 0) -> Optional[int]:
    """Offset in `html` of the first occurrence at or after `after` of any sibling shell
    title (a shorter sibling inside the row's own title does not count), or None."""
    h = _blank_scripts(html)
    end = min(len(h), after + SIBLING_SCAN_CHARS)   # beyond it: not found -> callers fail closed
    mine = [m.span() for m in _phrase_rx(title_n).finditer(h, 0, end)] if title_n else []
    best: Optional[int] = None
    for o in others:
        inside_ok = bool(title_n) and _has(o, title_n)
        for m in _phrase_rx(o).finditer(h, after, end):
            if not inside_ok and any(a <= m.start() and m.end() <= b for a, b in mine):
                continue
            if best is None or m.start() < best:
                best = m.start()
            break
    return best


def own_page_scope(row: dict, html: str, text: str, shell_titles: Iterable[str]) -> Tuple[str, str, str, Optional[str]]:
    """(html, text, lines, reason) the discovery pass may read on the event's OWN page.
    Rule 1: a heading (h1-h4, <title>) names another shell -> nothing at all
            (reason own_page_names_other_shell: no fees, venue, images or PDFs).
    Rule 4: another shell is named only in body / nav -> reason own_page_sibling_in_body and
            only a window is read: from the page's main <h1> up to the first sibling
            occurrence AFTER it (mentions above the h1 are site menus / banners and the
            window excludes them); a page without an <h1> keeps only the html before the
            first occurrence; the window never runs past the raw scan cap (start +
            SIBLING_SCAN_CHARS) and must itself name no sibling; a sibling named only in
            the caller text -> nothing. Sibling detection reads ALL visible text (FV8). (Level 2, FV6: the literal "before the first occurrence" rule
            cut the whole event content of pages whose mega-menu lists sibling meetings.)
    Otherwise the whole page, reason None. The extractor's own output is never touched."""
    title_n = _norm(row.get("conference_name"))
    others = _norm_shell_titles(row, shell_titles)
    full_text = text or _to_text(html)
    if not others:
        return html, full_text, _to_lines(html), None
    for h in _all_headings(html):
        if _names_other_shell(title_n, _norm(h), others):
            return "", "", "", "own_page_names_other_shell"
    # FV8: ALL visible text (no 250 k cap) decides whether the page names a sibling
    html_hit = _names_other_shell(title_n, _norm(_to_text(html, limit=None)), others)
    if not (html_hit or _names_other_shell(title_n, _norm(text or ""), others)):
        return html, full_text, _to_lines(html), None
    if not html_hit:
        return "", "", "", "own_page_sibling_in_body"         # named only in the caller's text
    h1 = next((m for m in re.finditer(r"<h1\b[^>]*>(.*?)</h1\s*>", _blank_scripts(html), re.I | re.S)
               if _strip_tags(m.group(1))), None)
    start = h1.start() if h1 else 0
    cut = _first_sibling_offset(html, title_n, others, after=start)
    if cut is None:
        # FV8: the raw scan stops at its cap; the window never extends past what was scanned
        cut = min(len(html), start + SIBLING_SCAN_CHARS)
    win = html[start:cut]
    if _names_other_shell(title_n, _norm(_to_text(win, limit=None)), others):
        return "", "", "", "own_page_sibling_in_body"         # a mention the raw matcher missed
    return win, _to_text(win), _to_lines(win), "own_page_sibling_in_body"


def _pdf_head_reason(run: "_Run", txt: str, url: Optional[str] = None) -> Optional[str]:
    """A PDF whose URL is a prior edition's (FV8), or whose first 2,000 characters name
    another shell title or a 20xx year that is not the row's, is not this event's document."""
    edition = url_edition_reason(run.row, url) if url else None
    if edition:
        return f"pdf_{edition}"
    head = (txt or "")[:2000]
    others = _norm_shell_titles(run.row, run.shell_titles)
    if others and _names_other_shell(_norm(run.row.get("conference_name")), _norm(head), others):
        return "pdf_names_other_shell"
    years = row_years(run.row)
    if years and _foreign_year(head, years, run.row.get("start_date")):
        return "pdf_other_year"
    return None


def discover(row: dict, page_html: str, page_text: str, base_url: str, *,
             hints: Optional[DiscoveryHints] = None,
             budget: Optional[DiscoveryBudget] = None,
             skip_urls: Iterable[str] = (),
             shared: bool = False,
             shell_titles: Iterable[str] = (),
             sibling_titles: Iterable[str] = ()) -> DiscoveryResult:
    """Find missing fees / venue / abstract info on linked pages, a PDF and fee
    images. Never raises, never calls a text LLM. `skip_urls`: pages already
    followed by the caller (e.g. the call-for-papers link of _ensure_submission_info).
    `shell_titles`: the titles of the source's OTHER shells; a fetched page naming one in
    a heading is rejected, in its body it is weak (see page_identity).
    `shared=True` or a #fragment row: the page carries several events -> NO scrape-time
    discovery at all (evidence [{"step": "skip", "reason": "shared_page"}]); the nightly
    remediator's windowed guard owns shared pages."""
    budget = budget or DiscoveryBudget()
    row = row or {}
    if is_shared_page(row, base_url or "", shared):
        res = DiscoveryResult()
        res.evidence.append({"step": "skip", "reason": "shared_page", "url": base_url or "", "found": [], "elapsed_ms": 0})
        return res
    own = own_paths(row)
    if not own and not (row.get("booking_url") or row.get("source_url")):
        own = [_own_path(base_url or "")]        # no stored URL: the page the caller holds is the event's
    run = _Run(row, budget, hints, own=own, shell_titles=list(shell_titles or ()) + list(sibling_titles or ()))
    try:
        _discover(run, page_html or "", page_text or "", base_url or "", {_page_key(u) for u in skip_urls if u})
    except Exception as e:  # noqa: BLE001
        logger.warning(f"discovery: aborted ({type(e).__name__}: {e})")
        run.res.evidence.append({"step": "error", "url": base_url, "found": [type(e).__name__], "elapsed_ms": 0})
    return run.res


def _discover(run: _Run, html: str, text: str, base_url: str, skip: set) -> None:
    b, res = run.budget, run.res
    if not run.missing or not base_url:
        return

    # 1. the page the caller already has (abstract info there is the caller's job)
    t = b.clock()
    page_missing_abs = FIELD_ABSTRACT in run.missing
    run.missing.discard(FIELD_ABSTRACT)
    # the event's own page (the extractor's page, not fetched here) is the row's identity
    # itself, but a related-events box naming ANOTHER shell is not (FV6 own_page_scope)
    o_html, o_text, o_lines, o_reason = own_page_scope(run.row, html, text, run.shell_titles)
    if o_reason:
        res.evidence.append({"step": "page", "url": base_url, "found": [o_reason], "reason": o_reason,
                             "elapsed_ms": int((b.clock() - t) * 1000)})
    if o_reason != "own_page_names_other_shell" and (o_html or o_lines):
        run.parse(o_html, o_text, o_lines, base_url, external=False, step="page", t_start=t)
    hints = run.hints
    if page_missing_abs:
        run.missing.add(FIELD_ABSTRACT)

    # 2. at most max_html sub-pages, one round-robin pass over the missing fields
    pools = {f: _candidates(f, html, base_url, run.row, hints, skip) for f in _FIELD_ORDER if f in run.missing}
    tried: set = set(skip)
    fetched = 0
    while fetched < b.max_html and run.any_needed() and run.left() > 1.0:
        cand = None
        for f in _FIELD_ORDER:
            if not run.need(f):
                continue
            while pools.get(f):
                c = pools[f].pop(0)
                if _page_key(c["url"]) not in tried:
                    cand = c
                    break
            if cand:
                break
        if cand is None:
            break
        tried.add(_page_key(cand["url"]))
        t = b.clock()
        body = _fetch_html(cand["url"], max(1.0, min(b.html_timeout, run.left())))
        fetched += 1
        step = f"fetch:{cand['field']}:{cand['why']}" + (":external" if cand["external"] else "")
        if not body:
            run.log(step, cand["url"], ["fetch_failed"], t)
            continue
        accepted = run.parse(body, _to_text(body), _to_lines(body), cand["url"], external=cand["external"],
                             step=step, t_start=t, verify=True, via_hint=cand["why"] == "hint")
        if accepted and fetched < b.max_html and not (cand["external"] and _is_ticketing_host(cand["url"])):
            # the fetched page's own links (same host as it) lead the pools: this is how
            # organiser_url (a homepage) reaches its /abstracts or /registration page
            for f in _FIELD_ORDER:
                if not run.need(f):
                    continue
                deeper = [dict(c, external=cand["external"])
                          for c in _candidates(f, body, cand["url"], run.row, hints, tried)
                          if c["why"] not in ("organiser_url", "linked_event_site")]
                pools[f] = deeper + pools.get(f, [])

    # 3. ONE PDF for whatever is still missing
    if run.any_needed() and run.pdfs and b.max_pdf > 0 and run.left() > PDF_MIN_FETCH + PDF_MIN_PARSE:
        _follow_pdf(run)

    # 4. fee images (vision), inside the per-source ledger
    if run.need(FIELD_FEES) and run.images:
        _read_images(run)


def _pick_pdf(run: _Run) -> Optional[Tuple[str, str, str]]:
    ranked = []
    for f in _FIELD_ORDER:
        if not run.need(f):
            continue
        for url, label in run.pdfs:
            if _PDF_NEG_RE.search(label) and f != FIELD_ABSTRACT:
                continue
            if f == FIELD_ABSTRACT and re.search(r"endorse|application|sponsor|exhibit|terms|privacy", label, re.I):
                continue
            if _PDF_KIND_RX[f].search(label):
                ranked.append((_FIELD_ORDER.index(f), url, label, f))
                break
    if not ranked:
        return None
    ranked.sort()
    _, url, label, f = ranked[0]
    return url, label, f


def _follow_pdf(run: _Run) -> None:
    pick = _pick_pdf(run)
    if not pick:
        return
    url, _label, fieldname = pick
    t = run.budget.clock()
    # the fetch may use the budget's PDF timeout, but never the slice the parse needs
    data = _fetch_bytes(url, max(PDF_MIN_FETCH, min(run.budget.pdf_timeout, run.left() - PDF_MIN_PARSE)), PDF_MAX_BYTES)
    if not data:
        run.log(f"pdf:{fieldname}", url, ["fetch_rejected"], t)
        return
    if run.left() < PDF_MIN_PARSE:
        run.log(f"pdf:{fieldname}", url, ["budget_exhausted"], t)
        return
    txt = _pdf_text(data, run.left())
    if len(txt.strip()) < 40:
        run.log(f"pdf:{fieldname}", url, ["no_text_layer"], t)
        return
    why = _pdf_head_reason(run, txt, url)
    if why:
        run.res.evidence.append({"step": f"pdf:{fieldname}", "url": url, "found": [why], "reason": why,
                                 "elapsed_ms": int((run.budget.clock() - t) * 1000)})
        return
    flat = re.sub(r"\s+", " ", txt)
    run.parse("", flat[:250_000], txt, url, external=False, step=f"pdf:{fieldname}", t_start=t, allow_images=False)


def _read_images(run: _Run) -> None:
    b, res, led = run.budget, run.res, run.budget.vision
    if not _vision_allowed():
        res.deferred.append("fee_image_pending")
        run.log("vision", "", ["skipped_safe_mode"], b.clock())
        return
    # the vision phase may use the long wall clock
    run.wall = max(run.wall, b.wall_seconds_vision)
    for src in run.images:
        if res.tiers:
            break
        if led.images_left() <= 0 or led.seconds_left() < 5.0 or run.left() < 5.0:
            res.deferred.append("fee_image_pending")
            run.log("vision", "", ["budget_exhausted"], b.clock())
            return
        t = b.clock()
        limit = min(led.seconds_left(), run.left(), 60.0)
        led.images_used += 1
        try:
            vt = _vision_pricing([src], time.time() + limit, limit)
        except Exception as e:  # noqa: BLE001
            vt = []
            logger.debug(f"discovery: vision failed: {type(e).__name__}")
        led.seconds_used += b.clock() - t
        got = _call("usable_vision_tiers", vt) if vt else []
        if got is None:
            got = [x for x in vt if x.get("currency")]
        tiers = _clean_tiers(got)
        label = "data-image" if src.startswith("data:") else src[:120]
        if tiers:
            res.tiers = tiers
        run.log("vision", label, [f"fees:{len(tiers)}"] if tiers else [], t)


# ── merge ────────────────────────────────────────────────────────────────────────
def apply_to_row(row: dict, res: DiscoveryResult) -> List[str]:
    """Merge a result into EMPTY fields of `row`; returns the fields written."""
    written: List[str] = []
    if res.tiers and not row.get("pricing_tiers"):
        row["pricing_tiers"] = res.tiers
        written.append("pricing_tiers")
    if res.venue_name and not row.get("venue_name"):
        row["venue_name"] = res.venue_name
        written.append("venue_name")
    if res.city and not row.get("city"):
        row["city"] = res.city
        written.append("city")
    if res.has_abstract() and not (row.get("abstract_deadline") or row.get("abstract_deadline_note")
                                   or row.get("abstract_open") is True):
        row["abstract_open"] = bool(res.abstract_open)
        row["abstract_deadline"] = res.abstract_deadline
        row["abstract_deadline_note"] = res.abstract_deadline_note
        written.append("abstract")
    return written
