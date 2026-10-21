"""CHEST Annual Meeting (chestnet.org): single-congress family subclass with a bespoke edition lookup.

The event page carries the *current* edition as undated-year header lines ("CHEST 2026: See What's on the
Horizon" / "October 18 to 21 | CHEST Annual Meeting") and a "save the dates" list for later years
("2027: October 24-27 | Vancouver, BC, Canada"). Header edition wins while it has not finished; afterwards
the first future entry of the save-the-dates list is the edition.
"""
import re
from datetime import date
from typing import Any, Dict, Optional

from .single_congress import SingleCongressExtractor, html_lines

_MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_HEAD_RE = re.compile(r"^([A-Z][a-z]+)\s+(\d{1,2})\s+to\s+(?:([A-Z][a-z]+)\s+)?(\d{1,2})\s*\|\s*CHEST Annual Meeting$")
_FUT_RE = re.compile(r"^(20\d\d):\s*([A-Z][a-z]+)\s+(\d{1,2})\s*[-–]\s*(?:([A-Z][a-z]+)\s+)?(\d{1,2})\s*\|\s*(.+)$")


def _d(y: int, mon: str, day: str) -> Optional[date]:
    m = _MON.get(mon[:3].lower())
    return date(y, m, int(day)) if m else None


class ChestnetExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.chestnet.org/learning-and-events/events/chest-annual-meeting"
    SOCIETY = "CHEST"
    EVENT_NAME = "CHEST Annual Meeting"
    DEFAULT_SPECIALTY = "Respiratory Medicine"
    DEFAULT_CURRENCY = "USD"
    FOLLOW_YEAR_LINKS = False

    def _edition_from(self, url: str, html: str) -> Optional[Dict[str, Any]]:
        lines = html_lines(html)
        today = date.today()
        year = next((int(m.group(1)) for l in lines[:40] for m in [re.match(r"^CHEST (20\d\d)\b", l)] if m), None)
        place = next((m.group(1).strip() for l in lines[:40] for m in [re.search(r"\bin ([A-Z][A-Za-z .]+, [A-Z][A-Za-z ]+?)(?:\.| With|$)", l)] if m and "CHEST" in l), None)
        for i, l in enumerate(lines[:60]):
            m = _HEAD_RE.match(l)
            if m and year:
                s, e = _d(year, m.group(1), m.group(2)), _d(year, m.group(3) or m.group(1), m.group(4))
                if s and e and e >= today:
                    return {"start": s.isoformat(), "end": e.isoformat(), "date_line": l, "idx": i, "source": "header-line", "year": year,
                            "page_title": None, "url": url, "lines": lines, "place_raw": place}
        for i, l in enumerate(lines):
            m = _FUT_RE.match(l)
            if m:
                yr = int(m.group(1))
                s, e = _d(yr, m.group(2), m.group(3)), _d(yr, m.group(4) or m.group(2), m.group(5))
                if s and e and e >= today:
                    return {"start": s.isoformat(), "end": e.isoformat(), "date_line": l, "idx": i, "source": "save-the-dates", "year": yr,
                            "page_title": None, "url": url, "lines": lines, "place_raw": m.group(6).strip(), "future": True}
        return None

    def list_shells_override(self):
        shells = super().list_shells_override()
        for s in shells or []:
            html = self._get(self.HOME_URL) or ""
            ed = self._edition_from(self.HOME_URL, html) or {}
            if ed.get("place_raw"):
                s["venue_raw"] = ed["place_raw"]
            s["future_only"] = bool(ed.get("future"))
        return shells

    def parse_place(self, raw):
        parts = [p.strip() for p in (raw or "").split(",")]
        if len(parts) == 3 and all(parts):               # "Vancouver, BC, Canada"
            return None, parts[0], parts[2], False
        return super().parse_place(raw)

    def detail_from_html(self, html, url, shell, llm_call):
        out = super().detail_from_html(html, url, shell, llm_call)
        if shell.get("future_only"):
            # The page text still describes the finished edition: keep only dates + place; no fees/abstracts yet.
            for k in ("pricing_tiers", "abstract_open", "abstract_deadline", "abstract_deadline_note", "cpd_points", "cpd_accredited"):
                out.pop(k, None)
            d1, d2 = date.fromisoformat(shell["start_date"]), date.fromisoformat(shell["end_date"])
            where = ", ".join(x for x in (out.get("city"), out.get("region")) if x)
            out["description"] = (f"Annual meeting of the American College of Chest Physicians (CHEST), {d1:%d %B} to {d2:%d %B %Y}"
                                  + (f", {where}." if where else "."))
        return out

    def fees_from_pages(self, pages, year):
        # /registration-information stacks several editions and layouts (2025 and 2026 blocks, tier-name
        # rows with the price in the label); the generic parser mislabels them ("$689 Registration Only
        # (Nonmember) · Member Rate"). Return nothing rather than wrong prices; revisit once the next
        # edition's fee table is live.
        return []
