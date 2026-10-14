"""ARRS events table: rows carry extra attributes since 2026-10-14."""
from extractors.arrs import _ROW_RE

ROWS = ('<table><tr><th>Event</th></tr><tbody>'
        '<tr class="type-ajr" data-end="2026-10-14"><td class="arrs-evt-name">AJR Live Webinar</td></tr>'
        '<tr class="type-longitudinal" data-end="2026-10-15"><td class="arrs-evt-name">Course</td></tr>'
        '<tr class="type-annual"><td class="arrs-evt-name">ARRS 2027</td></tr></tbody></table>')


def test_rows_with_and_without_attributes_match():
    assert [k for k, _ in _ROW_RE.findall(ROWS)] == ["ajr", "longitudinal", "annual"]
