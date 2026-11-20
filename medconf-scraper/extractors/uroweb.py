# extractors/uroweb.py
"""
EAU (European Association of Urology) — Event Calendar extractor.

Wave 2b source. https://uroweb.org/education-events/events is a Nuxt app that
is server-rendered, and (verified 2026-11-20) `?page=N` IS honoured by the
server: every page ships the calendar's entries inside the
`<script id="__NUXT_DATA__">` payload (Nuxt "devalue" format: one flat JSON
array, objects refer to each other by index), 16 entries per page, together
with the site's own `entryCount` (42 on 2026-11-20 = 16 + 16 + 10; page 4 is
empty). The visible HTML holds only 6 `card card--small` blocks, so the
payload — not the cards — is the complete source.

  1. Fetch `?page=1..N` with `http_fetch.fetch_html` (plain httpx, project
     default user agent; robots.txt is `Disallow:` empty) at ≤1 request/s
     until `entryCount` is reached or a page comes back empty.
  2. Decode the payload and keep upcoming entries (end date today or later).
     On-demand entries live in a different Craft entry type and are not part
     of this listing.
  3. Detail pages are server-rendered: `.lead`/first paragraph, a
     `table .event-details__label/.event-details__value` metadata block
     (Organiser, CME, Venue, Location "City, Country", Registration open).

History: until 2026-11-16 the listing was paged from the Craft GraphQL
endpoint with a bearer token sniffed from the browser; that capture stopped
working ("could not capture the site's GraphQL authorization header") and the
whole token-capture path was removed on 2026-11-20.

No fees are published on EAU pages (registration happens on the organiser's
site), so pricing_tiers is always [].
"""

import json
import logging
import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Page

from .abstract_classifier import extract_abstract_info
from .base import BaseExtractor

logger = logging.getLogger("medconf-scraper")

LISTING_URL = "https://uroweb.org/education-events/events"
SITE_ROOT = "https://uroweb.org/"
PAGE_SIZE = 16
REQUEST_GAP_S = 1.0
MAX_PAGES = 30  # hard stop: 30 * 16 = 480, far above the real total (42)

_NUXT_DATA_RE = re.compile(
    r'<script[^>]*\bid="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S
)
_WRAPPERS = {"Reactive", "ShallowReactive", "Ref", "ShallowRef", "EmptyRef", "EmptyShallowRef"}


def _resolve(data: List[Any], idx: Any, depth: int = 0) -> Any:
    """Resolve one node of a Nuxt devalue payload into plain Python values."""
    if not isinstance(idx, int) or idx < 0 or idx >= len(data) or depth > 8:
        return None
    v = data[idx]
    if isinstance(v, dict):
        return {k: _resolve(data, x, depth + 1) for k, x in v.items()}
    if isinstance(v, list):
        if v and isinstance(v[0], str):
            if v[0] in _WRAPPERS and len(v) == 2:
                return _resolve(data, v[1], depth + 1)
            return None  # other tagged values (Date, Set, ...) are not used here
        return [_resolve(data, x, depth + 1) for x in v]
    return v


