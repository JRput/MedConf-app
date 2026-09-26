"""
Royal College of Anaesthetists (RCoA) — extractor.

Drupal site (www.rcoa.ac.uk) behind a Cloudflare **managed challenge**, so
everything here is browser-first and every load goes through
`self.browser.navigate()`.

The site's quirk — found here and independently on FICM, and now handled
centrally in `browser.py` — is that Cloudflare clears exactly ONE navigation
per browser context. The first `goto` sits on "Just a moment…" for ~11 s,
solves, and serves the real page; every subsequent navigation in that same
context is re-challenged and then never clears (measured 2026-09-26: 3 × 25 s
of polling on `?page=1`, 30 s on a second detail URL, plus `reload()` and a
fresh *page* inside the cleared context — all still on the interstitial).
A brand-new *context* clears every time, first try.

`BrowserController.navigate()` now rotates to a fresh alternate-profile
context on every challenge, so this extractor just calls it and reads
`self.browser.page`: ~11 s for the first load of a run, ~3 s each after
that. Nothing here opens its own context.

One consequence worth knowing: a rotation CLOSES the previous page, so any
`Page` handle taken before a `navigate()` is dead afterwards. Hence
`extract_detail` scrapes everything it needs out of the DOM in a single
`evaluate()` up front, and only then navigates away to fetch the fee images.

Listing
-------
`/events?page=N`, **zero-indexed** (`?page=0` is page one) — the shared
page_query walker starts at 1 and would silently drop the first 9 events,
which is why this source uses `list_shells_override`. 9 `article.l-listing`
cards per page, and every card carries title, category, CPD credits,
location, date range and a summary:

    <article class="l-listing …">
      <li class="o-category_list__list-item"><a href="/event-category/…">Symposium</a>
      <span class="cpd-credits">10 anticipated CPD Credits</span>
      <div class="l-listing__section-title"><a href="/events/winter-symposium-2026">…
      <div class="l-listing__section-subtitle">Hybrid
      <div class="l-listing__section__date"><time datetime="19 to 20 November 2026">
      <div class="l-listing__section-summary">Attend our two-day annual…

Detail
------
Tabs are ARIA (`button[role=tab][aria-controls] → div[role=tabpanel]`), all
panels present in the DOM but hidden, so panel text must be read with
`textContent` — `innerText` returns "" for the inactive ones (this is why
recon initially reported "no fees on the page"). "Key details" is a clean
label/value sidebar (`.c-details-sidebar__details p`) giving Date, Location,
Availability, Clinical content lead(s) and CPD credits.

Fees live on the **Pricing** tab in two mutually exclusive shapes:
  1. JPG screenshots of the fee table (the common case) → vision LLM.
     Cloudflare refuses these files to every *subresource* request this
     browser makes — httpx 403 (so `vision.fetch_image_as_data_url` is out),
     `context.request.get` 403, in-page `fetch()` 403, and even the event
     page's own `<img>` never loads (`naturalWidth == 0`). But *navigating*
     to the image URL serves it normally, and the image is then the
     document, so `_image_as_data_url` navigates and re-encodes it off a
     canvas. `extract_pricing_from_images` is handed ready-made `data:`
     URLs, which `vision.extract_json` passes straight through.
  2. Inline prose, e.g. "£75.00 (Members: Anaesthetists in Training/MTI
     Doctors) and £95.00 (Non-members)" → parsed from the parenthetical.
Scoping both to the Pricing panel keeps prose money elsewhere on the page
(a "£100 Gift voucher" poster prize on the Overview tab) out of the fees.
"""

from __future__ import annotations

import re
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Page

from logger import logger

from .base import BaseExtractor
from .specialty_classifier import classify_specialty

BASE = "https://www.rcoa.ac.uk"
LISTING = f"{BASE}/events"
CARD_SEL = "article.l-listing"

NAV_TIMEOUT_MS = 45000
PAGE_DELAY_S = 1.5          # politeness between listing/detail loads
MAX_LISTING_PAGES = 8       # safety cap; real listing is 4 pages (page=0..3)
VISION_ATTEMPTS = 3         # the hosted vision model is erratic on these tables
NAV_ATTEMPTS = 2            # navigate() rotates context on challenge; retry once

