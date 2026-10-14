"""CCR London (Clinical Cosmetic Regenerative Congress, ExCeL London): single-congress family subclass.

The homepage JSON-LD still describes the PAST edition (2026-10-01..02), so find_edition skips it and reads the
"14 & 15 October 2027" header line; the next line is the venue ("Excel London").
"""
import re

from .single_congress import SingleCongressExtractor


class CcrLondonExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.ccrlondon.com/"
    SOCIETY = "CCR London"
    EVENT_NAME = "CCR London"
    DEFAULT_SPECIALTY = "Aesthetic & Cosmetic Medicine"
    DEFAULT_CURRENCY = "GBP"
    ACCEPT_PLACE_RE = re.compile(r"^excel london$", re.I)
    FREE_PATTERN = re.compile(r"free[\s-]to[\s-]attend", re.I)

    def parse_place(self, raw):
        if re.match(r"(?i)^excel london$", (raw or "").strip()):
            return "ExCeL London", "London", "United Kingdom", False
        return super().parse_place(raw)
