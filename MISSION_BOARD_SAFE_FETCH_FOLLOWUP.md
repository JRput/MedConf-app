# Mission: Safe-fetch follow-ups — conditional writes, inline-image strip, loud PDF rejects, encoding proof

**Opened:** 2026-10-24 · **Owner approval:** "do items 1, 3 and 4, strip the images for item 2. i want these completed as i want to move to testing deployment on vercel" · **Protocol:** HQ foreman (session plans on Opus, no Fable/Astra consult requested), proof-check before close.

## Brief
Close the four follow-ups filed in HQ `docs/BACKLOG.md` ("MedConf safe-fetch: LOW/loose ends", 2026-10-23) so the remediator is deployment-ready:
1. **Check-then-act writes** (`remediator/runner.py` `_patch_row`): every content write must land only if the stored value still matches what the remediator read; pricing tier replacement becomes an atomic DB function that inserts only when the conference has no tiers. Affects all 141 sources (pre-existing), not just community rows. Concrete race: `moderate_contribution` → `community_upsert_tiers` writes `pricing_tiers` for a community event while the community remediator job is mid-run on the same row.
2. **Inline `data:` images** reach the vision model untouched (`vision.extract_json` passes them straight through; only http(s) images were turned off under the flag). Owner decision: STRIP them under the flag.
3. **Silent PDF rejects**: `%PDF` header rejection in `extractors/abstract_classifier.py` is unlogged; `remediator/pdf_text.py` `_PDF_CHILD` swallows parse exceptions and exits 0 with empty output.
4. **Encoding refusal must not depend on installed decoders** (zstandard is transitive, unpinned): prove in the safe-mode tests that `gzip/br/zstd/deflate` responses are refused before any body read and that `Accept-Encoding: identity` is sent on every hop.

Item 5 (explicit `encoding_refused` mapping in `enrich_submissions.py`) stays a watch item — not in this mission.

## Baseline snapshot
- Repo HEAD `06916ac` (main). `git status --porcelain` before dispatch: `M Conference_masterlist/wave1d/mddus.json`, `M reports/remediation/learned_patterns.json` (pre-existing, not part of this mission, never committed).
- Scraper suite green at HEAD (412 tests, `--ignore=test_api.py`). Safe-mode tests: 25.
- Principles-block arm: OFF (no flag file) → no record/complete.

## Task graph
```
T1 builder `sf2-writes` (sonnet)  ── runner CAS writes + tier RPC migration + test_runner_writes.py + CI line
T2 builder `sf2-trio`   (sonnet)  ── vision data: strip · loud PDF rejects · encoding tests        (parallel, disjoint write sets)
        │                                   │
        ▼                                   ▼
T3 Commander: full suite · sabotage runs (new tests must FAIL on a worktree of 06916ac — Lesson 82) · commit candidate
T4 reviewer `hq-security-reviewer` (opus, read-only) — proof-check on the committed diff; CRITICAL/HIGH stop
T5 Commander: apply migration via apply_migration.py (BEFORE push — runner calls the RPC) · push · dispatch remediator-daily.yml · verify
T6 Commander: docs (CLAUDE.md §3, this board CLOSED, HQ backlog entry updated, memory), LESSON if new
```

## Write sets (disjoint — parallel dispatch allowed)
- **T1:** `medconf-scraper/remediator/runner.py` · new `medconf-scraper/test_runner_writes.py` · new `supabase/migrations/20261024000000_remediator_conditional_tier_insert.sql` + `20261024000000_checks.txt` · `supabase_schema.sql` (append the function only) · `.github/workflows/remediator-daily.yml` (the single pytest line, add the new test file).
- **T2:** `medconf-scraper/vision.py` · `medconf-scraper/remediator/pdf_text.py` · `medconf-scraper/extractors/abstract_classifier.py` · `medconf-scraper/remediator/explorer.py` (one `trail.notes` line in `_fetch_document_text` only) · `medconf-scraper/test_safe_mode.py`.

## Model routing · cost
Sonnet ×2 builders, Opus ×1 reviewer, Commander verifies/gates. No paid services, no new credentials (migration uses the existing `.env.db` pooler URL via `apply_migration.py`).

## Risk flags
- A hunk that changes flag-OFF behaviour affects all 141 sources — reviewer checks every T2 hunk is inside an `enabled()` branch or pure logging.
- T1 changes write semantics for every source: a conditional update that never matches would silently stop all remediation. Guard: happy-path tests + a live single-source run after the migration is applied + the next 04:00 UTC run's `patches_applied` counts compared with 2026-10-24's report.
- Migration must be applied before the new runner code runs on the runner (RPC missing → every pricing patch logs `patch failed`, no data loss). Order enforced in T5.
- Lesson 82: a guard test that raises inside except-Exception code cannot fail — every new test is proven red on the old code by the Commander, not by the builder's word.

## Acceptance
Whole scraper suite green; every new test fails on `06916ac`; reviewer PASS or PASS_WITH_NOTES with 0 CRITICAL/HIGH; migration applied with its checks green; `remediate-community` job green on the runner with the new test file; one live source remediated locally without `patch failed`/RPC errors.

## Ticket ledger
| id | tier | status/verdict | write set | evidence |
|---|---|---|---|---|
| T1 sf2-writes | sonnet | DONE_WITH_CONCERNS → fix wave 1 (explicit GRANT to service_role) | see above | Commander sabotage run: all 5 new tests FAIL on worktree of 06916ac, pass on new code; scalar RPC result parses as int (0/3) in postgrest 2.30.0 |
| T2 sf2-trio | sonnet | DISPATCHED 2026-10-24 | see above | — |

## Status log
- 2026-10-24 — board written; T1 + T2 dispatched in parallel.
- 2026-10-24 — T1 reported DONE_WITH_CONCERNS: `_patch_row` CAS (`is_(field,'null')` / `eq(field, expected)`), `abstract_status` conditional on `abstract_deadline IS NULL`, pricing via `remediator_insert_tiers_if_empty` RPC (no delete left in runner.py), migration + schema append + checks, CI line extended. Known cross-ticket effect: `test_safe_mode.py` stub needs `rpc` + non-empty update data → routed to T2 (owner of that file). Commander spot-check: sabotage run 5/5 red on old code; fix wave 1 → explicit `GRANT EXECUTE … TO service_role` (precedent: `expire_stale_contributions`).
