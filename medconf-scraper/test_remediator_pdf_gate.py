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


# ---- FV1b ----
def test_path_segments_checked():
    for u, a in (("https://x.org/membership/fees.pdf", "Fees"),
                 ("https://x.org/membership/rates.pdf", "Rates"),
                 ("https://x.org/about/brochure.pdf", "Brochure")):
        if "about" in u:
            continue  # 'about' is not negative; brochure alone is a fee word
        assert not document_gate(u, a, ROW27)[0], u
    assert not document_gate("https://x.org/training/fees.pdf", "Fees", ROW27)[0]


def test_membership_text_gate():
    assert not document_text_gate("Membership rates 2027 — Full member £180, Associate £90", ROW27)[0]
    assert not document_text_gate("Annual membership 2027 Full £180", ROW27)[0]


def test_rejected_doc_does_not_latch(monkeypatch):
    from remediator import explorer

    class B:
        fetches = 0
        def exhausted(self): return False

    class T:
        def __init__(self): self.notes = []; self.total_text_chars = 0

    texts = {"https://x.org/events/x-2027/fees-a-2027.pdf": "Membership rates 2027 — Full member £180 padding padding padding",
             "https://x.org/events/x-2027/fees-b-2027.pdf": "X Annual Conference 2027 Registration fees padding padding padding"}
    monkeypatch.setattr(explorer, "_fetch_document_text", lambda u, t: texts[u])
    monkeypatch.setattr(explorer, "_tiers_from_document_text",
                        lambda text, t: [{"tier_label": "m", "price_gbp": 1}] if "Registration" in text else [])
    html = ('<a href="/events/x-2027/fees-a-2027.pdf">Registration fees</a>'
            '<a href="/events/x-2027/fees-b-2027.pdf">Registration fees</a>')
    tr = T()
    res = explorer._follow_fee_document(html, "https://x.org/events/x-2027", B(), tr, row=ROW27)
    assert res and res[1].endswith("fees-b-2027.pdf")
    assert any(n.startswith("pdf_rejected:") for n in tr.notes)
    assert not any("fees-a" in n and n.startswith("pdf_followed") for n in tr.notes)


def test_legit_names_pass():
    for n, a in (("Registration-fees-and-training-day-2027.pdf", ""),
                 ("registration-fees-2027.pdf", "Download the fees (PDF)"),
                 ("Course-fees-training-courses-2027.pdf", ""),
                 ("Reporting-and-registration-fees-2027.pdf", "")):
        assert document_gate("https://x.org/events/" + n, a, ROW27)[0], n
    # a negative ANCHOR is the site telling us what the document is: never overridden (fail-closed)
    assert not document_gate("https://x.org/events/registration-fees-2027.pdf", "Download the fee report", ROW27)[0]


def test_override_not_for_hard_or_old():
    assert not document_gate("https://x.org/cost-of-training-2024.pdf", "", ROW27)[0]
    assert not document_gate("https://x.org/membership-rates-august-2026.pdf", "", ROW26)[0]
    assert not document_gate("https://x.org/exam-fees-2027.pdf", "", ROW27)[0]


def test_more_document_suffixes():
    for u in ("a/b.xls", "a/b.PPT", "a/b.odt?x=1", "a/b.rtf"):
        assert _is_document_url("https://a.org/" + u)



# --- foreman follow-up after the re-check (2026-10-30): the override must reach production ---
def test_find_fee_documents_lets_the_override_through_but_not_baseline_negatives():
    from remediator.pdf_text import find_fee_documents, document_gate
    row = {"conference_name": "X Annual Conference 2027", "start_date": "2027-04-14", "source_url": "https://x.org/events/x-2027/"}
    links = [
        ("/docs/Registration-fees-and-training-day-2027.pdf", "Fees"),
        ("/docs/Course-fees-training-courses-2027.pdf", "Course fees"),
        ("/docs/Exhibitor-rates-2027.pdf", "Exhibitor rates"),
        ("/docs/Sponsorship-registration-2027.pdf", "Sponsorship"),
        ("/docs/Abstract-fees-2027.pdf", "Abstract fees"),
        ("/docs/registration-fees-2027.pdf", "Registration fees 2027 (PDF)"),
    ]
    html = "".join(f'<a href="{h}">{a}</a>' for h, a in links)
    got = [u.rsplit("/", 1)[-1] for u, _ in find_fee_documents(html, "https://x.org/events/x-2027/", limit=6, row=row)]
    assert got == ["Registration-fees-and-training-day-2027.pdf", "Course-fees-training-courses-2027.pdf", "registration-fees-2027.pdf"]
    for bad in ("Exhibitor-rates-2027.pdf", "Sponsorship-registration-2027.pdf", "Abstract-fees-2027.pdf",
                "Accommodation-rates-2027.pdf", "Cancellation-fees-2027.pdf", "Policy-fees-2027.pdf"):
        assert document_gate(f"https://x.org/docs/{bad}", "", row)[0] is False, bad


def test_text_gate_accepts_ordinary_member_fees_wording_but_not_membership_rates():
    from remediator.pdf_text import document_text_gate
    row = {"conference_name": "X Annual Conference 2027", "start_date": "2027-04-14"}
    assert document_text_gate("X Annual Conference 2027 Registration fees. Member fees: \u00a3250, Non-member \u00a3350", row)[0] is True
    assert document_text_gate("Membership rates 2027 \u2014 Full member \u00a3180, Associate \u00a390", row)[0] is False



def test_override_never_admits_training_cost_documents_or_negative_anchors():
    """Final re-check (2026-10-30): the override must not reopen the incident's own signature."""
    from remediator.pdf_text import find_fee_documents, document_text_gate
    row = {"conference_name": "X Annual Conference 2027", "start_date": "2027-04-14", "source_url": "https://x.org/e/x-2027/"}
    links = [
        ("/e/Cost-of-training-fees-2027.pdf", ""),
        ("/e/registration-2027.pdf", "Training costs report"),
        ("/e/training-fees-2027.pdf", "Fees"),
        ("/e/Specialty-training-rates-2027.pdf", ""),
        ("/e/Curriculum-fees-2027.pdf", ""),
        ("/e/Trainee-handbook-fees-2027.pdf", ""),
        ("/e/Minutes-fees-2027.pdf", ""),
        ("/e/Newsletter-registration-2027.pdf", ""),
        ("/e/Registration-fees-and-training-day-2027.pdf", "Fees"),
        ("/e/registration-fees-2027.pdf", "Registration fees"),
    ]
    html = "".join(f'<a href="{h}">{a}</a>' for h, a in links)
    got = [u.rsplit("/", 1)[-1] for u, _ in find_fee_documents(html, "https://x.org/e/x-2027/", limit=10, row=row)]
    assert got == ["Registration-fees-and-training-day-2027.pdf", "registration-fees-2027.pdf"], got
    assert document_text_gate("Training fees 2027/28. Core trainee \u00a3450. Higher specialty trainee \u00a3600.", row)[0] is False
