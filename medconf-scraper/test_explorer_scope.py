"""Explorer: same-site sub-pages outside the event's own section need a strong identity match (RCPsych 1722, 2026-10-14)."""
from remediator.explorer import outside_event_path, identity_match_strength

EVENT = "https://www.rcpsych.ac.uk/events/conferences/detail/2026/10/15/default-calendar/deans-grand-rounds-psychodermatology"


def test_other_events_registration_is_outside_scope():
    assert outside_event_path(EVENT, "https://www.rcpsych.ac.uk/events/congress/international-congress-2026/registration")


def test_own_section_and_homepage_events_are_in_scope():
    assert not outside_event_path(EVENT, EVENT + "/registration")
    assert not outside_event_path(EVENT, "https://www.rcpsych.ac.uk/events/conferences/detail/2026/10/15/default-calendar/fees")
    assert not outside_event_path("https://www.iustiprague2026.com/", "https://www.iustiprague2026.com/registration/")
    assert not outside_event_path(EVENT, "https://other.example.org/registration")


def test_strength_requires_two_tokens_one_distinctive():
    toks = {"dean", "grand", "rounds", "psychodermatology", "treating", "mind", "skin", "together"}
    assert identity_match_strength(toks, "Join us together for the International Congress 2026. Register now.") == (["together"], False) or \
        identity_match_strength(toks, "Join us together for the International Congress 2026. Register now.")[1] is False
    assert identity_match_strength(toks, "Dean's Grand Rounds: Psychodermatology webinar registration")[1] is True
    assert identity_match_strength(toks, "mind and skin")[1] is False
