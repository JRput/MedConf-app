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
