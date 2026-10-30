import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
from repair_heuristic_city import decide, scan  # noqa: E402


def row(**k):
    base = dict(event_format="in-person", venue_name=None, conference_name="", region=None)
    base.update(k)
    return base


def test_online_null():
    assert decide(row(event_format="online", venue_name="London"), "London") == ("null", "online event")


def test_venue_keep():
    d, why = decide(row(venue_name="Royal College of Physicians, London"), "London")
    assert d == "keep" and "venue_name" in why


def test_name_keep():
    d, why = decide(row(conference_name="FAMUS/FUSIC Course, Reading"), "Reading")
    assert d == "keep" and "conference_name" in why


def test_foreign_venue_null():
    assert decide(row(venue_name="Centre de Congrès de Val d'Isère", conference_name="EANM"), "Reading") == (
        "null", "uncorroborated heuristic")


def test_region_keep():
    d, why = decide(row(region="London"), "London")
    assert d == "keep" and "region" in why


def test_whole_word():
    assert decide(row(venue_name="Spreading Hall"), "Reading")[0] == "null"


def _write(d, date, sid, patches):
    p = d / date
    p.mkdir(parents=True, exist_ok=True)
    (p / f"source-{sid}.json").write_text(json.dumps({"patches_applied": patches}))


def P(cid, field, after, method):
    return {"conference_id": cid, "conference_name": "x", "field": field,
            "value_before": None, "value_after": after, "method": method}


def test_scan(tmp_path):
    _write(tmp_path, "2026-10-01", 1, [
        P(1, "city", "Reading", "heuristic_known_city"),
        P(2, "city", "Sheffield", "heuristic_postcode_prefix"),
        P(3, "city", "London", "heuristic_postcode_prefix"),
        P(4, "venue_name", "Foo", "heuristic_known_city"),
    ])
    _write(tmp_path, "2026-10-05", 1, [P(1, "city", "London", "heuristic_known_city")])
    got = scan([tmp_path])
    assert set(got) == {1, 2}
    assert got[1] == ("London", "2026-10-05")
    assert got[2][0] == "Sheffield"


# ---- G: PATCH is compare-and-swap on the city that was read -----------------
class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body if body is not None else []

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 300:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def patch(self, url, **kw):
        self.calls.append((url, kw))
        return self.resp


def test_patch_carries_city_precondition():
    from repair_heuristic_city import apply_null
    c = _Client(_Resp(200, [{"id": 7}]))
    ok = apply_null(c, "https://x.supabase.co", {"apikey": "k"}, {"id": 7, "city": "Tunbridge Wells"})
    url, kw = c.calls[0]
    assert ok is True
    assert url == "https://x.supabase.co/rest/v1/conferences?id=eq.7&city=eq.Tunbridge%20Wells"
    assert kw["headers"]["Prefer"] == "return=representation"
    assert kw["json"] == {"city": None, "remediation_attempted_at": None}


def test_patch_empty_result_is_skipped_not_error(capsys):
    from repair_heuristic_city import apply_null
    c = _Client(_Resp(200, []))
    assert apply_null(c, "https://x", {}, {"id": 9, "city": "Reading"}) is False
    assert "row 9 changed since read, skipped" in capsys.readouterr().out


def test_patch_non_2xx_raises():
    import pytest
    from repair_heuristic_city import apply_null
    with pytest.raises(RuntimeError):
        apply_null(_Client(_Resp(500)), "https://x", {}, {"id": 1, "city": "Reading"})
