"""Classify active events whose stored pricing tiers are ALL zero (rendered "Free").

Dry-run (default): fetch pages, classify WRONG_FREE / LEGIT_FREE / UNKNOWN,
write reports/pricing/zero_tiers_<date>.{json,md}. Never writes to the DB.

--apply --from <dry-run json>: for the WRONG_FREE ids in that file only,
delete pricing_tiers, null listing_hash + remediation_attempted_at. Refuses
unless the file is today's dry-run JSON.

Run from medconf-scraper/:  ./.venv/bin/python -m tools.audit_zero_tiers
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent          # medconf-scraper/
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from remediator.audit import price_text_signal  # noqa: E402
from remediator.explorer import fetch_page_text_and_html  # noqa: E402
from remediator.fixers.pricing import _FREE_RE  # noqa: E402  (strict free phrases)

# Positive currency amounts only: not glued to code/identifier chars ("$8", "$4de").
AMOUNT_RE = re.compile(r"(?<![\w\"'\[\$])[£€$]\s?(\d[\d,]*(?:\.\d+)?)(?![\w])")
NON_FEE_CTX_RE = re.compile(r"deposit|refundable|penalt|cancellation|no-show|do not attend", re.I)
PAGE = 1000
MIN_INTERVAL_S = 1.0  # per host


def _env():
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("SUPABASE_URL / SUPABASE_KEY missing (medconf-scraper/.env)")
    return url.rstrip("/"), {"apikey": key, "Authorization": f"Bearer {key}"}


def load_candidates(source: int | None) -> list[dict]:
    url, hdr = _env()
    rows, off = [], 0
    sel = ("id,source_id,conference_name,source_url,booking_url,archived,"
           "pricing_tiers(id,tier_label,price_gbp,currency)")
    while True:
        q = f"{url}/rest/v1/conferences?select={sel}&archived=eq.false&order=id&limit={PAGE}&offset={off}"
        if source is not None:
            q += f"&source_id=eq.{source}"
        r = httpx.get(q, headers=hdr, timeout=60)
        r.raise_for_status()
        batch = r.json()
        rows += batch
        if len(batch) < PAGE:
            break
        off += PAGE
    out = []
    for c in rows:
        t = c.get("pricing_tiers") or []
        if t and all(float(x.get("price_gbp") or 0) == 0 for x in t):
            out.append(c)
    return out


_last_hit: dict[str, float] = {}


def polite_fetch(u: str):
    host = urlparse(u).netloc.lower()
    wait = MIN_INTERVAL_S - (time.time() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()
    text, html = fetch_page_text_and_html(u, timeout=30)
    _last_hit[host] = time.time()
    return text, html


def clean_text(text: str, html: str | None) -> str:
    """Prefer text rebuilt from html without <script>/<style> (JS payloads
    otherwise leak fake amounts); fall back to the fetcher's text."""
    if html:
        h = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", html)
        t = re.sub(r"<[^>]+>", " ", h)
        import html as _h
        return re.sub(r"\s+", " ", _h.unescape(t)).strip()
    return text


def unreadable(text: str) -> bool:
    return bool(text) and text.count("\ufffd") / max(len(text), 1) > 0.01


FEE_WORD_RE = re.compile(
    r"\bfees?\b|registration|\bregister\b|\brates?\b|ticket|delegate|\bprice|\bcost|"
    r"per\s+person|per\s+delegate|non-?\s?member|member\s+rate|\battend|booking|"
    r"early\s*bird|\bstandard\b", re.I)
EXCL_WORD_RE = re.compile(
    r"prize|award|bursar|\bgrants?\b|funding|million|billion|p/mo|per\s+month|monthly|"
    r"membership|subscription|donat|salary|\bworth\b|sponsor|scholarship|shipping", re.I)
CTX = 60
MEMBER_FREE_RE = re.compile(
    r"free\s+(?:of\s+charge\s+)?for\s+(?:\w+\s+){0,3}members?|members?\s*(?:[:\-–]|are)?\s*free\b", re.I)


def _nonfee_re():
    from remediator.signals import NON_FEE_CONTEXT_RE
    return NON_FEE_CONTEXT_RE


def fee_amounts(text: str, n: int = 3):
    """Return (best_snippets, fee_context_count, tags). Zero amounts never count.
    An amount counts only if its +-60 char context has a fee word and no exclusion word."""
    nonfee = _nonfee_re()
    out, count, tags = [], 0, set()
    for m in AMOUNT_RE.finditer(text):
        try:
            if float(m.group(1).replace(",", "")) <= 0:
                continue
        except ValueError:
            continue
        ctx = text[max(0, m.start() - CTX): m.end() + CTX]
        if EXCL_WORD_RE.search(ctx) or nonfee.search(ctx):
            continue
        if not FEE_WORD_RE.search(ctx):
            continue
        count += 1
        wide = text[max(0, m.start() - 120): m.end() + 120]
        if MEMBER_FREE_RE.search(wide):
            tags.add("member_free_nonmember_paid")
        if len(out) < n:
            out.append(re.sub(r"\s+", " ", text[max(0, m.start() - 55): m.end() + 55]).strip()[:120])
    return out, count, sorted(tags)


