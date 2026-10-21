"""AAIC (AAIC site): single-congress family subclass."""
import re

from .single_congress import SingleCongressExtractor


class AaicExtractor(SingleCongressExtractor):
    HOME_URL = "https://aaic.alz.org/overview.asp"
    SOCIETY = "AAIC"
    EVENT_NAME = "AAIC"
    DEFAULT_SPECIALTY = "Neurology"
    DEFAULT_CURRENCY = "USD"

    def list_shells_override(self):
        # Page title line says "AAIC | July 18-21, 2027 | Alzheimer's Association" (organiser, not a place);
        # the real place is the next header line "Chicago, United States, and Online" and the
        # "Conference Location" block names McCormick Place.
        shells = super().list_shells_override()
        if shells:
            import re
            from .http_fetch import fetch_html
            from .single_congress import html_lines
            lines = html_lines(fetch_html(self.HOME_URL, browser=getattr(self, "browser", None)) or "")
            venue = next((lines[i + 1] for i, l in enumerate(lines[:-1]) if l == "Conference Location"), None)
            city = next((l for l in lines[:12] if re.match(r"^[A-Z][a-z]+, [A-Z][A-Za-z ]+(?:, and Online)?$", l)), None)
            if city:
                shells[0]["venue_raw"] = ", ".join(x for x in (venue, city) if x)
        return shells

    def parse_place(self, raw):
        parts = [p.strip() for p in (raw or "").split(",")]
        hybrid = bool(parts) and re.search(r"online", parts[-1], re.I) is not None
        parts = [re.sub(r"(?i)^and\s+online$", "", p) for p in parts]
        parts = [p for p in parts if p]
        if len(parts) == 3:
            return parts[0], parts[1], "United States" if parts[2] in ("US", "USA") else parts[2], hybrid
        return super().parse_place(raw)

    def apply_abstracts(self, out, pages, shell):
        # Important Dates table is laid out Date | Event (date BEFORE its label), which the family key-date
        # reader pairs the wrong way round. Read the <tr> cells: the general closing date is the row
        # "Abstract and session submission closes (general deadline)"; the opening row may be vague
        # ("Mid November 2026") and is then treated as not yet open, never as an invented date.
        from datetime import date, datetime
        today = date.today()
        for html in pages.values():
            deadline, opens_txt = None, None
            for tr in re.findall(r"(?is)<tr.*?</tr>", html):
                cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", tr)]
                if len(cells) < 2:
                    continue
                d, ev = cells[0], cells[1]
                if re.fullmatch(r"(?i)abstract and session submission closes \(general deadline\)", ev):
                    m = re.fullmatch(r"([A-Z][a-z]+)\.? (\d{1,2}), (20\d\d)", d)
                    if m:
                        try:
                            deadline = datetime.strptime(f"{m.group(1)[:3]} {m.group(2)} {m.group(3)}", "%b %d %Y").date()
                        except ValueError:
                            pass
                elif re.fullmatch(r"(?i)abstract and session submission opens", ev):
                    opens_txt = d
            if deadline:
                opens = None
                m = re.fullmatch(r"([A-Z][a-z]+)\.? (\d{1,2}), (20\d\d)", opens_txt or "")
                if m:
                    try:
                        opens = datetime.strptime(f"{m.group(1)[:3]} {m.group(2)} {m.group(3)}", "%b %d %Y").date()
                    except ValueError:
                        opens = None
                out["abstract_deadline"] = deadline.isoformat()
                out["abstract_open"] = bool(opens and opens <= today <= deadline)      # vague opening text -> not open
                return
        super().apply_abstracts(out, pages, shell)
