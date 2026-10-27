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
    "discover", "apply_to_row", "missing_fields",
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
def _fetch_html(url: str, timeout: float) -> Optional[str]:
    """HTML body or None. extractors.http_fetch.fetch_html with no browser: honours
    the timeout and the safe-fetch flag (SafeClient), recognises bot-block pages and
    never launches Playwright."""
    try:
        from extractors import http_fetch
        return http_fetch.fetch_html(url, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"discovery: fetch failed {url}: {type(e).__name__}")
        return None


def _fetch_bytes(url: str, timeout: float, max_bytes: int = PDF_MAX_BYTES) -> Optional[bytes]:
    """PDF bytes (<= max_bytes, `%PDF` header) or None."""
    try:
        import safe_fetch
        if safe_fetch.enabled():
            verdict, _final, body, _enc, _st = safe_fetch.fetch_validated(
                url, safe_fetch.check_url_safe, max_bytes=max_bytes + 1,
                deadline=time.monotonic() + timeout)
            data = body if verdict == "ok" else None
        else:
            import httpx
            buf = bytearray()
            end = time.monotonic() + timeout
            with httpx.Client(timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0)), follow_redirects=True,
                              headers={"User-Agent": "Mozilla/5.0 (compatible; MedConfBot)"}) as c:
                with c.stream("GET", url) as r:
                    r.raise_for_status()
                    try:
                        if int(r.headers.get("content-length") or 0) > max_bytes:
                            return None
                    except ValueError:
                        pass
                    for chunk in r.iter_bytes():
                        buf.extend(chunk)
                        if len(buf) > max_bytes or time.monotonic() > end:
                            return None
            data = bytes(buf)
        if not data or len(data) > max_bytes or not data.startswith(b"%PDF"):
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


def _vision_pricing(image_urls: List[str], stop_at: float) -> List[Dict[str, Any]]:
    import vision
    return vision.extract_pricing_from_images(image_urls, stop_at=stop_at)


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


def _to_text(html: str) -> str:
    h = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1\s*>", " ", html or "")
    t = _html.unescape(re.sub(r"<[^>]+>", " ", h))
    return re.sub(r"\s+", " ", t).strip()[:250_000]


def _to_lines(html: str) -> str:
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
def _hint_candidates(fieldname: str, page_url: str, row: dict, hints: Optional[DiscoveryHints]) -> List[str]:
    if not hints:
        return []
    attr = _HINT_ATTR[fieldname]
    clean = page_url.split("#")[0].split("?")[0].rstrip("/")
    pu = urlparse(page_url)
    ctx = {"url": clean, "base": f"{pu.scheme}://{pu.netloc}",
           "year": (str(row.get("start_date") or "")[:4] or ""),
           "slug": clean.rsplit("/", 1)[-1]}
    out: List[str] = []
    for suf in getattr(hints, f"{attr}_suffixes", ()) or ():
        out.append(clean + suf if not suf.startswith("?") else clean + suf)
    for tpl in getattr(hints, f"{attr}_urls", ()) or ():
        try:
            out.append(tpl.format(**ctx))
        except (KeyError, IndexError, ValueError):
            continue
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


def _in_event_path(base_url: str, url: str) -> bool:
    """True only when `url` sits under the event page's OWN URL path
    (/events/conferences/<slug>/registration for the page /events/conferences/<slug>).
    The PARENT directory does not count: its other children are other events."""
    b, u = urlparse(base_url), urlparse(url)
    own = "/".join(x for x in b.path.split("/") if x)
    if not own or _host(base_url) != _host(url):
        return False
    return (u.path.rstrip("/") + "/").startswith("/" + own + "/")


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

    for u in _hint_candidates(fieldname, page_url, row, hints):
        add(u, "hint", 0)
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


def _money_sweep(lines_text: str) -> List[Dict[str, Any]]:
    """Fee-context sweep: every line with a currency-bearing amount under fee
    context (a fee word in the label or the 12 lines above), side charges and
    sponsor/hotel amounts excluded, ranges skipped. One tier needs a fee word on
    its own line; otherwise >= 1 labelled tier under a fee heading."""
    lines = [re.sub(r"[ \t\xa0]+", " ", l).strip() for l in (lines_text or "").split("\n")]
    lines = [l for l in lines if l]
    head = (lines_text or "")[:4000]
    tiers: List[Dict[str, Any]] = []
    for i, line in enumerate(lines):
        if _SIDE_CHARGE_RE.search(line):
            continue
        try:
            found = money.find_amounts(line, context=head)
        except Exception:  # noqa: BLE001
            continue
        for mny in found:
            if mny.high is not None or mny.currency is None or mny.amount <= 0:
                continue
            label = _label_for(lines, i, mny, head)
            if label is None:
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


