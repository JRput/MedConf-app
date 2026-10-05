"""Mission P15: nav-page follow + matrix fee grids (ESSIC shape)."""
from datetime import date
from remediator import explorer
from remediator.explorer import (
    prioritise_nav_links, _follow_nav_pages, AuditTrail, ExploreBudget,
)
from remediator.fee_matrix import parse_fee_matrix, parse_amount, html_to_lines

HOME = "https://www.essicmeeting.eu/"
NAV = [
    ("https://event.defoe.it/ASSWEB/index.asp", "ESSIC Member Area", True),
    ("https://www.essicmeeting.eu/", "Home", True),
    ("https://www.essicmeeting.eu/programme-2026", "Programme", True),
    ("https://www.essicmeeting.eu/abstracts-2026", "Abstracts", True),
    ("https://www.essicmeeting.eu/general-info-2026", "General Info", True),
    ("https://www.essicmeeting.eu/contact-us", "Contact Us", True),
    ("http://www.essic.org/", "ESSIC", True),
    ("https://www.essicmeeting.eu/about-2", "Privacy Policy", True),
]

ESSIC_ROWS = """Registration Fees

\xa0

MD, PhD

Residents, Nurses & Care Workers

Students, Patients

Workshops

ESSIC MEMBERS

By July 15th

€300,00

€170,00

€90,00

€40,00

After July 15th

€350,00

€220,00

€90,00

€40,00

NON MEMBERS

By July 15th

€350,00

€190,00

€90,00

€40,00

After July 15th

€450,00

€250,00

€90,00

€40,00

*Registration Fee is meant for each person, in Euros, VAT free.
"""


def test_nav_prioritisation_picks_general_info_and_abstracts_skips_privacy():
    picks = prioritise_nav_links(NAV, HOME)
    urls = [u for u, _, _ in picks]
    assert urls == ["https://www.essicmeeting.eu/general-info-2026",
                    "https://www.essicmeeting.eu/abstracts-2026"]
    assert [k for _, _, k in picks] == ["fees", "abstract"]
    joined = " ".join(urls)
    assert "about-2" not in joined and "contact" not in joined and "defoe" not in joined


def test_nav_fee_links_ranked_and_capped():
    links = [(f"https://x.org/{p}", t, True) for p, t in [
        ("venue", "Venue"), ("info", "Practical Information"), ("fees", "Registration"),
        ("gi", "General Info"), ("abs", "Call for Papers"), ("news", "News")]]
    picks = prioritise_nav_links(links, "https://x.org/")
    assert len(picks) <= 3
    assert picks[0][1] == "Registration"           # best rank first
    assert any(k == "abstract" for _, _, k in picks)  # abstract slot reserved
    assert not any(t == "News" for _, t, _ in picks)


def test_nav_other_host_and_abstract_off():
    picks = prioritise_nav_links(NAV, HOME, need_abstract=False)
    assert [t for _, t, _ in picks] == ["General Info"]


def test_essic_grid_row_oriented_european_decimals():
    tiers = parse_fee_matrix(ESSIC_ROWS)
    assert len(tiers) == 16
    by = {t["tier_label"]: t for t in tiers}
    t = by["ESSIC Members · MD, PhD · By July 15th"]
    assert t["price_gbp"] == 300.0 and t["currency"] == "EUR"
    assert by["Non Members · Residents, Nurses & Care Workers · After July 15th"]["price_gbp"] == 250.0
    assert by["ESSIC Members · Workshops · After July 15th"]["price_gbp"] == 40.0


def test_grid_without_group_label():
    t = ("Fees\nDelegate\nStudent\nEarly bird\n£200\n£100\nStandard\n£250\n£120\nNotes\n")
    # "Early bird" rows, 2 categories, 2 timeframes
    tiers = parse_fee_matrix(t)
    assert {(x["tier_label"], x["price_gbp"]) for x in tiers} == {
        ("Delegate · Early bird", 200.0), ("Student · Early bird", 100.0),
        ("Delegate · Standard", 250.0), ("Student · Standard", 120.0)}
    assert all(x["currency"] == "GBP" for x in tiers)


def test_grid_inline_prefix_rows():
    t = ("Registration fees\nMember\nNon-member\nBy 1 May 2026: $300 $400\nAfter 1 May 2026: $350 $450\n")
    tiers = parse_fee_matrix(t)
    assert len(tiers) == 4
    assert {x["tier_label"]: x["price_gbp"] for x in tiers}["Non-member · After 1 May 2026"] == 450.0
    assert tiers[0]["currency"] == "USD"


