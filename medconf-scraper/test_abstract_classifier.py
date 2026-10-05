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


# ---------------------------------------------------------------------------
# Mission P8 (2026-10-05): wordings found on the 30 survey A/B rows.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    # RCPsych: "Call for posters" + "closing date for entries will be 26 October" (no year)
    ("Call for posters. Further information on how to submit your posters is available, "
     "and the closing date for entries will be 26 October . All entries should be sent.",
     (True, date(2026, 10, 26), None)),
    # RCPsych: "Enter your submission by 1pm Friday 2 November 2026"
    ("Call for posters Call for poster for the Faculty 2027 Conference are now open. "
     "Enter your submission by 1pm Friday 2 November 2026. Programme", (True, date(2026, 11, 2), None)),
    # RCPsych: extended closing date
    ("Call for posters. Please submit your abstract via Microsoft Forms. "
     "Closing date has been extended: 1pm, Thursday 22 October 2026.", (True, date(2026, 10, 22), None)),
    # RCPsych: "The submission closing date is Monday 14 December 2026"
    ("Call for posters is now open - submit an abstract. The submission closing date is "
     "Monday 14 December 2026 at 11.59pm", (True, date(2026, 12, 14), None)),
    # BMJ Forum: "Call for Posters will close 7 October 2026"
    ("Call for Posters Lisbon Put your project on the global stage. Call for Posters will "
     "close 7 October 2026. Learn more and submit an abstract", (True, date(2026, 10, 7), None)),
    # ESC: dated table with the date BEFORE the label
    ("Deadlines 28 Jan 2027 Abstract Submission + 2027-01-28 Europe/Paris Abstract Submission "
     "04 Feb 2027 Clinical Case Submission", (True, date(2027, 1, 28), None)),
    # Vidknox: no separator after "Deadline"
    ("Abstract Submission Deadline October 09 , 2026 Early Bird Registration", (True, date(2026, 10, 9), None)),
    # RCPsych: poster competition webpage
    ("further information and how to enter your abstract via the Poster competition webpage . "
     "Deadline for entries: 25 October 2026 How to book", (True, date(2026, 10, 25), None)),
])
def test_p8_deadline_wordings(text, expected):
    assert classify_submission(text, TODAY, date(2027, 3, 1)) == expected


def test_p8_call_for_posters_closed_gives_note():
    out = classify_submission("Call for posters The call for posters is now closed. Thank you.",
                              TODAY, date(2026, 11, 1))
    assert out == (False, None, "Call for posters — closed")


def test_p8_abstract_submissions_closed_note():
    out = classify_submission(
        "Abstract Submission Abstract submissions for this event have now closed, and all "
        "submitters will be notified.", TODAY, date(2026, 11, 1))
    assert out == (False, None, "Abstract submissions — closed")


def test_p8_call_for_posters_open_without_date_is_open_with_note():
    is_open, dl, note = classify_submission(
        "Call for posters is now open - submit an abstract through the form.", TODAY, date(2027, 3, 1))
    assert (is_open, dl) == (True, None) and "Call for posters" in note


def test_p8_call_for_contributions_gives_note_not_open():
    out = classify_submission(
        "The symposium will be preceded by a call for contributions inviting practitioners "
        "to submit an abstract on their work.", TODAY, date(2027, 3, 11))
    assert out[0] is False and out[1] is None and "see page" in out[2]


def test_p8_ambiguous_poster_vs_session_deadline_prefers_poster():
    text = ("Call for posters ... Deadline for submissions is Friday 26 February at 1pm. "
            "Call for sessions. Enter your submission Deadline extended : The closing date is "
            "1pm, Wednesday 30 September 2026.")
    assert classify_submission(text, TODAY, date(2027, 4, 1))[1] == date(2027, 2, 26)
