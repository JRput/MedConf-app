"""ECCO (European Crohn's and Colitis Organisation) event calendar: constants-only family subclass.

The site is Joomla/YOOtheme (not WordPress). /congress-events/event-calendar is a single page of
`el-item` cards (title h4, Date / Location / Organiser h5 blocks, a "Visit website" link) that
mostly point at other organisers' sites, so external links are accepted. Cards without any link
(no page to scrape) are dropped.
"""
import re

from .wordpress_generic import WordPressGenericExtractor


class EccoIbdExtractor(WordPressGenericExtractor):
    LISTING_URL = "https://ecco-ibd.eu/congress-events/event-calendar"
    SOCIETY = "ECCO"
    DEFAULT_SPECIALTY = "Gastroenterology"
    PREFER_DEFAULT_SPECIALTY = True
    DEFAULT_CURRENCY = "EUR"
    CARD_SPLIT_RE = re.compile(r'<div class="el-item uk-card')
    EXTERNAL_LINKS = True
    EVENT_LINK_RE = re.compile(r".*")
