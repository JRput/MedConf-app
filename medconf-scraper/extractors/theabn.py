"""Association of British Neurologists (theabn.org): YourMembership community calendar, see `community_calendar.py`.

The calendar lists ABN's own meetings (Annual Meeting, Student Day, boot camps). Third-party meetings sit on a separate hand-written
"Non ABN Events" page (no dates structure, ABN disclaims them) and are not scraped. The Annual Meeting page has no body text in the
calendar; its `/page/annualmeeting2027` microsite page is passed on as `organiser_url` for the shared discovery engine.
"""
from .community_calendar import CommunityCalendarExtractor


class TheabnExtractor(CommunityCalendarExtractor):
    ROOT = "https://www.theabn.org"
    SOCIETY = "ABN"
    DEFAULT_SPECIALTY = "Neurology"
