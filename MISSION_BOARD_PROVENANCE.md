# Mission board — field provenance + structural identity gate (planned 2026-10-30)

**Owner ask:** "shouldn't the information being scraped like pricing, venues etc. be linked or identified to the event it is being scraped for" → every stored fee / venue / abstract value records WHERE it came from and HOW sure we are it is this event's, and the write boundary refuses anything that is not. Planned lean (owner: "be efficient").

**Baseline:** main `3fe97a7`. Planner = session model (no Fable/Astra consult). Workers `model: sonnet`, one verifier `model: opus`. PRINCIPLES arm OFF.

## Design (fixed — tickets implement, they do not redesign)
- **Columns.** `pricing_tiers`: `evidence_url TEXT`, `evidence_identity TEXT` (`own_page` | `strong` | `legacy`), `written_by TEXT` (`scraper` | `remediator`), `written_at TIMESTAMPTZ DEFAULT now()`. `conferences`: `venue_evidence_url`, `venue_evidence_identity`, `abstract_evidence_url`, `abstract_evidence_identity` (same vocabulary). Existing rows stay NULL = unknown provenance (no backfill; the audit lists them).
- **Vocabulary.** `own_page` = the event's own page (source_url / booking_url fetched for this row). `strong` = a discovered/explored page that passed `page_identity` STRONG (or the single-event-host relaxation). Nothing else is writable.
- **Rule at the boundary.** `database.insert_pricing_tiers` and both RPCs (`remediator_insert_tiers_if_empty`, `remediator_replace_tiers_if_zero_or_generic`) reject a tier whose identity is not `own_page`/`strong` (whole batch rejected, logged `provenance_rejected`). Remediator `_patch_row` for `venue_name`/`city`/`abstract_status` requires an evidence url + identity in the same set. Legacy/NULL is read-only history, never written anew.
- **Carry the evidence, don't recompute it.** Scraper: a tier from the extractor's own page → (page url, `own_page`); from discovery → that step's `url` + its `identity` (already in `DiscoveryResult.evidence`). Remediator: `ExploreResult` gains `evidence_url` + `evidence_identity` set where tiers are produced (own page, `_subpage_identity` STRONG, external page accepted by `external_identity_ok` → identity `strong` only when the external page is the row's organiser_url/booking_url, else rejected — this also closes the "external loose check" gap).
- **Website.** Under the fee table: "Fees as published on <host/path>" linking `evidence_url` when every displayed tier shares one url; otherwise nothing. No other UI.

## Tickets (3 workers in parallel, disjoint write sets)
| id | tier | write set | definition of done |
|---|---|---|---|
| T1 migration | sonnet | `supabase/migrations/20261031000000_provenance.sql`, `…_rollback.sql`, `…_checks.txt`, `supabase_schema.sql` (both RPCs + columns), `supabase/migrations/dry_run_20261031.sql` | additive columns; RPCs read `evidence_url`/`evidence_identity`/`written_by` from each tier's JSON and REJECT the call (RAISE with `provenance_rejected`) when any tier's identity ∉ (`own_page`,`strong`); dry run (rolled back) with behaviour tests: legacy insert path unchanged for NULL-free batches, rejection fires, columns present |
| T2 writers + gate | sonnet | `medconf-scraper/database.py`, `scraper.py`, `llm_agent.py`, `extractors/discovery.py` (only to expose per-field evidence), `remediator/explorer.py`, `remediator/runner.py`, `remediator/fixers/__init__.py`, new tests | every tier/venue/abstract write carries evidence; `insert_pricing_tiers` drops batches without `own_page`/`strong`; remediator venue/abstract explorers gated by `_subpage_identity` (same-site) and the external-page acceptance narrowed as above; `coverage_report.py` gains one line "tiers written since <date> without provenance = N" (red if > 0); full suite green |
| T3 website | sonnet | `medconf-website/src/components/conferences/PricingTable.tsx`, `src/lib/types.ts`, the event query that selects tiers, one test | "Fees as published on …" link when all tiers share an `evidence_url`; vitest + build green |
| V1 verifier | opus | read-only | T1 + T2: can any path still write a tier/venue/abstract without `own_page`/`strong`? does the RPC rejection match the Python rule? does the external-page narrowing lose a legitimate organiser site? |

**Order:** T1 ∥ T2 ∥ T3 → deterministic checks (scraper suite, vitest, build, SQL dry run via `apply_migration.py` — owner-run) → V1 → fix wave(s) ≤ 2 → foreman dry-runs then applies the migration with `apply_migration.py` (owner authorised 2026-10-30; additive, safe before code) → push → one local `main.py --run-now --source 81` + `python -m remediator --source 27` to see provenance populated → close. No data backfill. Est. 3 sonnet + 1 opus + ≤ 2 fix tickets.

**Out of scope (filed, not done):** backfilling provenance on existing rows; provenance for course_sessions pricing; community tiers (already carry `evidence_url`).

## Log
- 2026-10-30 — plan written; awaiting owner go.
- 2026-10-30 — owner: "you should be able to apply migrations" → migration step is the foreman's (`apply_migration.py` verified working; Supabase MCP denies SQL).
