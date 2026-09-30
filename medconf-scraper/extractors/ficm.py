"""
Faculty of Intensive Care Medicine (FICM) — events extractor.

Drupal site (same platform/theme as RCoA), listing at /events, details at
/events/<slug>. Pager is 0-indexed like RCoA's: ?page=0 is page one and
?page=1 is page two; ?page=2 came back empty on 2026-09-26, so the view is
two pages / 13 events.

CLOUDFLARE — read this before changing how pages are fetched.
The whole site is behind a Cloudflare managed challenge. browser.py's
navigate() handles it by switching the session to ALT_PROFILE the first
time a page comes back titled "Just a moment…", and that does clear FICM —
but only for ONE page load. Measured 2026-09-26, repeatedly:

    fresh BrowserController → navigate(/events)        → 200, real page
    same session → navigate(/events?page=1)            → 403 challenge
    same session → navigate(/events/<any slug>)        → 403 challenge
    same session → navigate(/events) again             → 403 challenge

The alternate context keeps its cf_clearance cookie and still gets
re-challenged, and the interstitial never resolves (polled 40 s). What DOES
clear reliably is a BRAND-NEW context per page load — every load then
succeeds in 0.4-0.8 s:

    browser.new_context(**ALT_PROFILE) → new_page() → goto  → 200

So this module fetches every FICM page through `_fetch()`, which opens a
fresh ALT_PROFILE context, loads the URL, and closes the context. It reuses
browser.py's own ALT_PROFILE constant rather than inventing a profile, and
it changes nothing in browser.py.

`extract_detail()` therefore cannot trust the `page` it is handed: the
scraper navigated it to the detail URL, but that navigation is load #2+ of
the session and lands on the challenge. It uses `page` when the page really
is the event (so that if browser.py is later fixed to rotate contexts, no
second fetch happens) and re-fetches through `_fetch()` otherwise.

Page shapes:
  * Listing card `.l-listing-grid__item`: link `/events/<slug>`, title,
    subtitle = format ("In person" / "Online"), `<time>` whose text is a
    HUMAN date range ("25 March to 26 November 2026", "7 to 16 September
    2026", "28 September 2026") — the datetime attribute repeats that text
    rather than an ISO stamp, so it must be parsed — plus a category
    ("External Event" / "Education") and a short summary.
  * Detail `.c-details-sidebar__details`: <p> rows keyed by a
    `.c-details-sidebar__highlight` label — "Date:" (+ optional
    `.time` "I 9:15am - 18.00pm"), "Location:" ("In person, <venue>"),
    "Availability:", "CPD credits:". Booking CTA in
    `.c-details-sidebar__actions`.
  * Detail tabs are ALL server-rendered (hidden with CSS, not lazy-loaded),
    so one fetch yields Overview, Programme, Pricing, Workshops and any
    "Abstract Competition" panel. Tab button -> panel via aria-controls.
  * Fee tables live in the Pricing panel as plain <table>s whose header row
    is "<Section> | Price".
"""

from __future__ import annotations

import html as html_lib
import json
import re
import time
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from playwright.sync_api import Page

from .base import BaseExtractor
from .abstract_classifier import extract_abstract_info
from .specialty_classifier import classify_specialty
from logger import logger

BASE_URL = "https://www.ficm.ac.uk"
# 2026-09-30: FICM changed its routing — the plain /events view now returns a
# truncated first page (1 card) and card links became /index.php/events/<slug>.
# /index.php/events lists all 9 on page 0 with the same ?page=N pager.
LISTING_URL = f"{BASE_URL}/index.php/events"
MAX_PAGES = 6

_CHALLENGE_TITLE = re.compile(r"just a moment|attention required", re.I)

_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"],
        start=1,
    )
}
_MONTH_RE = "|".join(_MONTHS)

_FORMAT_TOKENS = {
    "in person": "in_person",
    "in-person": "in_person",
    "online": "online",
    "hybrid": "hybrid",
}

