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
    # 2026-10-14: "free-to-attend" appears only in marketing copy / meta text,
    # not on the registration page, and not per visitor type — so no £0 tier is
    # asserted; the row points at the organiser's registration instead.
    FREE_PATTERN = None

    def parse_place(self, raw):
        if re.match(r"(?i)^excel london$", (raw or "").strip()):
            return "ExCeL London", "London", "United Kingdom", False
        return super().parse_place(raw)
