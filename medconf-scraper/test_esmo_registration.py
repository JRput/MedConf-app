"""ESMO registration-fee parser, precedence and re-detail hook (mission: false Free pricing)."""
import os
from datetime import datetime, timedelta

from extractors import esmo
from extractors.esmo import (
    ESMOExtractor,
    _pricing_from_esmo_fee_table,
    _pricing_from_registration_text,
)
from scraper import _stale_without_pricing

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def test_elcc_2027_27_tiers_exact_labels():
    tiers = _pricing_from_registration_text(_load("esmo_elcc2027_registration.txt"))
    assert len(tiers) == 27
    assert {t["currency"] for t in tiers} == {"EUR"}
    by = {t["tier_label"]: t for t in tiers}
    t = by["Early registration · ESMO / IASLC / ESTS / ESTRO Member"]
    assert t["price_gbp"] == 360.0 and t["is_early_bird"]
    assert t["early_bird_deadline"] == "2027-01-13"
    assert by["Full registration · ESMO / IASLC / ESTS / ESTRO Member"]["price_gbp"] == 765.0
    assert by["Late registration · ESMO / IASLC Member Nurse"]["price_gbp"] == 160.0
    assert by["Full registration · Non-Member Academia & Other (non-Industry)"]["price_gbp"] == 1010.0
    assert by["Early registration · Non-member Industry"]["price_gbp"] == 735.0
    late = by["Late registration · ESMO / IASLC Member Nurse"]
    assert not late["is_early_bird"] and late["early_bird_deadline"] is None
    assert sum(t["is_early_bird"] for t in tiers) == 9
    assert all("—" not in t["tier_label"] and "*" not in t["tier_label"] for t in tiers)


def test_breast_2027_27_tiers_and_other_fees_excluded():
    tiers = _pricing_from_registration_text(_load("esmo_breast2027_registration.txt"))
    assert len(tiers) == 27
    early = [t for t in tiers if t["is_early_bird"]]
    assert len(early) == 9 and {t["early_bird_deadline"] for t in early} == {"2027-03-03"}
    labels = " ".join(t["tier_label"] for t in tiers).lower()
    for bad in ("badge", "exhibition", "media", "press", "private meeting"):
        assert bad not in labels
    assert any(t["tier_label"] == "Early registration · ESMO Member" and t["price_gbp"] == 365.0
               for t in tiers)


def test_free_of_charge_row_is_not_a_tier():
    text = _load("esmo_elcc2027_registration.txt").replace(
        "Non-member Industry**\t€ 735.00\t€ 990.00\t€ 1,130.00",
        "Non-member Industry**\t€ 735.00\t€ 990.00\t€ 1,130.00\n"
        "Press Representatives\tFree of charge",
    )
    tiers = _pricing_from_registration_text(text)
    assert len(tiers) == 27 and all(t["price_gbp"] > 0 for t in tiers)


def test_synthetic_sgd_three_columns():
    text = (
        "Registration fees\n"
        "(8% GST included)\tEarly registration\nuntil 1 March 2027\t"
        "Late registration\nuntil 1 May 2027\tFull registration\nfrom 2 May 2027\n"
        "ESMO Member\tSGD 465.00\tSGD 670.00\tSGD 990.00\n"
        "Non-Member Industry*\tSGD 1,000.00\tSGD 1,150.00\tSGD 1,280.00\n"
        "\nOther registration fees\nExhibitor badge\tSGD 500.00\n"
    )
    tiers = _pricing_from_registration_text(text)
    assert len(tiers) == 6
    assert {t["currency"] for t in tiers} == {"SGD"}
    assert tiers[0]["tier_label"] == "Early registration · ESMO Member"
    assert tiers[0]["early_bird_deadline"] == "2027-03-01"
    assert tiers[-1]["price_gbp"] == 1280.0


def test_headerless_single_amount_rows():
    text = "Registration fees\nStandard rate\t€ 250.00\nPatient Advocate\t€ 50.00\n\nSee terms."
    tiers = _pricing_from_registration_text(text)
    assert [(t["tier_label"], t["price_gbp"]) for t in tiers] == [
        ("Standard rate", 250.0), ("Patient Advocate", 50.0)]


