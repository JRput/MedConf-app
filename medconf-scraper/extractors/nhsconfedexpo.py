"""NHS ConfedExpo (Manchester Central): single-congress family subclass.

JSON-LD on the homepage is the next edition (2027-06-16..17). The homepage only offers "Register your interest"
and no price, so pricing_tiers stays empty (free-to-NHS-staff is NOT stated on the site, so no 0 tier is invented).
"""
import re

from .single_congress import SingleCongressExtractor


class NhsConfedExpoExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.nhsconfedexpo.org/"
    SOCIETY = "NHS ConfedExpo"
    EVENT_NAME = "NHS ConfedExpo"
    DEFAULT_SPECIALTY = "Health Policy"
    DEFAULT_CURRENCY = "GBP"

    def parse_place(self, raw):
        if re.match(r"(?i)^manchester central", (raw or "").strip()):
            return "Manchester Central", "Manchester", "United Kingdom", False
        return super().parse_place(raw)
