"""ACOG (ACOG Annual Clinical & Scientific Meeting congress site): single-congress family subclass."""
from .single_congress import SingleCongressExtractor


class AcogExtractor(SingleCongressExtractor):
    HOME_URL = "https://annualmeeting.acog.org/"
    SOCIETY = "ACOG"
    EVENT_NAME = "ACOG Annual Clinical & Scientific Meeting"
    DEFAULT_SPECIALTY = "Obstetrics & Gynaecology"
    DEFAULT_CURRENCY = "USD"
