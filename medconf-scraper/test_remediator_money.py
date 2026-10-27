"""X1: every remaining amount/currency parser reads through money.py.

Remediator layers (signals, pricing sweep, flat/PDF sweeps, fee matrix, validators,
LLM tier normaliser, runner page_amount_count) and the four leftover extractors
(bsg, ems_calendar, isuog, ifosworld). Nothing here may default a currency to GBP.
"""
import logging

import money
from remediator import explorer as ex
from remediator import fee_matrix as fm
from remediator import signals as sg
from remediator import validators as rv
from remediator.fixers import pricing as fp
from remediator.runner import _gaps_with_page_amounts


class _Trail:
    def __init__(self):
        self.notes = []
        self.total_text_chars = 0


def _no_llm(_):
    return None


# ── signals ─────────────────────────────────────────────────────────────────────

def test_signal_reads_suffix_code_from_and_eu_forms():
    for s in ("Registration fee 1500 EUR", "Registration from 350 EUR", "Registration fee 1.500,00 €",
              "Fee CHF 1'200", "Fee S$465", "Fee 1 200 zł"):
        assert sg.price_text_signal(s), s


def test_signal_ignores_zero_penalty_and_bare_numbers():
    assert not sg.price_text_signal("Shipping £0.00")
    assert not sg.price_text_signal("A cancellation fee of 200 EUR applies")
    assert not sg.price_text_signal("Day 1 350")
    assert sg.price_text_signal("Cancellation policy: refunds less 50 EUR admin fee. Registration 300 EUR")


def test_page_amount_count_is_distinct_amounts():
    t = "Member 300 EUR, Student 170 EUR, Late 300 EUR, cancellation fee of 50 EUR, shipping £0"
    assert sg.page_amount_count(t) == 2


def test_free_verdict_blocked_by_suffix_and_eu_amounts():
    row = {"source_url": "https://my.rcr.ac.uk/event/1"}
    for amt in ("1500 EUR", "from 350 EUR", "1.500,00 €"):
        tiers, method = fp.fix_pricing(dict(row), f"This webinar is free to attend.\nBooking opens soon. Ticket {amt}.", _no_llm)
        assert method != "free_event", amt


# ── pricing text sweep ───────────────────────────────────────────────────────────

def test_text_sweep_currency_forms():
    t = fp._text_pricing_sweep("Member fee: 300 EUR\nStudent fee: 1.500,00 €\nTrainee fee | S$465.00\nNurse fee: CHF 1'200")
    got = {(x["price_gbp"], x["currency"]) for x in t}
    assert got == {(300.0, "EUR"), (1500.0, "EUR"), (465.0, "SGD"), (1200.0, "CHF")}


def test_text_sweep_never_defaults_currency():
    assert fp._text_pricing_sweep("Member fee: kr 2,500\nStudent fee: kr 1,000") == []
    assert fp._text_pricing_sweep("Day 1 350") == []


def test_text_sweep_inline_suffix_and_penalty_label():
    t = fp._text_pricing_sweep("Late registration 350 EUR applies after June. Cancellation fee £25 applies.")
    assert [(x["price_gbp"], x["currency"]) for x in t] == [(350.0, "EUR")]


def test_text_sweep_vat_tail_and_plausible_cap():
    t = fp._text_pricing_sweep("Consultant fee: EUR 300 + VAT\nStudent fee: £90000")
    assert [(x["price_gbp"], x["currency"]) for x in t] == [(300.0, "EUR")]


# ── explorer sweeps ─────────────────────────────────────────────────────────────

def test_flat_sweep_currency_forms():
    t = ex._flat_text_price_sweep("Registration fees. Member - EUR 300 Student - EUR 170 Nurse - EUR 90")
    assert {x["currency"] for x in t} == {"EUR"} and len(t) == 3
    t = ex._flat_text_price_sweep("Registration fees. Member - S$465 Student - S$300")
    assert {x["currency"] for x in t} == {"SGD"}
    t = ex._flat_text_price_sweep("Registration fees. Regular Member $ 799 Price Until June Student Member $ 399 Price Until June")
    assert {x["currency"] for x in t} == {"USD"}


