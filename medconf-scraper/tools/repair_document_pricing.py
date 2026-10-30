"""Undo pricing tiers / booking+organiser links the remediator wrote from an unrelated PDF/DOCX.

Scans remediation reports for
  * pricing patches whose method names a document (``explorer:pdf:NAME``, ``promoted:pdf:...``, ``.pdf``/``.docx``),
  * booking_url / organiser_url patches (method ``external_link_follow:...``) whose value_after is a .pdf/.docx URL,
fetches the current rows and tiers and decides per row:
  tiers: delete (every current tier came from the bad document) | keep | mixed - manual | none
  links: reset to source_url (document URL with a bad name) | keep (event-specific document, manual review) | ok

Dry-run (default): prints a decision table and totals. Never writes.
--apply: DELETE the row's tiers (after re-reading and re-confirming the labels), PATCH links with
         compare-and-swap, then null remediation_attempted_at + listing_hash so the row is revisited.
         Archived rows are never touched (counted only). Refuses on zero candidates.

Report patches truncate value_after at 200 characters, so only the first tier label (sometimes two) is
recoverable. The remediator inserts tiers only into a conference that has none, so when the report is
truncated and the first written label is present on the row, the other current tiers are taken to be
the document's too (reason says "truncated report").

Run from medconf-scraper/:  ./.venv/bin/python tools/repair_document_pricing.py [--reports DIR ...] [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import httpx

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORTS = ROOT.parent / "reports" / "remediation"
CHUNK = 150
TRUNC = 200
ROW_COLS = ("id,source_id,conference_name,start_date,source_url,booking_url,organiser_url,"
            "archived,listing_hash,remediation_attempted_at")

BAD_WORDS = re.compile(
    r"\b(?:training (?:costs?|fees?|rates?)|cost of|membership|subscription|exams?|examinations?|medicare|fee schedule|"
    r"reports?|minutes|agenda|policy|bylaws|handbook|newsletter|annual report)\b", re.I)
YEAR = re.compile(r"(?<!\d)(20\d\d)(?!\d)")
LABEL = re.compile(r"""'tier_label':\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")""")
DOC_IN_METHOD = re.compile(r"(?:pdf|docx):(.+)$", re.I)
DOC_EXT = (".pdf", ".docx")


# ---------------------------------------------------------------- pure helpers
def document_is_bad(name: str, row_start_year: int | None, row_title: str | None = None) -> tuple[bool, str]:
    n = unquote(name or "")
    words = re.sub(r"[-_.\s]+", " ", n)
    m = BAD_WORDS.search(words)
    if m:
        return True, f"name matches '{m.group(0).lower()}'"
    row_years = [int(y) for y in YEAR.findall(row_title or "")]
    if row_start_year:
        row_years.append(row_start_year)
    name_years = [int(y) for y in YEAR.findall(n)]
    if row_years and name_years and all(y < min(row_years) for y in name_years):
        return True, f"name year {max(name_years)} before event year {min(row_years)}"
    return False, "looks event-specific"


def is_doc_url(url: str | None) -> bool:
    if not url:
        return False
    return urlsplit(url).path.lower().endswith(DOC_EXT)


def url_doc_name(url: str) -> str:
    return unquote(urlsplit(url).path.rsplit("/", 1)[-1])


def method_doc_name(method: str) -> str | None:
    m = DOC_IN_METHOD.search(method or "")
    if m:
        return m.group(1).strip()
    for seg in re.split(r"[:/]", method or ""):
        if seg.lower().endswith(DOC_EXT):
            return seg
    return None


def extract_labels(value_after: str) -> list[str]:
    return [(a or b).strip() for a, b in LABEL.findall(value_after or "")]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def labels_match(current: str, written: str) -> bool:
    """Exact (normalised) match, or one label is a prefix of the other and the written label is >= 20 chars."""
    a, b = _norm(current), _norm(written)
    if not a or not b:
        return False
    if a == b:
        return True
    return len(b) >= 20 and min(len(a), len(b)) >= 20 and (a.startswith(b) or b.startswith(a))


def _is_pricing_doc_patch(p: dict) -> bool:
    m = (p.get("method") or "")
    return p.get("field") == "pricing" and ("pdf:" in m.lower() or ".pdf" in m.lower()
                                           or ".docx" in m.lower() or "docx:" in m.lower())


