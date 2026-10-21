"""AAO Annual Meeting (aao.org): single-congress family subclass with a bespoke edition lookup.

The /annual-meeting landing page is the *current* edition's page and flips to "Thank you for joining
us" as soon as the meeting ends (AAO 2026 ended 12 Oct 2026), so it carries no usable upcoming date.
The next edition is listed under "Future Meetings" on /annual-meeting/past-and-future-meetings:
    AAO 2027 / Las Vegas, Venetian Expo & Hotel / Nov. 12-15: AAO 2027
"""
import re
from datetime import date
from typing import Any, Dict, List, Optional

from .single_congress import SingleCongressExtractor, html_lines

_MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_RANGE_RE = re.compile(r"^([A-Z][a-z]{2,4})\.?\s+(\d{1,2})\s*[-–]\s*(?:([A-Z][a-z]{2,4})\.?\s+)?(\d{1,2}):\s*AAO (20\d\d)$")


class AaoExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.aao.org/annual-meeting/past-and-future-meetings"
    SOCIETY = "AAO"
    EVENT_NAME = "AAO Annual Meeting"
    DEFAULT_SPECIALTY = "Ophthalmology"
    DEFAULT_CURRENCY = "USD"

    def _edition_from(self, url: str, html: str) -> Optional[Dict[str, Any]]:
        lines = html_lines(html)
        try:
            start_i = next(i for i, l in enumerate(lines) if l == "Future Meetings")
        except StopIteration:
            return None
        today = date.today()
        for i in range(start_i + 1, len(lines) - 2):
            m = _RANGE_RE.match(lines[i])
            if not m or not re.match(r"^AAO 20\d\d$", lines[i - 2]):
                continue
            yr = int(m.group(5))
            m1, m2 = _MON.get(m.group(1)[:3].lower()), _MON.get((m.group(3) or m.group(1))[:3].lower())
            if not m1 or not m2:
                continue
            s, e = date(yr, m1, int(m.group(2))), date(yr, m2, int(m.group(4)))
            if e < today:
                continue
            return {"start": s.isoformat(), "end": e.isoformat(), "date_line": lines[i], "idx": i, "source": "future-meetings",
                    "year": yr, "page_title": None, "url": url, "lines": lines, "place_raw": lines[i - 1]}
        return None

    def list_shells_override(self) -> Optional[List[Dict[str, Any]]]:
        shells = super().list_shells_override()
        for s in shells or []:
            html = self._get(self.HOME_URL) or ""
            ed = self._edition_from(self.HOME_URL, html) or {}
            raw = ed.get("place_raw")       # "Las Vegas, Venetian Expo & Hotel" (city first)
            if raw:
                s["venue_raw"] = raw
        return shells

    def parse_place(self, raw):
        parts = [p.strip() for p in (raw or "").split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:       # "City, Venue"
            return parts[1], parts[0], "United States", False
        return super().parse_place(raw)

    def detail_from_html(self, html, url, shell, llm_call):
        # The future-meetings page is a schedule, not a marketing page: take place/dates from the
        # shell and write a factual description; registration for the next edition is not published.
        out = super().detail_from_html(html, url, shell, llm_call)
        out.pop("pricing_tiers", None)
        out.pop("abstract_open", None)
        out.pop("abstract_deadline", None)
        out.pop("abstract_deadline_note", None)
        v, c = out.get("venue_name"), out.get("city")
        d1, d2 = date.fromisoformat(shell["start_date"]), date.fromisoformat(shell["end_date"])
        out["description"] = (f"Annual meeting of the American Academy of Ophthalmology, {d1:%d %B} to {d2:%d %B %Y}"
                              + (f", {v}, {c}." if v and c else "."))
        return out
