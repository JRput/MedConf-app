"""Hard wall-clock budgets in remediator.audit (2026-10-22: BOA/BAPM hang)."""
import time

import pytest

from remediator import audit


def test_wallclock_interrupts_a_blocking_call():
    t = time.time()
    with pytest.raises(audit.BudgetExceeded):
        with audit._wallclock(1, "unit"):
            time.sleep(30)
    assert time.time() - t < 6


def test_wallclock_not_swallowed_by_except_exception():
    # The shared fetchers wrap network calls in `except Exception`; the budget
    # exception must get through them.
    t = time.time()
    with pytest.raises(audit.BudgetExceeded):
        with audit._wallclock(1, "unit"):
            try:
                time.sleep(30)
            except Exception:
                pass
            time.sleep(30)
    assert time.time() - t < 8


def test_wallclock_disarms_on_normal_exit():
    with audit._wallclock(2, "unit"):
        pass
    time.sleep(3)   # would raise here if the timer were still armed


def test_offline_probe_makes_no_network_call():
    audit._OFFLINE = True
    try:
        assert audit._hydrated_registration_probe("https://example.invalid/x") is None
    finally:
        audit._OFFLINE = False


def test_unreadable_page_is_neutral_not_suspect():
    row = {"id": 1, "conference_name": "Annual Meeting", "event_type": "conference",
           "source_url": "https://example.org/e", "abstract_open": True,
           "description": "x" * 100}
    audit._OFFLINE = True
    try:
        a = audit.audit_row(row, "", None, {"society": "X"}, [], cache=None)
    finally:
        audit._OFFLINE = False
    by = {f.field: f for f in a.fields}
    assert by["abstract_status"].status == "NOT_APPLICABLE"
    assert not any(f.status == "SUSPECT" and "page" in f.reason.lower() for f in a.fields)