def test_flat_sweep_suffix_and_eu_decimals():
    t = ex._flat_text_price_sweep("Registration fees. Member - 1.500,00 € Student - 900,50 €")
    assert [(x["price_gbp"], x["currency"]) for x in t] == [(1500.0, "EUR"), (900.5, "EUR")]


def test_flat_sweep_drops_unknown_currency():
    assert ex._flat_text_price_sweep("Registration fees. Member - kr 2,500 Student - kr 1,000") == []


def test_pdf_text_plain_fee_lines_use_detected_currency_and_eu_decimals():
    text = "Registration fees (EUR)\nMember  450\nStudent  1.200,50\nIndustry delegate  2.500\nPage 1 of 2"
    tiers = ex._tiers_from_document_text(text, _Trail())
    got = {(t["price_gbp"], t["currency"]) for t in tiers}
    assert (450.0, "EUR") in got and (1200.5, "EUR") in got and all(c == "EUR" for _, c in got)


def test_pdf_text_without_currency_is_dropped_not_gbp():
    text = "Registration fees\nMember  450\nStudent  300\nIndustry delegate  900\nDay 1 350"
    assert ex._tiers_from_document_text(text, _Trail()) == []


def test_pdf_text_day_1_350_is_not_1350():
    text = "Registration fees EUR\nMember  450\nStudent  300\nDay 1 350"
    tiers = ex._tiers_from_document_text(text, _Trail())
    assert all(t["price_gbp"] != 1350.0 for t in tiers)


def test_structured_price_num_uses_money():
    assert ex._num("1500.50") == 1500.5
    assert ex._num("95,50") == 95.5          # was refused before; EU decimal now read
    assert ex._num("1.500,00") == 1500.0
    assert ex._num("0") is None
    assert ex._num(80000, "GBP") is None and ex._num(80000, "JPY") == 80000


def test_offer_currency_must_be_known():
    tiers = ex._offer_tiers({"@type": "Offer", "name": "Delegate", "price": "250", "priceCurrency": "XXX"}, "Ticket")
    assert tiers == []
    tiers = ex._offer_tiers({"@type": "Offer", "name": "Delegate", "price": "250", "priceCurrency": "pln"}, "Ticket")
    assert [(t["price_gbp"], t["currency"]) for t in tiers] == [(250.0, "PLN")]


def test_non_fee_amount_values_read_any_currency():
    vals = ex._non_fee_amount_values("A 10 EUR holding fee is fully refunded. Delegate 300 EUR.")
    assert vals == {10.0}
    assert ex._strip_non_fee_amounts("A 10 EUR holding fee is fully refunded. Delegate 300 EUR.").count("300") == 1


def test_llm_tier_without_valid_currency_is_dropped(caplog):
    caplog.set_level(logging.WARNING)
    out = ex._llm_tiers_to_schema([
        {"tier_label": "Member", "price": 300, "currency": "eur"},
        {"tier_label": "Student", "price": 100},                       # absent
        {"tier_label": "Nurse", "price": 50, "currency": "unknown"},
        {"tier_label": "Trainee", "price": 60, "currency": "kr"},
        {"tier_label": "Day pass", "price": 90000, "currency": "GBP"},  # over cap
        {"tier_label": "Delegate", "price": 5000, "currency": "S$"},
    ])
    assert [(t["tier_label"], t["currency"]) for t in out] == [("Member", "EUR"), ("Delegate", "SGD")]
    assert "no valid currency" in caplog.text


# ── fee matrix ──────────────────────────────────────────────────────────────────

def test_matrix_cells_read_all_forms():
    assert fm._cells("EUR300,00  EUR170,00  EUR90,00  EUR40,00") == [(300.0, "EUR"), (170.0, "EUR"), (90.0, "EUR"), (40.0, "EUR")]
    assert fm._cells("CHF 1'200 | S$465") == [(1200.0, "CHF"), (465.0, "SGD")]
    assert fm._cells("300 € 170 € 90 €") == [(300.0, "EUR"), (170.0, "EUR"), (90.0, "EUR")]
    assert fm._cells("1.200,00 € n/a") == [(1200.0, "EUR"), (None, None)]