def test_no_fees_gives_nothing():
    assert _pricing_from_registration_text("Register now\nFree of charge for press") == []
    assert _pricing_from_registration_text(_load("esmo_elcc2027_main.txt")) == []


def test_main_page_two_column_fallback_uses_middot():
    html = "<p>Early registration</p><p>€70</p><p>€350</p>"
    tiers = _pricing_from_esmo_fee_table(html)
    assert tiers and all("—" not in t["tier_label"] for t in tiers)
    assert {t["price_gbp"] for t in tiers} >= {70.0, 350.0}
    assert [t["tier_label"] for t in tiers] == [
        "Early registration · member", "Early registration · non-member"]


def test_main_page_multi_column_uses_middot():
    html = ("Early registration Late registration Full registration "
            "ESMO Member €100 €200 €300")
    tiers = _pricing_from_esmo_fee_table(html)
    assert [t["tier_label"] for t in tiers] == [
        "Early registration · ESMO Member", "Late registration · ESMO Member",
        "Full registration · ESMO Member"]


def test_kontent_failure_warns_once(monkeypatch):
    calls = []

    class Boom:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **k):
            calls.append(1)
            raise RuntimeError("no route")

    monkeypatch.setattr(esmo, "_KONTENT_DEAD", False)
    monkeypatch.setattr(esmo.httpx, "Client", Boom)
    warnings = []
    monkeypatch.setattr(esmo.logger, "warning", lambda m, *a, **k: warnings.append(m))
    for _ in range(5):
        assert esmo._fetch_kontent_by_slugs({"x"}) == {}
    assert len(calls) == 1 and len(warnings) == 1


def _row(tiers, days_ago):
    return {"pricing_tiers": tiers,
            "last_detail_at": (datetime.utcnow() - timedelta(days=days_ago)).isoformat()}


def test_redetail_hook_decision():
    assert _stale_without_pricing(_row([], 8), 7) is True
    assert _stale_without_pricing(_row([], 2), 7) is False          # recent
    assert _stale_without_pricing(_row([{"id": 1}], 30), 7) is False  # has fees
    assert _stale_without_pricing({"last_detail_at": None, "pricing_tiers": []}, 7) is True
    assert _stale_without_pricing({"last_detail_at": "2020-01-01"}, 7) is False  # tiers unknown
    assert _stale_without_pricing(
        {"pricing_tiers": [], "last_detail_at": "2020-01-01T00:00:00+00:00"}, 7) is True


# --------------------------------------------------------------------------
# Review fixes: parser robustness
# --------------------------------------------------------------------------
_HDR = ("Registration fees\n(19% VAT included)\tEarly registration\nuntil 13 January 2027\t"
        "Late registration\nuntil 17 February 2027\tFull registration\nfrom 18 February 2027\n")


def test_prose_above_header_does_not_shift_columns():
    text = ("Benefit from Early registration until 13 January 2027.\n" + _HDR +
            "ESMO Member\t€ 360.00\t€ 505.00\t€ 765.00\n")
    t = _pricing_from_registration_text(text)
    assert [(x["tier_label"], x["price_gbp"]) for x in t] == [
        ("Early registration · ESMO Member", 360.0),
        ("Late registration · ESMO Member", 505.0),
        ("Full registration · ESMO Member", 765.0)]


def test_prose_line_with_one_amount_is_not_a_row():
    text = "Fees from €50 apply.\n" + _HDR + "ESMO Member\t€ 360.00\t€ 505.00\t€ 765.00\n"
    assert len(_pricing_from_registration_text(text)) == 3


def test_mid_table_free_row_does_not_truncate():
    text = (_HDR + "ESMO Member\t€ 360.00\t€ 505.00\t€ 765.00\n"
            "Press Representatives\tFree of charge\n"
            "Non-Member Industry**\t€ 735.00\t€ 990.00\t€ 1,130.00\n")
    labels = {x["tier_label"].split(" · ")[1] for x in _pricing_from_registration_text(text)}
    assert labels == {"ESMO Member", "Non-Member Industry"}


