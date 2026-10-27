"""Offline tests for coverage_report.py (synthetic rows, no network)."""
from datetime import datetime, timezone
import coverage_report as cr

NOW = datetime(2026, 10, 27, tzinfo=timezone.utc)


def conf(i, sid, **kw):
    d = {"id": i, "source_id": sid, "event_type": "conference", "event_format": "in_person",
         "venue_name": "V", "city": "C", "abstract_deadline": "2026-12-01"}
    d.update(kw)
    return d


def test_metrics_and_not_applicable():
    srcs = [{"id": 1, "source_name": "A", "society": "A"}]
    confs = [
        conf(1, 1),
        conf(2, 1, event_format="online", venue_name=None, city=None),       # online: excluded from venue/city
        conf(3, 1, event_type="course", abstract_deadline=None),              # course: excluded from abstracts
        conf(4, 1, venue_name=None, abstract_deadline=None),                  # gaps
        conf(5, 1, is_on_demand=True, abstract_deadline=None),                # on-demand: no abstract denom
        conf(6, 99),                                                          # other source ignored
    ]
    r = cr.compute_coverage(srcs, confs, {1, 2})["sources"]["1"]
    assert r["events"] == 5
    assert r["fees_pct"] == 40.0
    assert r["abstracts_n"] == 3 and r["abstracts_pct"] == 66.7   # c1 ok, c2 ok, c4 missing
    assert r["location_n"] == 4 and r["venue_pct"] == 75.0 and r["city_pct"] == 100.0


def test_note_counts_and_empty_denominator():
    srcs = [{"id": 1}]
    r = cr.compute_coverage(srcs, [conf(1, 1, abstract_deadline=None, abstract_deadline_note="closed",
                                        event_format="online")], set())["sources"]["1"]
    assert r["abstracts_pct"] == 100.0 and r["venue_pct"] is None


def _cur(events, **m):
    e = {"events": events, "name": "S", "fees_pct": 80.0, "abstracts_pct": 80.0, "venue_pct": 80.0, "city_pct": 80.0}
    e.update(m)
    return {"sources": {"1": e}}


def test_regression_threshold():
    base = _cur(30)
    prev_bad = _cur(30, fees_pct=60.0)
    assert cr.compare(base, _cur(30, fees_pct=70.0), [], prev_bad) == []         # exactly 10pp: ok
    assert len(cr.compare(base, _cur(30, fees_pct=69.9), [], prev_bad)) == 1     # 2 consecutive reports
    assert cr.compare(base, _cur(30, venue_pct=None), [], prev_bad) == []        # n/a ignored
    assert cr.compare(None, _cur(30, fees_pct=0.0), [], prev_bad) == []          # no baseline
    assert cr.compare(base, _cur(30, fees_pct=95.0), [], prev_bad) == []         # improvement


def test_single_day_dip_and_first_run_are_not_red():
    base = _cur(30)
    bad = _cur(30, fees_pct=50.0)
    probs, adv = cr.evaluate(base, bad, [], None)                                # no previous report
    assert probs == [] and len(adv) == 1
    probs, adv = cr.evaluate(base, bad, [], _cur(30, fees_pct=79.0))             # yesterday was fine
    assert probs == [] and "first day" in adv[0]
    probs, _ = cr.evaluate(base, bad, [], _cur(30, fees_pct=55.0))               # two bad days
    assert len(probs) == 1


def test_small_sources_are_advisory_only():
    base = _cur(20)
    probs, adv = cr.evaluate(base, _cur(20, fees_pct=0.0), [], _cur(20, fees_pct=0.0))
    assert probs == [] and len(adv) == 1 and "advisory" in adv[0]
    assert cr.evaluate(base, _cur(9, fees_pct=0.0), [], None)[0] == []


def test_load_previous_picks_latest_earlier_report(tmp_path):
    for d in ("2026-10-24", "2026-10-26", "2026-10-27", "baseline"):
        (tmp_path / f"{d}.json").write_text('{"date": "%s"}' % d)
    assert cr.load_previous(tmp_path, "2026-10-27") == {"date": "2026-10-26"}
    assert cr.load_previous(tmp_path, "2026-10-24") is None


def test_transport_error_exits_zero_with_skip_line(monkeypatch, capsys, tmp_path):
    import sys, types
    monkeypatch.setenv("SUPABASE_URL", "http://x"); monkeypatch.setenv("SUPABASE_KEY", "k")
    fake = types.ModuleType("supabase")
    def boom(*a, **k): raise ConnectionError("dns down")
    fake.create_client = boom
    monkeypatch.setitem(sys.modules, "supabase", fake)
    monkeypatch.setattr(sys, "argv", ["coverage_report.py", "--out-dir", str(tmp_path)])
    assert cr.main() == 0
    assert "coverage check skipped" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_recent_source_without_entry():
    srcs = [{"id": 1, "created_at": "2026-10-25T10:00:00+00:00"},
            {"id": 2, "created_at": "2026-09-01T10:00:00Z"},
            {"id": 3, "created_at": None}]
    assert cr.recent_source_ids(srcs, NOW) == [1]
    cur = {"sources": {"1": {"events": 0}, "2": {"events": 0}}}
    assert len(cr.compare(None, cur, [1])) == 1
    assert cr.compare(None, {"sources": {"1": {"events": 3}}}, [1]) == []
    assert len(cr.compare(None, {"sources": {}}, [1])) == 1


def test_markdown_renders():
    cur = cr.compute_coverage([{"id": 1, "source_name": "A"}], [conf(1, 1)], {1})
    md = cr.render_markdown(cur, ["x"], "2026-10-27")
    assert "| 1 | A | 1 | 100% |" in md and "- x" in md


def test_load_previous_ignores_baseline_and_today_and_future(tmp_path):
    """Restored cache = dated files only; baseline.json, today and later days never count."""
    import json
    for n, d in (("2026-10-25", "old"), ("2026-10-26", "yesterday"), ("2026-10-27", "today"),
                 ("2026-10-28", "future"), ("baseline", "baseline")):
        (tmp_path / f"{n}.json").write_text(json.dumps({"date": d}))
    assert cr.load_previous(tmp_path, "2026-10-27") == {"date": "yesterday"}
