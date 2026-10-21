"""UEG Week (ueg.eu/week): single-congress family subclass.

The landing page is always the *current* UEG Week (2026 Barcelona just finished, its platform stays up to
13 Nov) and ends with a "UEG Week 2027 / October 16 - 19, 2027 / Bella Center Copenhagen, Denmark" block for
the next edition. Hooks keep the 2026 blurbs and fee pages out of the 2027 row.
"""
import re
from typing import Any, Dict, List

from .single_congress import SingleCongressExtractor, html_lines


class UegExtractor(SingleCongressExtractor):
    HOME_URL = "https://ueg.eu/week"
    SOCIETY = "UEG"
    EVENT_NAME = "UEG Week"
    DEFAULT_SPECIALTY = "Gastroenterology"
    DEFAULT_CURRENCY = "EUR"

    def list_shells_override(self):
        shells = super().list_shells_override()
        if shells:
            lines = html_lines(self._get(self.HOME_URL) or "")
            y = shells[0].get("edition_year")
            i = next((k for k, l in enumerate(lines) if l == f"UEG Week {y}"), None)
            if i is not None and i + 2 < len(lines):
                m = re.match(r"^([A-Z][A-Za-z' .-]{3,50}?),\s*([A-Z][a-z]+(?: [A-Z][a-z]+)?)$", lines[i + 2])
                if m:
                    venue, country = m.group(1), m.group(2)
                    last = venue.split()[-1]
                    city = last if len(venue.split()) > 1 and last not in ("Center", "Centre", "Hall", "Hotel", "Arena", "Forum", "Palace") else None
                    shells[0]["venue_raw"] = ", ".join(x for x in (venue, city, country) if x)
        return shells

    def parse_place(self, raw):
        parts = [p.strip() for p in (raw or "").split(",")]
        if len(parts) == 3 and all(parts):
            return parts[0], parts[1], parts[2], False
        return super().parse_place(raw)

    def detail_from_html(self, html, url, shell, llm_call):
        out = super().detail_from_html(html, url, shell, llm_call)
        lines = html_lines(html)
        # family picks the congress-platform blurb of the finished edition; the site's own one-line intro is stable
        intro = next((l for l in lines if l.startswith("UEG Week is our")), None)
        if intro:
            out["description"] = re.split(r"(?<=\.)\s", intro)[0][:600]      # first sentence only (the next ones talk about 2026)
        # accreditation / abstract text on this page belongs to the finished edition
        for k in ("cpd_points", "cpd_accredited", "abstract_open", "abstract_deadline", "abstract_deadline_note"):
            out.pop(k, None)
        return out

    def fees_from_pages(self, pages: Dict[str, str], year: int) -> List[Dict[str, Any]]:
        # attendance/registration pages describe the finished edition until the next one opens
        keep = {u: h for u, h in pages.items() if re.search(rf"UEG Week {year}", " ".join(html_lines(h))) and not re.search(rf"UEG Week {year - 1}", " ".join(html_lines(h)))}
        return super().fees_from_pages(keep, year) if keep else []