def test_two_consecutive_non_rows_end_table():
    text = (_HDR + "ESMO Member\t€ 360.00\t€ 505.00\t€ 765.00\n"
            "A\tfree\nB\ton request\n"
            "Late Row\t€ 100.00\t€ 200.00\t€ 300.00\n")
    assert len(_pricing_from_registration_text(text)) == 3


def test_blank_line_ends_table_later_block_excluded():
    text = (_HDR + "ESMO Member\t€ 360.00\t€ 505.00\t€ 765.00\n\n"
            "Hotel Single\t€ 180.00\t€ 200.00\t€ 220.00\n")
    labels = {x["tier_label"] for x in _pricing_from_registration_text(text)}
    assert not any("Hotel" in l for l in labels) and len(labels) == 3


def test_heading_ends_table():
    text = (_HDR + "ESMO Member\t€ 360.00\t€ 505.00\t€ 765.00\nAccommodation\n"
            "Hotel Single\t€ 180.00\t€ 200.00\t€ 220.00\n")
    assert len(_pricing_from_registration_text(text)) == 3


def test_mixed_currency_row_dropped_with_warning(monkeypatch):
    warns = []
    monkeypatch.setattr(esmo.logger, "warning", lambda m, *a, **k: warns.append(m))
    text = (_HDR + "ESMO Member\t€ 360.00\t€ 505.00\t€ 765.00\n"
            "Odd Row\tUSD 100.00\tUSD 200.00\tUSD 300.00\n")
    t = _pricing_from_registration_text(text)
    assert len(t) == 3 and {x["currency"] for x in t} == {"EUR"}
    assert any("USD" in w for w in warns)


def test_short_rows(monkeypatch):
    warns = []
    monkeypatch.setattr(esmo.logger, "warning", lambda m, *a, **k: warns.append(m))
    text = (_HDR + "ESMO Member\t€ 360.00\t€ 505.00\t€ 765.00\n"
            "Student\t€ 90.00\n"
            "Nurse\t€ 130.00\t€ 160.00\n")
    t = _pricing_from_registration_text(text)
    labels = [x["tier_label"] for x in t]
    assert "Student" in labels                      # single amount, no suffix
    assert not any(l.startswith("Nurse") for l in labels)
    assert any("Nurse" in w for w in warns)


# --------------------------------------------------------------------------
# Review fixes: no location data without page evidence
# --------------------------------------------------------------------------
def test_facts_elcc_main_page():
    f = esmo._facts_from_rendered(_load("esmo_elcc2027_main.txt"),
                                  "European Lung Cancer Congress 2027")
    assert f == {"start_date": "2027-03-17", "end_date": "2027-03-20", "city": "Munich",
                 "event_format": "in_person",
                 "venue_name": "ICM-International Congress Centre of the Munich Messe"}


def test_facts_absent_without_evidence():
    assert esmo._facts_from_rendered("Some page\nwith nothing useful", "ESMO Workshop") == {}
    assert esmo._facts_from_rendered("", "x") == {}


def test_facts_online_from_location_or_title():
    f = esmo._facts_from_rendered("Location\nOnline\nVenue\n\n", "ESMO Webinar")
    assert f["event_format"] == "online" and "venue_name" not in f and "city" not in f
    assert esmo._facts_from_rendered("x", "Oncology Webinar Series")["event_format"] == "online"


def test_extract_detail_emits_no_format_or_type_without_evidence(monkeypatch):
    monkeypatch.setattr(esmo, "_KONTENT_DEAD", True)

    class Boom:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **k): raise RuntimeError("down")

    monkeypatch.setattr(esmo.httpx, "Client", Boom)
    ex = ESMOExtractor({"id": 17})
    out = ex.extract_detail(None, {"title": "ESMO Preceptorship on Something Else",
                                   "source_url": "https://www.esmo.org/meeting-calendar/x",
                                   "slug": "x"}, lambda p: None)
    for k in ("event_format", "city", "venue_name"):
        assert k not in out
    assert out["event_type"] == "course"             # preceptorship -> course (upgrade)
    assert "event_format" not in out["_evidence"] and "event_type" in out["_evidence"]