def test_grid_transposed_rows_are_categories():
    t = ("Registration Fees\nEarly bird\nStandard\nLate\nMember\n€300,00\n€350,00\n€400,00\n"
         "Non-member €400,00 €450,00 €500,00\nStudent\n€100,00\n€120,00\n€150,00\n")
    tiers = parse_fee_matrix(t)
    by = {x["tier_label"]: x["price_gbp"] for x in tiers}
    assert len(tiers) == 9
    assert by["Member · Early bird"] == 300.0
    assert by["Non-member · Late"] == 500.0
    assert by["Student · Standard"] == 120.0
    assert all(x["currency"] == "EUR" for x in tiers)


def test_html_table_grid_via_html_to_lines():
    html = ("<table><tr><td></td><td>Member</td><td>Non-member</td></tr>"
            "<tr><td>Early bird</td><td>€100,00</td><td>€150,00</td></tr>"
            "<tr><td>Late</td><td>€150,00</td><td>€200,00</td></tr></table>")
    tiers = parse_fee_matrix(html_to_lines(html))
    assert len(tiers) == 4 and tiers[0]["tier_label"] == "Member · Early bird"


def test_no_symbol_means_no_grid_and_prose_is_ignored():
    assert parse_fee_matrix("Member\nNon-member\nEarly bird\n100\n150\nLate\n150\n200\n") == []
    assert parse_fee_matrix("Welcome to the congress.\nDates: By July 15th\nWe look forward to seeing you.\n") == []


def test_parse_amount_european_and_us():
    assert parse_amount("300,00") == 300.0
    assert parse_amount("1.200,00") == 1200.0
    assert parse_amount("1,200.50") == 1200.5
    assert parse_amount("1.200") == 1200.0
    assert parse_amount("45") == 45.0


ABSTRACT_PAGE = ("ABSTRACTS\nMake a difference in BPS/IC\n\nBladder Pain Syndrome represent challenges "
                 "in London from October 22-24 2026.\n\nSubmit your abstract by July 30th, 2026.\n"
                 "Check the status of your abstract\n")


def test_follow_nav_pages_finds_fees_and_abstract_deadline(monkeypatch):
    pages = {
        HOME: ("Home", "<html></html>", NAV_RENDERED := [(u, t, n) for u, t, n in NAV]),
        "https://www.essicmeeting.eu/general-info-2026": (ESSIC_ROWS, "<html></html>", []),
        "https://www.essicmeeting.eu/abstracts-2026": (ABSTRACT_PAGE, "<html></html>", []),
    }
    monkeypatch.setattr(explorer, "render_page", lambda u: pages.get(u, (None, None, [])))
    monkeypatch.setattr(explorer, "vision_time_left", lambda: False)
    trail, extras = AuditTrail(), {}
    row = {"conference_name": "ESSIC 2026 Congress", "start_date": "2026-10-22"}
    res = _follow_nav_pages(row, "<html><body>no anchors</body></html>", HOME, trail, extras)
    assert res is not None
    tiers, url, method = res
    assert len(tiers) == 16 and url.endswith("general-info-2026") and method == "nav_matrix"
    assert extras["abstract_status"]["abstract_deadline"] == "2026-07-30"
    assert extras["abstract_status"]["abstract_open"] is False  # past
    notes = " ".join(trail.notes)
    assert "nav_page_followed: https://www.essicmeeting.eu/general-info-2026 (General Info)" in notes
    assert "abstracts-2026 (Abstracts)" in notes and "contact-us" not in notes


def test_follow_nav_pages_skips_abstract_page_when_deadline_known(monkeypatch):
    calls = []

    def fake(u):
        calls.append(u)
        return {HOME: ("Home", "<html></html>", NAV),
                "https://www.essicmeeting.eu/general-info-2026": (ESSIC_ROWS, "<html></html>", [])
                }.get(u, (None, None, []))
    monkeypatch.setattr(explorer, "render_page", fake)
    monkeypatch.setattr(explorer, "vision_time_left", lambda: False)
    extras = {}
    _follow_nav_pages({"abstract_deadline": "2026-07-30"}, "<html></html>", HOME, AuditTrail(), extras)
    assert "https://www.essicmeeting.eu/abstracts-2026" not in calls and not extras