def test_matrix_cells_refuse_unstated_currency_and_ranges():
    assert fm._cells("kr 2500 kr 1000") is None
    assert fm._cells("300 350 400") is None
    assert fm._cells("EUR 350 – 500") is None


def test_matrix_docstring_example_parses():
    text = ("MD, PhD\nResidents, Nurses & Care Workers\nStudents\nWorkshops\nESSIC MEMBERS\n"
            "By July 15th   EUR300,00  EUR170,00  EUR90,00  EUR40,00\n"
            "After July 15th   EUR350,00  EUR200,00  EUR100,00  EUR50,00")
    tiers = fm.parse_fee_matrix(text)
    assert len(tiers) == 8 and {t["currency"] for t in tiers} == {"EUR"}
    assert (300.0 in [t["price_gbp"] for t in tiers])


def test_matrix_parse_amount_docstring():
    assert fm.parse_amount("300,00") == 300.0
    assert fm.parse_amount("1.200,00") == 1200.0
    assert fm.parse_amount("1,200.50") == 1200.5
    assert fm.parse_amount("1.200") == 1200.0


# ── validators ──────────────────────────────────────────────────────────────────

def _v(price, cur="EUR"):
    return rv.validate_pricing_tiers([{"tier_label": "Member", "price_gbp": price, "currency": cur}])


def test_validator_accepts_every_known_code_and_rejects_others():
    for c in ("SEK", "PLN", "NZD", "CZK", "DKK", "NOK", "TRY", "AED", "ZAR", "JPY", "THB"):
        assert _v(100, c), c
    for c in (None, "", "XXX", "kr", "unknown"):
        assert not _v(100, c), c


def test_validator_caps_are_per_currency():
    assert _v(50000, "GBP") and not _v(50001, "GBP")
    assert _v(5_000_000, "JPY") and not _v(25_000_000, "JPY")
    assert _v(1_000_000, "IDR") and not _v(1_000_000, "EUR")


def test_validator_warns_on_tiny_amounts_but_accepts(caplog):
    caplog.set_level(logging.WARNING)
    assert _v(3, "EUR")
    assert "suspiciously small" in caplog.text
    caplog.clear()
    assert _v(0, "EUR") and _v(5, "EUR")
    assert "suspiciously small" not in caplog.text


def test_validator_missing_currency_key_is_rejected_not_gbp():
    assert not rv.validate_pricing_tiers([{"tier_label": "Member", "price_gbp": 100}])
    assert not rv.validate_pricing_tiers([{"tier_label": "Member", "price_gbp": 100, "currency": None}])
    assert rv.validate_pricing_tiers([{"tier_label": "Member", "price_gbp": 100, "currency": "GBP"}])


# ── runner page_amount_count ────────────────────────────────────────────────────

TIERS = [{"tier_label": "Member", "price_gbp": 300.0}]


def test_runner_flags_partial_when_page_shows_more_amounts():
    row = {"id": 1, "conference_name": "Annual Congress 2027"}
    page = "Registration: Member 300 EUR, Non-member 450 EUR, Student 150 EUR"
    gaps = _gaps_with_page_amounts(row, ["description"], TIERS, page, False)
    assert "pricing" in gaps and row["_pricing_gap_kind"] == "partial"


def test_runner_no_flag_when_counts_match_or_no_page():
    row = {"id": 1, "conference_name": "Annual Congress 2027"}
    assert "pricing" not in _gaps_with_page_amounts(row, ["description"], TIERS, "Member 300 EUR", False)
    assert "pricing" not in _gaps_with_page_amounts(row, ["description"], TIERS, "", False)
    assert "pricing" not in _gaps_with_page_amounts(row, ["description"], [], "Member 300 EUR Student 100 EUR", False)
    assert _gaps_with_page_amounts({**row, "is_on_demand": True}, ["x"], TIERS, "A 300 EUR B 400 EUR", False) == ["x"]


def test_runner_shared_page_counts_only_the_row_window():
    row = {"id": 1, "conference_name": "Annual Congress 2027"}
    page = ("Annual Congress 2027 Member 300 EUR. Spring Course 2027 Member 100 EUR Student 50 EUR "
            "Late 80 EUR")
    gaps = _gaps_with_page_amounts(row, ["description"], TIERS, page, True, ["Spring Course 2027"])
    assert "pricing" not in gaps                      # sibling's amounts are not this row's
    assert _gaps_with_page_amounts(dict(row), ["description"], TIERS, "nothing here", True, []) == ["description"]