def _identity_ok(row: dict, text: str) -> bool:
    got = _call("external_identity_ok", row, text)
    if got is not None:
        return bool(got)
    low = (text or "").lower()
    toks = {t for t in re.findall(r"[a-z0-9]{5,}", (row.get("conference_name") or "").lower())
            if t not in {"annual", "meeting", "conference", "congress", "course", "international"}}
    return any(t in low for t in toks)


# ── identity of a fetched page ───────────────────────────────────────────────────
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
_DATE_FORMATS = ("%d %B %Y", "%B %d, %Y", "%B %d %Y", "%d %b %Y", "%b %d, %Y", "%d/%m/%Y", "%Y-%m-%d", "%d %B", "%B %d")
ID_MIN_TOKENS_SMALL, ID_MIN_TOKENS_LARGE = 1, 2     # Level-2 decision: >= 3 title tokens need 2 hits off the event's own path


def _row_tokens(row: dict) -> set:
    name = row.get("conference_name") or ""
    toks = {t for t in re.findall(r"[a-z0-9]{4,}", name.lower()) if t not in _ID_WEAK and not t.isdigit()}
    toks |= {t.lower() for t in re.findall(r"\b[A-Z]{3}\b", name)}
    return toks


def _date_in_text(row: dict, low: str) -> bool:
    d = _is_date(row.get("start_date"))
    if not d:
        return False
    for f in _DATE_FORMATS[:7]:
        try:
            if d.strftime(f).lower().lstrip("0") in low or d.strftime(f).lower() in low:
                return True
        except ValueError:
            pass
    return False


def _heading_of(html: str) -> str:
    """The page's own heading: first <h1>, else the first segment of <title>."""
    m = re.search(r"<h1\b[^>]*>(.*?)</h1\s*>", html or "", re.I | re.S)
    if not m:
        m = re.search(r"<title\b[^>]*>(.*?)</title\s*>", html or "", re.I | re.S)
        if m:
            seg = re.split(r"\s[|\u2013\u2014-]\s|\|", _html.unescape(m.group(1)))[0]
            return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", seg)).strip()
        return ""
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip()


def _heading_names_other_event(row: dict, heading: str) -> bool:
    """The heading reads like an EVENT name (an event noun or a year plus at least one
    distinctive word) and shares no distinctive word with this row's title."""
    toks = _row_tokens(row)
    if not heading or not toks:
        return False
    low = heading.lower()
    if any(t in low for t in toks):
        return False
    words = {w for w in re.findall(r"[a-z]{4,}", low) if w not in _ID_WEAK and w not in _HEAD_GENERIC}
    return bool(words) and bool(_EVENT_NOUN_RE.search(heading))


def _page_identity_problem(row: dict, html: str, text: str, kind: str) -> Optional[str]:
    """None when the fetched page is this event's; else the reason it is not.
    kind: "own" (under the event's own URL path), "site" (same host, elsewhere),
    "external" (another host the event page linked to)."""
    if _heading_names_other_event(row, _heading_of(html)):
        return "heading_names_other_event"
    if kind == "external":
        return None if _identity_ok(row, text) else "no_identity"
    if kind == "own":
        return None                 # the page's address sits under the event's own URL: that is the identity evidence
    low = (text or "").lower()
    toks = _row_tokens(row)
    hits = sum(1 for t in toks if t in low)
    need = 1 if len(toks) < 3 else ID_MIN_TOKENS_LARGE
    if toks and hits >= min(need, len(toks)):
        return None
    if _date_in_text(row, low):
        return None
    return "no_identity"


# ── shared pages (one URL, several events) ───────────────────────────────────────
SHARED_WINDOW_LINES = 60


def _squash(x: Any) -> str:
    return re.sub(r"\s+", " ", str(x or "")).strip().lower()


