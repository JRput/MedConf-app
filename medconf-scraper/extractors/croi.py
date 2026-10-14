"""CROI (CROI congress site): single-congress family subclass."""
from .single_congress import SingleCongressExtractor


class CroiExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.croiconference.org/"
    SOCIETY = "CROI"
    EVENT_NAME = "CROI"
    DEFAULT_SPECIALTY = "Infectious Disease"
    DEFAULT_CURRENCY = "USD"