# --------------------------------------------------------------------------
# scrape_source with a fake agent and fake DB
# --------------------------------------------------------------------------
import scraper as scraper_mod  # noqa: E402


_UNSET = object()


class _FakeExtractor:
    """A generic (non-ESMO) extractor. `days` omitted = the attribute is absent
    (scraper default applies); `days=None` = explicit opt-out."""
    def __init__(self, days=_UNSET):
        if days is not _UNSET:
            self.REFRESH_DETAIL_WHEN_NO_PRICING_DAYS = days


class _FakeAgent:
    detailed: list = []

    def __init__(self, shells, days):
        self.extractor = _FakeExtractor(days)
        self._shells = shells
        self.browser = type("B", (), {"challenged_count": 0})()

    def open_browser(self): pass
    def close_browser(self): pass
    def list_shells(self): return self._shells

    def extract_detail_for_shell(self, shell):
        _FakeAgent.detailed.append(shell["booking_url"])
        # what the merge emits for an ESMO page with fees but no location
        return {"conference_name": shell["title"], "start_date": "2027-03-17",
                "end_date": "2027-03-20", "event_type": "conference",
                "description": "d" * 60, "specialty": "Oncology",
                "venue_name": None, "city": None, "event_format": "online",
                "pricing_tiers": [{"tier_label": "Early registration · ESMO Member",
                                   "price_gbp": 360.0, "currency": "EUR"}],
                "is_flagship": False, "organiser_url": shell["booking_url"]}


def _run(monkeypatch, rows, days=_UNSET):
    """rows: {booking_url: existing-row dict}. Returns (updates, inserted_tiers)."""
    shells = [{"title": f"Event {i}", "booking_url": u} for i, u in enumerate(rows)]
    for sh in shells:
        rows[sh["booking_url"]].setdefault("listing_hash", scraper_mod._compute_listing_hash(sh))
    _FakeAgent.detailed = []
    updates, tiers = [], []
    monkeypatch.setattr(scraper_mod, "AgentLoop", lambda src: _FakeAgent(shells, days))
    monkeypatch.setattr(scraper_mod, "get_conference_by_source_url", lambda u: rows.get(u))
    monkeypatch.setattr(scraper_mod, "update_conference", lambda i, ch: updates.append((i, ch)))
    monkeypatch.setattr(scraper_mod, "bump_last_seen", lambda i: None)
    monkeypatch.setattr(scraper_mod, "delete_pricing_tiers", lambda i: None)
    monkeypatch.setattr(scraper_mod, "insert_pricing_tiers", lambda i, t: tiers.append((i, t)))
    monkeypatch.setattr(scraper_mod.http_fetch, "reset_blocks", lambda: None)
    scraper_mod.scrape_source({"id": 99, "source_name": "Some Society"})
    return updates, tiers


def _stored(i, days_old, **kw):
    row = {"id": i, "event_format": "in_person", "venue_name": "ICM", "city": "Munich",
           "event_type": "conference", "is_flagship": True, "pricing_tiers": [],
           "last_detail_at": (datetime.utcnow() - timedelta(days=days_old)).isoformat()}
    row.update(kw)
    return row


def test_explicit_none_opts_out_of_redetail(monkeypatch):
    rows = {"https://x/a": _stored(1, 400)}
    updates, tiers = _run(monkeypatch, rows, days=None)
    assert _FakeAgent.detailed == [] and updates == []


def test_default_applies_to_every_extractor_without_the_attribute(monkeypatch):
    """Generalised hook: a non-ESMO extractor with no attribute is re-detailed at 7 days."""
    assert scraper_mod.DEFAULT_REFRESH_DETAIL_WHEN_NO_PRICING_DAYS == 7
    rows = {"https://x/a": _stored(1, 30), "https://x/b": _stored(2, 3)}
    updates, tiers = _run(monkeypatch, rows)          # attribute absent
    assert _FakeAgent.detailed == ["https://x/a"]
    assert [i for i, _ in tiers] == [1]


