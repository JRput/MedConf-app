"""
Faculty of Intensive Care Medicine (FICM) — events extractor.

ANTI-BOT SITUATION (probed 2026-09-26 — read this before changing anything).
The whole ficm.ac.uk HTML site sits behind an *interactive* Cloudflare
challenge ("Just a moment…", cf-chl / challenges.cloudflare.com turnstile):

  * httpx / curl / WebFetch on /events            → HTTP 403 challenge page
  * headless Chromium (BrowserController, prod flags), /events
    → HTTP 403, title "Just a moment...", 28 635 bytes, and it NEVER
      clears: polled every 5 s for 60 s, body length frozen after t=5 s.
  * HEADED Chromium (headless=False) → 200, the real 261 KB page — but only
    for the FIRST navigation. ?page=1, ?page=2 and a detail page in the same
    session all fell straight back to 403. So even a headed browser is not a
    dependable route, and headed is not available on a GitHub runner anyway.
  * /robots.txt, /sitemap.xml, /jsonapi, /events?_format=json, /events/feed,
    /node/feed, the apex host — all 403.

The one route that is NOT challenged is the site-wide Drupal RSS feed:

    https://www.ficm.ac.uk/rss.xml   → 200, ~104 KB, cf-cache-status DYNAMIC
                                       (origin-served, not a stale cache),
                                       works with ANY User-Agent including
                                       "python-httpx/0.27".

That feed is what this extractor uses, and it is unusually rich: Drupal
renders each node's FULL body into <description>, so one feed fetch gives
us the listing *and* every detail page. No per-event fetch is needed — and
no per-event fetch is *possible*.

Consequences you must know about:
  * COVERAGE IS PARTIAL. rss.xml is the 10 most recently *created* nodes
    site-wide — news posts included — not the /events view. On 2026-09-26 it
    carried 9 event nodes, of which only 5 were among the 9 upcoming events
    the real /events page 0 listed; famusfusic, fficm-oscesoe-exam-online-
    course-autumn-2026, getting-ready-...-acre and leeds-...-lactic were
    absent, as was everything on ?page=1. The feed can also drift to zero
    events if FICM publishes ten news items in a row.
  * `extract_detail()` IGNORES the Playwright `page`. The scraper navigates
    to booking_url before calling us; that navigation lands on the 403
    challenge. Everything is parsed from the node body stashed on the shell
    by `list_shells_override()` under `_ficm_body`.
  * booking_url is still the FICM event page — a human's real browser passes
    the challenge fine, so the link works for users.

Node-body shape (consistent across all 9 observed items):
  * a <span class="field field--name-created"><time>…</time></span> holding
    the node's CREATION timestamp — must be stripped before date parsing, or
    it is mistaken for the event date;
  * then 1-2 bare <time datetime="YYYY-MM-DDT12:00:00Z"> tags = start (and
    end) date;
  * then an availability word ("Places available" / "Sold out" /
    "Available soon"), then the BOOK NOW anchor;
  * the prose body, sometimes with <table> fee grids whose header row is
    "<Section> | Price";
  * a structured tail, read backwards from the literal line "Listing image":
    [category: "External Event" | "Education" | …], [venue line, sometimes
    absent], ["In person" | "Online" | "Hybrid"], [CPD points: "10", "6 TBC",
    "TBC" — sometimes absent].
  * "Pricing tab title / £300" near the very end is a Drupal *label*
    placeholder present on every node — never a real fee. It sits after the
    "Listing image" marker and outside any <table>, so cutting the prose at
    that marker is what keeps it out of pricing_tiers.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Page

from .base import BaseExtractor
from .http_fetch import fetch_html
from .specialty_classifier import classify_specialty
from logger import logger

FEED_URL = "https://www.ficm.ac.uk/rss.xml"
BASE_URL = "https://www.ficm.ac.uk"

_FORMAT_TOKENS = {
    "in person": "in_person",
    "in-person": "in_person",
    "online": "online",
    "hybrid": "hybrid",
}

# Availability words FICM renders under the date block.
_SOLD_OUT = re.compile(r"(?i)\b(sold\s*out|fully\s*booked|waiting\s*list\s*only)\b")

_UK_NATION_HINTS = [
    (re.compile(r"(?i)\b(belfast|northern ireland|derry|londonderry)\b"), "Northern Ireland"),
    (re.compile(r"(?i)\b(edinburgh|glasgow|aberdeen|dundee|scotland|stirling)\b"), "Scotland"),
    (re.compile(r"(?i)\b(cardiff|swansea|wales|newport|bangor)\b"), "Wales"),
]
_ENGLAND_HINT = re.compile(
    r"(?i)\b(london|manchester|birmingham|leeds|liverpool|bristol|sheffield|"
    r"newcastle|nottingham|leicester|coventry|oxford|cambridge|southampton|"
    r"brighton|york|exeter|plymouth|norwich|reading|derby|hull|preston)\b"
)

# Used to recover a city when the comma-separated tail of a venue line is
# another institution rather than a place ("…Institute, Queen's University
# Belfast" → city Belfast, not "Queen's University Belfast").
_CITY_TOKEN = re.compile(
    r"(?i)\b(london|manchester|birmingham|leeds|liverpool|bristol|sheffield|"
    r"newcastle|nottingham|leicester|coventry|oxford|cambridge|southampton|"
    r"brighton|york|exeter|plymouth|norwich|reading|derby|hull|preston|"
    r"belfast|edinburgh|glasgow|aberdeen|dundee|stirling|cardiff|swansea|"
    r"newport|bangor|derry|londonderry)\b"
)

# A comma-tail that names an organisation, not a town.
_ORG_TAIL = re.compile(
    r"(?i)\b(university|hospital|institute|college|centre|center|school|"
    r"faculty|trust|nhs|campus|academy|foundation)\b"
)


def _strip_tags(fragment: str) -> str:
    """HTML fragment → newline-separated text, entities decoded."""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", fragment)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = html_lib.unescape(text)
    return text.replace("\xa0", " ")


def _text_lines(fragment: str) -> List[str]:
    return [ln.strip() for ln in _strip_tags(fragment).split("\n") if ln.strip()]


def _flatten(fragment: str) -> str:
    return re.sub(r"\s+", " ", _strip_tags(fragment)).strip()


def _normalise_feed(raw: str) -> str:
    """Return the raw RSS, whichever way it arrived.

    httpx hands us the feed verbatim. The Playwright fallback (what a
    GitHub runner takes when httpx is blocked) hands us Chromium's XML
    *viewer*: the whole feed entity-escaped inside <html><body><pre>. One
    unescape of that <pre> reproduces the original bytes exactly — the node
    bodies are double-escaped there, so they land back at single-escaped.
    """
    if "<item>" in raw:
        return raw
    if "&lt;item&gt;" in raw:
        m = re.search(r"(?is)<pre[^>]*>(.*?)</pre>", raw)
        return html_lib.unescape(m.group(1) if m else raw)
    return raw


def _drop_created_field(body: str) -> str:
    """Remove the node-created <time>, which would otherwise be read as the
    event date (it always sorts first in the body)."""
    return re.sub(
        r'(?is)<span class="field field--name-created[^"]*"[^>]*>.*?</span>', "", body
    )


class FICMExtractor(BaseExtractor):
    """Feed-driven extractor — see the module docstring for why."""

    # ------------------------------------------------------------------ #
    # Phase A — listing, from rss.xml
    # ------------------------------------------------------------------ #
    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        xml = fetch_html(FEED_URL, browser=getattr(self, "browser", None))
        if not xml:
            logger.warning("FICM: rss.xml fetch returned nothing")
            return []
        xml = _normalise_feed(xml)

        today = date.today()
        shells: List[Dict[str, Any]] = []
        for item in re.findall(r"(?s)<item>(.*?)</item>", xml):
            link_m = re.search(r"(?s)<link>(.*?)</link>", item)
            title_m = re.search(r"(?s)<title>(.*?)</title>", item)
            desc_m = re.search(r"(?s)<description>(.*?)</description>", item)
            if not (link_m and title_m and desc_m):
                continue

            url = html_lib.unescape(link_m.group(1).strip())
            # The feed is site-wide: news, committee calls, job posts. Only
            # /events/ nodes are events.
            if "/events/" not in url:
                continue

            title = re.sub(r"\s+", " ", html_lib.unescape(title_m.group(1))).strip()
            body = html_lib.unescape(desc_m.group(1))
            start, end = self._parse_dates(body)
            if not start:
                logger.info(f"FICM: no event date on '{title[:60]}' — skipping")
                continue
            # Only upcoming: a multi-day event is live until its last day.
            if (end or start) < today:
                continue

            shells.append(
                {
                    "title": title,
                    "booking_url": url,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat() if end else None,
                    "is_sold_out": bool(_SOLD_OUT.search(_flatten(body))),
                    "_ficm_body": body,
                }
            )

        logger.info(f"FICM: {len(shells)} upcoming event shells from rss.xml")
        return shells

    @staticmethod
    def _parse_dates(body: str) -> tuple[Optional[date], Optional[date]]:
        """First/last bare <time datetime> in the node body, created-field removed."""
        stamps: List[date] = []
        for raw in re.findall(
            r'<time[^>]+datetime="([^"]+)"', _drop_created_field(body)
        ):
            try:
                stamps.append(datetime.fromisoformat(raw.replace("Z", "+00:00")).date())
            except ValueError:
                continue
        if not stamps:
            return None, None
        stamps.sort()
        return stamps[0], (stamps[-1] if stamps[-1] != stamps[0] else None)

    # ------------------------------------------------------------------ #
    # Phase B — detail, from the stashed node body
    # ------------------------------------------------------------------ #
    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        # `page` is deliberately unused: the scraper has already navigated it
        # to the Cloudflare challenge. Everything comes from the feed body.
        body: str = shell.get("_ficm_body") or ""
        if not body:
            logger.warning(f"FICM: no stashed body for {shell.get('booking_url')}")
            return {}

        title = shell.get("title")
        tail = self._parse_tail(body)
        prose = self._prose(body)

        result: Dict[str, Any] = {
            "event_type": self._event_type(title),
            "event_format": tail.get("event_format"),
            "venue_name": tail.get("venue_name"),
            "city": tail.get("city"),
            "region": tail.get("region"),
            "cpd_points": tail.get("cpd_points"),
            "cpd_accredited": tail.get("cpd_points") is not None,
            "pricing_tiers": self._pricing(body, prose),
            "start_time": self._start_time(prose),
        }
        result.update(self._soft_fields(title, prose, llm_call))
        return {k: v for k, v in result.items() if v is not None}

    # ------------------------------------------------------------------ #
    # Structured tail: CPD · format · venue · category
    # ------------------------------------------------------------------ #
    def _parse_tail(self, body: str) -> Dict[str, Any]:
        lines = _text_lines(body)
        try:
            stop = lines.index("Listing image")
        except ValueError:
            stop = len(lines)
        # The category line ("External Event" / "Education") is the last
        # entry before "Listing image"; the format token sits just above it.
        seg = lines[:stop]
        fmt_idx = None
        for i in range(len(seg) - 1, max(-1, len(seg) - 8), -1):
            if seg[i].strip().lower() in _FORMAT_TOKENS:
                fmt_idx = i
                break
        out: Dict[str, Any] = {
            "event_format": None,
            "venue_name": None,
            "city": None,
            "region": None,
            "cpd_points": None,
        }
        if fmt_idx is None:
            return out

        out["event_format"] = _FORMAT_TOKENS[seg[fmt_idx].strip().lower()]

        # CPD points: the line directly above the format token, when it is a
        # bare number ("10") or a number with a TBC qualifier ("6 TBC").
        if fmt_idx > 0:
            m = re.fullmatch(r"(\d{1,2})(?:\s*TBC)?", seg[fmt_idx - 1].strip(), re.I)
            if m:
                out["cpd_points"] = int(m.group(1))

        # Venue: the line between the format token and the category line.
        # Absent on some online-only nodes, where format is last before it.
        if fmt_idx + 1 < len(seg) - 1:
            venue = re.sub(r"^at\s+", "", seg[fmt_idx + 1].strip(), flags=re.I).strip(" ,")
            if venue and len(venue) < 160:
                out.update(self._place(venue, out["event_format"]))
        if out["event_format"] == "online" and not out["venue_name"]:
            out["city"] = out["city"] or "Online"
        return out

    @staticmethod
    def _place(venue: str, event_format: Optional[str]) -> Dict[str, Any]:
        """Split a FICM venue line into venue_name / city / region."""
        # "The Marriott, Manchester Piccadilly and Online" → hybrid signal.
        if event_format == "in_person" and re.search(r"(?i)\band online\b", venue):
            event_format = "hybrid"
        if re.fullmatch(r"(?i)(zoom|online|ms teams|teams|webinar)", venue.strip()):
            return {"venue_name": None, "city": "Online", "region": None,
                    "event_format": "online"}

        parts = [p.strip() for p in venue.split(",") if p.strip()]
        venue_name = venue
        city = None
        if len(parts) >= 2:
            tail = re.sub(r"(?i)\s+and online$", "", parts[-1]).strip()
            if _ORG_TAIL.search(tail):
                # "…Institute for Experimental Medicine, Queen's University
                # Belfast" — the tail is a second institution, so the whole
                # line is the venue and the town comes from a city token.
                venue_name = re.sub(r"(?i)\s+and online$", "", venue).strip()
                m = _CITY_TOKEN.search(venue)
                city = m.group(1).title() if m else None
            else:
                venue_name = ", ".join(parts[:-1])
                # "Manchester Piccadilly" → "Manchester": keep the town, not
                # the district/station the venue happens to sit by.
                m = _CITY_TOKEN.search(tail)
                city = m.group(1).title() if m else tail
        elif parts and _CITY_TOKEN.fullmatch(parts[0]):
            # A bare "Coventry" is a city, not a venue.
            venue_name, city = None, parts[0]

        haystack = venue
        region = None
        for pattern, nation in _UK_NATION_HINTS:
            if pattern.search(haystack):
                region = nation
                break
        if region is None and _ENGLAND_HINT.search(haystack):
            region = "England"

        out = {"venue_name": venue_name, "city": city, "region": region}
        if event_format == "hybrid":
            out["event_format"] = "hybrid"
        return out

    # ------------------------------------------------------------------ #
    # Prose body (everything after the BOOK NOW / availability block,
    # before the structured tail) — used for description + inline fees.
    # ------------------------------------------------------------------ #
    @staticmethod
    def _prose(body: str) -> str:
        stripped = _drop_created_field(body)
        cut = stripped.rfind("</time>")
        tail_html = stripped[cut:] if cut != -1 else stripped
        lines = _text_lines(tail_html)
        try:
            stop = lines.index("Listing image")
            lines = lines[:stop]
        except ValueError:
            pass
        # Drop the availability / CTA chrome that always leads the block.
        drop = re.compile(
            r"(?i)^(book now|register now|registration open|bookings? open(ing)?( soon)?|"
            r"places available|available soon|sold out|waiting list|more info(rmation)?|"
            r"external event|education|in person|online|hybrid|tbc|register:|contact:)[:.]?$"
        )
        keep = [ln for ln in lines if not drop.fullmatch(ln.strip()) and len(ln) > 2]
        return "\n".join(keep)

    @staticmethod
    def _start_time(prose: str) -> Optional[str]:
        """FICM programmes open with a "8:30 - 09:00 Registration" row."""
        m = re.search(
            r"(?m)^(\d{1,2})[:.](\d{2})\s*(?:am|pm)?\s*[-–]\s*\d{1,2}[:.]\d{2}",
            prose[:1500],
            re.I,
        )
        if not m:
            return None
        hour, minute = int(m.group(1)), int(m.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return f"{hour:02d}:{minute:02d}"

    # ------------------------------------------------------------------ #
    # Pricing — fee <table>s first, then an inline "Registration fee:" line
    # ------------------------------------------------------------------ #
    def _pricing(self, body: str, prose: str) -> List[Dict[str, Any]]:
        tiers = self._table_tiers(body)
        if tiers:
            return tiers

        # "Registration fee: Free" → a real £0 tier. "Registration fee: £160".
        m = re.search(r"(?i)registration fee\s*:?\s*(free|£\s*[\d,]+(?:\.\d\d)?)", prose)
        if m:
            token = m.group(1)
            price = 0.0 if token.lower() == "free" else self.parse_gbp(token)
            if price is not None:
                return [self._tier("Registration fee", price)]
        if re.search(r"(?i)\bthis is a free (webinar|event|course|meeting)\b", prose):
            return [self._tier("Registration fee", 0.0)]

        # Price-led lines: "£250 for 1 day (Day 1 echo…)" / "£450 for 2 days".
        # Only whole short lines that START with the amount — never a £ found
        # mid-paragraph, which is usually narrative, not a tier.
        led: List[Dict[str, Any]] = []
        for line in prose.split("\n"):
            line = line.strip()
            if len(line) > 110:
                continue
            m = re.fullmatch(r"(£\s*[\d,]+(?:\.\d\d)?)\s+(\S.{2,90})", line)
            if not m:
                continue
            price = self.parse_gbp(m.group(1))
            if price is None:
                continue
            label = m.group(2).strip(" .:-")
            led.append(self._tier(label[:1].upper() + label[1:], price))
        if led:
            return led

        # Last resort: "Fee: £400, £470" — a bare list with no labels. Emit
        # them as unlabelled tiers rather than guessing who pays what.
        m = re.search(r"(?i)\bfees?\s*:\s*((?:£\s*[\d,]+(?:\.\d\d)?\s*,?\s*){1,6})", prose)
        if m:
            out = []
            for raw in re.findall(r"£\s*[\d,]+(?:\.\d\d)?", m.group(1)):
                price = self.parse_gbp(raw)
                if price is not None:
                    out.append(self._tier("Registration fee", price))
            if out:
                return out
        return []

    def _table_tiers(self, body: str) -> List[Dict[str, Any]]:
        """FICM fee grids are plain <table>s whose header row reads
        "<Section> | Price". Programme tables (time | session | speaker)
        carry no £ and are skipped.

        The shared pricing_tables.parse_pricing_tables() does not fire here:
        it needs a fee-ish <h2>/<h3> above the table or a "Registration
        Fees"-style header row, and FICM has neither.
        """
        tiers: List[Dict[str, Any]] = []
        for tbl in re.findall(r"(?is)<table[^>]*>(.*?)</table>", body):
            rows = re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", tbl)
            priced = [r for r in rows if re.search(r"£\s*[\d,]", r)]
            if len(priced) < 1:
                continue

            section = None
            first_cells = re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", rows[0]) if rows else []
            if len(first_cells) >= 2 and not re.search(r"£", rows[0]):
                head_label = _flatten(first_cells[0])
                head_value = _flatten(first_cells[-1])
                if re.fullmatch(r"(?i)price|fee|cost|rate|amount", head_value) and head_label:
                    section = head_label

            for row in rows:
                cells = re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", row)
                if len(cells) < 2:
                    continue
                label = _flatten(cells[0])
                if not label or re.fullmatch(r"(?i)price|fee|cost|rate|amount|category|type", label):
                    continue
                price = None
                for cell in reversed(cells[1:]):
                    price = self.parse_gbp(_flatten(cell))
                    if price is not None:
                        break
                if price is None:
                    continue
                tiers.append(self._tier(f"{section} · {label}" if section else label, price))

        # Dedupe. The Drupal "Pricing tab title / £300" placeholder that every
        # node carries never reaches here: it lives after the "Listing image"
        # marker (so _prose() has cut it) and is not inside a <table>.
        seen = set()
        out = []
        for t in tiers:
            key = (t["tier_label"], t["price_gbp"])
            if key in seen:
                continue
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
    # event_type
    # ------------------------------------------------------------------ #
    @staticmethod
    def _event_type(title: Optional[str]) -> str:
        t = (title or "").lower()
        # Checked first: "Intensivists in Training Conference" is a
        # conference, not a course, despite the word "training".
        if re.search(r"\b(conference|congress|symposium|summit|meeting|forum)\b", t):
            return "conference"
        if re.search(r"\bworkshop\b", t):
            return "workshop"
        if re.search(r"\b(course|training|masterclass|webinar|study day|teaching day)\b", t):
            return "course"
        return "conference"

    # ------------------------------------------------------------------ #
    # Soft fields — one small LLM call, deterministic backstops
    # ------------------------------------------------------------------ #
    def _soft_fields(
        self,
        title: Optional[str],
        prose: str,
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        text = re.sub(r"\s*\n\s*", " ", prose)[:3000]
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
            result["description"] = self._first_paragraph(prose)
        return result

    @staticmethod
    def _first_paragraph(prose: str) -> Optional[str]:
        for line in prose.split("\n"):
            line = line.strip()
            # A real sentence, not a URL, a fee line or a programme row.
            if len(line) < 60 or line.startswith("http") or "£" in line:
                continue
            if re.match(r"^\d{1,2}[:.]\d{2}", line):
                continue
            if len(line) <= 320:
                return line
            cut = line[:320].rsplit(". ", 1)
            return (cut[0] + ".") if len(cut) == 2 else line[:320].rstrip() + "…"
        return None