def parse_listing_payload(html: str) -> Optional[Dict[str, Any]]:
    """Decode a listing page. Returns {"entries": [...], "total": int|None}
    or None when the payload / entries list cannot be found (markup change)."""
    m = _NUXT_DATA_RE.search(html or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    for node in data:
        if isinstance(node, dict) and "entryCount" in node and "entries" in node:
            entries = _resolve(data, node["entries"])
            total = _resolve(data, node["entryCount"])
            if not isinstance(entries, list):
                return None
            return {
                "entries": [e for e in entries if isinstance(e, dict)],
                "total": total if isinstance(total, int) else None,
            }
    return None

_ISO_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")

# liveType → event_type. Anything not listed falls back to a title heuristic.
_TYPE_MAP = {
    "esu course": "course",
    "masterclass": "workshop",
    "webinar": "workshop",
    "annual eau congress": "conference",
    "standalone meeting": "conference",
    "section meeting": "conference",
    "regional meeting": "conference",
}


def _iso_date(value: Optional[str]) -> Optional[str]:
    """'2026-10-03T02:00:00+02:00' -> '2026-10-03' (the site's own local date)."""
    m = _ISO_RE.match(value or "")
    return m.group(1) if m else None


def _event_type(live_type: Optional[str], title: str) -> str:
    lt = (live_type or "").strip().lower()
    if lt in _TYPE_MAP:
        return _TYPE_MAP[lt]
    t = title.lower()
    if re.search(r"masterclass|workshop|webinar|seminar|training|hands-on|skills", t):
        return "workshop"
    if re.search(r"\bcourse\b|programme|academy", t):
        return "course"
    return "conference"


_CHROME_RE = re.compile(
    r"cookie|privacy|©|share this|newsletter|log in|become (?:a )?member|sign up|"
    r"subscribe|contact our organiser|e-?mail:|mailto|all rights reserved|accept all|"
    r"terms (?:of|and) (?:use|conditions)|powered by",
    re.I,
)
_BAD_LINK_HOST_RE = re.compile(
    r"laposta|mailchimp|list-manage|linkedin|facebook|instagram|youtube|twitter|(^|\.)x\.com$|"
    r"whatsapp|t\.co$",
    re.I,
)
_EUR_RE = re.compile(r"^\s*(?:€|EUR)\s*(\d[\d,.\s]*?)\s*$|^\s*(\d[\d,.\s]*?)\s*(?:€|EUR)\s*$")


def _eur(cell: str) -> Optional[float]:
    m = _EUR_RE.match((cell or "").replace("\xa0", " "))
    if not m:
        return None
    raw = (m.group(1) or m.group(2) or "").replace(" ", "").replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _clean(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


class UrowebExtractor(BaseExtractor):

    # ------------------------------------------------------------------ #
    # Phase A — listing from the server-rendered Nuxt payload, ?page=N
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        from extractors import http_fetch

        browser = getattr(self, "browser", None)
        entries: List[Dict[str, Any]] = []
        seen = set()
        total: Optional[int] = None
        for n in range(1, MAX_PAGES + 1):
            url = LISTING_URL if n == 1 else f"{LISTING_URL}?page={n}"
            html = http_fetch.fetch_html(url, browser=browser)
            if not html:
                if n == 1:
                    logger.error("uroweb: listing fetch failed — generic fallback")
                    return None
                logger.warning("uroweb: page %d fetch failed — keeping %d entries", n, len(entries))
                break
            parsed = parse_listing_payload(html)
            if parsed is None:
                if n == 1:
                    logger.error("uroweb: no __NUXT_DATA__ entries payload on page 1 (markup changed?)")
                    return None
                logger.warning("uroweb: page %d has no payload — keeping %d entries", n, len(entries))
                break
            if total is None:
                total = parsed["total"]
            batch = parsed["entries"]
            for e in batch:
                uri = e.get("uri")
                if uri and uri not in seen:
                    seen.add(uri)
                    entries.append(e)
            if not batch or (total is not None and n * PAGE_SIZE >= total):
                break
            time.sleep(REQUEST_GAP_S)

        if total is not None and len(entries) != total:
            logger.warning("uroweb: fetched %d unique of site total %s", len(entries), total)
        else:
            logger.info("uroweb: fetched %d events (site total %s)", len(entries), total)

        shells = self._shells_from_entries(entries)
        if not shells:
            self.verified_empty = (
                "EAU events calendar answered 200 and lists no upcoming event "
                f"(site entryCount {total}, {len(entries)} entries decoded, all past)"
            )
        return shells

    @staticmethod
    def _shells_from_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        today = date.today().isoformat()
        shells: List[Dict[str, Any]] = []
        for e in entries:
            title = _clean(e.get("title"))
            start = _iso_date((e.get("dateRange") or {}).get("start"))
            end = _iso_date((e.get("dateRange") or {}).get("end")) or start
            if not title or not start or not e.get("uri") or (end or start) < today:
                continue
            live_type = ((e.get("type") or [{}])[0] or {}).get("title")
            shells.append({
                "title": title,
                "booking_url": SITE_ROOT + e["uri"].lstrip("/"),
                "start_date": start,
                "end_date": end,
                "city": _clean(e.get("city")) or None,
                "venue_name": _clean(e.get("venue")) or None,
                "event_type": _event_type(live_type, title),
                "category": live_type,
                "topics": [t.get("title") for t in (e.get("topics") or []) if t and t.get("title")],
            })
        return shells

    # ------------------------------------------------------------------ #
    # Phase B — detail page
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        try:
            raw = page.evaluate(r"""() => {
                const txt = (el) => el ? (el.textContent || '') : '';
                const meta = {};
                document.querySelectorAll('.event-details tr').forEach(tr => {
                    const l = txt(tr.querySelector('.event-details__label')).trim();
                    const v = txt(tr.querySelector('.event-details__value')).trim();
                    if (l) meta[l] = v;
                });
                const lead = txt(document.querySelector('h1 ~ .lead, .lead'));
                const paras = [];
                const root = document.querySelector('main') || document.body;
                // Event body = content sections only; never the metadata table,
                // organiser contact block, share bar, header/nav/footer.
                const SKIP = '.event-details, .event-contact, .social-links, footer, nav, header, [class*=cookie], [id*=cookie]';
                root.querySelectorAll('section.section').forEach(sec => {
                    if (sec.matches(SKIP) || sec.closest(SKIP)) return;
                    sec.querySelectorAll('p').forEach(p => {
                        if (!p.closest(SKIP) && !p.closest('table')) paras.push(txt(p));
                    });
                });
                const links = [];
                root.querySelectorAll('a[href]').forEach(a => {
                    if (a.closest(SKIP)) return;
                    const t = txt(a).replace(/\s+/g, ' ').trim().toLowerCase();
                    if (/^(join event|register( here| now)?|registration|book (now|here))$/.test(t)) links.push(a.href);
                });
                const tables = [];
                root.querySelectorAll('section.section table').forEach(t => {
                    if (t.closest('.event-details, footer, nav, header')) return;
                    tables.push(Array.from(t.querySelectorAll('tr')).map(tr =>
                        Array.from(tr.querySelectorAll('th, td')).map(c => txt(c).replace(/\s+/g, ' ').trim())));
                });
                const og = document.querySelector('meta[property="og:description"], meta[name=description]');
                return {meta, lead, paras, tables, links, og: og ? og.content : '',
                        body: (root.innerText || '').slice(0, 6000)};
            }""") or {}
        except Exception as e:  # noqa: BLE001
            logger.warning("uroweb: detail evaluate failed for %s: %s", shell.get("booking_url"), e)
            return {}

        meta = raw.get("meta") or {}
        out: Dict[str, Any] = {}

        # Venue / city / country
        venue = _clean(meta.get("Venue")) or shell.get("venue_name")
        out["venue_name"] = venue or None
        location = _clean(meta.get("Location"))
        city, country = shell.get("city"), None
        if location:
            if location.lower() == "online":
                city, country = "Online", None
            else:
                parts = [p.strip() for p in location.split(",") if p.strip()]
                if parts:
                    city = parts[0]
                    country = parts[-1] if len(parts) > 1 else None
        out["city"] = city
        out["region"] = country

        # Format
        body_lc = (raw.get("body") or "").lower()
        if (city or "").lower() == "online" or location.lower() == "online":
            out["event_format"] = "online"
        elif re.search(r"\bhybrid\b", body_lc):
            out["event_format"] = "hybrid"
        else:
            out["event_format"] = "in_person" if (city or venue) else None

        # CME credits ("11.00" / "To be approved")
        cme = _clean(meta.get("CME"))
        m = re.match(r"^(\d+(?:\.\d+)?)$", cme)
        if m:
            out["cpd_points"] = float(m.group(1))
            out["cpd_accredited"] = True

        # Description: lead paragraph, else first real body paragraph, else meta.
        desc = _clean(raw.get("lead"))
        if len(desc) < 40:
            desc = ""
            for p in raw.get("paras") or []:
                p = _clean(p)
                if len(p) >= 60 and not _CHROME_RE.search(p):
                    desc = p
                    break
        if not desc:
            og = _clean(raw.get("og"))
            # The site-wide default meta description is boilerplate, not event text.
            if og and not og.startswith("European Association of Urology -"):
                desc = og
        out["description"] = desc[:1200] or None

        # Abstracts (only if the page talks about them)
        try:
            is_open, deadline = extract_abstract_info(raw.get("body") or "")
            if is_open or deadline:
                out["abstract_open"] = bool(is_open)
                out["abstract_deadline"] = deadline.isoformat() if deadline else None
        except Exception:  # noqa: BLE001
            pass

        # EAU is a urology society: every event is Urology. Topic pills are
        # sub-topics, so keep them out of the specialty field.
        out["specialty"] = "Urology"
        # The event's own website / registration page ("Join event" /
        # "Register here"). source_url stays the uroweb page (dedupe key).
        ext = self._external_link(raw.get("links") or [], shell.get("booking_url"))
        if ext:
            out["organiser_url"] = ext
            out["booking_url"] = ext
        out["pricing_tiers"] = self._fee_tiers(raw.get("tables") or [])
        out["is_sold_out"] = False
        return out

    # ------------------------------------------------------------------ #
    # Fees — rich-text tables under a "Fees and inclusions" heading:
    #   [Category | EAU Member | Non-EAU Member] + one row per category, or
    #   [EAU Member | Non-EAU Member] + a single price row.
    # Hotel room rates in prose are not registration fees and are ignored
    # (only table cells are read).
    # ------------------------------------------------------------------ #
    @staticmethod
    def _fee_tiers(tables: List[List[List[str]]]) -> List[Dict[str, Any]]:
        tiers: List[Dict[str, Any]] = []
        seen = set()
        for rows in tables:
            rows = [[_clean(c) for c in r] for r in rows if r]
            if len(rows) < 2:
                continue
            header = rows[0]
            for row in rows[1:]:
                if not any(_eur(c) is not None for c in row):
                    continue
                if _eur(row[0]) is None and len(row) >= 2:
                    category, cols, cells = row[0], header[1:], row[1:]
                else:
                    category, cols, cells = "Delegate", header, row
                for col, cell in zip(cols, cells):
                    price = _eur(cell)
                    if price is None or not col:
                        continue
                    label = f"Registration \u00b7 {category} \u00b7 {col}"[:160]
                    if (label, price) in seen:
                        continue
                    seen.add((label, price))
                    tiers.append({
                        "tier_label": label,
                        "price_gbp": price,
                        "currency": "EUR",
                        "is_early_bird": False,
                        "early_bird_deadline": None,
                    })
        return tiers

    @staticmethod
    def _external_link(links: List[str], own_url: Optional[str]) -> Optional[str]:
        from urllib.parse import urlparse
        for href in links:
            u = urlparse(href or "")
            if u.scheme not in ("http", "https") or not u.netloc:
                continue
            if _BAD_LINK_HOST_RE.search(u.netloc):
                continue
            if own_url and href.rstrip("/") == own_url.rstrip("/"):
                continue
            return href
        return None
