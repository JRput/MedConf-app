"""British Oncology Pharmacy Association — events extractor.

Listing strategy:
  BOPA's site runs The Events Calendar (Tribe Events) WordPress plugin,
  which exposes a clean REST API at /wp-json/tribe/events/v1/events.
  No DOM walking needed — we hit the API for shells.

Detail strategy:
  The Tribe event page (`/event/<slug>/`) is a thin wrapper. Rich content
  for the BIG annual conference lives at separate URLs like
  `/latest-conference-2026/` and `/abstract-submission-...-2026/`.

  We intentionally let the per-event detail page give us only what's
  easy (title, date, venue, basic description). For the flagship
  conference where Tribe shows cost='-' and no abstract info, the
  remediator's Tier 2 explorer will discover the sub-pages and fill the
  gaps. This is the test case for the explorer-as-discoverer pattern.
"""

import re
import httpx
from datetime import date, timedelta
from typing import Dict, Any, Optional, Callable, List
from playwright.sync_api import Page

from .base import BaseExtractor
from .specialty_classifier import classify_specialty
from logger import logger


API_URL = "https://www.bopa.org.uk/wp-json/tribe/events/v1/events"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)


def _parse_cost_text(cost_text: str) -> List[Dict[str, Any]]:
    """Tribe's `cost` field is free-form: '£25', '£50 – £100', '£0', '-'.
    Convert to tier list. Returns empty list if no parseable money."""
    if not cost_text or cost_text.strip() == "-":
        return []
    txt = cost_text.strip()
    if re.search(r"\bfree\b", txt, re.I):
        return [{"tier_label": "Free", "price_gbp": 0.0, "currency": "GBP",
                 "is_early_bird": False, "early_bird_deadline": None}]
    # Range: "£50 – £100" → two tiers
    rng = re.search(r"£\s*([0-9]+(?:\.\d+)?)\s*[–-]\s*£\s*([0-9]+(?:\.\d+)?)", txt)
    if rng:
        low, high = float(rng.group(1)), float(rng.group(2))
        return [
            {"tier_label": "From", "price_gbp": low, "currency": "GBP",
             "is_early_bird": False, "early_bird_deadline": None},
            {"tier_label": "To", "price_gbp": high, "currency": "GBP",
             "is_early_bird": False, "early_bird_deadline": None},
        ]
    # Single: "£25"
    one = re.search(r"£\s*([0-9]+(?:\.\d+)?)", txt)
    if one:
        return [{"tier_label": "Standard", "price_gbp": float(one.group(1)),
                 "currency": "GBP", "is_early_bird": False,
                 "early_bird_deadline": None}]
    return []


def _strip_html(html: str) -> str:
    if not html:
        return ""
    t = re.sub(r"<[^>]+>", " ", html)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _classify_event_type(title: str, cats: List[str]) -> str:
    title_l = (title or "").lower()
    cat_text = " ".join(c.lower() for c in (cats or []))
    if any(k in title_l for k in ("course", "training", "module")):
        return "course"
    if any(k in title_l for k in ("workshop", "study day", "webinar")):
        return "workshop"
    if "webinar" in cat_text or "training" in cat_text:
        return "workshop"
    if "conference" in cat_text or "symposium" in title_l or "conference" in title_l:
        return "conference"
    return "conference"



CONFERENCE_PAGE = "https://www.bopa.org.uk/latest-conference-{year}/"
# hero line of the annual conference page: "1-3 October 2027  - Harrogate Convention Centre"
_HERO_RE = re.compile(
    r"(\d{1,2})\s*[-\u2013]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*[-\u2013]\s*([^<\n]{3,80}?)\s*(?:<|\n|$)")
_ORDINAL_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)\s+BOPA\s+(?:Annual\s+)?Conference", re.I)
_SAVE_THE_DATE_RE = re.compile(r"save the date|more info will follow", re.I)