def test_default_hook_keeps_location_and_type_for_generic_extractor(monkeypatch):
    rows = {"https://x/a": _stored(1, 30)}
    updates, _ = _run(monkeypatch, rows)              # attribute absent
    changed = {k for _, ch in updates for k in ch}
    assert not changed & {"venue_name", "city", "event_format", "event_type"}
    assert "is_flagship" not in changed


def test_attribute_redetails_stale_tierless_row(monkeypatch):
    rows = {"https://x/a": _stored(1, 30), "https://x/b": _stored(2, 1),
            "https://x/c": _stored(3, 30, pricing_tiers=[{"id": 9}])}
    updates, tiers = _run(monkeypatch, rows, days=7)
    assert _FakeAgent.detailed == ["https://x/a"]
    assert [i for i, _ in tiers] == [1]


def test_hook_redetail_keeps_location_and_type(monkeypatch):
    rows = {"https://x/a": _stored(1, 30)}
    updates, _ = _run(monkeypatch, rows, days=7)
    changed = {k for _, ch in updates for k in ch}
    assert not changed & {"venue_name", "city", "event_format", "event_type"}
    assert "is_flagship" not in changed  # True is never downgraded


def test_hook_cap_per_run_oldest_first(monkeypatch):
    rows = {f"https://x/{n}": _stored(n, 10 + n) for n in range(1, 21)}
    _run(monkeypatch, rows, days=7)
    assert len(_FakeAgent.detailed) == scraper_mod.HOOK_REDETAIL_CAP_PER_RUN == 10
    expected = {f"https://x/{n}" for n in range(11, 21)}  # the 10 oldest
    assert set(_FakeAgent.detailed) == expected


def test_online_event_has_no_venue():
    f = esmo._facts_from_rendered(
        "Location\nOnline\nVenue\n\nPhysician sign-off: luxury or necessity?\n", "ESMO Webinar")
    assert f["event_format"] == "online" and "venue_name" not in f


# --------------------------------------------------------------------------
# F1b: evidence-backed overwrites, venue menu, hybrid
# --------------------------------------------------------------------------
def test_evidence_backed_format_overwrites_stored_online():
    ex = {"event_format": "online", "city": None, "venue_name": None,
          "event_type": "workshop", "is_flagship": True}
    new = {"event_format": "in_person", "city": "Munich", "venue_name": "ICM",
           "event_type": "conference", "is_flagship": False}
    ev = {"event_format", "city", "venue_name", "event_type", "is_flagship"}
    ch = scraper_mod._non_destructive_changes(ex, new, ev)
    assert ch == new                                 # incl. stale flagship corrected


def test_no_evidence_keeps_stored_values():
    ex = {"event_format": "online", "event_type": "workshop", "is_flagship": True,
          "venue_name": "ICM"}
    new = {"event_format": "in_person", "event_type": "conference", "is_flagship": False,
           "venue_name": None}
    assert scraper_mod._non_destructive_changes(ex, new, set()) == {}


def test_absent_key_keeps_stored_value_even_with_other_evidence():
    ex = {"event_format": "in_person", "city": "Munich"}
    new = {"event_format": "in_person", "city": None}
    assert scraper_mod._non_destructive_changes(ex, new, {"event_format"}) == {}


def test_facts_menu_word_is_not_a_venue():
    txt = ("Overview\nProgramme\nVenue\nRegistration\nAbstracts\n\nEuropean Lung Cancer Congress 2027\n"
           "Start date\n17 Mar 2027\nEnd date\n20 Mar 2027\nLocation\nMunich, Germany\n")
    f = esmo._facts_from_rendered(txt, "European Lung Cancer Congress 2027")
    assert f["city"] == "Munich" and "venue_name" not in f


def test_facts_menu_venue_label_after_location_rejected():
    txt = "Start date\n1 Mar 2027\nLocation\nMunich, Germany\nVenue\nRegistration\n"
    assert "venue_name" not in esmo._facts_from_rendered(txt, "X")