def _is_doc_link_patch(p: dict) -> bool:
    return (p.get("field") in ("booking_url", "organiser_url")
            and (p.get("method") or "").startswith("external_link_follow:")
            and is_doc_url(p.get("value_after")))


def scan(dirs: list[Path]) -> dict[int, dict]:
    """conference_id -> {'pricing': {...}|None, 'links': {field: {...}}}; newer report date wins."""
    found: dict[int, dict] = {}
    for d in dirs:
        for f in sorted(Path(d).rglob("source-*.json")):
            date = f.parent.name
            try:
                data = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            for p in data.get("patches_applied") or []:
                if p.get("conference_id") is None:
                    continue
                cid = int(p["conference_id"])
                if _is_pricing_doc_patch(p):
                    va = p.get("value_after") or ""
                    rec = {"date": date, "doc": method_doc_name(p.get("method") or "") or "?",
                           "labels": extract_labels(va), "truncated": len(va) >= TRUNC,
                           "source_id": p.get("source_id")}
                    cur = found.setdefault(cid, {"pricing": None, "links": {}})["pricing"]
                    if cur is None or date >= cur["date"]:
                        found[cid]["pricing"] = rec
                elif _is_doc_link_patch(p):
                    url = p["value_after"]
                    rec = {"date": date, "url": url, "doc": url_doc_name(url)}
                    links = found.setdefault(cid, {"pricing": None, "links": {}})["links"]
                    cur = links.get(p["field"])
                    if cur is None or date >= cur["date"]:
                        links[p["field"]] = rec
    return found


def start_year(row: dict) -> int | None:
    s = (row.get("start_date") or "")[:4]
    return int(s) if s.isdigit() else None


def decide_tiers(row: dict, tiers: list[dict], pricing: dict | None) -> tuple[str, str, str]:
    """-> (decision, reason, doc). decision: delete | keep | manual | none."""
    if not pricing:
        return "none", "no document pricing patch", ""
    doc = pricing["doc"]
    if not tiers:
        return "none", "row has no tiers now", doc
    bad, why = document_is_bad(doc, start_year(row), row.get("conference_name"))
    if not bad:
        return "keep", f"{why}; review manually", doc
    written = pricing["labels"]
    cur = [t.get("tier_label") or "" for t in tiers]
    unmatched = [c for c in cur if not any(labels_match(c, w) for w in written)]
    if not unmatched:
        return "delete", why, doc
    if pricing["truncated"] and len(unmatched) < len(cur):
        return "delete", f"{why}; truncated report, first label present", doc
    return "manual", "mixed - manual (current tiers differ from what the document wrote)", doc


def parse_id_list(text: str | None) -> list[int]:
    out: list[int] = []
    for part in re.split(r"[,\s]+", text or ""):
        if part:
            if not part.isdigit():
                raise ValueError(f"not an id: {part!r}")
            if int(part) not in out:
                out.append(int(part))
    return out


def decide_tiers_explicit(tiers: list[dict]) -> tuple[str, str, str]:
    if not tiers:
        return "none", "explicit list, but row has no tiers", ""
    return "delete", "explicit", ""


def decide_link(row: dict, field: str, link: dict | None) -> tuple[str, str]:
    """-> (decision, reason). decision: reset | keep | ok."""
    cur = row.get(field)
    if not is_doc_url(cur):
        return "ok", "not a document URL"
    name = url_doc_name(cur)
    bad, why = document_is_bad(name, start_year(row), row.get("conference_name"))
    if link and cur == link["url"]:
        bad2, why2 = document_is_bad(link["doc"], start_year(row), row.get("conference_name"))
        bad, why = bad or bad2, why if bad else why2
    if not bad:
        return "keep", f"{why}; review manually"
    if not row.get("source_url"):
        return "keep", "bad document but no source_url to reset to"
    return "reset", why


# ------------------------------------------------------------------- database
def _env():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("SUPABASE_URL / SUPABASE_KEY missing (medconf-scraper/.env)")
    return url.rstrip("/"), {"apikey": key, "Authorization": f"Bearer {key}"}


