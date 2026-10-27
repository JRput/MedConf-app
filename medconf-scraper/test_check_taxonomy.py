"""Pure-function tests for check_taxonomy (no network)."""
from check_taxonomy import find_missing, long_codes, parse_taxonomy_keys

TS = '''
import x from 'y'
export const OTHER = {
  NOPE: { short: 'NOPE' },
}
export const SOCIETIES: Record<string, SocietyInfo> = {
  RCGP: { short: 'RCGP', name: 'Royal College', kind: 'royal-college', country: 'UK' },
  // COMMENTED: { short: 'COMMENTED', name: 'x' },
  'Resus Council UK': { short: 'Resus Council UK', name: 'Resus', kind: 'other', country: 'UK' },
  "Women's Society": { short: "Women's Society", name: 'W', kind: 'other', country: 'UK' },
  'Esc\\'d': { short: 'Esc\\'d', name: 'E', kind: 'other', country: 'UK' },
  NoShort: { name: 'no short field' },
}

export const AFTER = {
  TRAILING: { short: 'TRAILING', name: 't' },
}
'''


def test_parse_keys():
    assert parse_taxonomy_keys(TS) == {"RCGP", "Resus Council UK", "Women's Society", "Esc'd"}


def test_find_missing_filters():
    rows = [
        {"id": 5, "society": "NEW", "active": True},
        {"id": 2, "society": "ZZZ", "active": True},
        {"id": 3, "society": "OFF", "active": False},
        {"id": 4, "society": None, "active": True},
        {"id": 6, "society": "Community", "active": True},
        {"id": 7, "society": "RCGP", "active": True},
    ]
    assert find_missing(rows, {"RCGP"}) == [(2, "ZZZ"), (5, "NEW")]


def test_long_codes():
    rows = [
        {"id": 1, "society": "A" * 30, "active": True},
        {"id": 2, "society": "RCGP", "active": True},
        {"id": 3, "society": "B" * 30, "active": False},
    ]
    assert long_codes(rows) == [(1, "A" * 30)]


def test_missing_coverage_runs():
    from datetime import datetime, timezone
    import check_taxonomy as ct
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    rows = [
        {"id": 1, "active": True, "created_at": "2026-11-01T00:00:00Z", "source_name": "New", "base_url": "u1"},
        {"id": 2, "active": True, "created_at": "2026-11-01T00:00:00Z", "source_name": "Done", "base_url": "u2"},
        {"id": 3, "active": True, "created_at": "2026-11-01T00:00:00Z", "source_name": "NoBuild", "base_url": "u3"},
        {"id": 4, "active": True, "created_at": "2026-10-20T00:00:00Z", "source_name": "Old", "base_url": "u4"},
    ]
    docs = [{"source_id": 1, "source_row": {}}, {"source_id": 2, "coverage_run": {"exit_code": 0}},
            {"source_id": 4, "source_row": {}}]
    assert ct.missing_coverage_runs(rows, docs, now=now) == [(1, "New")]
    # grandfathered: registered before the required-from cutoff
    early = [dict(r, created_at="2026-10-26T00:00:00Z") for r in rows]
    assert ct.missing_coverage_runs(early, docs, now=datetime(2026, 10, 27, tzinfo=timezone.utc)) == []
