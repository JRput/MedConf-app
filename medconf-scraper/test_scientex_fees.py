"""Fee shapes seen on Scientex / Vidknox conference microsites (no network)."""
from remediator.fee_matrix import parse_fee_matrix
from remediator.explorer import _flat_text_price_sweep, _external_page_tiers

SCIENTEX = (
    "Choose your currency here\n USD  EUR\n"
    "Registration Type\tEarly Bird \xa0\xa0\n2026-05-31\tMid Term\xa0\xa0\n2026-09-15\tFinal Call \xa0\xa0\n2026-11-21\tQty\n"
    "Speaker Registration\t$ 399\t$ 499\t$ 599\t\n0\n1\n2\n3\n"
    "Poster Presentation\t$ 499\t$ 599\t$ 699\t\n0\n1\n2\n3\n"
    "Student Registration\t$ 299\t$ 399\t$ 499\t\n0\n1\n2\n3\n"
    "Accompanying person\t$ 249\t$ 299\t$ 349\t\n0\n1\n2\n3\n"
    "Total Payment : $\n By completing this form"
)


def test_tab_grid_with_spaced_symbols():
    tiers = parse_fee_matrix(SCIENTEX)
    got = {(t["tier_label"], t["price_gbp"]) for t in tiers}
    assert ("Speaker Registration · Early Bird", 399.0) in got
    assert ("Speaker Registration · Mid Term", 499.0) in got
    assert ("Speaker Registration · Final Call", 599.0) in got
    assert ("Accompanying person · Final Call", 349.0) in got
    assert len(tiers) == 12
    assert all(t["currency"] == "USD" for t in tiers)
    early = [t for t in tiers if t["tier_label"].endswith("Early Bird")][0]
    assert early["is_early_bird"] and early["early_bird_deadline"] == "2026-05-31"


def test_external_page_uses_tab_grid():
    tiers, method = _external_page_tiers(SCIENTEX, None, lines=SCIENTEX)
    assert method == "matrix" and len(tiers) == 12


def test_tab_grid_needs_currency_symbol():
    assert parse_fee_matrix("Registration Type\tEarly\tLate\nSpeaker\t399\t499\nPoster\t299\t399\nStudent\t199\t299\n") == []


CARDS = (
    "15:40 - 16:00 EVENING BREAK AND NETWORKING .pricing h3 sup { top: 20px; left: 120px; } "
    "Registration Pricing Speaker $ 799 Oral Presentation Networking with Fellow Speakers E-Abstract Book "
    "Access to All Sessions and Workshops Lunch and Coffee Breaks REGISTER NOW "
    "Delegate $ 899 Delegate Opportunities Connect with Fellow Delegates E-Abstract Book Schedule Handout "
    "Access to All Sessions and Workshops Lunch and Coffee Breaks REGISTER NOW "
    "Student $ 499 Student Presentation Meet Our Experts E-Abstract Book Certificate REGISTER NOW"
)


def test_flat_sweep_price_cards():
    tiers = _flat_text_price_sweep(CARDS)
    assert [(t["tier_label"], t["price_gbp"]) for t in tiers] == [
        ("Speaker", 799.0), ("Delegate", 899.0), ("Student", 499.0)]
    assert all(t["currency"] == "USD" for t in tiers)


def test_inline_sweep_labels_never_span_lines():
    from remediator.fixers.pricing import _text_pricing_sweep
    text = ("Access to All Sessions and Workshops\nLunch and Coffee Breaks\nREGISTER NOW\nDelegate\n$\n899\n"
            "Delegate Opportunities\nStudent\n$\n499\nStudent Presentation\n")
    labels = [t["tier_label"] for t in _text_pricing_sweep(text)]
    assert all("\n" not in l for l in labels)
