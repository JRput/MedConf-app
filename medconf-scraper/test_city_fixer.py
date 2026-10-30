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
