"""ESR (ECR congress site): single-congress family subclass."""
from .single_congress import SingleCongressExtractor


class MyesrExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.myesr.org/congress/"
    SOCIETY = "ESR"
    EVENT_NAME = "ECR"
    DEFAULT_SPECIALTY = "Radiology"
    DEFAULT_CURRENCY = "EUR"
