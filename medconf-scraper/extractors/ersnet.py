"""ERS (European Respiratory Society) events: constants-only WordPress family subclass."""
import re

from .wordpress_generic import WordPressGenericExtractor


class ErsnetExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://www.ersnet.org/events/"
    SOCIETY = "ERS"
    DEFAULT_SPECIALTY = "Respiratory Medicine"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "EUR"
    # the card grid also links to channel.ersnet.org: /event-NNN-... (conferences) and /media-NNN-... (webinars)
    EVENT_LINK_RE = re.compile(r"^/(?:events/(?!page/)[^/?#]+|event-\d+[^/?#]*|media-\d+[^/?#]*)/?$")
