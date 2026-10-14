"""ESCMID (ESCMID Global congress site): single-congress family subclass."""
from .single_congress import SingleCongressExtractor


class EscmidExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.escmid.org/congress-events/escmid-global/"
    SOCIETY = "ESCMID"
    EVENT_NAME = "ESCMID Global"
    DEFAULT_SPECIALTY = "Infectious Disease"
    DEFAULT_CURRENCY = "EUR"
