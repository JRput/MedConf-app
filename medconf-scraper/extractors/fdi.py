"""FDI World Dental Federation events: constants-only family subclass.

The site is Drupal 10 (not WordPress): one `<article class="node--type-event">`
teaser per event on /all-events, links are root-level slugs, ?page=N pager.
"""
import re

from .wordpress_generic import WordPressGenericExtractor


class FdiExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://www.fdiworlddental.org/all-events"
    SOCIETY = "FDI World Dental Federation"
    DEFAULT_SPECIALTY = "Dentistry"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "EUR"
    CARD_SPLIT_RE = re.compile(r"<article\b[^>]*node--type-event")
    EVENT_LINK_RE = re.compile(r"^/(?!all-events)[a-z0-9][a-z0-9-]*/?$")
    ONLINE_CATEGORY_RE = re.compile(r"CE programme", re.I)     # webinars; the card's place line is the speaker's country
