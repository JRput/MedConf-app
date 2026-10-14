"""PAS (PAS congress site): single-congress family subclass."""
from .single_congress import SingleCongressExtractor


class PasExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.pas-meeting.org/"
    SOCIETY = "PAS"
    EVENT_NAME = "PAS"
    DEFAULT_SPECIALTY = "Paediatrics"
    DEFAULT_CURRENCY = "USD"
