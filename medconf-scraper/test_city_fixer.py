"""fix_city must never return a city from a bare word match (2026-10-30 EANM incident)."""
from remediator.fixers.venue import fix_city


def _none(_prompt):
    return None


WIDGET = ("Skip to main content Accessibility Modules Reading Line Reading Mask "
          "Contrast Text size ")


def test_a_eanm_widget_reading_is_not_a_city():
    page = WIDGET + "Congress Val d'Isere. Venue: Future Health Lab"
    assert fix_city({}, page, _none) == (None, None)


def test_b_footer_london_ignored():
    body = "Welcome to the course. " * 260          # ~6000 chars
    footer = " Address: Royal College, 35-43 Lincoln's Inn Fields, London WC2A 3PE"
    page = body + footer
    assert len(page) > 4000 and page.rfind("Address:") > 0.9 * len(page)
    assert fix_city({}, page, _none) == (None, None)


def test_c_location_prefix_edinburgh():
    page = ("Location: Royal College of Surgeons of Edinburgh, Nicolson Street, "
            "Edinburgh EH8 9DW")
    assert fix_city({}, page, _none) == ("Edinburgh", "heuristic_city_after_prefix")


def test_d_city_in_stored_venue():
    row = {"venue_name": "Royal College of Physicians, London"}
    assert fix_city(row, WIDGET, _none) == ("London", "heuristic_city_in_venue")


def test_d2_longest_venue_city_wins():
    row = {"venue_name": "Spa Hotel, Tunbridge Wells"}
    assert fix_city(row, WIDGET, _none) == ("Tunbridge Wells", "heuristic_city_in_venue")


def test_e_online_event_has_no_city():
    row = {"event_format": "online"}
    assert fix_city(row, "Venue: London", _none) == (None, None)


def test_f_barnsley_postcode_not_sheffield():
    page = "Address: Barnsley Hospital, Gawber Road, Barnsley S75 2EP"
    assert fix_city({}, page, _none) == (None, None)


def test_g_manchester_after_venue():
    page = "Venue: The Studio, Manchester M1 1AB"
    assert fix_city({}, page, _none) == ("Manchester", "heuristic_city_after_prefix")


def test_h_postcode_prefix_gated_but_works():
    page = "Address: 10 Downing Street, SW1A 2AA"
    assert fix_city({}, page, _none) == ("London", "heuristic_postcode_prefix")


def test_bare_postcode_outside_window_ignored():
    page = "Some text. " * 30 + "SW1A 2AA"
    assert fix_city({}, page, _none) == (None, None)


# ---------------------------------------------------------------- FV1 fix wave
import pytest  # noqa: E402

NONE = (None, None)


# A. rule 1: longest name wins, then the last occurrence
@pytest.mark.parametrize("venue,city", [
    ("York Hall, Old Ford Road, London", "London"),
    ("Cambridge Suite, ICC Birmingham", "Birmingham"),
])
def test_A_venue_longest_name_wins(venue, city):
    assert fix_city({"venue_name": venue}, "", _none) == (city, "heuristic_city_in_venue")


def test_A_equal_length_last_occurrence_wins():
    assert fix_city({"venue_name": "Leeds Hall, Hull Road, Exeter"}, "x", _none)[0] == "Exeter"


# B. hyphen is not a word boundary
def test_B_newcastle_under_lyme_venue():
    assert fix_city({"venue_name": "Keele Hall, Newcastle-under-Lyme"}, "x", _none) == NONE


def test_B_newcastle_under_lyme_prefix():
    assert fix_city({}, "Venue: Keele Hall, Newcastle-under-Lyme, Staffordshire", _none) == NONE


# C. "Email address:" is not a location prefix
def test_C_email_address_prefix():
    page = "Email address: events@x.org  Our office in London is open"
    assert fix_city({}, page, _none) == NONE


def test_C_prefix_inside_word_or_hyphen_ignored():
    assert fix_city({}, "Postal-address: London", _none) == NONE


# D. windows stop at line / sentence ends; city must be an address token
def test_D_newline_cuts_window():
    page = "Venue: TBC\nOther courses\nIntroduction course - Oxford"
    assert fix_city({}, page, _none) == NONE


def test_D_sentence_cuts_window():
    page = "Our 2025 meeting was held at Glasgow SEC. The 2027 congress will be in Lisbon"
    assert fix_city({}, page, _none) == NONE


def test_D_glasgow_sec_not_city():
    page = "Our 2025 meeting was held at Glasgow SEC… 2027 congress will be in Lisbon"
    assert fix_city({}, page, _none) == NONE


