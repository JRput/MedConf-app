"""EFORT (EFORT congress site): single-congress family subclass."""
import re

from .single_congress import SingleCongressExtractor


class EfortExtractor(SingleCongressExtractor):
    HOME_URL = "https://congress.efort.org/"
    SOCIETY = "EFORT"
    EVENT_NAME = "EFORT"
    DEFAULT_SPECIALTY = "Orthopaedics"
    DEFAULT_CURRENCY = "EUR"

    def venue_from_lines(self, lines):
        # venue page: the venue name is the first line naming a centre/hall after the nav ("MEGARON Athens International Centre")
        for ln in lines[:20]:
            if len(ln) <= 70 and re.search(r"\b(?:centre|center|hall|palace|convention)\b", ln, re.I) and not re.search(r"\d|\|", ln):
                return ln
        return None
