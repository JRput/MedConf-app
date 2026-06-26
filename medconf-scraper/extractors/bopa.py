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
from datetime import date
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


class BOPAExtractor(BaseExtractor):
    """British Oncology Pharmacy Association."""

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        today = date.today().isoformat()
        url = f"{API_URL}?per_page=100&start_date={today}"
        shells: List[Dict[str, Any]] = []
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
                    events = data.get("events") or []
                    if not events:
                        break
                    for e in events:
                        title = e.get("title") or ""
                        booking_url = e.get("url") or ""
                        if not title or not booking_url:
                            continue
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
        except Exception as e:
            logger.warning(f"BOPA Tribe API fetch failed: {e}")
            return None
        logger.info(f"BOPA Tribe API returned {len(shells)} shells")
        return shells if shells else None

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
        if venue_name:
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

        # 7. Region — Tribe city → UK region (light heuristic)
        city = (shell.get("city") or "").lower()
        if "london" in city:
            out["region"] = "London"

        # NOTE: We deliberately do NOT scrape the detail page HTML for fees,
        # abstracts, CPD here. The remediator's Tier 2 explorer will discover
        # sub-pages (e.g. /latest-conference-2026/) for the flagship event.
        # This makes BOPA a clean test case for the explorer.

        return out
