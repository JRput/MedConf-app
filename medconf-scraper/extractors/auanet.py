"""AUA Annual Meeting (auanet.org/AUA2027): single-congress family subclass."""
import re

from .single_congress import SingleCongressExtractor, find_edition, html_lines
from .wordpress_generic import _meta


class AuanetExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.auanet.org/AUA2027"
    SOCIETY = "AUA"
    EVENT_NAME = "AUA Annual Meeting"
    DEFAULT_SPECIALTY = "Urology"
    DEFAULT_CURRENCY = "USD"
    # Nav links are relative to /AUA2027/ but the URL has no trailing slash, so family discovery
    # resolves them against the site root (404). Registration rates are not published yet
    # (key-dates: "Registration Opens 2 Dec 2026"), so the key-dates page stands in for both.
    REG_URLS = ("https://www.auanet.org/AUA2027/key-dates",)
    ABSTRACT_URLS = ("https://www.auanet.org/AUA2027/key-dates",)

    def _edition_from(self, url, html):
        # The homepage shows no date line; the only dated text is the meta description
        # ("AUA Annual Meeting 2027, May 21 - 24, 2027 in San Diego,CA").
        ed = super()._edition_from(url, html)
        if ed or not html:
            return ed
        lines = html_lines(html)
        md = _meta(html, "description") or _meta(html, "og:description") or ""
        m = re.search(r"([A-Z][a-z]+ \d{1,2}\s*[\u2013-]\s*\d{1,2}, 20\d\d)\s+in\s+([^.]+)\.", md)
        if not m:
            return None
        lines = [f"{m.group(1)} | {m.group(2).replace(',', ', ').replace(',  ', ', ').strip()}"] + lines
        ed = find_edition(html, lines, url)
        if ed:
            ed.update(url=url, lines=lines)
        return ed

    def list_shells_override(self):
        shells = super().list_shells_override()
        if shells:
            from .http_fetch import fetch_html
            md = _meta(fetch_html(self.HOME_URL, browser=getattr(self, "browser", None)) or "", "description") or ""
            m = re.search(r"20\d\d\s+in\s+([A-Z][A-Za-z .]+),\s*([A-Z]{2})\b", md)
            if m:
                shells[0]["venue_raw"] = f"{m.group(1).strip()}, {m.group(2)}"
            shells[0]["meta_desc"] = md
        return shells

    def detail_from_html(self, html, url, shell, llm_call):
        out = super().detail_from_html(html, url, shell, llm_call)
        # The homepage opens with an "AUA content may not be used in AI tools" legal notice;
        # use the sentence after the dates in the meta description instead.
        md = shell.get("meta_desc") or _meta(html, "description") or ""
        m = re.search(r"20\d\d\s+in\s+[^.]+\.\s*([A-Z][^.]+\.)", md)
        if m:
            out["description"] = m.group(1).strip()
        elif re.search(r"(?i)prohibited|large language|artificial intelligence", out.get("description", "")):
            out.pop("description", None)
        return out