def test_facts_own_block_wins_over_related_event_above_title():
    txt = ("Related\nStart date\n1 Jan 2027\nEnd date\n2 Jan 2027\nLocation\nParis, France\n"
           "Venue\n\nPalais des Congres\n\nMy Event 2027\n"
           "Start date\n17 Mar 2027\nEnd date\n20 Mar 2027\nLocation\nMunich, Germany\n"
           "Venue\n\nICM Munich\n")
    f = esmo._facts_from_rendered(txt, "My Event 2027")
    assert (f["city"], f["venue_name"], f["start_date"]) == ("Munich", "ICM Munich", "2027-03-17")


def test_facts_title_absent_two_blocks_gives_nothing():
    txt = ("Start date\n17 Mar 2027\nLocation\nMunich, Germany\n\nYou may also like\n"
           "Start date\n1 Jan 2027\nLocation\nLugano, Switzerland\n")
    f = esmo._facts_from_rendered(txt, "Renamed Event 2027")
    assert not {"city", "venue_name", "event_format", "start_date"} & set(f)


def test_facts_title_absent_single_block_used():
    txt = "Start date\n17 Mar 2027\nLocation\nMunich, Germany\n"
    assert esmo._facts_from_rendered(txt, "Renamed")["city"] == "Munich"


def test_facts_hybrid():
    f = esmo._facts_from_rendered("Start date\n1 Mar 2027\nLocation\nMunich, Germany & Online\n", "X")
    assert (f["event_format"], f["city"]) == ("hybrid", "Munich")
    f = esmo._facts_from_rendered("Start date\n1 Mar 2027\nLocation\nHybrid - Munich\n", "X")
    assert (f["event_format"], f["city"]) == ("hybrid", "Munich")
    f = esmo._facts_from_rendered("Start date\n1 Mar 2027\nLocation\nMunich, Germany\n", "X")
    assert f["event_format"] == "in_person"


def test_hook_logs_info_when_delete_skipped(monkeypatch):
    infos = []
    monkeypatch.setattr(scraper_mod.logger, "info", lambda m, *a, **k: infos.append(m))
    shells = [{"title": "E", "booking_url": "https://x/a"}]
    row = _stored(1, 400, pricing_tiers=[{"id": 5}])
    row["listing_hash"] = "changed"   # listing changed -> re-detail, agent returns tiers
    monkeypatch.setattr(scraper_mod, "AgentLoop", lambda src: _FakeAgent(shells, 7))
    monkeypatch.setattr(_FakeAgent, "extract_detail_for_shell",
                        lambda self, sh: {"conference_name": "E", "start_date": "2027-03-17",
                                          "end_date": "2027-03-17", "event_type": "conference",
                                          "description": "d" * 60, "specialty": "x",
                                          "pricing_tiers": [], "organiser_url": "u"})
    monkeypatch.setattr(scraper_mod, "get_conference_by_source_url", lambda u: row)
    monkeypatch.setattr(scraper_mod, "update_conference", lambda i, c: None)
    monkeypatch.setattr(scraper_mod, "bump_last_seen", lambda i: None)
    deleted = []
    monkeypatch.setattr(scraper_mod, "delete_pricing_tiers", lambda i: deleted.append(i))
    monkeypatch.setattr(scraper_mod, "insert_pricing_tiers", lambda i, t: None)
    monkeypatch.setattr(scraper_mod.http_fetch, "reset_blocks", lambda: None)
    scraper_mod.scrape_source({"id": 99, "source_name": "Some Society"})
    assert deleted == [] and any("delete skipped" in m for m in infos)


import pytest  # noqa: E402


@pytest.mark.parametrize("title,expected", [
    ("ESMO Breast Cancer 2027", "conference"),
    ("ESMO Sarcoma and GIST Symposium 2027", "conference"),
    ("ESMO Virtual Plenary", "conference"),
    ("ESMO Women for Oncology Forum", "conference"),
    ("ESMO Gastrointestinal Cancers Congress 2027", "conference"),
    ("ESMO Asia Congress 2027", "conference"),
    ("ESMO Targeted Anticancer Therapies Congress 2027", "conference"),
    ("ESMO Novel Cancer Therapies 2027", "conference"),
    ("ESMO Immuno-Oncology Congress 2027", "conference"),
    ("ESMO Annual Meeting 2027", "conference"),
    ("ESMO Preceptorship on Lung Cancer", "course"),
    ("ESMO Masterclass in Clinical Research", "course"),
    ("ESMO Summer School", "course"),
    ("ESMO Real World Data Webinar", None),
    ("ESMO Congress Highlights Webinar GI 2026", None),
    ("Some Unrelated Thing", None),
    ("ESMO Deep Dive: Gynaecological Cancers Webinar: Update", None),
    ("ESMO Deep Dive: Gynaecological Cancers Update", None),
    ("Best of ESMO Congress 2026", None),
    ("ESMO Congress 2026 Highlights", None),
])
def test_title_event_type(title, expected):
    assert esmo._title_event_type(title) == expected