# ── money.py guard (item 8) ──────────────────────────────────────────────────────

def test_bare_day_1_350_is_not_1350():
    got = money.find_amounts("Day 1 350", require_currency=False)
    assert [m.amount for m in got] == [350.0]
    assert money.find_amounts("Day 1 350") == []
    assert money.parse_amount("Day 1 350").amount == 350.0


def test_space_thousands_still_read_with_a_currency_marker():
    assert money.parse_amount("£1 350").amount == 1350.0
    assert money.parse_amount("1 350 zł").amount == 1350.0
    assert money.parse_amount("CZK 5 000").amount == 5000.0


# ── the four extractors ─────────────────────────────────────────────────────────

def test_bsg_fees_read_sgd_and_eu_decimals():
    from extractors.bsg import parse_fees, prose_fees
    t = parse_fees(["Registration fees", "Members: S$465.00", "Non-members: 1.250,00 €"])
    assert [(x["price_gbp"], x["currency"]) for x in t] == [(465.0, "SGD"), (1250.0, "EUR")]
    assert parse_fees(["Registration fees", "Members: £50.00"])[0]["currency"] == "GBP"
    assert parse_fees(["Registration fees", "Members: $50"])[0]["currency"] == "USD"
    assert prose_fees(["The non-member rate is A$250 for the day"])[0]["currency"] == "AUD"
    assert parse_fees(["Registration fees", "Members: kr 500"], "GBP") == []


def test_ems_fees_read_aud_and_eu_decimals():
    from extractors.ems_calendar import ems_fee_tiers, ems_prose_fees
    t = ems_fee_tiers(["ICS members - A$215", "Non-members - €1.250,00", "Staff - £4,250.00"])
    assert [(x["price_gbp"], x["currency"]) for x in t] == [(215.0, "AUD"), (1250.0, "EUR"), (4250.0, "GBP")]
    p = ems_prose_fees("A discounted course fee of S$200 is available only for BOA members. (S$300 for non-BOA members)")
    assert {(x["price_gbp"], x["currency"]) for x in p} == {(200.0, "SGD"), (300.0, "SGD")}


def test_isuog_price_cells():
    from extractors.isuog import _parse_price
    assert _parse_price("S$465") == (465.0, "SGD")
    assert _parse_price("1.500,00 €") == (1500.0, "EUR")
    assert _parse_price("$300") == (300.0, "USD")
    assert _parse_price("350") is None


def test_ifosworld_cost_no_default_currency():
    from extractors.ifosworld import _parse_cost
    t = _parse_cost({"cost": "$150", "cost_details": {"values": ["150"]}})
    assert [(x["price_gbp"], x["currency"]) for x in t] == [(150.0, "USD")]
    t = _parse_cost({"cost": "S$1.500", "cost_details": {"values": ["1.500"]}})
    assert [(x["price_gbp"], x["currency"]) for x in t] == [(1500.0, "SGD")]
    assert _parse_cost({"cost": "150", "cost_details": {"values": ["150"]}}) == []     # was USD by default
    t = _parse_cost({"cost": "", "cost_details": {"currency_code": "EUR", "values": ["1.250,00"]}})
    assert [(x["price_gbp"], x["currency"]) for x in t] == [(1250.0, "EUR")]


def test_bare_cell_number_keeps_space_thousands():
    assert money.parse_amount("1 200,00").amount == 1200.0       # the cell IS the number
    assert money.parse_amount("2 500").amount == 2500.0


def test_matrix_suffix_code_grid_keeps_first_column():
    text = ("Physicians\nResidents\nStudents\n"
            "By July 15th   1500 EUR  900 EUR  600 EUR\n"
            "After July 15th   1800 EUR  1100 EUR  700 EUR")
    tiers = fm.parse_fee_matrix(text)
    assert sorted(t["price_gbp"] for t in tiers) == [600, 700, 900, 1100, 1500, 1800]
    assert {t["currency"] for t in tiers} == {"EUR"}
    assert not any(any(ch.isdigit() for ch in t["tier_label"].replace("15th", "")) for t in tiers)
    assert "Physicians · By July 15th" in [t["tier_label"] for t in tiers]


