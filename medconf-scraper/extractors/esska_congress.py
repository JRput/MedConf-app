"""ESSKA Congress (esska-congress.org): single-congress family subclass.

The congress's own site only. Nothing on esska.org is fetched (its events pages are challenged on the runner).
The congress is biennial: between editions the site already announces the next one ("The 23rd ESSKA Congress will take
place in Gothenburg, Sweden, from June 7 to June 9, 2028"), registration opens "in fall 2027" and the programme is
"revealed next year", so fees and the abstract deadline stay empty until the site publishes them.
Hooks (each proven by the harness):
  * the family read the place from the home sentence "... will take place in Gothenburg, Sweden,\\nfrom June 7 ..." as
    city "from"; the place is taken from that sentence (cut at the comma before "from");
  * the venue is the "Congress Venue" block of /about-esska-congress/ ("Svenska Mässan Gothia Towers");
  * the description is the site's meta description (the first prose line is a newsletter banner).
REG_URLS pins the fee lookup to the about page so discovery never follows the "Registration" photo on the home page.
"""
import re
from typing import Any, Callable, Dict, List, Optional

from .single_congress import SingleCongressExtractor, html_lines
from .wordpress_generic import _meta

_PLACE_RE = re.compile(r"will take place in ([A-Z][\wÀ-ſ' -]+?),\s*([A-Z][a-z]+(?: [A-Z][a-z]+)?),?\s+from\b")


class EsskaCongressExtractor(SingleCongressExtractor):
    HOME_URL = "https://esska-congress.org/"
    SOCIETY = "ESSKA"
    EVENT_NAME = "ESSKA Congress"
    DEFAULT_SPECIALTY = "Orthopaedics"
    DEFAULT_CURRENCY = "EUR"
    REG_URLS = ("https://esska-congress.org/about-esska-congress/",)
    ABSTRACT_URLS = ("https://esska-congress.org/scientific-programme/",)
    VENUE_URLS = ("https://esska-congress.org/about-esska-congress/",)
    MAX_AUX_PAGES = 2

    def venue_from_lines(self, lines: List[str]) -> Optional[str]:
        for i, l in enumerate(lines[:-1]):
            if l == "Congress Venue" and i > 12:       # the first hits are menu entries
                nxt = lines[i + 1]
                if 3 <= len(nxt) <= 60 and not re.search(r"[.!?]$", nxt):
                    return nxt
        return None

    def detail_from_html(self, html: str, url: str, shell: Dict[str, Any], llm_call: Optional[Callable[[str], Optional[str]]]) -> Dict[str, Any]:
        out = super().detail_from_html(html, url, shell, llm_call)
        text = " ".join(html_lines(html))
        m = _PLACE_RE.search(text)
        if m:
            out["city"], out["region"] = m.group(1).strip(), m.group(2).strip()
            out.setdefault("event_format", "in_person")
        md = _meta(html, "description")
        if md and len(md) >= 50:
            out["description"] = re.sub(r"\s+", " ", md).strip()[:600]
        return out
