"""Scraper call sites wired to money.py (ticket A1, 2026-10-27): nothing defaults to GBP,
every fee form is read at the layer that used to misread it."""
import ast
import glob
import os

import pytest

import database
import validator
import vision
from extractors import esmo, tribe_events as te, wordpress_generic as wg


# ── validator ───────────────────────────────────────────────────────────────────

def _conf(tiers, **kw):
    base = {"conference_name": "X", "source_url": "https://example.com/x", "pricing_tiers": tiers}
    base.update(kw)
    return validator.validate_conference(base)


def _tier(price, cur=None, label="Member"):
    t = {"tier_label": label, "price_gbp": price,
         "evidence_url": "https://e.org/x", "evidence_identity": "own_page"}
    if cur is not None:
        t["currency"] = cur
    return t


def test_validator_skips_tier_without_currency_unless_url_evidences_it():
    r = _conf([_tier(120)])
    assert r["data"]["pricing_tiers"] == [] and any("No currency" in w for w in r["warnings"])
    r = _conf([_tier(120)], source_url="https://www.rcgp.org.uk/events/x")
    assert [(t["price_gbp"], t["currency"]) for t in r["data"]["pricing_tiers"]] == [(120.0, "GBP")]


def test_validator_skips_unknown_currency_and_normalises_symbols():
    r = _conf([_tier(120, "XXX"), _tier(465, "S$", "Delegate")])
    assert [(t["tier_label"], t["currency"]) for t in r["data"]["pricing_tiers"]] == [("Delegate", "SGD")]
    assert any("Unknown currency" in w for w in r["warnings"])


def test_validator_per_currency_cap_and_low_price_warning():
    r = _conf([_tier(1_500_000, "JPY", "A"), _tier(60_000, "GBP", "B"), _tier(1.5, "EUR", "C")])
    kept = {t["tier_label"]: t["price_gbp"] for t in r["data"]["pricing_tiers"]}
    assert kept == {"A": 1_500_000.0, "C": 1.5}
    assert any("Suspiciously low" in w for w in r["warnings"]) and any("Implausible" in w for w in r["warnings"])


def test_validator_dedupe_is_per_currency():
    r = _conf([_tier(100, "GBP"), _tier(100, "EUR")])
    assert len(r["data"]["pricing_tiers"]) == 2


# ── database.insert_pricing_tiers ────────────────────────────────────────────────

class _FakeSupabase:
    def __init__(self):
        self.rows = None

    def table(self, name):
        assert name == "pricing_tiers"
        return self

    def insert(self, rows):
        self.rows = rows
        return self

    def execute(self):
        return None


def test_insert_pricing_tiers_refuses_missing_currency(monkeypatch):
    fake = _FakeSupabase()
    monkeypatch.setattr(database, "supabase", fake)
    database.insert_pricing_tiers(7, [_tier(10), _tier(20, "", "B"), _tier(30, "kr", "C"), _tier(40, "€", "D")])
    assert [(r["tier_label"], r["currency"]) for r in fake.rows] == [("D", "EUR")]
    fake.rows = None
    database.insert_pricing_tiers(7, [_tier(10)])
    assert fake.rows is None                                     # nothing to insert, nothing inserted


# ── tribe_events ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("line,expected", [
    ("Members: S$465", (465.0, "SGD", 9)),
    ("Delegate 1.500,00 €", (1500.0, "EUR", 9)),
    ("Fee £1,250.00", (1250.0, "GBP", 4)),
    ("Early A$250", (250.0, "AUD", 6)),
    ("Student 350 PLN", (350.0, "PLN", 8)),
])
def test_tribe_amount_in(line, expected):
    assert te._amount_in(line, "GBP") == expected


def test_tribe_kr_needs_extractor_context_and_never_defaults():
    assert te._amount_in("Fee kr 2,500", "GBP") is None
    assert te._amount_in("Fee kr 2,500", "SEK")[:2] == (2500.0, "SEK")
    assert te._amount_in("2027 edition", "GBP") is None


def test_tribe_cost_details_currency_and_decimal():
    e = {"cost_details": {"currency_symbol": "A$", "values": ["25,50", "1.200"]}}
    assert [(t["price_gbp"], t["currency"]) for t in te.tiers_from_cost_details(e, "GBP")] == [(25.5, "AUD"), (1200.0, "AUD")]
    assert te.tiers_from_cost_details({"cost_details": {"values": ["25"]}}, "") == []        # no currency anywhere


# ── wordpress_generic ───────────────────────────────────────────────────────────

def test_wordpress_fee_lines_read_any_currency_and_decimal_style():
    t = wg.fee_tiers_from_lines(["Registration fees", "Member", "€ 1.500,00", "Student"], "GBP")
    assert [(x["price_gbp"], x["currency"]) for x in t] == [(1500.0, "EUR")]
    t = wg.fee_tiers_from_lines(["Price A$200-A$350"], "GBP")
    assert [(x["price_gbp"], x["currency"]) for x in t] == [(200.0, "AUD"), (350.0, "AUD")]
    t = wg.fee_tiers_from_lines(["Fees", "From £350 + VAT"], "")
    assert [(x["price_gbp"], x["currency"]) for x in t] == [(350.0, "GBP")]


