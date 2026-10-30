import json
from tools import repair_document_pricing as R


def test_document_is_bad_cases():
    assert R.document_is_bad("cost-of-training-2024.pdf", 2027)[0]
    assert R.document_is_bad("Brochure membership updated Jan 2025.pdf", 2027)[0]
    assert R.document_is_bad("aaos-2026-reg-rates.pdf", 2027)[0]
    assert not R.document_is_bad("aaos-2026-reg-rates.pdf", 2026)[0]
    ok, why = R.document_is_bad("registration-fees-2027.pdf", 2027)
    assert not ok and "event-specific" in why
    assert R.document_is_bad("ESHRE-2026-Registrations-report-dd-16-10-2026_c.pdf", 2026)[0]


def _w(d, date, name, patches):
    p = d / date
    p.mkdir(parents=True)
    (p / name).write_text(json.dumps({"patches_applied": patches}))


def test_scan_newer_wins(tmp_path):
    pr = lambda cid, doc, label: {"conference_id": cid, "field": "pricing", "method": f"explorer:pdf:{doc}",
                                  "value_after": f"[{{'tier_label': '{label}', 'price_gbp': 1.0}}]"}
    lk = {"conference_id": 5, "field": "booking_url", "method": "external_link_follow:explorer:pdf:x.pdf",
          "value_after": "https://a.org/docs/Cost%20of%20Training.pdf"}
    venue = {"conference_id": 5, "field": "venue_name", "method": "explorer:text", "value_after": "Hall"}
    _w(tmp_path, "2026-10-05", "source-1.json", [pr(5, "old.pdf", "Old label"), lk, venue])
    _w(tmp_path, "2026-10-21", "source-1.json", [pr(5, "new.pdf", "New label")])
    out = R.scan([tmp_path])
    assert out[5]["pricing"]["doc"] == "new.pdf"
    assert out[5]["pricing"]["labels"] == ["New label"]
    assert out[5]["links"]["booking_url"]["doc"] == "Cost of Training.pdf"
    assert "venue_name" not in out[5]["links"]


ROW = {"id": 1, "start_date": "2027-01-29", "source_url": "https://s/x", "booking_url": None}
PR = {"doc": "cost-of-training-2024.pdf", "truncated": False,
      "labels": ["The total cost of sitting the MRCPsych examinations in 2023 for PMPT/Associates is", "Fees"]}


def test_tier_decisions():
    t = lambda *ls: [{"tier_label": x} for x in ls]
    assert R.decide_tiers(ROW, t("The total cost of sitting the MRCPsych examinations in 2023 for PMPT/Associates is", "Fees"), PR)[0] == "delete"
    assert R.decide_tiers(ROW, t("Fees", "Early bird delegate"), PR)[0] == "manual"
    assert R.decide_tiers(ROW, [], PR)[0] == "none"
    good = {**PR, "doc": "registration-fees-2027.pdf"}
    assert R.decide_tiers(ROW, t("Fees"), good)[0] == "keep"
    trunc = {**PR, "truncated": True, "labels": ["The total cost of sitting the MRCPsych examinations in 2023 for PMPT/Associates is"]}
    assert R.decide_tiers(ROW, t("The total cost of sitting the MRCPsych examinations in 2023 for PMPT/Associates is", "Fees"), trunc)[0] == "delete"


def test_link_decisions():
    row = {**ROW, "booking_url": "https://a/cost-of-training-2024.pdf"}
    assert R.decide_link(row, "booking_url", None)[0] == "reset"
    row2 = {**ROW, "booking_url": "https://a/registration-fees-2027.pdf"}
    assert R.decide_link(row2, "booking_url", None)[0] == "keep"
    assert R.decide_link(ROW, "booking_url", None)[0] == "ok"


def test_db_scan_link_decision_bad_booking_good_organiser():
    row = {**ROW, "booking_url": "https://a/Membership-rates.pdf", "organiser_url": "https://a/registration-fees-2027.pdf"}
    assert R.decide_link(row, "booking_url", None)[0] == "reset"
    assert R.decide_link(row, "organiser_url", None)[0] == "keep"


def test_explicit_list_parsing_and_decision():
    assert R.parse_id_list("1870, 2596,2168,3111,1870") == [1870, 2596, 2168, 3111]
    assert R.parse_id_list(None) == []
    import pytest
    with pytest.raises(ValueError):
        R.parse_id_list("12,x")
    assert R.decide_tiers_explicit([{"tier_label": "Student"}]) == ("delete", "explicit", "")
    assert R.decide_tiers_explicit([])[0] == "none"
