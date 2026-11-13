"""FACE / The Aesthetic Show UK (faceconference.com): single-congress family subclass, constants only.

One annual aesthetics conference + exhibition (Informa / AMWC series). The 2026 debut edition ran 26-27 June 2026
at Convene Sancroft, London; the home page now thanks attendees and publishes no 2027 dates, so the family sets
verified_empty until a later edition appears. Clinician-facing delegate fees only (never exhibitor packages).
"""
from .single_congress import SingleCongressExtractor


class FaceExtractor(SingleCongressExtractor):
    HOME_URL = "https://www.faceconference.com/"
    SOCIETY = "FACE"
    EVENT_NAME = "The Aesthetic Show UK"
    DEFAULT_SPECIALTY = "Aesthetic Medicine"
    DEFAULT_CURRENCY = "GBP"
    REG_URLS = ("https://www.faceconference.com/registration-info/",)
    VENUE_URLS = ("https://www.faceconference.com/venue/",)