def conference_page_shell(html: str, url: str, year: int) -> Optional[Dict[str, Any]]:
    """The annual conference page (/latest-conference-<year>/) is a plain page, not a
    Tribe event, so the events API never lists it (2026-11-20: the 2027 save-the-date
    page sat in the database undated and 'online'). Build its shell from the hero
    line; None when the page carries no hero line for that year."""
    if not html:
        return None
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    m = None
    for cand in _HERO_RE.finditer(text):
        if int(cand.group(4)) == year:
            m = cand
            break
    if not m:
        return None
    try:
        from datetime import datetime
        month = datetime.strptime(m.group(3)[:3], "%b").month
        start = date(year, month, int(m.group(1)))
        end = date(year, month, int(m.group(2)))
    except ValueError:
        return None
    if end < start:
        return None
    venue = re.sub(r"\s+", " ", _strip_html(m.group(5))).strip(" -\u2013")
    city = None
    cm = re.match(r"([A-Z][a-z]+)\s+(?:Convention|Conference|Exhibition)\s+Centre", venue)
    if cm:
        city = cm.group(1)
    plain = _strip_html(text)
    om = _ORDINAL_RE.search(plain)
    n = om.group(1) if om else None
    title = f"{n}{_suffix(int(n))} BOPA Annual Conference {year}" if n else f"BOPA Annual Conference {year}"
    return {
        "title": title, "booking_url": url, "source_url": url,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "venue_name": venue or None, "city": city, "cost_raw": "", "description_html": "",
        "categories": ["Conference"], "category": "Conference", "image_url": None,
        "flagship_page": True, "save_the_date": bool(_SAVE_THE_DATE_RE.search(plain)),
    }


