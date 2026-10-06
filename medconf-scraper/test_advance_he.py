from extractors.advance_he import AdvanceHeExtractor as A

_PRICE = ('<h2>Event prices</h2><div class="table-wrapper"><table><tr><td>Aurora: Member Ticket</td>'
          '<td>Member Ticket</td><td>&pound;1130</td></tr><tr><td>Aurora: Non-Member Ticket</td>'
          '<td>Non-Member ticket</td><td>&pound;1505</td></tr></table></div>')


def test_pricing_entity_pound():
    t = A._pricing(_PRICE)
    assert [(x["tier_label"], x["price_gbp"], x["currency"]) for x in t] == [
        ("Registration · Member", 1130.0, "GBP"), ("Registration · Non-Member", 1505.0, "GBP")]


def test_no_table_no_tiers():
    assert A._pricing("<h2>Event times</h2><p>Tue 2 Feb 2027</p>") == []


def test_fact_description_mentions_title_and_dates():
    d = A._fact_description("NTFS 2027 Reviewer Training – Option 1", "Member Bundle Event",
                            "2027-02-02", "2027-02-02", "online", None)
    assert "NTFS 2027 Reviewer Training" in d and "2 Feb 2027" in d and "online" in d and len(d) >= 50


def test_fact_description_range_in_person():
    d = A._fact_description("Aurora 26/27 – Midlands", "Aurora", "2027-01-15", "2027-06-25", "in_person", "Birmingham")
    assert "15 Jan 2027 to 25 Jun 2027" in d and "in person in Birmingham" in d


def test_prose_fees_programme_page():
    t = A._pricing_prose("Dates, application and booking Member Ticket: £6190 Non-Member Ticket: £8,235 Application Deadline")
    assert [(x["tier_label"], x["price_gbp"]) for x in t] == [
        ("Registration · Member", 6190.0), ("Registration · Non-Member", 8235.0)]


def test_prose_fees_ignores_unlabelled_pound():
    assert A._pricing_prose("A bursary of £500 is available to staff.") == []