def free_snippet(text: str) -> str | None:
    m = _FREE_RE.search(text)
    if not m:
        return None
    a, b = max(0, m.start() - 60), min(len(text), m.end() + 60)
    if re.search(r"\bjobs?\b|advert|vacanc|newsletter|list your|membership|member(?:s)? only", text[a:b], re.I):
        return None  # free phrase about something other than attending the event
    return re.sub(r"\s+", " ", text[a:b]).strip()[:120]


def candidate_urls(c: dict) -> list[str]:
    urls = [c.get("source_url"), c.get("booking_url")]
    if c.get("source_id") == 17 and c.get("source_url"):
        urls.append(c["source_url"].rstrip("/") + "/registration")  # ESMO fee sub-page
    seen, out = set(), []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def strip_frag(u: str) -> str:
    return u.split("#", 1)[0]


_cache: dict[tuple[str, str], tuple] = {}   # (how, url-no-frag) -> (text|None, status)


def render_fetch(u: str):
    from remediator.explorer import render_page
    t, h, _ = render_page(u)
    return (t, h) if t else (None, None)


def fetch_cached(u: str, rendered: bool):
    key = ("rendered" if rendered else "http", strip_frag(u))
    if key in _cache:
        return _cache[key] + (True,)
    try:
        if rendered:
            text, html = render_fetch(key[1])
            text = text or None
        else:
            text, html = polite_fetch(key[1])
            text = clean_text(text, html) if text else None
    except Exception as e:  # noqa: BLE001
        _cache[key] = (None, f"error:{type(e).__name__}")
        return _cache[key] + (False,)
    if text and unreadable(text):
        _cache[key] = (None, "unreadable")
    else:
        _cache[key] = (text, "ok" if text else "failed")
    return _cache[key] + (False,)


def gather(urls, rendered, fetched, texts):
    for u in urls:
        text, status, cached = fetch_cached(u, rendered)
        fetched.append({"url": u, "how": "rendered" if rendered else "http", "status": status,
                        "chars": len(text or ""), "cached": cached})
        if text:
            texts.append((u, text))


def analyse(texts):
    """Per-row evidence before the cross-row shared-page guard."""
    best = None
    for u, t in texts:
        amts, cnt, tags = fee_amounts(t)
        if cnt and (best is None or cnt > best["n"]):
            best = {"n": cnt, "snips": amts, "url": u, "tags": tags,
                    "hash": hashlib.sha1(t.encode("utf-8", "ignore")).hexdigest()}
    free = None
    for u, t in texts:
        fs = free_snippet(t)
        if fs:
            free = {"snip": fs, "url": u, "hash": hashlib.sha1(t.encode("utf-8", "ignore")).hexdigest()}
            break
    return best, free


def prelim(best, free):
    return "WRONG_FREE" if best else ("LEGIT_FREE" if free else "UNKNOWN")


def fetch_row(c, render=True):
    urls = candidate_urls(c)
    fetched, texts = [], []
    gather(urls, False, fetched, texts)
    best, free = analyse(texts)
    if prelim(best, free) == "UNKNOWN" and render:
        gather(urls, True, fetched, texts)
        best, free = analyse(texts)
    return {"c": c, "fetched": fetched, "texts": texts, "best": best, "free": free}


def finalize(rows):
    """Cross-row pass: shared page text / identical snippet across >=3 conferences."""
    hash_ids, snip_ids = {}, {}
    for r in rows:
        ev = r["best"] or r["free"]
        if not ev:
            continue
        hash_ids.setdefault(ev["hash"], set()).add(r["c"]["id"])
        s = (ev["snips"][0] if r["best"] else ev["snip"])
        snip_ids.setdefault(s, set()).add(r["c"]["id"])
    results = []
    for r in rows:
        c = r["c"]
        best, free = r["best"], r["free"]
        tags = []
        v = prelim(best, free)
        ev = best or free
        evu = ev["url"] if ev else None
        snippet = None
        shared = False
        if ev:
            s = best["snips"][0] if best else free["snip"]
            snippet = s
            if len(hash_ids[ev["hash"]]) >= 3 or len(snip_ids[s]) >= 3:
                shared = True
        if shared and v in ("WRONG_FREE", "LEGIT_FREE"):
            tags.append("shared_page_text")
            v = "UNKNOWN"
        elif best:
            tags += best["tags"]
        if not r["texts"]:
            tags.append("fetch_failed")
        elif not ev:
            tags.append("no_evidence")
        tiers = [{"label": t["tier_label"], "price": t["price_gbp"], "cur": t.get("currency")}
                 for t in c["pricing_tiers"]]
        results.append({
            "id": c["id"], "source_id": c["source_id"], "name": c["conference_name"],
            "url": c.get("source_url"), "verdict": v, "tags": tags,
            "fee_context_amounts": best["n"] if best else 0,
            "snippet": snippet, "evidence": (best["snips"] if best else ([free["snip"]] if free else [])),
            "evidence_url": evu,
            "tiers": {"count": len(tiers), "labels": [t["label"] for t in tiers], "detail": tiers},
            "fetched": r["fetched"]})
    return results