def test_D_widget_reading_line():
    page = "Location: Val d'Isere Accessibility Modules Reading Line Reading Mask"
    assert fix_city({}, page, _none) == NONE


@pytest.mark.parametrize("page,city", [
    ("Venue: The Hall, Oxford Road, Oxford.", "Oxford"),
    ("Venue: The Hall, London", "London"),
    ("Venue: The Hall, London.", "London"),
    ("Venue: Hall (London)", "London"),
    ("Venue: Hall, Edinburgh EH8 9DW", "Edinburgh"),
    ("Venue: Hall 3, Leeds 12 Park Row", "Leeds"),
])
def test_D_address_token_accepted(page, city):
    assert fix_city({}, page, _none) == (city, "heuristic_city_after_prefix")


# E. short pages get footer protection; footer signatures skip a window
def test_E_footer_on_3000_char_page():
    body = "Welcome to the course. " * 125
    page = body[:2650] + " Address: Royal College, Lincoln's Inn Fields, London WC1H 9HR"
    assert 2000 < len(page) <= 4000 and page.rfind("Address:") > 0.85 * len(page)
    assert fix_city({}, page, _none) == NONE


def test_E_footer_signature_window_skipped():
    page = "Address: Royal College, London. Registered charity no. 123456"
    assert fix_city({}, page, _none) == NONE
    page2 = "Address: Royal College, London © 2026"
    assert fix_city({}, page2, _none) == NONE


# F. low-severity
def test_F1_venue_rule_runs_with_empty_page():
    row = {"venue_name": "Royal College, London"}
    assert fix_city(row, "", _none) == ("London", "heuristic_city_in_venue")


def test_F1_online_with_empty_page():
    assert fix_city({"event_format": "online", "venue_name": "London"}, "", _none) == NONE


def test_F2_case_rules():
    assert fix_city({"venue_name": "ExCeL LONDON"}, "", _none) == ("London", "heuristic_city_in_venue")
    assert fix_city({"venue_name": "the reading room"}, "x", _none) == NONE
    assert fix_city({"venue_name": "Reading"}, "x", _none) == ("Reading", "heuristic_city_in_venue")


def test_F3_postcode_rule_needs_uppercase():
    assert fix_city({}, "Address: 10 Downing Street, sw1a 2aa", _none) == NONE


def test_city_followed_by_dash_or_pipe_separator():
    """Foreman tune after FV1: "London - Docklands" / "Manchester | Central" keep the city."""
    assert fix_city({}, "Venue: ExCeL, London - Docklands", lambda _p: None) == ("London", "heuristic_city_after_prefix")
    assert fix_city({}, "Venue: Manchester | Central", lambda _p: None) == ("Manchester", "heuristic_city_after_prefix")
    # a capitalised word after the city still does not count ("Reading Line", "Glasgow SEC")
    assert fix_city({}, "Location: Val d'Isere Accessibility Modules Reading Line Reading Mask", lambda _p: None) == (None, None)


# ---------------------------------------------------------------- FV2
@pytest.mark.parametrize("page,city", [
    ("Venue: St. Thomas' Hospital, Westminster Bridge Rd, London SE1 7EH", "London"),
    ("Venue: St. George's Hospital, Blackshaw Road, London SW17 0QT", "London"),
    ("Venue: Leeds. Registration opens in London", "Leeds"),
])
def test_FV2_abbreviation_is_not_sentence_end(page, city):
    assert fix_city({}, page, _none) == (city, "heuristic_city_after_prefix")


@pytest.mark.parametrize("venue,city", [
    ("Reading Road, London", "London"),
    ("Thistle Hotel, Brighton Road, Leeds", "Leeds"),
    ("York Hall, Old Ford Road, London", "London"),
])
def test_FV2_road_names_are_not_cities(venue, city):
    assert fix_city({"venue_name": venue}, "x", _none) == (city, "heuristic_city_in_venue")


def test_FV2_reading_room_is_not_a_city():
    assert fix_city({"venue_name": "The Reading Room, British Library"}, "x", _none) == NONE


def test_FV2_road_word_dropped_in_windows_too():
    assert fix_city({}, "Venue: Reading Road, Henley", _none) == NONE


def test_FV2_manchester_postcode_still_ok():
    assert fix_city({}, "Venue: The Studio, Manchester M1 1AB", _none) == (
        "Manchester", "heuristic_city_after_prefix")