_SOLD_OUT = re.compile(r"(?i)\b(sold\s*out|fully\s*booked|waiting\s*list\s*only)\b")

_UK_NATION_HINTS = [
    (re.compile(r"(?i)\b(belfast|northern ireland|derry|londonderry)\b"), "Northern Ireland"),
    (re.compile(r"(?i)\b(edinburgh|glasgow|aberdeen|dundee|scotland|stirling)\b"), "Scotland"),
    (re.compile(r"(?i)\b(cardiff|swansea|wales|newport|bangor)\b"), "Wales"),
]
_CITY_TOKEN = re.compile(
    r"(?i)\b(london|manchester|birmingham|leeds|liverpool|bristol|sheffield|"
    r"newcastle|nottingham|leicester|coventry|oxford|cambridge|southampton|"
    r"brighton|york|exeter|plymouth|norwich|reading|derby|hull|preston|"
    r"belfast|edinburgh|glasgow|aberdeen|dundee|stirling|cardiff|swansea|"
    r"newport|bangor|derry|londonderry)\b"
)
# A comma-tail naming an organisation rather than a town.
_ORG_TAIL = re.compile(
    r"(?i)\b(university|hospital|institute|college|centre|center|school|"
    r"faculty|trust|nhs|campus|academy|foundation)\b"
)


