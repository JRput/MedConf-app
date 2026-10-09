"""BCIS (British Cardiovascular Intervention Society) events: constants-only WordPress family subclass."""
from .wordpress_generic import WordPressGenericExtractor


class BcisExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://www.bcis.org.uk/event/"
    SOCIETY = "BCIS"
    DEFAULT_SPECIALTY = "Cardiology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"
