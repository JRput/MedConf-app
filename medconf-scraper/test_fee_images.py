import base64
import struct
import zlib

from remediator.image_scan import fee_image_signal, scan_images, select_fee_images
from remediator.explorer import find_money_images, usable_vision_tiers
import remediator.explorer as ex
from vision import normalize_currency
from remediator.validators import validate_pricing_tiers

BASE = "https://www.example.org/event/x.html"


def _png(w=716, h=113, pad=7000):
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"\x00" * 10)) + chunk(b"junk", b"\x01" * pad))
    return "data:image/png;base64," + base64.b64encode(raw).decode()


DATA = _png()
KSUOG = f"<html><body><h1>Course</h1><p>Venue: Hyatt</p><p><strong>Registration</strong></p><p><a href='/r'>link</a></p><p><img src=\"{DATA}\" /></p></body></html>"


def test_data_uri_accepted_unchanged():
    out = select_fee_images(KSUOG, BASE)
    assert [c.src for c in out] == [DATA]
    assert out[0].width == 716 and out[0].is_data
    assert any(r.startswith("fee_heading_block") for r in out[0].rules)


def test_find_money_images_passes_data_uri_and_records_rule(monkeypatch):
    monkeypatch.setattr(ex, "_vision_images_sent", 0)
    trail = ex.AuditTrail()
    urls = find_money_images(KSUOG, BASE, strict=True, trail=trail)
    assert urls == [DATA]
    assert trail.image_selections[0]["rules"][0].startswith("fee_heading_block")
    assert "data-uri" in trail.image_selections[0]["image"]  # payload not logged


def test_heading_adjacent_selected_without_currency_text():
    html = '<h3>Registration fees</h3><img src="/img/table.jpg" width="600" height="300">'
    out = select_fee_images(html, BASE)
    assert [c.src for c in out] == ["https://www.example.org/img/table.jpg"]
    assert out[0].rules[0].startswith("fee_heading_block")


def test_non_fee_heading_breaks_block():
    html = '<h3>Registration fees</h3><p>x</p><h3>Speakers</h3><img src="/img/p.jpg" width="600" height="300">'
    assert select_fee_images(html, BASE, strict=True) == []


def test_strict_ignores_money_word_only_images():
    html = '<p>Register now, fees apply</p><img src="/img/promo.jpg" width="600" height="300">'
    assert select_fee_images(html, BASE, strict=True) == []
    assert select_fee_images(html, BASE)[0].rules == ["money_words_nearby"]


def test_size_filter_and_larger_first():
    html = ('<h3>Fees</h3><img src="/a-small.png" width="80" height="60">'
            '<img src="/b-mid.png" width="400" height="200"><img src="/c-big.png" width="900" height="700">')
    out = select_fee_images(html, BASE)
    assert [c.src.rsplit("/", 1)[1] for c in out] == ["c-big.png", "b-mid.png"]
    small = [c for c in scan_images(html, BASE) if "small" in c.src][0]
    assert small.skipped.startswith("too small")


def test_logo_skipped_even_under_fee_heading():
    html = '<h3>Registration</h3><img src="/assets/logo.png" width="600" height="300">'
    assert select_fee_images(html, BASE) == []
    assert fee_image_signal(html, BASE) is None


def test_audit_signal_needs_heading():
    assert fee_image_signal(KSUOG, BASE) is not None
    nohead = f"<html><body><p>Hello</p><img src=\"{DATA}\"></body></html>"
    assert fee_image_signal(nohead, BASE) is None


def test_audit_check_pricing_flags_image_fee(monkeypatch):
    from remediator import audit
    monkeypatch.setattr(audit, "_hydrated_registration_probe", lambda *a, **k: None)
    v = audit.check_pricing({"source_url": BASE}, "Registration", KSUOG, None, [])
    assert v.status == "MISSING" and "image" in v.reason.lower()
    v2 = audit.check_pricing({"source_url": BASE}, "Hello", "<p>Hello</p>", None, [])
    assert v2.status == "GENUINELY_ABSENT"


def test_currency_normalisation_and_validation():
    assert normalize_currency("usd") == "USD"
    assert normalize_currency("₩") == "KRW"
    assert normalize_currency("€") == "EUR"
    assert normalize_currency("unknown") is None and normalize_currency(None) is None
    ok = {"tier_label": "Delegate · Early", "price_gbp": 150000, "currency": "KRW"}
    assert validate_pricing_tiers([ok])
    assert not validate_pricing_tiers([{**ok, "currency": None}])
    assert usable_vision_tiers([ok, {**ok, "currency": None}]) == [ok]


def test_registration_link_picker():
    from remediator.explorer import find_registration_links
    base = "https://www.fluidacademy.org/ifad-2026/"
    html = (
        '<nav><a href="/ifad-2026-programme/">Programme</a>'
        '<a href="/ifad-2026-registration-2/"><span>Registration</span></a></nav>'
        '<a href="https://newsletters.example.com/signup">Register your interest</a>'
        '<a href="/newsletter">Register for newsletter</a>'
        '<a href="/ifad-2026/">Register</a>'
        '<a href="/ifad-2026-registration-2/#top">Registration</a>'
        '<a href="/shop/rates">Prices</a>'
    )
    out = find_registration_links(html, base)
    assert out[0] == ("https://www.fluidacademy.org/ifad-2026-registration-2/", "Registration")
    urls = [u for u, _ in out]
    assert len(urls) == len(set(urls))
    assert not any("example.com" in u or "newsletter" in u or u.rstrip("/") == base.rstrip("/") for u in urls)
    assert "https://www.fluidacademy.org/shop/rates" in urls


def test_two_hop_external_registration_subpage(monkeypatch):
    import remediator.explorer as ex
    landing = ('<html><a href="/programme">Programme</a><a href="/registration/">Registration</a>'
               '<a href="https://other.example.com/registration">Registration</a></html>')
    fees = "<html><body>Registration fees: Delegate €450 Student €200</body></html>"
    fetched = []

    class B:
        def exhausted(self): return False
        def fetch(self, url):
            fetched.append(url)
            return (fees, fees) if url.rstrip("/").endswith("/registration") else (None, None)
    trail = ex.AuditTrail()
    out = ex._follow_registration_subpages(landing, "https://essic2026.org/", B(), trail, limit=2)
    assert out is not None
    tiers, url, method = out
    assert url == "https://essic2026.org/registration/" and method == "text"
    assert {t["currency"] for t in tiers} == {"EUR"}
    assert all("other.example.com" not in u for u in fetched)
    assert any(n.startswith("external_subpage_followed") for n in trail.notes)
