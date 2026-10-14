"""EAPS (EAPS congress site): single-congress family subclass."""
from .single_congress import SingleCongressExtractor


class EapsExtractor(SingleCongressExtractor):
    HOME_URL = "https://eaps.kenes.com/"
    SOCIETY = "EAPS"
    EVENT_NAME = "EAPS"
    DEFAULT_SPECIALTY = "Paediatrics"
    DEFAULT_CURRENCY = "EUR"
