from datetime import datetime, timezone

import purge_notifications as pn


class FakeQuery:
    def __init__(self, client, table):
        self.c, self.table, self.op = client, table, "select"

    def select(self, *a, **k):
        self.op = "select"; return self

    def delete(self):
        self.op = "delete"; return self

    def lt(self, col, val):
        self.c.filters.append(("lt", col, val)); return self

    def in_(self, col, vals):
        self.c.filters.append(("in", col, list(vals))); return self

    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def execute(self):
        if self.op == "delete":
            self.c.deletes += 1
            return type("R", (), {"data": []})()
        data = self.c.batches.pop(0) if self.c.batches else []
        return type("R", (), {"data": data, "count": 5})()


class FakeClient:
    def __init__(self, batches):
        self.batches, self.deletes, self.filters = list(batches), 0, []

    def table(self, name):
        assert name == "notifications"
        return FakeQuery(self, name)


def test_cutoff_is_12_months_utc():
    now = datetime(2026, 10, 31, 8, 0, tzinfo=timezone.utc)
    assert pn.cutoff_iso(now).startswith("2025-10-31T08:00:00")
    assert pn.cutoff_iso(now).endswith("+00:00")


def test_cutoff_clamps_leap_day():
    now = datetime(2028, 2, 29, tzinfo=timezone.utc)
    assert pn.cutoff_iso(now).startswith("2027-02-28")


def test_cutoff_january_wraps_year():
    now = datetime(2026, 1, 15, tzinfo=timezone.utc)
    assert pn.cutoff_iso(now).startswith("2025-01-15")


def test_batch_loop_two_batches_then_empty():
    c = FakeClient([[{"id": "a"}, {"id": "b"}], [{"id": "c"}], []])
    assert pn.purge(c, "2025-01-01T00:00:00+00:00") == 3
    assert c.deletes == 2
    assert ("in", "id", ["a", "b"]) in c.filters and ("in", "id", ["c"]) in c.filters


def test_dry_run_makes_no_delete():
    c = FakeClient([[{"id": "a"}]])
    assert pn.purge(c, "2025-01-01T00:00:00+00:00", dry_run=True) == 5
    assert c.deletes == 0
