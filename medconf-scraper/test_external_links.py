from remediator.explorer import find_external_event_links

BASE = "https://b-s-h.org.uk/education/conference-and-events/events/glasgow-surgical-forum-2026"

BSH = """
<html><body>
<nav><ul><li><a href="https://partner.example.org/events">here</a> Book events</li></ul></nav>
<main><h1>Glasgow Surgical Forum 2026</h1>
<p>Further details and registration can be found
<a href="https://rcpsg.ac.uk/education/glasgow-surgical-forum">here</a>.</p>
<p>Click <a href="https://unrelated.example.com/x">here</a> to see our cat pictures.</p>
<a href="https://facebook.com/bsh">here</a>
</main></body></html>
"""


def test_generic_here_in_registration_sentence_qualifies():
    out = find_external_event_links(BSH, BASE)
    urls = [u for u, _ in out]
    assert "https://rcpsg.ac.uk/education/glasgow-surgical-forum" in urls


def test_unrelated_and_nav_here_do_not_qualify():
    urls = [u for u, _ in find_external_event_links(BSH, BASE)]
    assert "https://partner.example.org/events" not in urls  # inside <nav>
    assert "https://unrelated.example.com/x" not in urls     # no registration context
    assert all("facebook.com" not in u for u in urls)        # junk host


def test_explicit_register_wins_priority():
    html = BSH.replace("</main>", '<a href="https://tickets.example.com/e">Register now</a></main>')
    out = find_external_event_links(html, BASE)
    assert out[0][0] == "https://tickets.example.com/e"
    assert out[1][0] == "https://rcpsg.ac.uk/education/glasgow-surgical-forum"


def test_bare_url_and_domain_anchor():
    html = ('<p>Booking is via <a href="https://www.rcpsg.ac.uk/e">www.rcpsg.ac.uk</a>.</p>')
    assert find_external_event_links(html, BASE)[0][0] == "https://www.rcpsg.ac.uk/e"