def _chunks(ids):
    for i in range(0, len(ids), CHUNK):
        yield ",".join(str(x) for x in ids[i:i + CHUNK])


def fetch_rows(ids: list[int]) -> list[dict]:
    url, hdr = _env()
    out: list[dict] = []
    for c in _chunks(ids):
        r = httpx.get(f"{url}/rest/v1/conferences?select={ROW_COLS}&id=in.({c})", headers=hdr, timeout=60)
        r.raise_for_status()
        out.extend(r.json())
    return out


def fetch_tiers(ids: list[int]) -> dict[int, list[dict]]:
    url, hdr = _env()
    out: dict[int, list[dict]] = {}
    for c in _chunks(ids):
        r = httpx.get(f"{url}/rest/v1/pricing_tiers?select=id,conference_id,tier_label,price_gbp,currency"
                      f"&conference_id=in.({c})", headers=hdr, timeout=60)
        r.raise_for_status()
        for t in r.json():
            out.setdefault(t["conference_id"], []).append(t)
    return out


def fetch_doc_link_rows() -> list[dict]:
    url, hdr = _env()
    flt = ("or=(booking_url.ilike.*.pdf,organiser_url.ilike.*.pdf,"
           "booking_url.ilike.*.docx,organiser_url.ilike.*.docx)&archived=eq.false")
    rows: list[dict] = []
    off = 0
    while True:
        r = httpx.get(f"{url}/rest/v1/conferences?select={ROW_COLS}&{flt}&order=id.asc&limit=1000&offset={off}",
                      headers=hdr, timeout=60)
        r.raise_for_status()
        rows.extend(r.json())
        if len(r.json()) < 1000:
            return rows
        off += 1000


def link_patch_url(url: str, row: dict, field: str) -> str:
    return (f"{url}/rest/v1/conferences?id=eq.{row['id']}&archived=eq.false"
            f"&{field}=eq.{quote(row[field], safe='')}")


def stamp_patch_url(url: str, cid: int) -> str:
    return f"{url}/rest/v1/conferences?id=eq.{cid}&archived=eq.false"


def delete_decided_tiers(client, url: str, wh: dict, cid: int, decided: list[dict], fetcher=None) -> int:
    """Delete exactly the tiers the decision pass saw; 0 (and nothing deleted) if the row's tier ids changed."""
    fetcher = fetcher or fetch_tiers
    cur = fetcher([cid]).get(cid, [])
    if not cur or {t["id"] for t in cur} != {t["id"] for t in decided}:
        print(f"row {cid}: tiers changed since read, skipped")
        return 0
    print(f"  {cid}: deleting tiers: " + " | ".join(t.get("tier_label") or "" for t in cur))
    ids = ",".join(str(t["id"]) for t in sorted(decided, key=lambda t: t["id"]))
    r = client.delete(f"{url}/rest/v1/pricing_tiers?conference_id=eq.{cid}&id=in.({ids})", headers=wh, timeout=60)
    r.raise_for_status()
    n = len(r.json())
    print(f"  {cid}: deleted {n} tiers")
    return n


def apply_row(row: dict, tdec: str, decided_tiers: list[dict], ldecs: dict[str, str]) -> dict:
    url, hdr = _env()
    wh = {**hdr, "Content-Type": "application/json", "Prefer": "return=representation"}
    res = {"tiers": 0, "links": 0, "skipped": 0}
    did = False
    if tdec == "delete":
        n = delete_decided_tiers(httpx, url, wh, row["id"], decided_tiers)
        res["tiers"] = n
        did = n > 0
        if n == 0:
            res["skipped"] += 1
    for field, d in ldecs.items():
        if d != "reset":
            continue
        r = httpx.patch(link_patch_url(url, row, field),
                        headers=wh, timeout=60, json={field: row["source_url"]})
        r.raise_for_status()
        if r.json():
            print(f"  {row['id']}: {field} reset to source_url")
            res["links"] += 1
            did = True
        else:
            print(f"  {row['id']}: {field} changed since read, skipped")
            res["skipped"] += 1
    if did:
        r = httpx.patch(stamp_patch_url(url, row["id"]), headers=wh, timeout=60,
                        json={"remediation_attempted_at": None, "listing_hash": None})
        r.raise_for_status()
        print(f"  {row['id']}: stamps nulled")
    return res