def _extract_no_kontent(monkeypatch, title):
    monkeypatch.setattr(esmo, "_KONTENT_DEAD", True)

    class Boom:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **k): raise RuntimeError("down")

    monkeypatch.setattr(esmo.httpx, "Client", Boom)
    return ESMOExtractor({"id": 17}).extract_detail(
        None, {"title": title, "source_url": "https://www.esmo.org/meeting-calendar/x",
               "slug": "x"}, lambda p: None)


def test_breast_redetail_keeps_conference_and_flagship(monkeypatch):
    out = _extract_no_kontent(monkeypatch, "ESMO Breast Cancer 2027")
    assert out["event_type"] == "conference" and out["is_flagship"] is True
    stored = {"event_type": "conference", "is_flagship": True}
    ch = scraper_mod._non_destructive_changes(stored, {"event_type": out["event_type"],
                                                       "is_flagship": True}, set(out["_evidence"]))
    assert ch == {}


def test_default_workshop_is_not_evidence_and_never_overwrites(monkeypatch):
    out = _extract_no_kontent(monkeypatch, "Some Unrelated Thing")
    assert out["event_type"] == "workshop"
    assert "event_type" not in out["_evidence"] and "is_flagship" not in out["_evidence"]
    ch = scraper_mod._non_destructive_changes(
        {"event_type": "conference", "is_flagship": True},
        {"event_type": "workshop", "is_flagship": False}, set(out["_evidence"]))
    assert ch == {}


def test_header_widest_row_not_first_row():
    text = (_HDR + "Trainee\t€ 200.00\t€ 300.00\n"
            "ESMO Member\t€ 360.00\t€ 505.00\t€ 765.00\n")
    t = _pricing_from_registration_text(text)
    assert [(x["tier_label"], x["price_gbp"]) for x in t] == [
        ("Early registration · ESMO Member", 360.0),
        ("Late registration · ESMO Member", 505.0),
        ("Full registration · ESMO Member", 765.0)]


def test_over_wide_rows_skipped_with_warning(monkeypatch):
    warns = []
    monkeypatch.setattr(esmo.logger, "warning", lambda m, *a, **k: warns.append(m))
    text = (_HDR + "ESMO Member\t€ 360.00\t€ 505.00\t€ 765.00\n"
            "Hotel 4 nights\t€ 100.00\t€ 200.00\t€ 300.00\t€ 400.00\n")
    t = _pricing_from_registration_text(text)
    assert len(t) == 3 and any("Hotel" in w for w in warns)
    two = ("Registration fees\nX\tEarly registration\nuntil 1 March 2027\tFull registration\n"
           "from 2 March 2027\nAlpha\t€ 100.00\t€ 200.00\nBeta\t€ 100.00\t€ 200.00\t€ 300.00\n")
    t = _pricing_from_registration_text(two)
    assert {x["tier_label"].split(" · ")[1] for x in t} == {"Alpha"}


def test_best_of_title_not_flagship_evidence(monkeypatch):
    out = _extract_no_kontent(monkeypatch, "Best of ESMO Congress 2026")
    assert "is_flagship" not in out and "event_type" not in out["_evidence"]
    assert "is_flagship" not in out["_evidence"]


