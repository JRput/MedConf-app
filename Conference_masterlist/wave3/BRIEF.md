# Wave 3 build brief (delta over wave 2d)

Read `Conference_masterlist/wave2c/BRIEF.md` IN FULL first, then `wave2d/BRIEF.md`
(every rule in both applies: hard rules, read-first list, shared helpers,
requirements, harness, deliverable JSON, coverage checklist). This file only states
what differs for wave 3.

## Differences
- **Today is 2026-11-09.** Only upcoming events.
- **Deliverable path:** `Conference_masterlist/wave3/<slug>.json`. Extractor at
  `medconf-scraper/extractors/<slug>.py`. Only those two files per source. Harness:
  `PYTHONPATH=. ./.venv/bin/python ../Conference_masterlist/wave2c/harness.py <slug> <ClassName> ../Conference_masterlist/wave3/<slug>.json --details 5`
  (then once more with `--force-fallback`; shell counts must match).
- **Your batch** is a key in `Conference_masterlist/wave3/plan.json` → `batches`
  (`domain`, `source_id`, `slug`, `candidate_urls`, `recon`). `ClassName` =
  CamelCase(slug) + `Extractor`.
- **Since wave 2d the pipeline changed (read before building):**
  - `extractors/discovery.py` runs for EVERY source at scrape time (registration /
    abstract / venue sub-pages, PDFs, fee images) behind a fail-closed `page_identity`
    gate. Do NOT re-implement sub-page following in your extractor; rely on
    discovery unless the harness shows a concrete miss, and say which in `concerns`.
  - One shared money parser `money.py` (never default a currency; set `currency`
    per tier from the page).
  - **Provenance:** tiers / venue / abstract values must carry `evidence_url` +
    `evidence_identity` (`own_page` for values read from the event's own page).
    Read `llm_agent.py` `_stamp_own_page_tiers` / `_stamp_own_page_fields` and
    `database.py` `tiers_have_provenance` — a batch without provenance is dropped.
    Follow what `extractors/bofas.py` (2026-11-07) and `croi.py` do.
  - `event_type='degree'` exists (`extractors/degree_rule.py`); `verified_empty`
    contract for between-editions single-congress sites (`idweek.py`, `bofas.py`).
  - `pricing_tables.py` parses dual-currency grids; try it before a bespoke parser.
- **Single-congress sites (batch 3-S):** subclass `extractors/single_congress.py`
  `SingleCongressExtractor` constants-only, hooks only on a harness-proven miss.
  Do NOT edit `single_congress.py`; describe family gaps in `concerns`.
- **Cloud access:** a runner probe of your domains is running
  (`probe-cloud-access.yml` on `wave3/candidates.json`); the foreman will message
  the result. If `blocked`, finish with `status: "blocked"`; never fight anti-bot.
- **Member-only fees / logins:** record only public values; never log in.
- **Relevance:** NHS England's portal (156) and IMCAS (157) list many events; keep
  only dated CPD-relevant events for clinicians (drop internal admin/IT sessions,
  exhibitor-only items) and log dropped titles like BOA/BAAPS do.
- **Terms of use:** if a site forbids automated access or AI use, stop, report it in
  `concerns`, and do not register (AAN/AAD/CNS precedent).
- Never spawn subagents. Never run git commands. Never touch files outside your
  write set. Never run `test_api.py`.

## Final message (5–10 lines per source)
status · shell count (normal / forced-fallback) · field coverage counts · 3 spot-checked
URLs · concerns (coverage checklist items verified, anything unproven, shared-file asks).

## Batch 3-C delta (2026-11-13)
- **Today is 2026-11-13.** Your batch key is `3-C multi_event` or `3-C single_congress` in
  `wave3/plan.json` (ids 159–165). Deliverables still `wave3/<slug>.json` + `extractors/<slug>.py`.
- The four big US/EU sites (astro, heart, himss, esska) are NOT in this batch: their events
  pages are challenged on the runner. Do not touch them.
- **Robots:** `discovery.py` now consults `robots_gate.allowed(url)` before every sub-page
  fetch. Your extractor must not fetch a URL `robots_gate.allowed()` returns False for;
  say so in `concerns` when a fee/abstract page is disallowed (IMCAS/BSPED precedent:
  fees stay absent, we respect robots).
- **HQ LESSON #95:** the harness reads static HTML, production reads the Playwright DOM.
  Where the page has sliders/menus, check the venue/abstract values you return against
  the rendered page (`fetch_html`) not only the raw HTML. The foreman runs the live
  `main.py --run-now --source N` after review; you cannot (no DB writes).
- Family rule unchanged: single-congress sites subclass `SingleCongressExtractor`
  constants-only; `verified_empty` is set family-wide once an edition has ended.
- Keep total requests per site ≤ 40 across both harness runs. Never fight anti-bot.
