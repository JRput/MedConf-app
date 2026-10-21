"""ANESTHESIOLOGY / ASA Annual Meeting (asahq.org/annualmeeting): single-congress family subclass.

The landing page flips to "Thank you for making ANESTHESIOLOGY 2026 a success" and carries the next edition
as one pipe line: "ANESTHESIOLOGY 2027 | October 15- 19 | Boston, MA | Thomas M. Menino Convention & Exhibition Center"
(note the stray space in "15- 19"), which the family date finder does not read.
"""
import re
from typing import Any, Dict, Optional

from .single_congress import SingleCongressExtractor, find_edition, html_lines

_LINE_RE = re.compile(r"^ANESTHESIOLOGY (20\d\d)\s*\|\s*([A-Z][a-z]+ \d{1,2})\s*[-–]\s*(\d{1,2})\s*\|\s*([^|]+?)\s*\|\s*(.+)$")


class AsahqExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.asahq.org/annualmeeting"
    SOCIETY = "ASA"
    EVENT_NAME = "ANESTHESIOLOGY Annual Meeting"
    DEFAULT_SPECIALTY = "Anaesthesia"
    DEFAULT_CURRENCY = "USD"

    def _edition_from(self, url: str, html: str) -> Optional[Dict[str, Any]]:
        lines = html_lines(html)
        for l in lines[:40]:
            m = _LINE_RE.match(l)
            if m:
                syn = f"{m.group(2)}-{m.group(3)}, {m.group(1)} | {m.group(4)}"
                ed = find_edition(html, [syn] + lines, url)
                if ed:
                    ed.update(url=url, lines=lines, venue_line=l)
                    return ed
        return super()._edition_from(url, html)

    def list_shells_override(self):
        shells = super().list_shells_override()
        if shells:
            for l in html_lines(self._get(self.HOME_URL) or "")[:40]:
                m = _LINE_RE.match(l)
                if m:
                    shells[0]["venue_raw"] = f"{m.group(5).strip()}, {m.group(4).strip()}"      # "<venue>, Boston, MA"
                    break
        return shells

    def parse_place(self, raw):
        parts = [p.strip() for p in (raw or "").split(",")]
        if len(parts) == 3 and re.fullmatch(r"[A-Z]{2}", parts[2]):
            return parts[0], parts[1], "United States", False
        return super().parse_place(raw)

    def detail_from_html(self, html, url, shell, llm_call):
        out = super().detail_from_html(html, url, shell, llm_call)
        # page text is still the finished 2026 meeting ("claim credit", "recordings"): keep only 2027 facts
        for k in ("cpd_points", "cpd_accredited"):
            out.pop(k, None)
        lines = html_lines(html)
        y = shell.get("edition_year")
        if not out.get("description") or re.search(r"2026|thank you|recordings", out.get("description", ""), re.I):
            where = ", ".join(x for x in (out.get("venue_name"), out.get("city")) if x)
            out["description"] = f"ANESTHESIOLOGY {y}, the annual meeting of the American Society of Anesthesiologists" + (f", {where}." if where else ".")
        return out

    ABSTRACT_URLS = ("https://www.asahq.org/annualmeeting/education/submissions",)
    REG_URLS = ("https://www.asahq.org/annualmeeting/attend/registration",)

    def fees_from_pages(self, pages, year):
        # the registration page describes the finished edition ("ANESTHESIOLOGY 2026 Registration") until the next opens
        keep = {u: h for u, h in pages.items() if (f"ANESTHESIOLOGY {year} Registration" in " ".join(html_lines(h)))}
        return super().fees_from_pages(keep, year) if keep else []

    def apply_abstracts(self, out, pages, shell):
        from datetime import date, datetime
        today = date.today()
        for html in pages.values():
            for l in html_lines(html):
                m = re.match(r"^Scientific Abstracts:\s*([A-Z][a-z]+ \d{1,2})(?:,? (20\d\d))?\s*[-–]\s*([A-Z][a-z]+ \d{1,2}),? (20\d\d)$", l)
                if m:
                    try:
                        end = datetime.strptime(f"{m.group(3)} {m.group(4)}", "%B %d %Y").date()
                        opens = datetime.strptime(f"{m.group(1)} {m.group(2) or m.group(4)}", "%B %d %Y").date()
                    except ValueError:
                        continue
                    out["abstract_open"] = opens <= today <= end
                    out["abstract_deadline"] = end.isoformat()
                    return
        super().apply_abstracts(out, pages, shell)
