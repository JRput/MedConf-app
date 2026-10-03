"""European Society of Pathology (ESP) — Tribe Events family.

The API record has no venue for most events; the description opens with a
header line "<Title> <dates> <City>, <Country>" and sometimes "Venue: ...".
Fees are listed as "Registration Fees / ESP Members* ... / EUR 380" lines.
"""

import re
from .tribe_events import TribeEventsExtractor, city_country_after_year


class EspPathologyExtractor(TribeEventsExtractor):
    API_URL = "https://www.esp-pathology.org/wp-json/tribe/events/v1/events"
    SOCIETY = "ESP"
    DEFAULT_SPECIALTY = "Pathology"
    DEFAULT_CURRENCY = "EUR"
    PREFER_DEFAULT_SPECIALTY = True   # every ESP event is pathology ("Perinatal" etc. must not retag)

    def location_from_text(self, text, shell):
        loc = city_country_after_year(text)
        if not loc:
            return None
        v = re.search(r"Venue:\s*(.+?)(?:\s+Sessions:|\s+More information|\.\s|$)", text[:600])
        return (v.group(1).strip() if v else None), loc[0], loc[1]
