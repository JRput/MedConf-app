"""Free-event guard: the remediator must never call an event free when the page
shows fee amounts (ESMO ELCC 2027 / Breast 2027, 2026-10-18) and the audit must
flag a stored all-zero tier set against a priced page."""
from pathlib import Path

from remediator.fixers.pricing import fix_pricing
from remediator.audit import check_pricing

FIX = Path(__file__).parent / "fixtures"
ROW = {"source_url": "https://my.rcr.ac.uk/event/1"}  # skips guessed fee sub-pages: no network


def _no_llm(_):
    return None


def _fix(text):
    return fix_pricing(dict(ROW), text, _no_llm)


def test_elcc_registration_page_not_free():
    text = (FIX / "esmo_elcc2027_registration.txt").read_text()
    tiers, method = _fix(text)
    assert method != "free_event"
    assert tiers and all(t["price_gbp"] != 0 for t in tiers)


def test_elcc_main_page_not_free():
    text = (FIX / "esmo_elcc2027_main.txt").read_text()
    tiers, method = _fix(text)
    assert method != "free_event"
    assert not tiers or all(t["price_gbp"] != 0 for t in tiers)


def test_genuinely_free_webinar_is_free():
    tiers, method = _fix("This webinar is free to attend. Register below.")
    assert method == "free_event"
    assert tiers[0]["price_gbp"] == 0.0


def test_sccm_complimentary_webcast_not_free():
    text = "Registered attendees receive complimentary access to the webcast."
    tiers, method = _fix(text)
    assert method != "free_event"


def test_single_table_row_free_of_charge_not_free():
    # no page_url fallbacks: use a source without guessed fee sub-pages
    row = {"source_url": "https://my.rcr.ac.uk/event/1"}
    tiers, method = fix_pricing(row, "Press Representatives\tFree of charge", _no_llm)
    assert method != "free_event"


def test_free_phrase_with_amounts_not_free():
    text = "Attendance is free of charge for members. Non-members pay £50 to register."
    tiers, method = _fix(text)
    assert method != "free_event"


def _audit(tiers, text):
    return check_pricing({}, text, "", {}, tiers)


def test_audit_flags_zero_tier_on_priced_page():
    v = _audit([{"tier_label": "Standard", "price_gbp": 0.0}],
               "Registration fees: Member £120, Non-member £200")
    assert v.status == "SUSPECT"
    assert "Stored as free but page shows fee amounts" in v.reason


def test_audit_silent_for_zero_tier_without_amounts():
    v = _audit([{"tier_label": "Standard", "price_gbp": 0.0}],
               "This webinar is free to attend.")
    assert v.status == "OK"


def test_audit_silent_for_priced_tiers():
    v = _audit([{"tier_label": "Standard", "price_gbp": 50.0}], "Fee £50")
    assert v.status == "OK"


# --- tests that FAIL on the pre-F2 code ------------------------------------
def test_eur_code_amount_blocks_free():
    tiers, method = _fix("Attendance is free of charge.\nRegistration fee EUR 350 for non-members")
    assert method != "free_event"


def test_chf_code_amount_blocks_free():
    tiers, method = _fix("Attendance is free of charge for members. Non-members: CHF 200.")
    assert method != "free_event"


def test_cancellation_fee_is_not_a_price():
    tiers, method = _fix("This webinar is free to attend.\n"
                         "A cancellation fee £10 applies if you do not attend.")
    assert method == "free_event"
    assert all("cancellation" not in t["tier_label"].lower() for t in tiers)
    assert [t["price_gbp"] for t in tiers] == [0.0]


def test_zero_amount_footer_does_not_block_free():
    text = "This webinar is free to attend. Register below.\nShipping £0.00"
    tiers, method = _fix(text)
    assert method == "free_event"
    v = _audit([{"tier_label": "Standard", "price_gbp": 0.0}], text)
    assert v.status == "OK"


def test_usd_comma_amount_priced_page():
    text = "Registration: USD 1,200 per delegate."
    tiers, method = _fix(text)
    assert method != "free_event"
    v = _audit([{"tier_label": "Standard", "price_gbp": 0.0}], text)
    assert v.status == "SUSPECT"


def test_penalty_lookback_stops_at_sentence_boundary():
    from remediator.signals import price_text_signal
    assert price_text_signal("Cancellation policy: refunds less £50 admin fee. Registration £300")


def test_admin_fee_after_price_not_a_tier():
    from remediator.signals import price_text_signal
    from remediator.fixers.pricing import _text_pricing_sweep
    text = "Registration £300. A £50 admin fee applies to cancellations."
    assert price_text_signal(text)
    assert all(t["price_gbp"] != 50 for t in _text_pricing_sweep(text))


def test_deposit_plus_balance_is_priced():
    from remediator.signals import price_text_signal
    assert price_text_signal("£500 deposit + £1,500 balance")


def test_free_with_refundable_deposit_stays_free():
    # Documented positive control: a refundable deposit is not a fee.
    tiers, method = _fix("Attendance is free of charge. A refundable deposit of £100 is required to register.")
    assert method == "free_event"
