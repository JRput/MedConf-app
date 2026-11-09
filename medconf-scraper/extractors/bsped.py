"""BSPED Annual Meeting (bsped.org.uk): single-congress family subclass.

bsped.org.uk only carries a three-line entry ("53rd Meeting of the British Society for Paediatric Endocrinology
and Diabetes - Bristol" / "8-10 December 2026" / "Bristol"); registration, abstracts and venue live on an
EventsForce microsite whose robots.txt is "User-agent: * / Disallow: /", so it is deliberately NOT fetched.
Hook (proven by the harness): the bare one-word city line is not read as a place by the family reader, so the
city comes from the entry's title line and the UK nation is England (Bristol).
"""
import re

from .single_congress import SingleCongressExtractor, html_lines

_NATION = {"Bristol": "England", "Sheffield": "England", "Manchester": "England", "Birmingham": "England", "London": "England",
           "Leeds": "England", "Liverpool": "England", "Newcastle": "England", "Nottingham": "England", "Glasgow": "Scotland",
           "Edinburgh": "Scotland", "Cardiff": "Wales", "Belfast": "Northern Ireland"}


class BspedExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.bsped.org.uk/meetings/forthcoming-meetings/"
    SOCIETY = "BSPED"
    EVENT_NAME = "BSPED Annual Meeting"
    DEFAULT_SPECIALTY = "Paediatric Endocrinology"
    DEFAULT_CURRENCY = "GBP"
    MAX_AUX_PAGES = 0
    REG_URLS = ()
    ABSTRACT_URLS = ()

    def _discover(self, html, base, want_re, bad_re):
        return []                                   # every sub-page is on the EventsForce microsite (robots Disallow: /)

    def detail_from_html(self, html, url, shell, llm_call):
        out = super().detail_from_html(html, url, shell, llm_call)
        lines = html_lines(html)
        for i, l in enumerate(lines):
            m = re.match(r"^(\d+(?:st|nd|rd|th) Meeting of the British Society for .+?) - ([A-Z][a-z]+)$", l)
            if m and i + 2 < len(lines) and lines[i + 2] == m.group(2) and m.group(2) in _NATION:
                out["city"], out["region"], out["event_format"] = m.group(2), _NATION[m.group(2)], "in_person"
                out["description"] = f"{m.group(1)}, {m.group(2)}, {lines[i + 1]}."
                break
        return out
