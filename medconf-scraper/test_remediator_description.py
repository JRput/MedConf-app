"""Description fixer must never store site chrome (AUGIS/ESHRE nav-leak, 2026-10-22)."""
from remediator.fixers.description import fix_description, _is_clean

AUGIS_HTML = """<html><head><title>Yorkshire Regional Meeting</title></head><body>
<div class="breadcrumb">AUGIS &gt; Events &gt; Event Booking</div>
<ul class="menu"><li>Login</li><li>Become a Member</li><li>Contact Us</li><li>Home</li>
<li>About</li><li>What we do</li><li>Sustainability &amp; Accessibility</li></ul></body></html>"""
AUGIS_TEXT = ("AUGIS > Events > Event Booking Login Become a Member Contact Us Home About "
              "What we do Sustainability & Accessibility News Events Education Research")
ESHRE_HTML = """<html><body><div id="cookie-banner"><p>ESHRE 2027 Cookies ESHRE uses cookies
to improve your browsing experience on its website, as defined in the privacy policy.</p></div>
</body></html>"""
ESHRE_TEXT = ("ESHRE 2027 Cookies ESHRE ® uses cookies to improve your browsing experience "
              "on its website, as defined in the Cookie Policy. Accept all cookies")
GOOD_HTML = """<html><head><meta name="description" content="Short."></head><body>
<nav><a>Home</a> <a>Login</a></nav><main><h1>Spring Urology Meeting</h1>
<p>The Spring Urology Meeting brings together surgeons and trainees to discuss advances in
stone management, reconstructive surgery and robotic techniques over two days in Leeds.</p>
</main><footer>Privacy Terms</footer></body></html>"""


def _no_llm(_p):
    return None


def test_augis_chrome_rejected():
    row = {"id": 3438, "conference_name": "Yorkshire Regional Meeting", "_page_html": AUGIS_HTML}
    assert fix_description(row, AUGIS_TEXT, _no_llm) == (None, None)


def test_eshre_cookie_rejected():
    row = {"id": 3429, "conference_name": "ESHRE 2027", "_page_html": ESHRE_HTML}
    assert fix_description(row, ESHRE_TEXT, _no_llm) == (None, None)


def test_llm_output_revalidated():
    bad = "AUGIS > Events > Event Booking Login Become a Member Contact Us Home About What we do"
    row = {"id": 1, "conference_name": "X", "_page_html": GOOD_HTML}
    val, method = fix_description(row, "", lambda p: bad)
    assert method == "heuristic_overview" and "Spring Urology Meeting brings" in val


def test_llm_gets_only_clean_text():
    seen = []
    row = {"id": 1, "conference_name": "X", "_page_html": GOOD_HTML}
    fix_description(row, "Login Become a Member Contact Us", lambda p: seen.append(p))
    assert seen and "Become a Member" not in seen[0] and "Spring Urology" in seen[0]


def test_real_paragraph_returned():
    row = {"id": 1, "conference_name": "Spring Urology Meeting", "_page_html": GOOD_HTML}
    val, method = fix_description(row, "", _no_llm)
    assert val and val.startswith("The Spring Urology Meeting") and method == "heuristic_overview"


def test_plain_text_paragraph():
    txt = ("Home Login\nThis two day course covers the assessment and management of acute "
           "kidney injury for trainees and consultants, with practical case discussions.")
    val, _ = fix_description({"id": 2}, txt, _no_llm)
    assert val and val.startswith("This two day course")


def test_is_clean_rejects():
    assert not _is_clean("Home About Us News Events Education Research Training Contact Members Area Links Page")
    assert not _is_clean("Short text here.")
    assert not _is_clean("We value your privacy and this website stores data on your device to help us improve it.")
