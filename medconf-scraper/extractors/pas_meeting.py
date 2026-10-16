"""PAS (PAS congress site): single-congress family subclass."""
from datetime import date

from .single_congress import SingleCongressExtractor


class PasExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.pas-meeting.org/"
    SOCIETY = "PAS"
    EVENT_NAME = "PAS"
    DEFAULT_SPECIALTY = "Paediatrics"
    DEFAULT_CURRENCY = "USD"
    # 2026-10-16: the congress dates live only on the "<year> KEY DATES" page.
    # The home page now lists four year-stamped links ahead of it (2027
    # meeting / registration, 2026 sponsors / grant supporters), so the
    # generic year-link walk ran out of candidates before reaching it and
    # the source reported "no upcoming edition". Name it first.
    EDITION_URLS = tuple(
        f"https://www.pas-meeting.org/{y}-key-dates/"
        for y in (date.today().year + 1, date.today().year)
    )