_CHALLENGE_TITLE = re.compile(r"just a moment|attention required", re.I)

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

# RCoA runs almost everything from Churchill House (London) or online, but
# the flagship conference moves around the UK.
_UK_REGIONS = {
    "london": "London",
    "newport": "Wales",
    "cardiff": "Wales",
    "swansea": "Wales",
    "manchester": "North West England",
    "liverpool": "North West England",
    "birmingham": "West Midlands",
    "leeds": "Yorkshire and the Humber",
    "sheffield": "Yorkshire and the Humber",
    "york": "Yorkshire and the Humber",
    "newcastle": "North East England",
    "bristol": "South West England",
    "exeter": "South West England",
    "brighton": "South East England",
    "oxford": "South East England",
    "cambridge": "East of England",
    "edinburgh": "Scotland",
    "glasgow": "Scotland",
    "belfast": "Northern Ireland",
}
_UK_CITIES = set(_UK_REGIONS)
# Values the Location field uses as a nation/region rather than a city.
_NATIONS = {"wales": "Wales", "scotland": "Scotland",
            "northern ireland": "Northern Ireland", "england": None}

# RCoA's own event-category taxonomy → our 3-way event_type.
_CATEGORY_EVENT_TYPE = {
    "annual conference": "conference",
    "symposium": "conference",
    "anaesthetic updates": "conference",
    "conference": "conference",
    "revision courses": "course",
    "revision course": "course",
    "courses": "course",
    "course": "course",
    "training": "course",
    "webinar": "workshop",
    "webinars": "workshop",
    "career events": "workshop",
    "study day": "workshop",
    "workshop": "workshop",
}

