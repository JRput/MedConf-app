"""ESPID (ESPID congress site): single-congress family subclass."""
from .single_congress import SingleCongressExtractor


class EspidExtractor(SingleCongressExtractor):
    HOME_URL = "https://espidmeeting.org/welcome-to-espid-2027/"
    SOCIETY = "ESPID"
    EVENT_NAME = "ESPID"
    DEFAULT_SPECIALTY = "Paediatrics"
    DEFAULT_CURRENCY = "EUR"
