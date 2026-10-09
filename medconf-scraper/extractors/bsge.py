"""BSGE (British Society for Gynaecological Endoscopy) events: constants-only WordPress family subclass."""
from .wordpress_generic import WordPressGenericExtractor


class BsgeExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://www.bsge.org.uk/event/"
    SOCIETY = "BSGE"
    DEFAULT_SPECIALTY = "Obstetrics & Gynaecology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "GBP"
