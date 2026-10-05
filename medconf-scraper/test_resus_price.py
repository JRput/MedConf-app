from extractors.resus import ResusExtractor as R

def test_blsi():
    t = R._direct_price("How much? The BLSi course costs £80 inc VAT. To purchase visit the RCUK Learning Portal .")
    assert [(x["tier_label"], x["price_gbp"]) for x in t] == [("Course fee (incl. VAT)", 80.0)]

def test_anaphylaxis():
    t = R._direct_price("visit the RCUK Learning Portal . The course costs £35 (Incl. VAT). Volume prices from £1.75 per licence")
    assert t[0]["price_gbp"] == 35.0

def test_centre_charge_ignored():
    assert R._direct_price("Course fees are decided locally; RCUK only charges the Course Centre £31.57 per Candidate registration and £35.89 per ALS manual.") == []
