"""Tests for extractors.abstract_classifier (Mission P4: poster programmes)."""
from datetime import date

import pytest

from extractors.abstract_classifier import classify_submission, extract_abstract_info

TODAY = date(2026, 10, 4)
EVENT = date(2026, 11, 11)

BSH_TEXT = (
    "Poster competition Reflecting this year's International Pathology Day (IPD) theme, "
    "'Pathology in an era of personalised medicine', the theme of the competition sponsored "
    "by Epredia is, 'Innovations in pathology for personalised patient care' . We invite "
    "individuals and teams from around the world to submit posters showcasing innovations in "
    "pathology for personalised patient care across all specialties. The competition closes at "
    "midnight (GMT) on Tuesday 27 October 2026 . All entries should be submitted to the email."
)


def test_bsh_poster_competition():
    assert classify_submission(BSH_TEXT, TODAY, EVENT) == (True, date(2026, 10, 27), None)


@pytest.mark.parametrize("text,expected", [
    ("Poster competition. The deadline for submissions is 7th November 2026.", date(2026, 11, 7)),
    ("Submit your posters by 5pm on Friday 6 November.", date(2026, 11, 6)),   # no year
    ("Case report competition: entries must be submitted no later than 30 October 2026.",
     date(2026, 10, 30)),
])
def test_deadline_phrasings(text, expected):
    is_open, dl, note = classify_submission(text, TODAY, EVENT)
    assert (is_open, dl, note) == (True, expected, None)


def test_yearless_resolves_before_event():
    # 2 March would be next-year after today, but the event is 11 Nov 2026 so it
    # must be the occurrence before the event (already past -> closed).
    is_open, dl, _ = classify_submission("Poster submissions close on 2 March.", TODAY, EVENT)
    assert dl == date(2026, 3, 2) and is_open is False


def test_programme_without_date_gives_note_not_open():
    is_open, dl, note = classify_submission(
        "Join our poster competition and showcase your work.", TODAY, EVENT)
    assert is_open is False and dl is None
    assert note == "Poster competition — see page for submission date"


def test_programme_explicit_open_without_date():
    is_open, dl, note = classify_submission(
        "The poster competition is now open. See terms and conditions.", TODAY, EVENT)
    assert is_open is True and dl is None and note


def test_applications_open_negative():
    text = ("Applications are now open for this course. Application deadline - 30 November 2026. "
            "Submit your application by 30 November 2026.")
    assert classify_submission(text, TODAY, EVENT) == (False, None, None)
    assert extract_abstract_info(text, TODAY) == (False, None)


def test_closed_in_past():
    text = "Poster competition. The competition closes on 1 September 2026."
    assert classify_submission(text, TODAY, EVENT) == (False, date(2026, 9, 1), None)


def test_legacy_abstract_still_works():
    text = "Abstract submission: the deadline for submissions is 29 November 2026."
    assert extract_abstract_info(text, TODAY) == (True, date(2026, 11, 29))
