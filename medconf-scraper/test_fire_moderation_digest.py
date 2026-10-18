import fire_moderation_digest as d


class Resp:
    def __init__(self, data=None, count=None):
        self.data, self.count = data, count


class Q:
    def __init__(self, db, table):
        self.db, self.table, self.op, self.filters, self.row = db, table, "select", {}, None

    def select(self, *a, **k): self.op = "select"; return self
    def delete(self): self.op = "delete"; return self
    def insert(self, row): self.op = "insert"; self.row = row; return self
    def eq(self, k, v): self.filters[k] = v; return self
    def in_(self, k, v): self.filters[k + "__in"] = v; return self
    def is_(self, k, v): self.filters[k + "__is"] = v; return self

    def execute(self):
        if self.op == "delete":
            self.db.deletes.append((self.table, self.filters))
            return Resp([])
        if self.op == "insert":
            self.db.inserts.append((self.table, self.row))
            return Resp([self.row])
        if self.table == "user_profiles":
            return Resp([{"id": a} for a in self.db.admins])
        rows = self.db.rows
        for k, v in self.filters.items():
            if k.endswith("__in"):
                rows = [r for r in rows if r["status"] in v]
            elif not k.endswith("__is"):
                rows = [r for r in rows if r.get(k) == v]
        return Resp(rows, count=len(rows))


class Rpc:
    def __init__(self, db, name): self.db, self.name = db, name
    def execute(self): self.db.rpcs.append(self.name); return Resp(2)


class FakeDB:
    def __init__(self, rows=(), admins=()):
        self.rows, self.admins = list(rows), list(admins)
        self.deletes, self.inserts, self.rpcs = [], [], []

    def table(self, name): return Q(self, name)
    def rpc(self, name): return Rpc(self, name)


def rows(n):
    return [
        {"status": "pending", "kind": "new_event" if i == 0 else "add_info", "enrichment_status": "fetched" if i else "waiting"}
        for i in range(n)
    ]


def test_zero_pending_no_notifications(capsys):
    db = FakeDB(rows(0), ["a1"])
    out = d.run(db)
    assert db.rpcs == ["expire_stale_contributions"]
    assert db.inserts == [] and db.deletes == []
    assert out["pending"] == 0


def test_three_pending_two_admins(capsys):
    db = FakeDB(rows(3), ["a1", "a2"])
    d.run(db)
    assert len(db.deletes) == 2 and len(db.inserts) == 2
    for t, r in db.inserts:
        assert t == "notifications" and r["type"] == "moderation"
        assert r["title"] == "3 contribution(s) awaiting review"
        assert r["conference_id"] is None
    assert all(f["type"] == "moderation" and f["read_at__is"] == "null" for _, f in db.deletes)


def test_dry_run_writes_nothing(capsys):
    db = FakeDB(rows(3), ["a1", "a2"])
    d.run(db, dry_run=True)
    assert db.rpcs == [] and db.inserts == [] and db.deletes == []
    assert "would expire" in capsys.readouterr().out.lower()


def test_email_line(monkeypatch, capsys):
    monkeypatch.setenv("MODERATION_NOTIFY_EMAIL", "mod@example.org")
    d.run(FakeDB(rows(3), ["a1"]))
    assert "EMAIL (not sent — no provider configured) to mod@example.org: 3 contribution(s) awaiting review" in capsys.readouterr().out
