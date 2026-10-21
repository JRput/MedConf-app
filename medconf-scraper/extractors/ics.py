"""ICS (Intensive Care Society) events calendar: the same Eventfolio (Preside EMS) calendar as the BOA.

`ics.ac.uk/events/calendar.html` lists ~14 upcoming events (page size 21, no "Show more" needed today). Like the BOA
it is backed by `/ems/eventCalendar/ajaxResults/`, so Phase A reuses `EmsCalendarExtractor` from `ems_calendar.py`.

Rows are the Society's own webinars (Inside Intensive Care), virtual and face-to-face study days, FUSIC assessment days,
the State of the Art (SOA) congress, and the odd supported external conference (UK Shock). `On demand` rows (the SOA26
box set) are skipped. Fees are in the Booking widget when published ("ICS members - £215", "Free for ICS members" /
"£30 for non-members"); the booking pages themselves are behind a login, so rows with no widget price have no fee.

The congress card (`calendar/soa-congress-2027-soa27.html`) is a stub that links to the real congress microsite
`/events/soa27.html`: key deadlines (abstract opening/closing, early-bird end) are read from there, and its
`/events/soa27/tickets.html` publishes the fee tables only as images (PLAYBOOK coverage pattern 3). The extractor stores no
fee row for them and exposes the tickets page as `organiser_url` for the remediator's image fee explorer.
"""
import html as _html
import re
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from logger import logger

from .ems_calendar import EmsCalendarExtractor, _clean, _iso, _MONTHS, _MON_RE
from .http_fetch import fetch_html
from .tribe_events import html_to_lines

_SOA_LINK_RE = re.compile(r'href="(https?://(?:www\.)?ics\.ac\.uk/events/(soa\d+)\.html)"', re.I)


def parse_soa_deadlines(text: str) -> Dict[str, Optional[str]]:
    """'Abstract submission opens: 15 October 2026' / 'closes: 15 February 2027' / 'Early Bird registration: 12 April 2027'. Pure."""
    out: Dict[str, Optional[str]] = {"opens": None, "closes": None, "early_bird": None}

    def grab(label_rx: str) -> Optional[str]:
        m = re.search(rf"{label_rx}\s*:?\s*(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MON_RE})\s+(\d{{4}})", text, re.I)
        return _iso(int(m.group(3)), _MONTHS[m.group(2)[:3].lower()], int(m.group(1))) if m else None

    out["opens"] = grab(r"abstract submission opens")
    out["closes"] = grab(r"abstract submission closes")
    out["early_bird"] = grab(r"early bird registration")
    return out


class IcsExtractor(EmsCalendarExtractor):
    ROOT = "https://ics.ac.uk"
    CALENDAR_PATH = "/events/calendar.html"
    LISTING_URL = ROOT + CALENDAR_PATH
    SOCIETY = "Intensive Care Society"
    DEFAULT_SPECIALTY = "Intensive Care Medicine"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"

    def event_type_for(self, title: str, category: str, days: int = 0) -> str:
        c = (category or "").lower()
        if re.search(r"webinar|study day|assessment", c):
            return "workshop"
        if re.search(r"congress|conference", c):
            return "conference"
        return super().event_type_for(title, category, days)

    def extra_detail(self, html: str, shell: Dict[str, Any], out: Dict[str, Any]) -> None:
        cat = (shell.get("category") or "").lower()
        if not out.get("event_format") and re.search(r"webinar|virtual", cat):
            out["event_format"] = "online"                # webinar / virtual study day cards carry a camera badge and no venue
        if (shell.get("category") or "").lower() != "congress":
            return
        m = _SOA_LINK_RE.search(html)
        if not m:
            return
        browser = getattr(self, "browser", None)
        micro_url, code = m.group(1), m.group(2).lower()
        micro = fetch_html(micro_url, browser=browser)
        if micro:
            dl = parse_soa_deadlines(" ".join(html_to_lines(micro)))
            today = date.today().isoformat()
            if dl["closes"]:
                out["abstract_deadline"] = dl["closes"]
                out["abstract_open"] = bool(dl["closes"] >= today and (not dl["opens"] or dl["opens"] <= today))
            intro = re.search(r'(?is)class="page-banner-content-intro"[^>]*>(.*?)</div>', micro)
            text = _clean(intro.group(1)) if intro else ""
            if len(text) > len(out.get("description") or "") or (out.get("description") or "").lower().startswith("welcome"):
                out["description"] = text[:600] or out.get("description")
        # The ticket page publishes its fee tables as images only (the 3-day image file is even named "SOA26-3-day-price-table").
        # A trial run of the vision chain timed out on two of three images and returned broken JSON on the third, so no fee row
        # is stored here. The page is handed to the remediator's explorer (image fee tables, PLAYBOOK pattern 3) instead.
        out["pricing_tiers"] = []
        out["organiser_url"] = f"{self.ROOT}/events/{code}/tickets.html"

