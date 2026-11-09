"""BAD Annual Meeting (badannualmeeting.co.uk): single-congress family subclass.

Hooks (each proven by the harness):
  * the home slider says "Liverpool Experience Campus 29 June - 1 July 2027" (venue, no comma, no city), so the
    city comes from the intro paragraph ("returning to Liverpool") and the UK nation is England;
  * the first prose line of every page is the sponsorship declaration, which the family reader used as the
    description: it is replaced by the Chair/intro paragraph.
Fees: /registration/ still describes the 2026 Manchester meeting (the family year gate returns no tiers) and the
home page says registration for 2027 opens in February 2027, so there are no 2027 tiers to read yet.
"""
import re

from .single_congress import SingleCongressExtractor, html_lines

_NATION = {"Liverpool": "England", "Manchester": "England", "Birmingham": "England", "Glasgow": "Scotland", "Edinburgh": "Scotland",
           "Cardiff": "Wales", "Belfast": "Northern Ireland", "London": "England", "Harrogate": "England", "Brighton": "England"}


class BadAnnualExtractor(SingleCongressExtractor):
    HOME_URL = "https://badannualmeeting.co.uk/"
    SOCIETY = "BAD"
    EVENT_NAME = "BAD Annual Meeting"
    DEFAULT_SPECIALTY = "Dermatology"
    DEFAULT_CURRENCY = "GBP"
    REG_URLS = ("https://badannualmeeting.co.uk/registration/",)
    ABSTRACT_URLS = ("https://badannualmeeting.co.uk/abstracts/",)
    VENUE_URLS = ("https://badannualmeeting.co.uk/venue/",)

    def detail_from_html(self, html, url, shell, llm_call):
        out = super().detail_from_html(html, url, shell, llm_call)
        lines = html_lines(html)
        intro = next((l for l in lines if re.match(r"^We are delighted to be returning to [A-Z]", l)), None)
        if out.get("venue_name") and not out.get("city"):
            m = re.search(r"returning to ([A-Z][a-z]+)", intro or "")
            if m and m.group(1) in _NATION:
                out["city"], out["region"] = m.group(1), _NATION[m.group(1)]
        elif out.get("city") and not out.get("region") and out["city"] in _NATION:
            out["region"] = _NATION[out["city"]]
        if intro:
            # The prose later calls the venue "Liverpool Central" while the slider and venue page say Liverpool
            # Experience Campus; keep only the first sentence so the description never contradicts venue_name.
            out["description"] = re.split(r"(?<=[a-z0-9])\. ", intro)[0].rstrip(".") + "."
        elif str(out.get("description", "")).startswith("This event is sponsored"):
            out.pop("description")
        return out
