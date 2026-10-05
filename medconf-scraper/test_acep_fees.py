"""Offline tests for ACEP microsite fee parsing (extractors/acep.py)."""
from extractors.acep import _parse_cr_tables, _register_link

HTML = """<h1>Conference Pricing</h1><section id="crTable">
<div class="crHeader"><div class="crCol col1"><p>Member Type</p></div></div>
<div class="crRow"><div class="crCol col1"><p>ACEP Member</p></div><div class="crCol col3"><p>$1,195</p></div></div>
<div class="crRow"><div class="crCol col1"><p>Life Member</p></div><div class="crCol col3"><p>$0</p></div></div>
<div class="crRow"><div class="crCol col1"><p>Skills Labs</p></div><div class="crCol col3"><p>$195</p></div></div>
</section>"""


def test_cr_tables():
    t = _parse_cr_tables(HTML)
    assert [(x["tier_label"], x["price_gbp"], x["currency"]) for x in t] == [
        ("Full Conference · ACEP Member", 1195.0, "USD"), ("Add-on · Skills Labs", 195.0, "USD")]


def test_register_link():
    h = '<a id="microsite-reg-link" class="btn" href="https://webapps.acep.org/x?mcode=ACEP-26">Register Today</a>'
    assert _register_link(h, "https://www.acep.org/sa").endswith("mcode=ACEP-26")
    assert _register_link('<a href="/reg">Register now</a>', "https://a.org/") == "https://a.org/reg"


from extractors.acep import _find_location, _microsite_venue


def test_location_needs_state_match():
    t = "Meeting Details Marriott Marquis Chicago Chicago, Illinois October 5-7, 2026"
    assert _find_location(t, "Illinois") == {"venue_name": "Marriott Marquis Chicago", "city": "Chicago"}
    assert _find_location(t, "Ohio") == {}          # state mismatch -> nothing guessed
    assert _find_location("Chicago is lovely", "Illinois") == {}


def test_location_address_and_multiword():
    t = "Location Thomas J. Stickrath Conference Center 1970 West Broad St. Columbus, OH 43223"
    assert _find_location(t, "Ohio")["city"] == "Columbus"
    assert _find_location("Disney Resort, Lake Buena Vista, Florida", "Florida")["city"] == "Lake Buena Vista"


def test_microsite_venue():
    assert _microsite_venue("Join us for ACEP26 at the McCormick Place Convention Center Discover") \
        == "McCormick Place Convention Center"