# ── FV2: runner shared venue guard, replace RPC, currency, shared key ───────────

import logging
from types import SimpleNamespace as _NS

from remediator import runner as _runner
from test_runner_writes import _SB as _BaseSB, _conf as _rconf


def test_shared_base_keeps_query_strips_fragment():
    b = _runner._base_url
    assert b("https://e.org/events?id=1#top") == b("https://e.org/events?id=1")
    assert b("https://e.org/events?id=1") != b("https://e.org/events?id=2")
    rows = [{"source_url": "https://alsg.org.uk/e?id=1"}, {"source_url": "https://alsg.org.uk/e?id=2"}]
    assert _runner._shared_bases(rows) == set()
    rows = [{"source_url": "https://e.org/c#a"}, {"source_url": "https://e.org/c#b"}]
    assert _runner._shared_bases(rows) == {"https://e.org/c"}


def test_venue_and_city_are_shared_guarded():
    assert {"venue_name", "city"} <= set(_runner.SHARED_GUARDED_FIELDS)


def test_shared_page_venue_fixer_gets_only_the_row_window(monkeypatch):
    from test_detector_runner import _drive
    page = ("Intro. Basic Life Support Course - Venue: Leeds Hall.\n"
            "Advanced Sepsis Masterclass - Venue: Cardiff Arena.\nFooter")

    class Cache:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, u): return page
        def get_html(self, u): return "<html>" + page + "</html>"

    seen, explored = {}, []

    def venue_fixer(row, text, llm):
        seen[row["id"]] = text
        return None, None

    confs = [_rconf(id=1, conference_name="Basic Life Support Course", source_url="https://e.org/c#bls"),
             _rconf(id=2, conference_name="Advanced Sepsis Masterclass", source_url="https://e.org/c#sep"),
             _rconf(id=3, conference_name="Unrelated Gala Dinner", source_url="https://e.org/c#gala")]
    monkeypatch.setattr(_runner, "PageCache", Cache)
    import test_detector_runner as tdr
    monkeypatch.setattr(tdr, "_Cache", Cache, raising=False)
    explorers = {"venue_name": lambda **kw: explored.append(kw["row"]["id"])}
    sb = _BaseSB({"scraper_sources": [{"id": 5, "society": "S", "source_name": "n"}],
                  "conferences": confs, "pricing_tiers": []})
    monkeypatch.setattr(_runner, "_get_supabase", lambda: sb)
    monkeypatch.setattr(_runner, "_llm_call_factory", lambda: (lambda *a, **k: None))
    monkeypatch.setattr(_runner, "FIXERS", {"venue_name": venue_fixer})
    monkeypatch.setattr(_runner, "EXPLORERS", explorers)
    monkeypatch.setattr(_runner, "validate", lambda f, v: True)
    monkeypatch.setattr(_runner, "detect_gaps_for_rows", lambda c, p: [(r, ["venue_name"]) for r in c])
    monkeypatch.setattr(_runner, "get_promoted_patterns", lambda *a, **k: [])
    monkeypatch.setattr(_runner, "close_render_browser", lambda: None)
    monkeypatch.setattr(_runner, "write_report", lambda **k: "r.json")
    _runner.remediate_source(5)
    assert "Leeds" in seen[1] and "Cardiff" not in seen[1]
    assert "Cardiff" in seen[2] and "Leeds" not in seen[2]
    assert 3 not in seen and explored == []


class _ReplaceSB(_BaseSB):
    """Fake Supabase whose replace-tiers function is present or absent."""
    def __init__(self, tables, present):
        super().__init__(tables)
        self.present, self.calls = present, []

    def rpc(self, name, params):
        sb = self
        class R:
            def execute(self_):
                sb.calls.append((name, params))
                if name == _runner.REPLACE_TIERS_RPC:
                    if not sb.present:
                        raise Exception("{'code': 'PGRST202', 'message': 'Could not find the function'}")
                    return _NS(data=0 if params["p_conference_id"] == 0 else len(params["p_tiers"]))
                return _NS(data=len(params["p_tiers"]))
        return R()


