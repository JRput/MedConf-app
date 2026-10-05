"""Mission P12: external registration-site fee recovery."""
from remediator.explorer import (
    find_external_event_links, _flat_text_price_sweep, _external_page_tiers,
    external_identity_ok,
)

BASE = "https://www.acpgbi.org.uk/events/1848/some_event"


def test_book_online_and_further_details_text_qualify():
    html = ('<main><a href="https://nursinghealthcareconferences.com/registration">Book online for this event</a>'
            '<a href="https://cssanz.org/x.aspx">Further details about this event</a></main>')
    urls = [u for u, _ in find_external_event_links(html, BASE)]
    assert "https://nursinghealthcareconferences.com/registration" in urls
    assert "https://cssanz.org/x.aspx" in urls


def test_ticketing_host_with_generic_or_empty_text_qualifies():
    html = ("<main><a href='https://www.eventbrite.co.uk/e/123'>Tickets</a>"
            "<a href=\"//x.eventsairsite.com/\"><img src=a.png></a></main>")
    urls = [u for u, _ in find_external_event_links(html, BASE)]
    assert "https://www.eventbrite.co.uk/e/123" in urls
    assert "https://x.eventsairsite.com/" in urls


def test_ticketing_host_in_footer_ignored():
    html = '<footer><a href="https://www.eventbrite.co.uk/o/acpgbi">Follow</a></footer>'
    assert find_external_event_links(html, BASE) == []


def test_flat_dash_prices():
    t = ("Venue: BMA House Date: 16 November 2026 Pricing: Medical Students - £10 "
         "Nurses, Pharmacists, AHPs - £35 NHS Consultants - £125 Accreditation for CPD")
    tiers = _flat_text_price_sweep(t)
    assert [(x["tier_label"], x["price_gbp"]) for x in tiers] == [
        ("Medical Students", 10.0), ("Nurses, Pharmacists, AHPs", 35.0), ("NHS Consultants", 125.0)]
    assert all(x["currency"] == "GBP" for x in tiers)


def test_flat_dollar_spaced_prices_with_deadlines():
    t = ("BOOK YOUR SEAT Academia Speaker Registration EarlyBird $ 699 Price Until Oct 04, 2026 "
         "Select Regular $ 799 Price Until Oct 08, 2026 Select")
    tiers = _flat_text_price_sweep(t)
    assert [x["price_gbp"] for x in tiers] == [699.0, 799.0]
    assert tiers[0]["is_early_bird"] and tiers[0]["currency"] == "USD"


def test_flat_rejects_sponsor_budget_and_single_holding_fee():
    assert _flat_text_price_sweep(
        "Become a Sponsor Budget Range Under $5,000 $5,000 – $15,000 $15,000 – $30,000") == []
    assert _flat_text_price_sweep(
        "Please note that a £10 holding fee is charged at registration. Refunded on attendance.") == []


def test_flat_requires_fee_context():
    assert _flat_text_price_sweep("Our cat Tom - £10 and our dog Rex - £20 are cute pets") == []


def test_external_page_tiers_prefers_table_then_flat():
    html = ("<h2>Registration fees (GBP)</h2><table><tr><th>Category</th><th>Early</th><th>Standard</th></tr>"
            "<tr><td>Member</td><td>£100</td><td>£150</td></tr>"
            "<tr><td>Non-member</td><td>£200</td><td>£250</td></tr></table>")
    tiers, how = _external_page_tiers("Registration fees Member 100 150", html)
    assert tiers and how in ("table", "text")
    tiers, how = _external_page_tiers("Registration Workshop A - £350 Workshop B - £350", "")
    assert how in ("text", "flat") and len(tiers) == 2


ROW = {"conference_name": "CRSM 2026 | CSSANZ & GSA Combined Scientific Meeting", "start_date": "2026-09-16"}


def test_identity_loose_token_or_date():
    assert external_identity_ok(ROW, "Welcome to the CSSANZ Spring Meeting")
    assert external_identity_ok({"conference_name": "Annual Course", "start_date": "2026-11-16"},
                                "Course date: 16 November 2026 at BMA House")
    assert not external_identity_ok(ROW, "Login to your member portal. Forgot password?")


def test_flat_label_cleanup_dates_and_script_residue():
    t = ("Registration Ends: April 5, 2027 Speaker (In-Person) $699 $799 $899 "
         "Poster Presentation (In-Person) $499")
    tiers = _flat_text_price_sweep(t)
    assert tiers[0]["tier_label"] == "Speaker (In-Person)" and tiers[0]["price_gbp"] == 699.0
    junk = 'Registration {\\"children\\":[[\\"$\\"],\\"c\\"]} fees $6 \\"x\\":$7'
    assert _flat_text_price_sweep(junk) == []
