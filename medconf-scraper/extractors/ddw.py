"""DDW (DDW congress site): single-congress family subclass."""
from .single_congress import SingleCongressExtractor


class DdwExtractor(SingleCongressExtractor):
    HOME_URL = "https://ddw.org/"
    SOCIETY = "DDW"
    EVENT_NAME = "DDW"
    DEFAULT_SPECIALTY = "Gastroenterology"
    DEFAULT_CURRENCY = "USD"
