"""UKIO (UKIO congress site): single-congress family subclass."""
from .single_congress import SingleCongressExtractor


class UkioExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.ukio.org.uk/"
    SOCIETY = "UKIO"
    EVENT_NAME = "UKIO"
    DEFAULT_SPECIALTY = "Radiology"
    DEFAULT_CURRENCY = "GBP"