def test_wordpress_offers_skip_tiers_with_no_currency():
    ev = {"offers": [{"name": "Standard", "price": "1.200,00"}]}
    assert wg.tiers_from_offers(ev, "") == []
    ev = {"offers": [{"name": "Standard", "price": "1.200,00", "priceCurrency": "eur"}]}
    assert [(x["price_gbp"], x["currency"]) for x in wg.tiers_from_offers(ev, "")] == [(1200.0, "EUR")]


# ── esmo / vision / prompts ────────────────────────────────────────────────────────

def test_esmo_registration_text_reads_singapore_dollars():
    text = "Registration fees\nMember\tS$ 1,280\nStudent\tS$ 640\n"
    assert [(t["price_gbp"], t["currency"]) for t in esmo._pricing_from_registration_text(text)] == [(1280.0, "SGD"), (640.0, "SGD")]


def test_esmo_existing_symbols_unchanged():
    text = "Registration fees\nMember\t€ 360.00\nStudent\t€ 180.00\n"
    assert [(t["price_gbp"], t["currency"]) for t in esmo._pricing_from_registration_text(text)] == [(360.0, "EUR"), (180.0, "EUR")]


def test_vision_reexports_money_and_prompt_lists_the_symbol_table():
    import money
    assert vision.normalize_currency is money.normalize_currency
    assert "{SYMBOLS}" not in vision.PRICING_PROMPT
    for token in ("S$=SGD", "A$=AUD", "₩=KRW", "zł=PLN", "kr=SEK/NOK/DKK only if stated"):
        assert token in vision.PRICING_PROMPT


def test_llm_prompts_no_longer_require_a_gbp_amount():
    """The old prompts said 'if no GBP amount (£N) ...' and had no currency field; the
    new ones must forbid guessing GBP and put "currency" in the pricing_tiers schema."""
    import inspect
    import re
    import llm_agent
    from extractors import fallback
    for mod in (llm_agent, fallback):
        src = inspect.getsource(mod)
        assert "no GBP amount" not in src and "no GBP prices" not in src
        assert "never guess GBP" in src.replace("Never guess GBP", "never guess GBP")
        assert re.search(r'"pricing_tiers": \[\{\{[^\]]*"currency"', src), mod.__name__


# ── guard: a literal tier dict must name its currency ─────────────────────────────────

_EXTRACTOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extractors")


def _tier_builders_without_currency(tree):
    """Dict literals (spread or not), dict(...) calls, and x["price_gbp"] = ... assignments
    that name a price but whose builder never names a currency."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict):
            keys = [k.value if isinstance(k, ast.Constant) else None for k in n.keys]
            if "price_gbp" in keys and "currency" not in keys:
                out.append(n.lineno)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "dict":
            kw = [k.arg for k in n.keywords]
            if "price_gbp" in kw and "currency" not in kw:
                out.append(n.lineno)
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        subs = [(t.slice.value, n.lineno) for n in ast.walk(fn) if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)]
        names = {k for k, _ in subs}
        out += [ln for k, ln in subs if k == "price_gbp" and "currency" not in names]
    return out


def test_no_extractor_builds_a_tier_without_a_currency_key():
    files = sorted(glob.glob(os.path.join(_EXTRACTOR_DIR, "*.py")))
    assert len(files) > 50, "extractor glob is empty (cwd-relative?)"       # the old glob passed on []
    offenders = [f"{os.path.basename(f)}:{ln}" for f in files
                 for ln in _tier_builders_without_currency(ast.parse(open(f, encoding="utf-8").read()))]
    assert offenders == []


def _lines(src):
    return sorted(_tier_builders_without_currency(ast.parse(src)))


def test_tier_builder_guard_sees_spread_dict_call_and_subscript_forms():
    # each form alone, with its exact line: a guard that drops one form, or that
    # counts another form twice, cannot reach the right answer
    assert _lines("def f(t):\n    return {**t, 'price_gbp': 1}\n") == [2]
    assert _lines("def f():\n    return dict(price_gbp=2, tier_label='x')\n") == [2]
    assert _lines("def f(t):\n    t['price_gbp'] = 3\n    return t\n") == [2]
    assert _lines("def f(t):\n    a = {**t, 'price_gbp': 1}\n    b = dict(price_gbp=2)\n    t['price_gbp'] = 3\n") == [2, 3, 4]
    # compliant forms stay clean, each alone
    assert _lines("def f(t):\n    return {**t, 'price_gbp': 1, 'currency': 'EUR'}\n") == []
    assert _lines("def f():\n    return dict(price_gbp=2, currency='USD')\n") == []
    assert _lines("def f(t):\n    t['price_gbp'] = 3\n    t['currency'] = 'GBP'\n") == []
    # scoping: a currency named in ANOTHER function does not excuse this builder
    assert _lines("def g(t):\n    t['currency'] = 'GBP'\ndef f(t):\n    t['price_gbp'] = 3\n") == [4]
