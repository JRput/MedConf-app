from datetime import datetime, timezone, timedelta
from remediator.detector import order_gap_rows

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


def _r(i, days):
    ts = None if days is None else (NOW - timedelta(days=days)).isoformat()
    return ({"id": i, "remediation_attempted_at": ts}, ["pricing"])


def test_order():
    rows = [_r(1, 1), _r(2, 10), _r(3, None), _r(4, 30), _r(5, None), _r(6, 2)]
    out = [r["id"] for r, _ in order_gap_rows(rows, now=NOW)]
    # never-attempted by id, then oldest first, recent (<3d) last, none dropped
    assert out == [3, 5, 4, 2, 6, 1]