def _drive_pricing(monkeypatch, present, confs):
    sb = _ReplaceSB({"scraper_sources": [{"id": 5, "society": "S", "source_name": "n"}],
                     "conferences": confs, "pricing_tiers": []}, present)
    fixed = []

    def fixer(row, text, llm):
        fixed.append(row["id"])
        return [{"tier_label": "Member", "price_gbp": 100.0, "currency": "EUR"}], "text"

    class Cache:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, u): return "Member 100 EUR"
        def get_html(self, u): return ""

    monkeypatch.setattr(_runner, "_get_supabase", lambda: sb)
    monkeypatch.setattr(_runner, "_llm_call_factory", lambda: (lambda *a, **k: None))
    monkeypatch.setattr(_runner, "PageCache", Cache)
    monkeypatch.setattr(_runner, "FIXERS", {"pricing": fixer})
    monkeypatch.setattr(_runner, "EXPLORERS", {})
    monkeypatch.setattr(_runner, "validate", lambda f, v: True)
    monkeypatch.setattr(_runner, "detect_gaps_for_rows",
                        lambda c, p: [({**r, "_pricing_gap_kind": "zero"}, ["pricing"]) for r in c])
    monkeypatch.setattr(_runner, "get_promoted_patterns", lambda *a, **k: [])
    monkeypatch.setattr(_runner, "close_render_browser", lambda: None)
    cap = {}
    monkeypatch.setattr(_runner, "write_report", lambda **k: cap.update(k) or "r.json")
    _runner.remediate_source(5)
    return sb, fixed, cap


def test_zero_tier_rows_write_through_replace_rpc_when_present(monkeypatch):
    confs = [_rconf(id=1, source_url="https://a.org/1"), _rconf(id=2, source_url="https://a.org/2")]
    sb, fixed, cap = _drive_pricing(monkeypatch, True, confs)
    names = [c[0] for c in sb.calls]
    assert fixed == [1, 2]
    assert names.count(_runner.REPLACE_TIERS_RPC) == 3        # one probe + two replaces
    assert "remediator_insert_tiers_if_empty" not in names
    assert {a["conference_id"] for a in cap["patches_applied"]} == {1, 2}


def test_zero_tier_rows_skipped_when_replace_rpc_absent(monkeypatch, caplog):
    confs = [_rconf(id=1, source_url="https://a.org/1"), _rconf(id=2, source_url="https://a.org/2")]
    with caplog.at_level(logging.WARNING):
        sb, fixed, cap = _drive_pricing(monkeypatch, False, confs)
    assert fixed == []                                         # no fetch / fixer budget burned
    assert [c[0] for c in sb.calls] == [_runner.REPLACE_TIERS_RPC]   # probed ONCE
    assert cap["patches_applied"] == []
    assert caplog.text.count("not installed yet") == 1


def test_tier_without_currency_is_dropped_never_gbp(caplog):
    row = {"id": 9, "source_url": "https://x.org/e"}
    with caplog.at_level(logging.INFO):
        assert _runner._with_currency([{"tier_label": "Member", "price_gbp": 5.0}], "text", row, "") is None
    assert "no currency" in caplog.text
    kept = _runner._with_currency([{"tier_label": "A", "price_gbp": 5.0, "currency": "EUR"},
                                   {"tier_label": "B", "price_gbp": 5.0}], "text", row, "")
    assert [t["tier_label"] for t in kept] == ["A"]


def test_free_event_tier_currency_rule():
    free = [{"tier_label": "Standard", "price_gbp": 0.0, "currency": "GBP"}]
    uk = _runner._with_currency(free, "free_event", {"id": 1, "source_url": "https://rcp.ac.uk/e"}, "Free of charge")
    assert uk[0]["currency"] == "GBP"
    eu = _runner._with_currency(free, "free_event", {"id": 1, "source_url": "https://esmo.org/e"},
                                "Free of charge. Hotel from €120")
    assert eu[0]["currency"] == "EUR"
    assert _runner._with_currency(free, "free_event", {"id": 1, "source_url": "https://esmo.org/e"},
                                  "Free of charge") is None
