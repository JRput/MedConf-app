"""PDF/DOCX fee-document following in the explorer (no network)."""
import io
import zipfile

from remediator import explorer as ex
from remediator.pdf_text import find_fee_documents, pdf_to_text, docx_to_text


def make_pdf(lines):
    """Minimal one-page text PDF built by hand (pypdf writer has no text API)."""
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = "BT /F1 12 Tf 14 TL 50 750 Td " + " ".join(f"({esc(l)}) Tj T*" for l in lines) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def make_docx(rows):
    body = "".join(
        "<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in r) + "</w:tr>"
        for r in rows)
    xml = f'<?xml version="1.0"?><w:document xmlns:w="x"><w:body><w:tbl>{body}</w:tbl></w:body></w:document>'
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("word/document.xml", xml)
    return b.getvalue()


FEES = ["Registration Fees (USD)", "Member 450", "Non-member 650", "Trainee 250", "Page 2"]


def test_pdf_text_roundtrip():
    assert "Non-member 650" in pdf_to_text(make_pdf(FEES))


def test_pdf_plain_number_tiers():
    trail = ex.AuditTrail()
    tiers = ex._tiers_from_document_text(pdf_to_text(make_pdf(FEES)), trail)
    got = {(t["tier_label"].split(" · ")[-1], t["price_gbp"], t["currency"]) for t in tiers}
    assert got == {("Member", 450.0, "USD"), ("Non-member", 650.0, "USD"), ("Trainee", 250.0, "USD")}


def test_year_and_no_currency_dropped():
    trail = ex.AuditTrail()
    assert ex._tiers_from_document_text("Registration fees\nMember 450\nNon-member 650\n", trail) == []
    t = ex._tiers_from_document_text("Fees (EUR)\nCongress 2026\nStudent 90\n", trail)
    assert [x["price_gbp"] for x in t] == [90.0]


def test_symbol_lines_use_text_sweep():
    t = ex._tiers_from_document_text("Early bird £200\nStandard £300\n", ex.AuditTrail())
    assert {x["price_gbp"] for x in t} == {200.0, 300.0}


def test_docx_text_and_tiers():
    text = docx_to_text(make_docx([["Delegate type", "Fee (EUR)"], ["Member", "300"], ["Student", "120"]]))
    t = ex._tiers_from_document_text(text, ex.AuditTrail())
    assert {(x["price_gbp"], x["currency"]) for x in t} == {(300.0, "EUR"), (120.0, "EUR")}


def test_cap_40():
    lines = ["Fees (USD)"] + [f"Category {chr(65+i%26)}{chr(97+i//26)} {100+i}" for i in range(80)]
    assert len(ex._tiers_from_document_text("\n".join(lines), ex.AuditTrail())) <= 40


def test_find_fee_documents_filters():
    html = ('<a href="/docs/Registration-Brochure.pdf">Brochure</a>'
            '<a href="/x/Endorsement-Application.pdf">Registration fee for endorsement</a>'
            '<a href="/programme.pdf">Programme</a><a href="/fees.docx">Fees</a>')
    got = [u for u, _ in find_fee_documents(html, "https://e.org/p")]
    assert got == ["https://e.org/docs/Registration-Brochure.pdf", "https://e.org/fees.docx"]


def test_follow_document_records_trail_and_one_per_event(monkeypatch):
    pdf = make_pdf(FEES)
    calls = []
    from remediator import pdf_text
    monkeypatch.setattr(ex, "_fetch_document_text",
                        lambda u, tr: calls.append(u) or pdf_text.pdf_to_text(pdf))
    html = '<a href="/a/fees.pdf">Fees</a><a href="/b/brochure.pdf">Brochure</a>'
    trail, budget = ex.AuditTrail(), ex.ExploreBudget()
    tiers, url, method = ex._follow_fee_document(html, "https://e.org/", budget, trail)
    assert method == "pdf:fees.pdf" and len(tiers) == 3
    assert any(n == f"pdf_followed: {url}" for n in trail.notes)
    assert ex._follow_fee_document(html, "https://e.org/", budget, trail) is None
    assert calls == [url]


def test_scanned_pdf_noted(monkeypatch):
    monkeypatch.setattr(ex, "_fetch_document_text", lambda u, tr: "")
    trail = ex.AuditTrail()
    r = ex._follow_fee_document('<a href="/f.pdf">Fees</a>', "https://e.org/", ex.ExploreBudget(), trail)
    assert r is None and any("no_text_layer" in n for n in trail.notes)


def test_vat_suffix_and_multiline_label():
    text = ("Registration fees for healthcare professionals working within the NHS\n"
            "Consultant: £40 + VAT\nResident Doctor, Nurse, AHP: £30 + VAT\n")
    t = ex._tiers_from_document_text(text, ex.AuditTrail())
    assert {(x["tier_label"], x["price_gbp"]) for x in t} == {
        ("Consultant", 40.0), ("Resident Doctor, Nurse, AHP", 30.0)}
