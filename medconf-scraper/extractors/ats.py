"""ATS International Conference (site.thoracic.org/conference): single-congress family subclass.

Hooks (each proven by the harness):
  * the home page is a news feed; the first prose line (a BEAR Cage promotion) was used as description, so it
    comes from the site's About page lead sentence instead;
  * /program/call-for-scientific-abstracts-and-case-reports says "The deadline has passed ..." and "The deadline for
    late breaking abstracts will be Wednesday, Jan. 27, 2027" (abbreviated month with a dot), recorded as a closed
    main call plus the late-breaking date in the note.
No ATS 2027 registration page or fee table is public yet (the /conference/registration paths 404; the CME and
accreditation pages still describe ATS 2026), so no tiers.
"""
import re
from datetime import date, datetime

from .single_congress import SingleCongressExtractor, html_lines

_ABOUT = "https://site.thoracic.org/conference/about"


class AtsExtractor(SingleCongressExtractor):
    HOME_URL = "https://site.thoracic.org/conference"
    SOCIETY = "ATS"
    EVENT_NAME = "ATS International Conference"
    DEFAULT_SPECIALTY = "Respiratory Medicine"
    DEFAULT_CURRENCY = "USD"
    REG_URLS = ()
    ABSTRACT_URLS = ("https://site.thoracic.org/conference/program/call-for-scientific-abstracts-and-case-reports",)
    MAX_AUX_PAGES = 1

    def _discover(self, html, base, want_re, bad_re):
        return []                                    # sub-pages are the explicit URLs above; nav links are 2026 pages / promotions

    def apply_abstracts(self, out, pages, shell):
        for html in pages.values():
            text = " ".join(html_lines(html))
            m = re.search(r"deadline for late[\s-]breaking abstracts will be (?:[A-Z][a-z]+day, )?([A-Z][a-z]{2,8})\.? (\d{1,2}), (\d{4})", text)
            closed = re.search(r"The deadline has passed\. ATS is not accepting abstracts", text)
            if not (m or closed):
                continue
            out["abstract_open"] = False
            if m:
                d = datetime.strptime(f"{m.group(1)[:3]} {m.group(2)} {m.group(3)}", "%b %d %Y").date()
                if d >= date.today():
                    out["abstract_deadline"] = d.isoformat()
                out["abstract_deadline_note"] = f"Main abstract call closed; late-breaking abstract deadline {d.strftime('%d %B %Y').lstrip('0')}"
            else:
                out["abstract_deadline_note"] = "Main abstract call closed"
            return

    def detail_from_html(self, html, url, shell, llm_call):
        out = super().detail_from_html(html, url, shell, llm_call)
        about = self._get(_ABOUT)
        if about:
            lead = next((l for l in html_lines(about)[3:8] if l.startswith("Where today") and len(l) < 300), None)
            if lead:
                out["description"] = lead
        return out