def _shared_window(row: dict, html: str, sibling_titles: Iterable[str]) -> Optional[Tuple[str, str]]:
    """(lines_text, flat_text) of the part of a shared page that belongs to THIS row:
    from the line carrying its full title up to the next sibling's title (mirrors
    remediator.runner.identity_window). None when the title is not found, or only
    inside a longer sibling's title."""
    title = _squash(row.get("conference_name"))
    if len(title) < 6:
        return None
    lines = [l for l in (re.sub(r"\s+", " ", x).strip() for x in _to_lines(html).split("\n")) if l]
    sibs = {_squash(t) for t in sibling_titles}
    sibs = {t for t in sibs if len(t) >= 6 and t != title}
    longer = [t for t in sibs if title in t]
    start, pos0 = -1, 0
    for i, l in enumerate(lines):
        low = l.lower()
        p = low.find(title)
        while p >= 0:
            inside = any(low.startswith(t, q) for t in longer
                         for q in range(max(0, p - len(t) + len(title)), p + 1))
            if not inside:
                start, pos0 = i, p
                break
            p = low.find(title, p + 1)
        if start >= 0:
            break
    if start < 0:
        return None
    end = min(len(lines), start + SHARED_WINDOW_LINES)
    first = lines[start][pos0:]
    cut = len(first)
    for t in sibs:
        j = first.lower().find(t, len(title))
        if 0 <= j < cut:
            cut = j
    out = [first[:cut]]
    if cut == len(first):
        for k in range(start + 1, end):
            low = lines[k].lower()
            hit = [low.find(t) for t in sibs if t in low]
            if hit:
                if min(hit) > 0:
                    out.append(lines[k][:min(hit)])
                break
            out.append(lines[k])
    win = [l for l in out if l.strip()]
    return "\n".join(win), " ".join(win)[:250_000]


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
    def __init__(self, row, budget, hints):
        self.row, self.budget, self.hints = row, budget, hints
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
              step: str, t_start: float, allow_images: bool = True, verify: Optional[str] = None) -> bool:
        """Parse one body. `verify` ("own" | "site" | "external") runs the identity check
        first; a page that fails it contributes NOTHING. Returns False when rejected."""
        found: List[str] = []
        if verify:
            why = _page_identity_problem(self.row, html, text, verify)
            if why:
                self.res.evidence.append({"step": step, "url": url, "found": ["identity_mismatch"],
                                          "reason": "identity_mismatch", "detail": why,
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
        return True


def discover(row: dict, page_html: str, page_text: str, base_url: str, *,
             hints: Optional[DiscoveryHints] = None,
             budget: Optional[DiscoveryBudget] = None,
             skip_urls: Iterable[str] = (),
             shared: bool = False,
             sibling_titles: Iterable[str] = ()) -> DiscoveryResult:
    """Find missing fees / venue / abstract info on linked pages, a PDF and fee
    images. Never raises, never calls a text LLM. `skip_urls`: pages already
    followed by the caller (e.g. the call-for-papers link of
    _ensure_submission_info). `shared=True`: the page carries several events
    (calendar page, #fragment row); only the row's own title block is parsed and no
    link of the page is followed (organiser_url still is, behind the identity check);
    when no block can be found nothing is discovered (evidence shared_page_no_window)."""
    budget = budget or DiscoveryBudget()
    shared = bool(shared) or bool(urlparse(base_url or "").fragment)     # a #fragment row lives on a shared page
    run = _Run(row or {}, budget, hints)
    try:
        _discover(run, page_html or "", page_text or "", base_url or "",
                  {_page_key(u) for u in skip_urls if u}, shared=shared, siblings=list(sibling_titles or ()))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"discovery: aborted ({type(e).__name__}: {e})")
        run.res.evidence.append({"step": "error", "url": base_url, "found": [type(e).__name__], "elapsed_ms": 0})
    return run.res


def _discover(run: _Run, html: str, text: str, base_url: str, skip: set,
              shared: bool = False, siblings: Optional[List[str]] = None) -> None:
    b, res = run.budget, run.res
    if not run.missing or not base_url:
        return

    # 1. the page the caller already has (abstract info there is the caller's job)
    t = b.clock()
    page_missing_abs = FIELD_ABSTRACT in run.missing
    run.missing.discard(FIELD_ABSTRACT)
    if shared:
        win = _shared_window(run.row, html, siblings or [])
        if win is None:
            run.log("page", base_url, ["shared_page_no_window"], t)
            res.evidence[-1]["reason"] = "shared_page_no_window"
            return
        # only this row's block is read; nothing of the shared page is followed
        run.parse("", win[1], win[0], base_url, external=False, step="page:window", t_start=t)
        html, hints = "", None
    else:
        run.parse(html, text or _to_text(html), _to_lines(html), base_url, external=False, step="page", t_start=t)
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
        kind = ("external" if cand["external"] else
                "own" if (cand["why"] in ("hint", "hint_anchor") or _in_event_path(base_url, cand["url"])) else "site")
        accepted = run.parse(body, _to_text(body), _to_lines(body), cand["url"], external=cand["external"],
                             step=step, t_start=t, verify=kind)
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
            vt = _vision_pricing([src], time.time() + limit)
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
