# extractors/uroweb.py
"""
EAU (European Association of Urology) — Event Calendar extractor.

Wave 2b source. https://uroweb.org/education-events/events is a Nuxt SPA.
Page 1 is server-rendered but `?page=N` is ignored by the server: every
later page is fetched client-side from the Craft CMS GraphQL endpoint
(`https://cms.uroweb.org/graphql`) with a public bearer token that the site
itself sends from the browser. We therefore:

  1. Load the listing in the real browser and capture the `Authorization`
     header from the site's own GraphQL request (no token is hard-coded).
  2. Page the same `entries(section: "educationAndEvents", type: "live",
     isFuture: ["dateRange", true])` query the calendar uses (limit 16,
     offset N) from inside that page, ≤1 request/s, until `entryCount` is
     reached. Count is proven against the site's own `entryCount` (55 on
     2026-10-03 — the "700" in recon was the sitemap, which also holds past
     and on-demand entries; on-demand lives in a different Craft entry type
     and is deliberately NOT listed here).
  3. Detail pages are server-rendered: `.lead`/first paragraph, a
     `table .event-details__label/.event-details__value` metadata block
     (Organiser, CME, Venue, Location "City, Country", Registration open).

No fees are published on EAU pages (registration happens on the organiser's
site), so pricing_tiers is always [].

Never hold a Page handle across `self.browser.navigate()` (a Cloudflare
rotation closes the previous page); listing code re-reads `browser.page`.
"""

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
GRAPHQL_URL = "https://cms.uroweb.org/graphql"
SITE_ROOT = "https://uroweb.org/"
PAGE_SIZE = 16
REQUEST_GAP_S = 1.0
MAX_PAGES = 80  # hard stop: 80 * 16 = 1280, far above the real total

_QUERY = """
query Live($offset: Int) {
  entries(section: "educationAndEvents" type: "live" offset: $offset limit: 16
          isFuture: ["dateRange", true] orderBy: "dateRange ASC" site: ["uroweb"]) {
    id title uri
    ... on educationAndEvents_live_Entry {
      membersOnly
      dateRange { start end }
      city venue
      type: liveType { ... on liveTypes_Category { title } }
      topics { ... on topics_topic_Entry { title } }
    }
  }
  entryCount(section: "educationAndEvents" type: "live"
             isFuture: ["dateRange", true] site: ["uroweb"])
}
"""

_FETCH_JS = """async ([url, query, offset, auth]) => {
  const r = await fetch(url, {
    method: 'POST',
    headers: {'content-type': 'application/json', authorization: auth},
    body: JSON.stringify({query, variables: {offset}}),
  });
  if (!r.ok) throw new Error('graphql http ' + r.status);
  return await r.json();
}"""

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
    # Phase A — listing via the site's own GraphQL query
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        browser = getattr(self, "browser", None)
        if browser is None:
            return None
        for attempt in range(3):
            try:
                shells = self._walk_listing(browser)
                if shells:
                    return shells
                logger.warning("uroweb: empty listing (attempt %d)", attempt + 1)
            except Exception as e:  # noqa: BLE001
                logger.warning("uroweb: listing attempt %d failed: %s", attempt + 1, e)
            time.sleep(3)
        logger.error("uroweb: listing failed after 3 tries — returning no shells")
        return []

    def _walk_listing(self, browser) -> List[Dict[str, Any]]:
        browser.navigate(LISTING_URL)
        page = browser.page
        auth: Dict[str, str] = {}

        def _on_request(req) -> None:
            if "graphql" in req.url and req.headers.get("authorization"):
                auth["v"] = req.headers["authorization"]

        page.on("request", _on_request)
        try:
            # The SPA issues its GraphQL calls on load; reload so the listener
            # (attached after navigate) sees them.
            page.reload(wait_until="networkidle")
        finally:
            page.remove_listener("request", _on_request)
        if "v" not in auth:
            page.wait_for_timeout(3000)
        if "v" not in auth:
            raise RuntimeError("could not capture the site's GraphQL authorization header")

        entries: List[Dict[str, Any]] = []
        seen = set()
        total: Optional[int] = None
        offset = 0
        for _ in range(MAX_PAGES):
            data = page.evaluate(_FETCH_JS, [GRAPHQL_URL, _QUERY, offset, auth["v"]])
            if data.get("errors"):
                raise RuntimeError(f"graphql errors: {str(data['errors'])[:200]}")
            d = data["data"]
            total = d.get("entryCount")
            batch = d.get("entries") or []
            for e in batch:
                if e.get("uri") and e["uri"] not in seen:
                    seen.add(e["uri"])
                    entries.append(e)
            offset += PAGE_SIZE
            if not batch or (total is not None and offset >= total):
                break
            time.sleep(REQUEST_GAP_S)

        if total is not None and len(entries) != total:
            logger.warning("uroweb: fetched %d unique of site total %s", len(entries), total)
        else:
            logger.info("uroweb: fetched %d events (site total %s)", len(entries), total)

        today = date.today().isoformat()
        shells: List[Dict[str, Any]] = []
        for e in entries:
            title = _clean(e.get("title"))
            start = _iso_date((e.get("dateRange") or {}).get("start"))
            end = _iso_date((e.get("dateRange") or {}).get("end")) or start
            if not title or not start or (end or start) < today:
                continue
            live_type = ((e.get("type") or [{}])[0] or {}).get("title")
            city = _clean(e.get("city")) or None
            shells.append({
                "title": title,
                "booking_url": SITE_ROOT + e["uri"].lstrip("/"),
                "start_date": start,
                "end_date": end,
                "city": city,
                "venue_name": _clean(e.get("venue")) or None,
                "event_type": _event_type(live_type, title),
                "category": live_type,
                "topics": [t.get("title") for t in (e.get("topics") or []) if t.get("title")],
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
                const tables = [];
                root.querySelectorAll('section.section table').forEach(t => {
                    if (t.closest('.event-details, footer, nav, header')) return;
                    tables.push(Array.from(t.querySelectorAll('tr')).map(tr =>
                        Array.from(tr.querySelectorAll('th, td')).map(c => txt(c).replace(/\s+/g, ' ').trim())));
                });
                const og = document.querySelector('meta[property="og:description"], meta[name=description]');
                return {meta, lead, paras, tables, og: og ? og.content : '',
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