def _strip_tags(fragment: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", fragment)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "\n", text)
    return html_lib.unescape(text).replace("\xa0", " ")


def _flatten(fragment: str) -> str:
    return re.sub(r"\s+", " ", _strip_tags(fragment)).strip()


def _lines(fragment: str) -> List[str]:
    return [ln.strip() for ln in _strip_tags(fragment).split("\n") if ln.strip()]


def _div_block(html: str, start_at: int) -> str:
    """Return the inner HTML of the <div> whose opening tag ends at start_at,
    balancing nested <div>s."""
    depth = 1
    for m in re.finditer(r"<div\b|</div>", html[start_at:]):
        depth += 1 if m.group(0) != "</div>" else -1
        if depth == 0:
            return html[start_at : start_at + m.start()]
    return html[start_at:]


class FICMExtractor(BaseExtractor):
    """Browser-first extractor; see the module docstring for the Cloudflare note."""

    # ------------------------------------------------------------------ #
    # Fetching — a fresh ALT_PROFILE context per page load
    # ------------------------------------------------------------------ #
    def _fetch(self, url: str, wait_s: float = 12.0) -> Optional[str]:
        browser = getattr(self, "browser", None)
        if browser is None or getattr(browser, "browser", None) is None:
            logger.warning("FICM: no launched browser available")
            return None

        # Import here so the module still imports if browser.py predates
        # ALT_PROFILE; fall back to the same desktop-Chrome shape.
        try:
            from browser import ALT_PROFILE as profile
        except ImportError:  # pragma: no cover - defensive
            profile = {
                "user_agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/124.0.0.0 Safari/537.36"),
                "viewport": {"width": 1366, "height": 850},
                "locale": "en-GB",
            }

        context = None
        try:
            context = browser.browser.new_context(**profile)
            page = context.new_page()
            page.set_default_timeout(30000)
            page.goto(url, wait_until="load", timeout=40000)
            deadline = time.time() + wait_s
            while time.time() < deadline:
                if not _CHALLENGE_TITLE.search(page.title() or ""):
                    break
                page.wait_for_timeout(1000)
            if _CHALLENGE_TITLE.search(page.title() or ""):
                logger.warning(f"FICM: Cloudflare challenge did not clear for {url}")
                return None
            return page.content()
        except Exception as e:
            logger.warning(f"FICM: fetch of {url} failed: {e}")
            return None
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------ #
    # Phase A — listing
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today()
        shells: List[Dict[str, Any]] = []
        seen: set = set()

        for page_no in range(MAX_PAGES):
            url = LISTING_URL if page_no == 0 else f"{LISTING_URL}?page={page_no}"
            html = self._fetch(url)
            if not html:
                logger.warning(f"FICM: listing page {page_no} unavailable — stopping")
                break

            cards = self._parse_cards(html)
            if not cards:
                break

            new_on_page = 0
            for card in cards:
                if card["booking_url"] in seen:
                    continue
                seen.add(card["booking_url"])
                new_on_page += 1
                start, end = card.pop("_dates")
                if not start:
                    logger.info(f"FICM: unparsable date on '{card['title'][:50]}' — skipping")
                    continue
                # Keep an event until its LAST day has passed; the FICM view
                # itself still lists events that finished a day or two ago.
                if (end or start) < today:
                    continue
                card["start_date"] = start.isoformat()
                card["end_date"] = end.isoformat() if end else None
                shells.append(card)

            if new_on_page == 0:
                break

        logger.info(f"FICM: {len(shells)} upcoming shells")
        return shells

    def _parse_cards(self, html: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for chunk in html.split('<div class="l-listing-grid__item">')[1:]:
            card = chunk[:6000]
            link = re.search(r'href="(?:/index\.php)?(/events/[^"#?]+)"', card)
            if not link:
                continue
            title_m = re.search(
                r'(?s)l-listing__section-title.*?<a[^>]*>(.*?)</a>', card
            )
            title = _flatten(title_m.group(1)) if title_m else None
            if not title:
                continue
            date_m = re.search(r"(?s)l-listing__section__date.*?<time[^>]*>(.*?)</time>", card)
            subtitle_m = re.search(
                r"(?s)l-listing__section-subtitle.*?<span[^>]*>(.*?)</span>", card
            )
            summary_m = re.search(r'(?s)l-listing__section-summary">(.*?)</div>', card)
            category_m = re.search(
                r'(?s)o-category_list__list-item"><a[^>]*>(.*?)</a>', card
            )
            subtitle = _flatten(subtitle_m.group(1)) if subtitle_m else ""

            out.append(
                {
                    "title": title,
                    "booking_url": urljoin(BASE_URL, link.group(1)),
                    "event_format": _FORMAT_TOKENS.get(subtitle.lower()),
                    "description_hint": _flatten(summary_m.group(1))[:300] if summary_m else None,
                    "category": _flatten(category_m.group(1)) if category_m else None,
                    "_dates": self._parse_card_dates(
                        _flatten(date_m.group(1)) if date_m else ""
                    ),
                }
            )
        return out

    @staticmethod
    def _parse_card_dates(text: str) -> Tuple[Optional[date], Optional[date]]:
        """Parse FICM's human date strings.

        "28 September 2026"            → (2026-09-28, None)
        "7 to 16 September 2026"       → (2026-09-07, 2026-09-16)
        "3 to 4 November 2026"         → (2026-11-03, 2026-11-04)
        "25 March to 26 November 2026" → (2026-03-25, 2026-11-26)
        """
        if not text:
            return None, None
        # Normalise the separator to " to ". \b matters: an unanchored "to"
        # also matches inside "Oc-to-ber".
        text = re.sub(r"\s*[-–—]\s*", " to ", text)
        text = re.sub(r"(?i)\s+\b(?:to|until)\b\s+", " to ", text)

        tail = re.search(
            rf"(?i)(\d{{1,2}})\s+({_MONTH_RE})\s+(\d{{4}})\s*$", text.strip()
        )
        if not tail:
            return None, None
        end_day, end_month, year = int(tail.group(1)), _MONTHS[tail.group(2).lower()], int(tail.group(3))
        try:
            last = date(year, end_month, end_day)
        except ValueError:
            return None, None

        head = re.sub(r"(?i)\s*\bto\s*$", "", text[: tail.start()].strip()).strip()
        if not head:
            return last, None
        # "1 December 2026" (own month AND year), "25 March" (own month), or
        # a bare "7" that borrows the end month.
        start_year = year
        m = re.search(rf"(?i)(\d{{1,2}})\s+({_MONTH_RE})\s+(\d{{4}})\s*$", head)
        if m:
            day, month, start_year = (
                int(m.group(1)), _MONTHS[m.group(2).lower()], int(m.group(3))
            )
        else:
            m = re.search(rf"(?i)(\d{{1,2}})\s+({_MONTH_RE})\s*$", head)
            if m:
                day, month = int(m.group(1)), _MONTHS[m.group(2).lower()]
            else:
                m = re.search(r"(\d{1,2})\s*$", head)
                if not m:
                    return last, None
                day, month = int(m.group(1)), end_month
        try:
            first = date(start_year, month, day)
        except ValueError:
            return last, None
        if first > last:  # range spanning a new year, e.g. Dec → Jan
            try:
                first = date(start_year - 1, month, day)
            except ValueError:
                return last, None
        return first, (last if last != first else None)

    # ------------------------------------------------------------------ #
    # Phase B — detail
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        url = shell.get("booking_url")
        html = self._page_html_if_usable(page)
        if html is None:
            # Expected today: the scraper's navigate() was load #2+ of the
            # session and hit the challenge. Fetch it ourselves.
            html = self._fetch(url)
        if not html:
            logger.warning(f"FICM: no usable detail HTML for {url}")
            return {}

        panels = self._panels(html)
        sidebar = self._sidebar(html)
        overview = panels.get("overview", "")
        body_text = self._overview_text(overview) or _flatten(overview)

        result: Dict[str, Any] = {
            "event_type": self._event_type(shell.get("title"), url, body_text),
            "start_time": self._start_time(sidebar.get("date_time")),
            "cpd_points": self._cpd(sidebar.get("cpd")),
            "is_sold_out": bool(_SOLD_OUT.search(sidebar.get("availability") or "")),
            "pricing_tiers": self._pricing(panels, body_text),
        }
        result["cpd_accredited"] = result["cpd_points"] is not None
        result.update(self._location(sidebar.get("location"), shell.get("event_format")))

        # Refine the dates from the detail sidebar when it is more precise
        # than the card (same human format, but authoritative for the node).
        start, end = self._parse_card_dates(sidebar.get("date") or "")
        if start:
            result["start_date"] = start.isoformat()
            result["end_date"] = end.isoformat() if end else shell.get("end_date")

        abstract_text = " ".join(
            _flatten(v) for k, v in panels.items() if "abstract" in k
        )
        if abstract_text:
            is_open, deadline = extract_abstract_info(abstract_text)
            result["abstract_open"] = is_open
            result["abstract_deadline"] = deadline.isoformat() if deadline else None

        result.update(self._soft_fields(shell.get("title"), body_text, shell, llm_call))
        return {k: v for k, v in result.items() if v is not None}

    def _page_html_if_usable(self, page: Optional[Page]) -> Optional[str]:
        """The handed-in page, but only if it really is a FICM event page."""
        if page is None:
            return None
        try:
            if _CHALLENGE_TITLE.search(page.title() or ""):
                return None
            html = page.content()
        except Exception:
            return None
        return html if "c-details-sidebar__details" in html else None

    # ------------------------------------------------------------------ #
    # Tab panels — every one is server-rendered, keyed by its button text
    # ------------------------------------------------------------------ #
    @staticmethod
    def _panels(html: str) -> Dict[str, str]:
        panels: Dict[str, str] = {}
        for panel_id, label_html in re.findall(
            r'(?s)aria-controls="([^"]+)"[^>]*>(.*?)</button>', html
        ):
            label = _flatten(label_html).lower()
            if not label:
                continue
            m = re.search(
                r'<div class="c-tabs__panels-panel[^"]*"[^>]*id="%s"[^>]*>'
                % re.escape(panel_id),
                html,
            )
            if m:
                panels[label] = _div_block(html, m.end())
        return panels

    @staticmethod
    def _sidebar(html: str) -> Dict[str, Optional[str]]:
        """Read the "Key details" sidebar into {date, date_time, location,
        availability, cpd, booking_cta}."""
        out: Dict[str, Optional[str]] = {}
        m = re.search(r'<div class="c-details-sidebar__details">', html)
        if not m:
            return out
        block = _div_block(html, m.end())
        for para in re.findall(r"(?s)<p>(.*?)</p>", block):
            label_m = re.search(
                r'(?s)<span class="c-details-sidebar__highlight">(.*?)</span>', para
            )
            if not label_m:
                continue
            label = _flatten(label_m.group(1)).rstrip(":").lower()
            rest = para[label_m.end():]
            if label == "date":
                d = re.search(r'(?s)<span class="date">(.*?)</span>', rest)
                t = re.search(r'(?s)<span class="time">(.*?)</span>', rest)
                out["date"] = _flatten(d.group(1)) if d else _flatten(rest)
                out["date_time"] = _flatten(t.group(1)) if t else None
            elif label == "location":
                out["location"] = _flatten(rest)
            elif label == "availability":
                out["availability"] = _flatten(rest)
            elif label.startswith("cpd"):
                out["cpd"] = _flatten(rest)
        return out

    # ------------------------------------------------------------------ #
    # Field parsers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _start_time(time_text: Optional[str]) -> Optional[str]:
        """"I 9:15am - 18.00pm" → "09:15". The leading "I" is the theme's
        separator glyph, not a character of the time."""
        if not time_text:
            return None
        m = re.search(r"(\d{1,2})[:.](\d{2})\s*(am|pm)?", time_text, re.I)
        if not m:
            return None
        hour, minute = int(m.group(1)), int(m.group(2))
        meridiem = (m.group(3) or "").lower()
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return f"{hour:02d}:{minute:02d}"

    @staticmethod
    def _cpd(cpd_text: Optional[str]) -> Optional[int]:
        """"6 TBC" → 6; "TBC" → None."""
        if not cpd_text:
            return None
        m = re.search(r"\b(\d{1,2})\b", cpd_text)
        return int(m.group(1)) if m else None

    def _location(
        self, location: Optional[str], card_format: Optional[str]
    ) -> Dict[str, Any]:
        """"In person, The Marriott, Manchester Piccadilly and Online" →
        format + venue + city + region."""
        out: Dict[str, Any] = {
            "event_format": card_format,
            "venue_name": None,
            "city": None,
            "region": None,
        }
        if not location:
            return out

        parts = [p.strip() for p in location.split(",") if p.strip()]
        if parts and parts[0].lower() in _FORMAT_TOKENS:
            out["event_format"] = _FORMAT_TOKENS[parts[0].lower()]
            parts = parts[1:]
        venue = ", ".join(parts).strip(" ,")
        if not venue:
            if out["event_format"] == "online":
                out["city"] = "Online"
            return out

        if re.search(r"(?i)\band online\b", venue):
            # "…Manchester Piccadilly and Online" — both modes.
            if out["event_format"] == "in_person":
                out["event_format"] = "hybrid"
            venue = re.sub(r"(?i)\s+and online$", "", venue).strip(" ,")
        if re.fullmatch(r"(?i)(zoom|online|ms teams|teams|webinar|virtual)", venue):
            out["event_format"] = "online"
            out["city"] = "Online"
            return out

        # FICM editors often write "At Bridge Community Church, Leeds".
        venue = re.sub(r"^at\s+", "", venue, flags=re.I).strip(" ,")
        parts = [p.strip() for p in venue.split(",") if p.strip()]
        if len(parts) >= 2 and not _ORG_TAIL.search(parts[-1]):
            out["venue_name"] = ", ".join(parts[:-1])
            m = _CITY_TOKEN.search(parts[-1])
            # "Manchester Piccadilly" → "Manchester": keep the town.
            out["city"] = m.group(1).title() if m else parts[-1]
        elif len(parts) == 1 and _CITY_TOKEN.fullmatch(parts[0]):
            out["city"] = parts[0]
        else:
            # Whole line is one or more institutions — keep it as the venue
            # and recover the town from a city token inside it.
            out["venue_name"] = venue
            m = _CITY_TOKEN.search(venue)
            out["city"] = m.group(1).title() if m else None

        for pattern, nation in _UK_NATION_HINTS:
            if pattern.search(venue):
                out["region"] = nation
                break
        if out["region"] is None and _CITY_TOKEN.search(venue):
            out["region"] = "England"
        if out["event_format"] == "online" and not out["city"]:
            out["city"] = "Online"
        return out

    @staticmethod
    def _event_type(title: Optional[str], url: Optional[str], body_text: str) -> str:
        t = (title or "").lower()
        # Checked first: "Intensivists in Training Conference" is a
        # conference despite the word "training".
        if re.search(r"\b(conference|congress|symposium|summit|meeting|forum)\b", t):
            return "conference"
        if re.search(r"\bworkshop\b", t):
            return "workshop"
        if re.search(r"\b(course|training|masterclass|webinar|study day|teaching day|exam)\b", t):
            return "course"
        # The listing truncates long titles ("Leeds FUSIC (Focussed
        # Ultrasound in Intensive Care)" loses its trailing "course"), so
        # fall back to the slug, which keeps the full node title.
        slug = (url or "").rsplit("/", 1)[-1].replace("-", " ").lower()
        if re.search(r"\b(course|masterclass|webinar|training day|study day|exam)\b", slug):
            return "course"
        if re.search(r"\b(conference|congress|symposium|summit)\b", slug):
            return "conference"
        if re.search(r"\bcourses?\b", (body_text or "")[:600], re.I):
            return "course"
        return "conference"

    # ------------------------------------------------------------------ #
    # Pricing — the Pricing tab's tables, then an inline fee line
    # ------------------------------------------------------------------ #
    def _pricing(self, panels: Dict[str, str], body_text: str) -> List[Dict[str, Any]]:
        pricing_html = " ".join(
            html for label, html in panels.items()
            if "pricing" in label or "fee" in label or "cost" in label
        )
        tiers = self._table_tiers(pricing_html) if pricing_html else []
        if tiers:
            return tiers

        # Fees sometimes appear only as prose in the Overview tab.
        m = re.search(
            r"(?i)registration fee\s*:?\s*(free|£\s*[\d,]+(?:\.\d\d)?)", body_text
        )
        if m:
            token = m.group(1)
            price = 0.0 if token.lower() == "free" else self.parse_gbp(token)
            if price is not None:
                return [self._tier("Registration fee", price)]
        if re.search(r"(?i)\bthis is a free (webinar|event|course|meeting)\b", body_text):
            return [self._tier("Registration fee", 0.0)]

        # Price-led fragments: "£250 for 1 day", "£450 for 2 days".
        led: List[Dict[str, Any]] = []
        for frag in re.split(r"[\n;]", body_text):
            frag = frag.strip()
            if len(frag) > 110:
                continue
            m = re.fullmatch(r"(£\s*[\d,]+(?:\.\d\d)?)\s+(\S.{2,90})", frag)
            if not m:
                continue
            price = self.parse_gbp(m.group(1))
            if price is None:
                continue
            label = m.group(2).strip(" .:-")
            led.append(self._tier(label[:1].upper() + label[1:], price))
        if led:
            return led

        # "Fee: £400, £470" — amounts with no labels at all.
        m = re.search(r"(?i)\bfees?\s*:\s*((?:£\s*[\d,]+(?:\.\d\d)?\s*,?\s*){1,6})", body_text)
        if m:
            out = []
            for raw in re.findall(r"£\s*[\d,]+(?:\.\d\d)?", m.group(1)):
                price = self.parse_gbp(raw)
                if price is not None:
                    out.append(self._tier("Registration fee", price))
            if out:
                return out
        return []

    def _table_tiers(self, html: str) -> List[Dict[str, Any]]:
        """FICM fee grids are plain <table>s whose header row reads
        "<Section> | Price". Scoped to the Pricing panel, so programme and
        workshop tables are never seen.

        The shared pricing_tables.parse_pricing_tables() does not fire here:
        it needs a fee-ish <h2>/<h3> above the table or a "Registration
        Fees"-style header row, and FICM has neither.
        """
        tiers: List[Dict[str, Any]] = []
        for tbl in re.findall(r"(?is)<table[^>]*>(.*?)</table>", html):
            rows = re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", tbl)
            if not rows or not any(re.search(r"£\s*[\d,]", r) for r in rows):
                continue

            section = None
            head_cells = re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", rows[0])
            if len(head_cells) >= 2 and "£" not in rows[0]:
                head_label, head_value = _flatten(head_cells[0]), _flatten(head_cells[-1])
                if re.fullmatch(r"(?i)price|fee|cost|rate|amount", head_value) and head_label:
                    section = head_label

            for row in rows:
                cells = re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", row)
                if len(cells) < 2:
                    continue
                label = _flatten(cells[0])
                if not label or re.fullmatch(
                    r"(?i)price|fee|cost|rate|amount|category|type", label
                ):
                    continue
                price = None
                for cell in reversed(cells[1:]):
                    price = self.parse_gbp(_flatten(cell))
                    if price is not None:
                        break
                if price is None:
                    continue
                tiers.append(
                    self._tier(f"{section} · {label}" if section else label, price)
                )

        seen: set = set()
        out: List[Dict[str, Any]] = []
        for t in tiers:
            key = (t["tier_label"], t["price_gbp"])
            if key not in seen:
                seen.add(key)
                out.append(t)
        return out

    @staticmethod
    def _tier(label: str, price: float) -> Dict[str, Any]:
        return {
            "tier_label": label[:120],
            "price_gbp": price,
            "currency": "GBP",
            "is_early_bird": bool(re.search(r"(?i)early[- ]?bird", label)),
            "early_bird_deadline": None,
        }

    # ------------------------------------------------------------------ #
    # Description + specialty
    # ------------------------------------------------------------------ #
    @staticmethod
    def _overview_text(overview_html: str) -> str:
        """The Overview tab's prose body, without the Key-details sidebar."""
        if not overview_html:
            return ""
        m = re.search(r'<div class="c-event-pane-overview__body">', overview_html)
        if not m:
            return ""
        return re.sub(r"\s*\n\s*", "\n", _strip_tags(_div_block(overview_html, m.end()))).strip()

    def _soft_fields(
        self,
        title: Optional[str],
        body_text: str,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        text = re.sub(r"\s*\n\s*", " ", body_text)[:3000]
        result: Dict[str, Any] = {}

        if text:
            prompt = f"""You are summarising a single medical event page from the Faculty of Intensive Care Medicine. Extract ONLY two fields.

EVENT TITLE: {title}

PAGE BODY:
{text}

Respond with valid JSON only, no markdown, no extra text:
{{
  "description": "concise 30-50 word summary built only from the page text" or null,
  "specialty": "primary clinical/topic area (e.g. Intensive Care Medicine, Critical Care Ultrasound, Anaesthetics, Neurology)" or null
}}"""
            raw = llm_call(prompt)
            if raw:
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
                    try:
                        parsed = json.loads(m.group(0))
                        result["description"] = parsed.get("description") or None
                        result["specialty"] = parsed.get("specialty") or None
                    except Exception as e:
                        logger.warning(f"FICM soft-fields JSON parse failed: {e}")

        if not result.get("specialty"):
            result["specialty"] = (
                classify_specialty(title, text) or "Intensive Care Medicine"
            )
        if not result.get("description"):
            result["description"] = (
                self._first_paragraph(body_text) or shell.get("description_hint")
            )
        return result

    @staticmethod
    def _first_paragraph(body_text: str) -> Optional[str]:
        for line in body_text.split("\n"):
            line = line.strip()
            if len(line) < 60 or line.startswith("http") or "£" in line:
                continue
            if re.match(r"^\d{1,2}[:.]\d{2}", line):
                continue
            if len(line) <= 320:
                return line
            cut = line[:320].rsplit(". ", 1)
            return (cut[0] + ".") if len(cut) == 2 else line[:320].rstrip() + "…"
        return None