def _suffix(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


class BOPAExtractor(BaseExtractor):
    """British Oncology Pharmacy Association."""

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today()
        # Ask from 30 days back: Tribe's start_date filter is on the START, so an
        # event already under way (BOPA AI Hackathon, 18-25 Nov 2026) vanished
        # from a from-today query. Events that have ENDED are skipped below.
        since = (today - timedelta(days=30)).isoformat()
        url = f"{API_URL}?per_page=100&start_date={since}"
        shells: List[Dict[str, Any]] = []
        api_answered = False          # a 200 JSON answer, even an empty one, is the site's own reply
        try:
            with httpx.Client(timeout=30, follow_redirects=True,
                              headers={"User-Agent": USER_AGENT,
                                       "Accept": "application/json"}) as c:
                # Tribe paginates; walk till empty
                page = 1
                while page <= 5:
                    r = c.get(f"{url}&page={page}")
                    if r.status_code != 200:
                        break
                    data = r.json()
                    api_answered = True
                    events = data.get("events") or []
                    if not events:
                        break
                    for e in events:
                        title = e.get("title") or ""
                        booking_url = e.get("url") or ""
                        if not title or not booking_url:
                            continue
                        end_iso = (e.get("end_date") or e.get("start_date") or "")[:10]
                        if end_iso and end_iso < today.isoformat():
                            continue                      # already over
                        cats = [c.get("name") for c in (e.get("categories") or []) if c.get("name")]
                        venue = e.get("venue") or {}
                        if isinstance(venue, dict):
                            venue_name = venue.get("venue") or ""
                            city = venue.get("city") or ""
                        else:
                            venue_name = ""
                            city = ""
                        shells.append({
                            "title": title,
                            "booking_url": booking_url,
                            "source_url": booking_url,
                            "start_date": (e.get("start_date") or "")[:10] or None,
                            "end_date": (e.get("end_date") or "")[:10] or None,
                            "venue_name": venue_name if venue_name.lower() not in ("online", "") else None,
                            "city": city if city else None,
                            "cost_raw": e.get("cost") or "",
                            "description_html": e.get("description") or "",
                            "categories": cats,
                            "category": cats[0] if cats else None,
                            "image_url": (e.get("image") or {}).get("url"),
                        })
                    page += 1
                # the annual conference page, this year's or next year's, when the API
                # does not already list a conference for that year
                for year in (today.year, today.year + 1):
                    if any(str(year) in sh["title"] and "conference" in sh["title"].lower()
                           for sh in shells):
                        continue
                    try:
                        pr = c.get(CONFERENCE_PAGE.format(year=year))
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"BOPA conference page {year} fetch failed: {e}")
                        continue
                    sh = conference_page_shell(pr.text, str(pr.url), year) if pr.status_code == 200 else None
                    if sh and sh["end_date"] >= today.isoformat():
                        shells.append(sh)
                        break                 # a past year's page: try the next year
        except Exception as e:
            logger.warning(f"BOPA Tribe API fetch failed: {e}")
            return None
        logger.info(f"BOPA Tribe API returned {len(shells)} shells")
        if shells:
            return shells
        if api_answered:
            # 2026-11-19: the API answered 200 with zero published upcoming events.
            # Returning None here handed the listing to the generic page walker,
            # which turned every /events/list/page/N/ (bopa.org.uk serves a 200
            # page for ANY page number) into an "event" titled from the Tribe
            # search bar heading, "Events Search and Views Navigation" (60 rows).
            # Zero from the API is the site's answer: verified empty, no fallback.
            self.verified_empty = "Tribe events API answered 200 with no published upcoming events"
            return []
        return None

    def extract_detail(
        self,
        page: Page,
        shell: Dict[str, Any],
        llm_call: Callable[[str], Optional[str]],
    ) -> Dict[str, Any]:
        out: Dict[str, Any] = {}

        title = shell.get("title") or ""
        cats = shell.get("categories") or []

        # 1. Event type from title + categories
        out["event_type"] = _classify_event_type(title, cats)

        # 2. Format
        venue_name = shell.get("venue_name") or ""
        cat_text = " ".join(c.lower() for c in cats)
        if venue_name and re.search(r"virtual|online|zoom|webinar", venue_name, re.I):
            out["event_format"] = "online"        # Tribe venue "Virtual – Online" (AI Hackathon)
        elif venue_name:
            out["event_format"] = "in_person"
            out["venue_name"] = venue_name
            if shell.get("city"):
                out["city"] = shell["city"]
        elif "webinar" in cat_text or "online" in cat_text:
            out["event_format"] = "online"
        else:
            out["event_format"] = "online"  # Tribe leaves venue blank for online

        # 3. Description from API
        desc_text = _strip_html(shell.get("description_html") or "")
        if desc_text:
            # Trim to 50-700 chars range (validator-safe)
            if len(desc_text) > 700:
                desc_text = desc_text[:697].rstrip() + "..."
            if len(desc_text) >= 50:
                out["description"] = desc_text

        # 4. Pricing from cost_raw (only if it parses)
        cost_raw = shell.get("cost_raw") or ""
        tiers = _parse_cost_text(cost_raw)
        if tiers:
            out["pricing_tiers"] = tiers

        # 5. Specialty
        out["specialty"] = (
            classify_specialty(title) or "Oncology"  # BOPA = Oncology Pharmacy
        )

        # 6. Society
        out["society"] = "BOPA"

        # 6b. The annual conference page (conference_page_shell): flagship; a
        # save-the-date page has no abstract call yet, and saying so keeps the
        # discovery engine from reading the previous year's "Submit your
        # abstract for BOPA <year-1>" link on the same page as this year's call.
        if shell.get("flagship_page"):
            out["is_flagship"] = True
            out["description"] = (f"{title} will be held at {shell.get('venue_name') or 'a venue to be announced'} "
                                  f"on {shell['start_date']} to {shell['end_date']}. "
                                  "Registration and abstract details follow on the BOPA website.")
            if shell.get("save_the_date"):
                out["abstract_open"] = False
                out["abstract_deadline_note"] = "Abstract submission not yet announced"

        # 7. Region — Tribe city → UK region (light heuristic)
        city = (shell.get("city") or "").lower()
        if "london" in city:
            out["region"] = "London"

        # NOTE: We deliberately do NOT scrape the detail page HTML for fees,
        # abstracts, CPD here. The remediator's Tier 2 explorer will discover
        # sub-pages (e.g. /latest-conference-2026/) for the flagship event.
        # This makes BOPA a clean test case for the explorer.

        return out