# ----------------------------------------------------------------------- main
def _t(s, n):
    s = (s or "").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports", action="append", type=Path)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--scan-db", action="store_true", help="also scan live rows whose booking/organiser URL is a .pdf/.docx")
    ap.add_argument("--delete-tiers", help="comma-separated row ids whose tiers are deleted regardless of report evidence")
    a = ap.parse_args(argv)
    explicit = set(parse_id_list(a.delete_tiers))
    found = scan(a.reports or [DEFAULT_REPORTS])
    rows_by_id = {r["id"]: r for r in fetch_rows(sorted(set(found) | explicit))}
    db_ids: set[int] = set()
    if a.scan_db:
        for r in fetch_doc_link_rows():
            db_ids.add(r["id"])
            rows_by_id.setdefault(r["id"], r)
    for cid in explicit - set(rows_by_id):
        print(f"warning: explicit id {cid} not found")
    ids = sorted(rows_by_id)
    tiers = fetch_tiers(ids)
    cands, archived = [], 0
    for r in sorted(rows_by_id.values(), key=lambda x: x["id"]):
        if r.get("archived"):
            archived += 1
            continue
        f = found.get(r["id"]) or {"pricing": None, "links": {}}
        if r["id"] in explicit:
            td, twhy, tdoc = decide_tiers_explicit(tiers.get(r["id"], []))
        else:
            td, twhy, tdoc = decide_tiers(r, tiers.get(r["id"], []), f["pricing"])
        ld = {fld: decide_link(r, fld, f["links"].get(fld)) for fld in ("booking_url", "organiser_url")}
        doc = tdoc or next((l["doc"] for l in f["links"].values()), "") or next(
            (url_doc_name(r[k]) for k in ("booking_url", "organiser_url") if is_doc_url(r.get(k))), "")
        if td == "none" and all(v[0] == "ok" for v in ld.values()):
            continue
        src = "both" if (r["id"] in found and r["id"] in db_ids) else "db" if r["id"] in db_ids and r["id"] not in found else "report"
        if r["id"] in explicit and r["id"] not in found and r["id"] not in db_ids:
            src = "explicit"
        cands.append((r, td, twhy, ld, doc, f, src))
    for r, td, twhy, ld, doc, _, src in cands:
        n = len(tiers.get(r["id"], []))
        print(f"{r['id']}\t{r['source_id']}\t{_t(r['conference_name'],40)}\t{r.get('start_date')}\t"
              f"{src}\ttiers={td}{' (explicit)' if td == 'delete' and twhy == 'explicit' else ''}({n})\tbooking={ld['booking_url'][0]}\torganiser={ld['organiser_url'][0]}\t"
              f"doc={_t(doc,45)}\t[{_t(twhy if td != 'none' else ld['booking_url'][1],60)}]")
    c = lambda pred: sum(1 for x in cands if pred(x))
    n_del = c(lambda x: x[1] == "delete")
    n_tiers = sum(len(tiers.get(x[0]["id"], [])) for x in cands if x[1] == "delete")
    n_reset = sum(1 for x in cands for v in x[3].values() if v[0] == "reset")
    print(f"\ncandidates={len(cands)} tiers-delete-rows={n_del} (tiers={n_tiers}) "
          f"tiers-keep={c(lambda x: x[1]=='keep')} tiers-manual={c(lambda x: x[1]=='manual')} "
          f"link-resets={n_reset} link-keep={sum(1 for x in cands for v in x[3].values() if v[0]=='keep')} "
          f"archived-skipped={archived}")
    if not a.apply:
        return 0
    if not cands:
        sys.exit("refusing to apply: 0 candidates")
    tot = {"tiers": 0, "links": 0, "skipped": 0}
    for r, td, _, ld, _, f, _ in cands:
        if td == "delete" or any(v[0] == "reset" for v in ld.values()):
            res = apply_row(r, td, tiers.get(r["id"], []), {k: v[0] for k, v in ld.items()})
            for k in tot:
                tot[k] += res[k]
    print(f"applied: tiers deleted={tot['tiers']} links reset={tot['links']} skipped={tot['skipped']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
