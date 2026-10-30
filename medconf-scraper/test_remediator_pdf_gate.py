"""Remediator document gate: site-wide PDFs never price an event or become its link."""
from remediator import learned_patterns
from remediator.pdf_text import find_fee_documents, document_gate, document_text_gate
from remediator.runner import _is_document_url

ROW27 = {"start_date": "2027-04-14", "conference_name": "X Annual Conference 2027",
         "source_url": "https://x.org/events/x-2027"}
ROW26 = {"start_date": "2026-04-14", "conference_name": "X Annual Conference 2026",
         "source_url": "https://x.org/events/x-2026"}

HTML = """
<a href="/docs/default-source/training/training/cost-of-training-2024.pdf">Cost of training</a>
<a href="/docs/Brochure%20membership%20updated%20Jan%202025.pdf">Membership brochure</a>
<a href="/events/x-2027/registration-fees-2027.pdf">Registration fees 2027 (PDF)</a>
"""


def test_find_fee_documents_only_event_document():
    out = find_fee_documents(HTML, "https://x.org/events/x-2027", row=ROW27)
    assert [u for u, _ in out] == ["https://x.org/events/x-2027/registration-fees-2027.pdf"]


def test_document_gate_prior_edition():
    url = "https://x.org/docs/aaos-2026-reg-rates.pdf"
    ok, why = document_gate(url, "Registration rates", ROW27)
    assert not ok and ("other_year" in why or "prior" in why)
    assert document_gate(url, "Registration rates", ROW26)[0] is True


def test_document_gate_negative_names():
    for n in ("fph-subscription-rates-2027.pdf", "Medicare-Physician-Fee-Schedule-Proposed-Rule.pdf",
              "ESHRE-2027-Registrations-report.pdf"):
        assert not document_gate("https://x.org/" + n, "", ROW27)[0], n


def test_document_text_gate():
    assert not document_text_gate("The total cost of sitting the MRCPsych examinations in 2023 ...", ROW27)[0]
    assert not document_text_gate("Registration fees 2023 Members £250", ROW27)[0]
    assert document_text_gate("X Annual Conference 2027 — Registration fees: Members £250", ROW27)[0]


def test_is_document_url():
    assert _is_document_url("https://a.org/x/y.pdf")
    assert _is_document_url("https://a.org/x/Y.PDF?x=1")
    assert _is_document_url("https://a.org/x/y.docx#p")
    assert not _is_document_url("https://a.org/events/x-2027/register")


def test_promoted_pdf_patterns_filtered(monkeypatch):
    def entry(name):
        return {"domain": "www.rcpsych.ac.uk", "field": "pricing", "promoted": True,
                "method": f"pdf:{name}", "hits": 5}
    data = {"patterns": {"a": entry("cost-of-training-2024.pdf"),
                         "b": entry("registration-fees-2027.pdf")}}
    monkeypatch.setattr(learned_patterns, "_load", lambda: data)
    got = learned_patterns.get_promoted_patterns("https://www.rcpsych.ac.uk/events/x", "pricing")
    assert [e["method"] for e in got] == ["pdf:registration-fees-2027.pdf"]
