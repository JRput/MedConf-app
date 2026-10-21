"""EAN (EAN Congress site): single-congress family subclass."""
from .single_congress import SingleCongressExtractor


class EanExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.ean.org/congress2027"
    SOCIETY = "EAN"
    EVENT_NAME = "EAN Congress"
    DEFAULT_SPECIALTY = "Neurology"
    DEFAULT_CURRENCY = "EUR"

    def _edition_from(self, url, html):
        # The page body lists dated sessions (the Presidential Symposium on 13 June) before the
        # congress dates, which only appear in the meta description: "... will be on 12-15 June
        # 2027, in Gothenburg, Sweden". Put that sentence first as a synthetic header line.
        import re
        from .single_congress import html_lines
        m = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', html or "")
        lines = html_lines(html)
        mm = re.search(r"will be on\s+([^,]+\d{4}),\s*in\s+(.+)$", m.group(1)) if m else None
        if mm:
            lines = [f"{mm.group(1)} | {mm.group(2).strip()}"] + lines
            from .single_congress import find_edition
            ed = find_edition(html, lines, url)
            if ed:
                ed.update(url=url, lines=lines)
                return ed
        return super()._edition_from(url, html)

    def list_shells_override(self):
        # Place: the meta description names city + country; the body says "takes place at <Venue>".
        shells = super().list_shells_override()
        if shells and not shells[0].get("venue_raw"):
            import re
            from .http_fetch import fetch_html
            import html as _h
            html = _h.unescape(fetch_html(self.HOME_URL, browser=getattr(self, "browser", None)) or "").replace("\xa0", " ")
            m = re.search(r"takes place at\s+([^,.<]{3,50}),\s*([^,.<]{3,40}),\s*([A-Z][a-z]+)", html)
            if m:
                shells[0]["venue_raw"] = ", ".join(x.strip() for x in m.groups())
        return shells

    def parse_place(self, raw):
        parts = [p.strip() for p in (raw or "").split(",")]
        if len(parts) == 3 and all(parts):          # "Venue, City, Country" (family parse_place drops venue+city)
            return parts[0], parts[1], parts[2], False
        return super().parse_place(raw)

    def apply_abstracts(self, out, pages, shell):
        # The key-date table says "Public Abstract Submission Opening 29 Oct 2026" (not "opens"), which the
        # family reads as a deadline. Read opening and deadline explicitly: open only between the two.
        import re
        from datetime import date
        from .single_congress import html_lines, key_date_entries
        today = date.today()
        try:
            start = date.fromisoformat(shell["start_date"])
        except (KeyError, ValueError, TypeError):
            start = None
        opens, deadline = None, None
        for html in pages.values():
            for label, d1, _d2 in key_date_entries(html_lines(html), start):
                if re.search(r"abstract submission opening", label, re.I) and not re.search(r"late", label, re.I):
                    opens = d1
                elif re.fullmatch(r"(?i)abstract submission deadline", label.strip()):
                    deadline = d1
        if deadline:
            out["abstract_deadline"] = deadline.isoformat()
            out["abstract_open"] = (opens is None or opens <= today) and today <= deadline
            return
        super().apply_abstracts(out, pages, shell)

    def detail_from_html(self, html, url, shell, llm_call):
        out = super().detail_from_html(html, url, shell, llm_call)
        # first body paragraph is the abstract call-to-action; the congress blurb is the intro line / meta description
        import re
        from .single_congress import html_lines
        from .wordpress_generic import _meta
        intro = next((l for l in html_lines(html)[:15] if l.startswith("The EAN Congress is")), None) or _meta(html, "description")
        if intro and not re.search(r"(?i)submit|cookie", intro):
            out["description"] = intro[:600]
        return out