# ---- FV1: the non-destructive rule is for hook-only re-details ---------------------------
def _redetail(monkeypatch, row, detail, days=7):
    """Run one event through scrape_source with the agent returning `detail`; return the updates."""
    shells = [{"title": "E", "booking_url": "https://x/a"}]
    updates = []
    monkeypatch.setattr(scraper_mod, "AgentLoop", lambda src: _FakeAgent(shells, days))
    monkeypatch.setattr(_FakeAgent, "extract_detail_for_shell", lambda self, sh: dict(detail))
    monkeypatch.setattr(scraper_mod, "get_conference_by_source_url", lambda u: row)
    monkeypatch.setattr(scraper_mod, "update_conference", lambda i, ch: updates.append(ch))
    monkeypatch.setattr(scraper_mod, "bump_last_seen", lambda i: None)
    monkeypatch.setattr(scraper_mod, "delete_pricing_tiers", lambda i: None)
    monkeypatch.setattr(scraper_mod, "insert_pricing_tiers", lambda i, t: None)
    monkeypatch.setattr(scraper_mod.http_fetch, "reset_blocks", lambda: None)
    scraper_mod.scrape_source({"id": 99, "source_name": "Some Society"})
    out = {}
    for ch in updates:
        out.update(ch)
    return out


_DETAIL = {"conference_name": "E", "start_date": "2027-03-17", "end_date": "2027-03-17",
           "event_type": "conference", "description": "d" * 60, "specialty": "x",
           "event_format": "online", "venue_name": None, "city": None, "abstract_deadline": None,
           "is_flagship": False, "pricing_tiers": [], "organiser_url": "u"}


def _stored_pending(**kw):
    row = _stored(1, 30, abstract_deadline="2027-01-01", **kw)
    row["listing_hash"] = scraper_mod._compute_listing_hash({"title": "E", "booking_url": "https://x/a"})
    return row


def test_listing_changed_redetail_writes_a_real_move_to_online(monkeypatch):
    """Reviewer T4: a non-ESMO row whose listing changed and which went online must be written."""
    row = _stored_pending()
    row["listing_hash"] = "old-hash"                       # listing changed -> ordinary re-detail
    got = _redetail(monkeypatch, row, _DETAIL)
    assert got["event_format"] == "online" and got["abstract_deadline"] is None
    assert got["is_flagship"] is False and got["venue_name"] is None


def test_hook_only_redetail_without_evidence_keeps_stored_values(monkeypatch):
    got = _redetail(monkeypatch, _stored_pending(), _DETAIL)
    assert not set(got) & {"event_format", "venue_name", "city", "abstract_deadline", "is_flagship"}


def test_hook_redetail_with_listing_backed_format_change_is_written(monkeypatch):
    got = _redetail(monkeypatch, _stored_pending(), dict(_DETAIL, _evidence=["event_format"]))
    assert got["event_format"] == "online"
    assert "venue_name" not in got                          # still protected: no evidence for it


def test_evidence_aware_extractor_keeps_non_destructive_rule_on_listing_change(monkeypatch):
    row = _stored_pending()
    row["listing_hash"] = "old-hash"
    got = _redetail(monkeypatch, row, dict(_DETAIL, _evidence=[], _evidence_aware=True))
    assert not set(got) & {"event_format", "venue_name", "city", "is_flagship"}


def test_shell_card_values_are_evidence_for_every_extractor():
    from llm_agent import AgentLoop
    ag = AgentLoop.__new__(AgentLoop)
    shell = {"title": "Webinar X", "booking_url": "https://x.org/w", "start_date": "2027-02-01",
             "end_date": "2027-02-02", "location_hint": "Online"}
    out = ag._merge_shell_and_detail(shell, {})
    assert {"event_format", "start_date", "end_date", "conference_name"} <= set(out["_evidence"])
    out2 = ag._merge_shell_and_detail({"title": "T", "booking_url": "https://x.org/w", "start_date": "2027-02-01"},
                                      {"event_format": "in_person", "end_date": "2027-02-03", "conference_name": "T2"})
    assert "event_format" not in out2["_evidence"] and "end_date" not in out2["_evidence"]
    assert "conference_name" not in out2["_evidence"]
    out3 = ag._merge_shell_and_detail({"title": "T", "booking_url": "https://x.org/w", "start_date": "2027-02-01"}, {})
    assert "end_date" not in out3["_evidence"]              # a defaulted end (= start) is not evidence
