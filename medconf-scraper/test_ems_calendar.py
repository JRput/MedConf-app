"""Tests for extractors.ems_calendar and the BOA relevance filter: pure parsing on saved snippets, no network."""
from datetime import date

from extractors.boa import BoaExtractor, is_relevant, is_third_party, parse_future_congress
from extractors.ems_calendar import (
    _UK_PLACES, EmsCalendarExtractor, ems_dates, ems_event_type, ems_fee_tiers, ems_prose_fees, ems_time, parse_ems_articles,
)

ARTICLE = """<article class="eventfolio-calendar-event article-list-item event-list-item ">
<div class="article-wrapper"><div class="article-details"><div class="event-badge-wrap"><span class="badge event-badge">External</span></div>
<div class="article-pre-meta"><div class="meta article-cpd pull-right">6 CPD</div><div class="meta article-date"> 23 &ndash; 24 October 2026 </div></div>
<h4 class="article-title"><a href="https://www.boa.ac.uk/x/foot-ankle-course.html"> FOOT &amp; ANKLE COURSE </a></h4>
<div class="article-teaser"><p>A 3-day course.</p></div>
<div class="article-post-meta"><span class="badge event-type-badge" >Non-BOA Event</span><span class="event-venue" >Shropshire</span></div>
</div></div></article>"""


def make():
    return EmsCalendarExtractor({"id": 0, "source_name": "x"})


def test_date_ranges_single_cross_month_and_cross_year():
    assert ems_dates("22 October 2026") == ("2026-10-22", "2026-10-22")
    assert ems_dates("23 – 24 October 2026") == ("2026-10-23", "2026-10-24")
    assert ems_dates("30 August – 10 November 2026") == ("2026-08-30", "2026-11-10")
    assert ems_dates("14 December 2026 – 22 January 2027") == ("2026-12-14", "2027-01-22")
    assert ems_dates("no date here") is None


def test_time_parsing_and_all_day_marker():
    assert ems_time("9.30am – 5pm GMT") == "09:30"
    assert ems_time("6.30pm – 8pm GMT") == "18:30"
    assert ems_time("12am – 11.59pm GMT") is None


def test_card_parsing_extracts_badges_type_venue_cpd():
    (c,) = parse_ems_articles(ARTICLE)
    assert c["title"] == "FOOT & ANKLE COURSE"
    assert c["dates"] == ("2026-10-23", "2026-10-24")
    assert c["badges"] == ["External"] and c["type"] == "Non-BOA Event" and c["venue"] == "Shropshire" and c["cpd"] == 6.0


def test_on_demand_and_cancelled_cards_are_skipped():
    e = make()
    assert e.skip_card({"title": "SOA26 On Demand Box Set", "type": "On demand"})
    assert e.skip_card({"title": "BOA Annual Congress 2026 - Digital Access Only", "type": "Annual Congress"})
    assert e.skip_card({"title": "Wexham Meeting [CANCELLED]", "type": "Training"})
    assert not e.skip_card({"title": "BOA New Consultants Course", "type": "Training"})


def test_place_to_region_and_online():
    e = make()
    assert e.place_from_spans(["London", "Smith & Nephew plc"], None) == {
        "event_format": "in_person", "city": "London", "region": "London", "venue_name": "Smith & Nephew plc"}
    assert e.place_from_spans(["Barcelona, Spain"], None)["region"] == "Spain"
    assert e.place_from_spans(["Online"], None) == {"event_format": "online"}
    assert _UK_PLACES["edinburgh"] == "Scotland"


def test_fee_rows_in_widget_and_course_fee_layouts():
    t = ems_fee_tiers(["Pricing:", "ICS members - £215", "Non-Members - £315"])
    assert [(x["tier_label"], x["price_gbp"]) for x in t] == [("Registration · ICS members", 215.0), ("Registration · Non-Members", 315.0)]
    t = ems_fee_tiers(["Free for ICS members", "£30 for non-members"])
    assert [x["price_gbp"] for x in t] == [0.0, 30.0]
    t = ems_fee_tiers(["UK & IE Candidates - £4,250.00", "International Candidates - £4,275.00"])
    assert [x["price_gbp"] for x in t] == [4250.0, 4275.0]


def test_event_type_title_then_category():
    assert ems_event_type("February 2027 - Casting Course 1", "Casting") == "course"
    assert ems_event_type("MSK Ultrasound Injection Skills Workshop", "Non-BOA Event") == "workshop"
    assert ems_event_type("UK Shock 26", "Conference") == "conference"
    assert ems_event_type("Inside Intensive Care", "Webinar") == "workshop"


def test_boa_relevance_filter_keeps_orthopaedics_drops_the_rest():
    assert is_third_party({"badges": ["External"], "type": "Non-BOA Event"})
    assert not is_third_party({"badges": [], "type": "Casting"})
    assert is_relevant("Hip Fracture Summit Improving Care", "Non-BOA Event")
    assert is_relevant("Foundations in Surgical Leadership (FSL)")
    assert is_relevant("BSCOS Current Concepts 2026", "Non-BOA Event", "paediatric orthopaedic surgery meeting")
    assert not is_relevant("Global Forum on Cardiology", "Non-BOA Event")
    assert not is_relevant("16th World Probiotics, Nutrition, Gut Health Conference and Exhibition", "Non-BOA Event")


def test_boa_own_rows_bypass_the_filter_and_future_congress_line_is_read():
    e = BoaExtractor({"id": 0, "source_name": "x"})
    assert not e.skip_card({"title": "Foundations of Something Else", "badges": [], "type": "Training"})
    assert e.skip_card({"title": "Global Forum on Cardiology", "badges": ["External"], "type": "Non-BOA Event", "teaser": ""})
    html = "<main><p>2026 - 22nd - 24th September,</p><p>Olympia London</p><p>2027 - 14th - 17th September,</p><p>ACC Liverpool</p></main>"
    fc = parse_future_congress(html, date(2026, 10, 21))
    assert fc == {"start": "2027-09-14", "end": "2027-09-17", "venue": "ACC Liverpool"}


def test_course_heuristic_title_words_and_multiweek_span_but_workshop_wins():
    assert ems_event_type("Core Skills in Orthopaedic Surgery", "Non-BOA Event") == "course"
    assert ems_event_type("Leadership Programme 2026", "") == "course"
    assert ems_event_type("Foundations in Surgical Leadership (FSL)", "Non-BOA Event", days=71) == "course"
    assert ems_event_type("MSK Ultrasound Injection Skills Workshop", "Non-BOA Event") == "workshop"
    assert ems_event_type("Wexham Cruciate Meeting", "Training", days=1) == "conference"


def test_boa_filter_keeps_orthogeriatric_rows():
    assert is_relevant("Falls Prevention Summit: Reducing Inpatient Falls", "")
    assert is_relevant("Preventing Hospital Acquired Deconditioning", "")
    assert not is_relevant("Global Forum on Cardiology", "Non-BOA Event")


def test_prose_fee_sentence_gives_member_and_non_member_tiers():
    t = ems_prose_fees("Course Fee A discounted course fee of \u00a3200 is available only for BOA members. (\u00a3300 for non-BOA members)")
    assert [(x["tier_label"], x["price_gbp"]) for x in t] == [("Registration \u00b7 BOA members", 200.0), ("Registration \u00b7 non-BOA members", 300.0)]
    assert ems_prose_fees("The course is free to attend.") == []