def write_reports(results: list[dict], out: Path, day: str) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    verdicts = Counter(r["verdict"] for r in results)
    per_src: dict[int, Counter] = {}
    for r in results:
        per_src.setdefault(r["source_id"], Counter())[r["verdict"]] += 1
    fetches = [f for r in results for f in r["fetched"]]
    uniq = [f for f in fetches if not f.get("cached")]
    stats = {"requests": len(uniq), "ok": sum(f["status"] == "ok" for f in uniq),
             "failed": sum(f["status"] != "ok" for f in uniq), "cache_hits": len(fetches) - len(uniq),
             "tags": dict(Counter(t for r in results for t in r["tags"]))}
    jp, mp = out / f"zero_tiers_{day}.json", out / f"zero_tiers_{day}.md"
    jp.write_text(json.dumps({
        "date": day, "count": len(results), "verdicts": dict(verdicts),
        "per_source": {str(k): dict(v) for k, v in sorted(per_src.items())},
        "fetch_stats": stats, "results": results}, indent=2, ensure_ascii=False))
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")
    L = [f"# Zero-tier audit {day}", "", f"Candidates: {len(results)}  ",
         f"Fetch: {stats['requests']} requests, {stats['ok']} ok, {stats['failed']} failed, {stats['cache_hits']} cache hits  ",
         f"Tags: {stats['tags']}", "",
         "## Per verdict", "", "| verdict | n |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in sorted(verdicts.items())]
    L += ["", "## Per source", "", "| source | WRONG_FREE | LEGIT_FREE | UNKNOWN |", "|---|---|---|---|"]
    L += [f"| {k} | {v['WRONG_FREE']} | {v['LEGIT_FREE']} | {v['UNKNOWN']} |"
          for k, v in sorted(per_src.items())]
    L += ["", "## Events", "", "| id | source | name | verdict | tags | tiers | evidence | url |", "|---|---|---|---|---|---|---|---|"]
    for r in sorted(results, key=lambda r: (r["verdict"], r["source_id"], r["id"])):
        L.append(f"| {r['id']} | {r['source_id']} | {esc(r['name'])} | {r['verdict']} | "
                 f"{esc(' / '.join(r['evidence']))} | {r['url']} |")
    mp.write_text("\n".join(L) + "\n")
    return jp, mp


def apply(path: Path, day: str):
    if path.name != f"zero_tiers_{day}.json" or not path.exists():
        sys.exit(f"refusing: --from must be today's dry-run file zero_tiers_{day}.json")
    data = json.loads(path.read_text())
    ids = [r["id"] for r in data["results"] if r["verdict"] == "WRONG_FREE"]
    url, hdr = _env()
    for i in ids:
        r1 = httpx.delete(f"{url}/rest/v1/pricing_tiers?conference_id=eq.{i}", headers=hdr, timeout=60)
        r2 = httpx.patch(f"{url}/rest/v1/conferences?id=eq.{i}", headers=hdr, timeout=60,
                         json={"listing_hash": None, "remediation_attempted_at": None})
        print(f"apply id={i} tiers_delete={r1.status_code} conf_patch={r2.status_code}")
        r1.raise_for_status(); r2.raise_for_status()
    print(f"applied to {len(ids)} conferences: {ids}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--from", dest="from_file")
    ap.add_argument("--day", help="report date suffix, e.g. 2026-10-27b")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--source", type=int)
    ap.add_argument("--ids", help="comma-separated conference ids (debug)")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--out", default="reports/pricing")
    a = ap.parse_args()
    day = a.day or dt.date.today().isoformat()
    out = Path(a.out)
    if not out.is_absolute():
        out = ROOT.parent / out
    if a.apply:
        if not a.from_file:
            sys.exit("--apply requires --from reports/pricing/zero_tiers_<date>.json")
        return apply(Path(a.from_file), day)
    cands = load_candidates(a.source)
    if a.ids:
        want = {int(x) for x in a.ids.split(",")}
        cands = [c for c in cands if c["id"] in want]
    if a.limit:
        cands = cands[: a.limit]
    print(f"{len(cands)} candidates", flush=True)
    rows = []
    for n, c in enumerate(cands, 1):
        try:
            r = fetch_row(c, render=not a.no_render)
        except Exception as e:  # continue on failure
            r = {"c": c, "fetched": [{"url": c.get("source_url"), "how": "http",
                 "status": f"error:{type(e).__name__}", "chars": 0, "cached": False}],
                 "texts": [], "best": None, "free": None}
        rows.append(r)
        print(f"[{n}/{len(cands)}] {c['id']} s{c['source_id']} {prelim(r['best'], r['free'])}", flush=True)
    results = finalize(rows)
    jp, mp = write_reports(results, out, day)
    print(jp, mp)


if __name__ == "__main__":
    main()
