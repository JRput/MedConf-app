"""European Association of Neurosurgical Societies (eans.org): YourMembership community calendar, see `community_calendar.py`.

The calendar carries EANS courses plus national-society and community meetings, in six categories (EANS events, training courses,
national member society events, congresses, community events). All are neurosurgery meetings for clinicians, so the family default
(keep everything dated, drop administrative rows) applies. Rows already running (start before today) are skipped.

The EANS Annual Congress is not in the calendar: its page `/page/EANS_Congress` lists "Future Congresses" as
`2027 September 26-30, Basel, Switzerland` bullets, which `extra_shells()` turns into one shell for each fully dated edition.
Editions with only a month or a city ("2028 October Krakow, Poland") are skipped until a day range is published.
"""
import html as html_lib
import re
from datetime import date
from typing import Any, Dict, List, Optional

from logger import logger

from .community_calendar import CommunityCalendarExtractor
from .http_fetch import fetch_html
from .tribe_events import html_to_lines

CONGRESS_URL = "https://www.eans.org/page/EANS_Congress"
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}
_MON = "|".join(_MONTHS)
_FUTURE_RE = re.compile(rf"(?i)\b(20\d\d)\s+({_MON})\s+(\d{{1,2}})\s*[-–]\s*(?:({_MON})\s+)?(\d{{1,2}})\s*,\s*([^,<]+?)\s*,\s*([^,<]+?)\s*$")


def parse_future_congresses(html: str, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """'Future Congresses' bullets -> [{year, start_date, end_date, city, country}] for editions with a full day range. Pure."""
    today = today or date.today()
    m = re.search(r"(?is)Future Congresses(.*?)(?:</div>|$)", html or "")
    out: List[Dict[str, Any]] = []
    for line in html_to_lines(m.group(1) if m else ""):
        fm = _FUTURE_RE.search(line)
        if not fm:
            continue
        year, mon1, d1, mon2, d2, city, country = fm.groups()
        try:
            start = date(int(year), _MONTHS[mon1.lower()], int(d1))
            end = date(int(year), _MONTHS[(mon2 or mon1).lower()], int(d2))
        except ValueError:
            continue
        if end < start or start < today:
            continue
        out.append({"year": int(year), "start_date": start.isoformat(), "end_date": end.isoformat(),
                    "city": city.strip(), "country": country.strip()})
    return out


class EansExtractor(CommunityCalendarExtractor):
    ROOT = "https://www.eans.org"
    SOCIETY = "EANS"
    DEFAULT_SPECIALTY = "Neurosurgery"

    def extra_shells(self) -> List[Dict[str, Any]]:
        html = fetch_html(CONGRESS_URL, browser=getattr(self, "browser", None))
        if not html:
            logger.warning("EANS: congress page fetch failed; Annual Congress not added")
            return []
        out = []
        for c in parse_future_congresses(html):
            out.append({"title": f"EANS Congress {c['year']}", "booking_url": CONGRESS_URL, "start_date": c["start_date"],
                        "end_date": c["end_date"], "venue_raw": f"{c['city']}, {c['country']}", "_extra": True,
                        "_city": c["city"], "_country": c["country"]})
            break                       # one source_url (this page) can carry one edition: the next upcoming
        return out

    def extra_detail(self, page, shell: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {"society": self.SOCIETY, "conference_name": shell["title"], "start_date": shell["start_date"],
                               "end_date": shell["end_date"], "city": shell.get("_city"), "region": shell.get("_country"),
                               "event_format": "in_person", "specialty": self.DEFAULT_SPECIALTY}
        html = ""
        try:
            html = page.content() if page is not None else ""
        except Exception:
            html = ""
        pm = re.search(r"(?is)<p>\s*(The EANS Congress is the highlight.*?)</p>", html)
        desc = html_to_lines(re.sub(r"\s*\n\s*", " ", pm.group(1)))[0] if pm else None
        if desc:
            if len(desc) > 400:
                cut = desc[:400]
                idx = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
                desc = cut[:idx + 1] if idx >= 150 else cut.rstrip() + "..."
            out["description"] = desc
        return {k: v for k, v in out.items() if v}
