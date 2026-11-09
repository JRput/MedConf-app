"""AAP National Conference & Exhibition (aapexperience.org): single-congress family subclass.

The site's only public edition list is /future-dates/: blocks of lines "2027 / Chicago / McCormick Place /
October 15-19, 2027". Hooks (each proven by the harness):
  * the venue + city sit on the lines BEFORE the date line, which the family reader does not look at, so the
    shell gets "Venue, City, United States" from the block whose year matches the edition;
  * the 'Call for Educational Content' page lists session-proposal due dates next to the real
    "Due April 9, 2027: Abstract Submission Deadline"; the base class picked the nearest (session proposals,
    Nov 20), so only the labelled abstract deadline is used and the proposal date goes in the note.
  * /conference-registration/ still describes the 2026 conference, so no fees are attached until it names the next edition
    (when a browser clears Cloudflare it loads, and the family gate alone would attach 2026 rates to 2027).
robots.txt asks for Crawl-delay 10, so REQUEST_GAP_S is 10 s.
"""
import re
from datetime import date, datetime
from typing import Any, Dict, Optional

from .single_congress import SingleCongressExtractor, find_edition, html_lines


class AapExtractor(SingleCongressExtractor):
    HOME_URL = "https://aapexperience.org/future-dates/"
    SOCIETY = "AAP"
    EVENT_NAME = "AAP National Conference"
    DEFAULT_SPECIALTY = "Paediatrics"
    DEFAULT_CURRENCY = "USD"
    REQUEST_GAP_S = 10.0
    REG_URLS = ("https://aapexperience.org/conference-registration/",)
    ABSTRACT_URLS = ("https://aapexperience.org/call-for-educational-content/",)
    MAX_AUX_PAGES = 2

    def _edition_from(self, url: str, html: str) -> Optional[Dict[str, Any]]:
        ed = super()._edition_from(url, html)
        if ed and ed.get("lines"):
            L = ed["lines"]
            for i in range(len(L) - 3):
                if L[i] == str(ed["year"]) and re.search(str(ed["year"]), L[i + 3]) and 1 < len(L[i + 1]) <= 40 and 1 < len(L[i + 2]) <= 60:
                    ed["block_place"] = (L[i + 2], L[i + 1])
                    break
        self._block_place = (ed or {}).get("block_place")
        return ed

    def list_shells_override(self):
        self._block_place = None
        shells = super().list_shells_override()
        if shells and self._block_place:
            v, c = self._block_place
            shells[0]["venue_raw"] = f"{v}, {c}, United States"        # AAP's conferences are all in US cities
        return shells

    def parse_place(self, raw):
        parts = [p.strip() for p in (raw or "").split(",")]
        if len(parts) == 3 and all(parts) and parts[2] == "United States":
            return parts[0], parts[1], parts[2], False
        return super().parse_place(raw)

    def fees_from_pages(self, pages, year):
        # /conference-registration/ keeps describing the edition just held ("Join us in San Diego for the 2026 National
        # Conference") and only mentions 2027 in recording-access dates, so the family year gate lets its grid through
        # (and the matrix reader mangles the member/non-member grid). Fees are read only once the page names THIS edition.
        ok = {u: h for u, h in pages.items() if re.search(rf"\bthe {year} National Conference", " ".join(html_lines(h)))}
        return super().fees_from_pages(ok, year) if ok else []

    def apply_abstracts(self, out, pages, shell):
        today = date.today()
        for html in pages.values():
            text = " ".join(html_lines(html))
            m = re.search(r"Due ([A-Z][a-z]+ \d{1,2}, \d{4}):?\s*Abstract Submission Deadline", text)
            if not m:
                continue
            dl = datetime.strptime(m.group(1), "%B %d, %Y").date()
            if str(shell.get("edition_year")) not in text:
                continue
            out["abstract_open"] = dl >= today
            out["abstract_deadline"] = dl.isoformat()
            p = re.search(r"Due ([A-Z][a-z]+ \d{1,2}, \d{4})\s*General Session Proposals", text)
            if p:
                out["abstract_deadline_note"] = f"General session proposals were due {p.group(1)}"
            return