# Words in a Location string that describe the online half of an event
# rather than a place. Delivery platforms count: RCoA writes "Online, Zoom",
# and Zoom is not a venue.
_ONLINE_WORDS = re.compile(
    r"\b(online|virtual|webinar|and|live\s*stream(?:ed|ing)?|"
    r"zoom|ms\s*teams|microsoft\s*teams|teams|webex|gotowebinar|on\s*demand)\b",
    re.I,
)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _iso(day: int, month: int, year: int) -> Optional[str]:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _parse_date_range(text: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Parse RCoA's `<time datetime>` / Key-details date strings.

    Handles the four shapes the site emits:
        "23 October 2026"                  -> single day
        "19 to 20 November 2026"           -> same month
        "1 July to 5 March 2027"           -> crosses a year boundary; only
                                              the END year is printed, so the
                                              start year is inferred (start
                                              month > end month -> year-1)
        "1 July 2026 to 5 March 2027"      -> both years explicit
    """
    if not text:
        return None, None
    t = re.sub(r"\s+", " ", text).strip()
    # Normalise separators to " to ". The word boundaries matter: without
    # them "Oc(to)ber" is mangled into a fake range.
    t = re.sub(r"\s*[–—-]\s*", " to ", t)
    t = re.sub(r"\s*\b(?:to|until)\b\s*", " to ", t, flags=re.I)

    def mon(name: str) -> Optional[int]:
        return _MONTHS.get(name.lower().rstrip("."))

    # Both years explicit
    m = re.search(r"\b(\d{1,2}) ([A-Za-z]+) (\d{4}) to (\d{1,2}) ([A-Za-z]+) (\d{4})\b", t)
    if m:
        m1, m2 = mon(m.group(2)), mon(m.group(5))
        if m1 and m2:
            return (_iso(int(m.group(1)), m1, int(m.group(3))),
                    _iso(int(m.group(4)), m2, int(m.group(6))))

    # Cross-month, single trailing year
    m = re.search(r"\b(\d{1,2}) ([A-Za-z]+) to (\d{1,2}) ([A-Za-z]+) (\d{4})\b", t)
    if m:
        m1, m2 = mon(m.group(2)), mon(m.group(4))
        if m1 and m2:
            end_year = int(m.group(5))
            start_year = end_year - 1 if m1 > m2 else end_year
            return (_iso(int(m.group(1)), m1, start_year),
                    _iso(int(m.group(3)), m2, end_year))

    # Same month "19 to 20 November 2026"
    m = re.search(r"\b(\d{1,2}) to (\d{1,2}) ([A-Za-z]+) (\d{4})\b", t)
    if m:
        mn = mon(m.group(3))
        if mn:
            year = int(m.group(4))
            return (_iso(int(m.group(1)), mn, year), _iso(int(m.group(2)), mn, year))

    # Single day
    m = re.search(r"\b(\d{1,2}) ([A-Za-z]+) (\d{4})\b", t)
    if m:
        mn = mon(m.group(2))
        if mn:
            iso = _iso(int(m.group(1)), mn, int(m.group(3)))
            return iso, None

    return None, None


def _parse_start_time(text: Optional[str]) -> Optional[str]:
    """"| 09:00 - 16:30" -> "09:00"."""
    if not text:
        return None
    m = re.search(r"\b([0-2]?\d):([0-5]\d)\b", text)
    if not m:
        return None
    hh = int(m.group(1))
    return f"{hh:02d}:{m.group(2)}" if hh <= 23 else None


# ---------------------------------------------------------------------------
# Location helpers
# ---------------------------------------------------------------------------

def _infer_region(city: Optional[str]) -> Optional[str]:
    if not city:
        return None
    c = city.lower()
    for key, region in _UK_REGIONS.items():
        if key in c:
            return region
    return None


def _parse_location(raw: Optional[str]) -> Dict[str, Any]:
    """Parse the Key-details Location value.

    Real examples:
        "Hybrid, London and Online"   -> hybrid, city London
        "Wales, ICC Wales and online" -> hybrid, region Wales, venue ICC Wales
        "Online,"                     -> online
        "London, Churchill House"     -> in_person, city London, venue …
    """
    out: Dict[str, Any] = {"event_format": None, "city": None,
                           "venue_name": None, "region": None}
    if not raw:
        return out
    raw = re.sub(r"\s+", " ", raw).strip().strip(",").strip()
    if not raw:
        return out
    low = raw.lower()

    # --- format -----------------------------------------------------------
    physical = _ONLINE_WORDS.sub(" ", low)
    physical = re.sub(r"\bhybrid\b|\bin[- ]person\b", " ", physical)
    physical = re.sub(r"[,\s]+", " ", physical).strip()
    if "hybrid" in low:
        out["event_format"] = "hybrid"
    elif re.search(r"\b(online|virtual|webinar)\b", low):
        out["event_format"] = "hybrid" if physical else "online"
    else:
        out["event_format"] = "in_person"

    # --- place ------------------------------------------------------------
    parts = []
    for p in raw.split(","):
        cleaned = _ONLINE_WORDS.sub(" ", p)
        cleaned = re.sub(r"\bhybrid\b|\bin[- ]person\b", " ", cleaned, flags=re.I)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,-")
        if cleaned:
            parts.append(cleaned)

    for part in parts:
        pl = part.lower()
        if pl in _NATIONS:
            out["region"] = out["region"] or _NATIONS[pl]
        elif pl in _UK_CITIES:
            out["city"] = out["city"] or part
        elif not out["venue_name"]:
            out["venue_name"] = part

    out["region"] = out["region"] or _infer_region(out["city"])
    return out


def _parse_cpd(text: Optional[str]) -> Optional[int]:
    """"10 anticipated" / "5 CPD Credits" -> 10 / 5."""
    if not text:
        return None
    m = re.search(r"\b(\d{1,3})\b", text)
    if not m:
        return None
    val = int(m.group(1))
    return val if 0 < val <= 100 else None


def _clean_text(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _event_type_from(category: Optional[str], title: Optional[str]) -> str:
    cat = (category or "").strip().lower()
    if cat in _CATEGORY_EVENT_TYPE:
        return _CATEGORY_EVENT_TYPE[cat]
    for key, val in _CATEGORY_EVENT_TYPE.items():
        if key in cat:
            return val
    tl = (title or "").lower()
    if re.search(r"\bcourse\b|\brevision\b|\btraining\b", tl):
        return "course"
    if re.search(r"\bwebinar\b|\bworkshop\b|\bstudy day\b", tl):
        return "workshop"
    return "conference"


# ---------------------------------------------------------------------------
# Browser-side scripts
# ---------------------------------------------------------------------------

_CARDS_JS = """
() => Array.from(document.querySelectorAll('article.l-listing')).map(el => {
  const txt = s => {
    const n = el.querySelector(s);
    return n ? (n.textContent || '').replace(/\\s+/g, ' ').trim() : null;
  };
  const link = el.querySelector('.l-listing__section-title a[href], a[href^="/events/"]');
  const time = el.querySelector('.l-listing__section__date time');
  return {
    title: txt('.l-listing__section-title'),
    url: link ? link.href : null,
    subtitle: txt('.l-listing__section-subtitle'),
    date_text: time ? (time.getAttribute('datetime') || time.textContent) : txt('.l-listing__section__date'),
    summary: txt('.l-listing__section-summary'),
    cpd: txt('.cpd-credits'),
    category: txt('.o-category_list__list-item a'),
  };
})
"""

_DETAIL_JS = """
() => {
  const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
  // Key-details sidebar: <p><span class="highlight">Label: </span>value</p>
  const details = {};
  document.querySelectorAll('.c-details-sidebar__details p').forEach(p => {
    const h = p.querySelector('.c-details-sidebar__highlight');
    if (!h) return;
    const label = clean(h.textContent).replace(/:\\s*$/, '');
    const value = clean(p.textContent.replace(h.textContent, ''));
    if (label) details[label] = value;
  });
  const dateEl = document.querySelector('.c-details-sidebar__details .date');
  const timeEl = document.querySelector('.c-details-sidebar__details .time');

  // ARIA tabs -> panel ids. Panels are in the DOM but hidden, so use
  // textContent (innerText is empty for an inactive panel).
  const tabs = {};
  document.querySelectorAll('button[role="tab"][aria-controls]').forEach(b => {
    const label = clean(b.textContent);
    if (label) tabs[label] = b.getAttribute('aria-controls');
  });
  const panelText = {}, panelImgs = {};
  Object.entries(tabs).forEach(([label, id]) => {
    const panel = document.getElementById(id);
    if (!panel) return;
    panelText[label] = clean(panel.textContent).slice(0, 8000);
    panelImgs[label] = Array.from(panel.querySelectorAll('img[src]'))
      .map(i => ({src: i.src, alt: i.getAttribute('alt') || ''}));
  });

  const bookEl = document.querySelector('.c-details-sidebar__actions a[href]');
  const h1 = document.querySelector('h1');
  const metaDesc = document.querySelector('meta[name="description"]');
  const body = document.querySelector('.c-event-pane-overview__body');

  return {
    details: details,
    date_text: dateEl ? clean(dateEl.textContent) : null,
    time_text: timeEl ? clean(timeEl.textContent) : null,
    tabs: tabs,
    panel_text: panelText,
    panel_imgs: panelImgs,
    booking_external: bookEl ? bookEl.href : null,
    title: h1 ? clean(h1.textContent) : null,
    meta_description: metaDesc ? clean(metaDesc.getAttribute('content')) : null,
    overview_body: body ? clean(body.textContent).slice(0, 6000) : null,
    days_left: clean((document.querySelector('.c-event-pane-overview__details-days-left') || {}).textContent),
  };
}
"""


# Re-encode the navigated-to image off a canvas. Same-origin, so the canvas
# is not tainted and toDataURL() is allowed.
_IMAGE_TO_DATA_URL_JS = """
() => {
  const img = document.querySelector('img');
  if (!img) return 'no-img';
  if (!img.naturalWidth) return 'not-loaded';
  // Fee tables are ~1000px screenshots; a huge canvas would bloat the
  // vision request for no extra legibility.
  if (img.naturalWidth > 4000 || img.naturalHeight > 4000) return 'too-large';
  const c = document.createElement('canvas');
  c.width = img.naturalWidth;
  c.height = img.naturalHeight;
  c.getContext('2d').drawImage(img, 0, 0);
  return c.toDataURL('image/jpeg', 0.92);
}
"""


class RCoAExtractor(BaseExtractor):
    """Royal College of Anaesthetists — /events (Drupal, Cloudflare-challenged)."""

    # ------------------------------------------------------------------ #
    # Navigation — always via BrowserController, which handles the challenge
    # ------------------------------------------------------------------ #
    @staticmethod
    def _is_challenged(pg) -> bool:
        try:
            return bool(_CHALLENGE_TITLE.search(pg.title() or ""))
        except Exception:
            return False

    def _nav(self, url: str):
        """Navigate to `url` and return the live page, or None.

        `BrowserController.navigate()` rotates to a fresh alternate-profile
        context whenever Cloudflare challenges, which is what actually clears
        this site. Note the page object changes across a rotation, so always
        use the page this returns rather than one cached earlier.
        """
        br = getattr(self, "browser", None)
        if br is None:
            logger.warning("RCoA: no BrowserController available")
            return None
        for attempt in range(NAV_ATTEMPTS):
            try:
                br.navigate(url)
                pg = br.page
                if pg is not None and not self._is_challenged(pg):
                    return pg
                logger.warning(f"RCoA: still challenged on {url} "
                               f"(attempt {attempt + 1}/{NAV_ATTEMPTS})")
            except Exception as e:
                logger.warning(f"RCoA: navigation failed for {url} "
                               f"(attempt {attempt + 1}/{NAV_ATTEMPTS}): {e}")
            if attempt + 1 < NAV_ATTEMPTS:
                time.sleep(PAGE_DELAY_S)
        return None

    # ------------------------------------------------------------------ #
    # Phase A — listing
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        """Walk /events?page=0..N. Zero-indexed, hence the override."""
        shells: List[Dict[str, Any]] = []
        seen: set[str] = set()
        today = date.today().isoformat()

        for n in range(MAX_LISTING_PAGES):
            url = f"{LISTING}?page={n}"
            pg = self._nav(url)
            if pg is None:
                # Page 0 failing is fatal; a later page failing just ends the walk.
                if n == 0:
                    logger.warning("RCoA: listing page 0 unavailable — no shells")
                break
            try:
                pg.wait_for_selector(CARD_SEL, timeout=15000)
            except Exception:
                pass
            try:
                cards = pg.evaluate(_CARDS_JS) or []
            except Exception as e:
                logger.warning(f"RCoA: card parse failed on page {n}: {e}")
                break

            new = 0
            for c in cards:
                url_c = (c.get("url") or "").split("?")[0].split("#")[0]
                title = _clean_text(c.get("title"))
                if not url_c or not title or "/events/" not in url_c:
                    continue
                if url_c in seen:
                    continue
                seen.add(url_c)

                start, end = _parse_date_range(c.get("date_text"))
                # Skip finished events. An event whose start has passed but
                # whose end has not is still open (the online revision
                # courses) — keep it, flagged on-demand in extract_detail.
                latest = end or start
                if latest and latest < today:
                    continue

                category = _clean_text(c.get("category")) or None
                shells.append({
                    "title": title,
                    "booking_url": url_c,
                    "start_date": start,
                    "end_date": end,
                    "date_text": _clean_text(c.get("date_text")) or None,
                    "location_hint": _clean_text(c.get("subtitle")) or None,
                    "description_hint": _clean_text(c.get("summary")) or None,
                    "cpd_points": _parse_cpd(c.get("cpd")),
                    "category": category,
                    "event_type": _event_type_from(category, title),
                    "is_sold_out": False,
                    "page_index": n,
                })
                new += 1

            logger.info(f"  RCoA: page={n} → {len(cards)} cards, {new} new "
                        f"(running total {len(shells)})")
            if not cards or new == 0:
                break
            time.sleep(PAGE_DELAY_S)

        return shells

    # ------------------------------------------------------------------ #
    # Phase B — detail
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        url = shell.get("booking_url") or ""

        # llm_agent has already navigated `page` here; re-navigate only if it
        # did not come through (a challenge that outlived the rotation).
        target = page
        if target is None or self._is_challenged(target):
            target = self._nav(url)
            if target is None:
                return self._shell_only(shell)

        # Read EVERYTHING off the page in one go. Fetching the fee images
        # navigates away, and a context rotation would close this page.
        try:
            data = target.evaluate(_DETAIL_JS) or {}
        except Exception as e:
            logger.warning(f"RCoA: detail parse failed for {url}: {e}")
            return self._shell_only(shell)

        tiers = self._pricing(data)

        details = {k.lower(): v for k, v in (data.get("details") or {}).items()}
        result: Dict[str, Any] = {}

        # --- dates / time -------------------------------------------------
        start, end = _parse_date_range(data.get("date_text") or details.get("date"))
        start = start or shell.get("start_date")
        end = end or shell.get("end_date")
        start_time = _parse_start_time(data.get("time_text") or details.get("date"))

        # Ongoing flexible-access online courses (RCoA's FRCA revision
        # courses): booking is open now, content runs until the exam date.
        # Same shape as RCEM's on-demand catch-up — start_date carries the
        # access deadline so the event doesn't read as already finished.
        today = date.today().isoformat()
        if start and end and start < today <= end:
            result["is_on_demand"] = True
            start, end = end, None

        result["start_date"] = start
        result["end_date"] = end
        if start_time:
            result["start_time"] = start_time

        # --- location -----------------------------------------------------
        loc = _parse_location(details.get("location") or shell.get("location_hint"))
        result.update({k: v for k, v in loc.items() if v})

        # --- CPD ------------------------------------------------------------
        cpd = _parse_cpd(details.get("cpd credits")) or shell.get("cpd_points")
        if cpd:
            result["cpd_points"] = cpd
            result["cpd_accredited"] = True

        # --- availability ---------------------------------------------------
        avail = (details.get("availability") or "").lower()
        if re.search(r"sold out|fully booked|waiting list|no places", avail):
            result["is_sold_out"] = True
        elif avail:
            result["is_sold_out"] = False

        # --- event type -------------------------------------------------------
        result["event_type"] = shell.get("event_type") or _event_type_from(
            shell.get("category"), shell.get("title"))

        if tiers:
            result["pricing_tiers"] = tiers

        # --- soft fields ------------------------------------------------------
        overview = (data.get("panel_text") or {}).get("Overview") or data.get("overview_body") or ""
        result.update(self._soft_fields(shell, data, overview, llm_call))
        return result

    # ------------------------------------------------------------------ #
    # Pricing
    # ------------------------------------------------------------------ #
    def _pricing(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fees from the Pricing tab: fee-table images (vision) else prose."""
        tabs = data.get("panel_text") or {}
        imgs_by_tab = data.get("panel_imgs") or {}
        label = next((k for k in tabs if re.search(r"pricing|fees?\b", k, re.I)), None)
        if not label:
            return []

        # 1) Fee-table screenshots
        srcs: List[str] = []
        for img in imgs_by_tab.get(label) or []:
            src = (img.get("src") or "").strip()
            low = src.lower()
            if not low.startswith("http"):
                continue
            if any(k in low for k in ("logo", "icon", "favicon", ".svg", "sprite")):
                continue
            srcs.append(src)
        if srcs:
            data_urls = self._as_data_urls(srcs)
            if data_urls:
                from vision import extract_pricing_from_images
                logger.info(f"  RCoA: sending {len(data_urls)} fee image(s) to vision LLM")
                # The hosted vision model is erratic on these tables — it
                # returns an empty body or truncated JSON on a noticeable
                # share of calls, then reads the SAME image correctly on a
                # retry (measured 2026-09-26). Re-ask before giving up.
                for attempt in range(VISION_ATTEMPTS):
                    tiers = extract_pricing_from_images(data_urls)
                    if tiers:
                        return tiers
                    logger.warning(
                        f"  RCoA: vision returned no tiers (attempt {attempt + 1}"
                        f"/{VISION_ATTEMPTS})")

        # 2) Prose fees — "£75.00 (Members: …) and £95.00 (Non-members)"
        return self._prose_tiers(tabs.get(label) or "")

    def _as_data_urls(self, srcs: List[str]) -> List[str]:
        """Fetch the fee images as `data:` URLs for the vision LLM.

        Every ordinary route to these files is refused: httpx (what
        `vision.fetch_image_as_data_url` would use) gets 403, so does
        `context.request.get` and an in-page `fetch()`, and even the event
        page's own `<img>` sits at `naturalWidth == 0` — Cloudflare refuses
        *subresource* requests from this browser, not the files themselves.
        Navigating to the image is served normally, and then the image IS
        the document, so we can re-encode it off a canvas.
        """
        out: List[str] = []
        for src in srcs:
            data_url = self._image_as_data_url(src)
            if data_url:
                out.append(data_url)
            else:
                logger.warning(f"  RCoA: fee image not retrievable: {src}")
        return out

    def _image_as_data_url(self, src: str) -> Optional[str]:
        pg = self._nav(src)
        if pg is None:
            return None
        try:
            result = pg.evaluate(_IMAGE_TO_DATA_URL_JS)
        except Exception as e:
            logger.warning(f"  RCoA: fee image encode failed for {src}: {e}")
            return None
        if isinstance(result, str) and result.startswith("data:image/"):
            return result
        logger.warning(f"  RCoA: fee image did not render ({result!r}): {src}")
        return None

    @staticmethod
    def _prose_tiers(text: str) -> List[Dict[str, Any]]:
        """Only the explicitly-labelled `£<amount> (<who>)` form — anything
        looser picks up terms-and-conditions noise."""
        tiers: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for m in re.finditer(r"£\s*([\d,]+(?:\.\d{1,2})?)\s*\(([^)]{2,80})\)", text):
            try:
                price = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if price <= 0:
                continue
            label = _clean_text(m.group(2)).rstrip(".")
            key = f"{label}|{price}"
            if not label or key in seen:
                continue
            seen.add(key)
            tiers.append({
                "tier_label": label[:200],
                "price_gbp": price,
                "currency": "GBP",
                "is_early_bird": bool(re.search(r"early", label, re.I)),
                "early_bird_deadline": None,
            })
        return tiers

    # ------------------------------------------------------------------ #
    # Soft fields
    # ------------------------------------------------------------------ #
    def _soft_fields(
        self,
        shell: Dict[str, Any],
        data: Dict[str, Any],
        overview: str,
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        title = shell.get("title") or data.get("title") or ""

        # Deterministic backstops first — the card summary is organiser-written
        # copy, and the meta description is the same text server-side.
        fallback_desc = (_clean_text(shell.get("description_hint"))
                         or _clean_text(data.get("meta_description")))
        if not fallback_desc and overview:
            for para in re.split(r"(?<=[.!?]) ", overview):
                p = _clean_text(para)
                if len(p) > 80 and not re.search(
                        r"cookie|privacy|terms and conditions|payment must be made", p, re.I):
                    fallback_desc = p
                    break

        description = fallback_desc or None
        specialty = None

        body = _clean_text(overview)[:2800]
        if body:
            prompt = (
                "You are given the text of a medical event page from the Royal "
                "College of Anaesthetists. Reply with ONLY a JSON object:\n"
                '{"description": "<2-3 sentence factual summary of the event>", '
                '"specialty": "<single primary medical specialty>"}\n'
                "Use only facts present in the text. If unsure of the specialty, "
                'use "Anaesthetics".\n\n'
                f"TITLE: {title}\n\nPAGE TEXT:\n{body}"
            )
            raw = llm_call(prompt)
            if raw:
                m = re.search(r"\{.*\}", raw, re.S)
                if m:
                    try:
                        import json
                        parsed = json.loads(m.group(0))
                        d = _clean_text(parsed.get("description"))
                        s = _clean_text(parsed.get("specialty"))
                        if len(d) > 40:
                            description = d[:1500]
                        if s and len(s) < 60:
                            specialty = s
                    except Exception:
                        pass

        if not specialty:
            specialty = classify_specialty(title, description) or "Anaesthetics"

        out: Dict[str, Any] = {"specialty": specialty}
        if description:
            out["description"] = description
        return out

    # ------------------------------------------------------------------ #
    @staticmethod
    def _shell_only(shell: Dict[str, Any]) -> Dict[str, Any]:
        """Challenge never cleared / page unparseable — keep the listing facts
        rather than inventing detail ones."""
        return {
            "start_date": shell.get("start_date"),
            "end_date": shell.get("end_date"),
            "cpd_points": shell.get("cpd_points"),
            "cpd_accredited": bool(shell.get("cpd_points")),
            "event_type": shell.get("event_type") or "conference",
            "description": _clean_text(shell.get("description_hint")) or None,
            "specialty": classify_specialty(shell.get("title")) or "Anaesthetics",
            "pricing_tiers": [],
        }
