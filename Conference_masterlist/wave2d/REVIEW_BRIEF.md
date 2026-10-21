# Wave 2d review brief (one reviewer agent per batch, fresh eyes)

You review a finished build batch BEFORE registration. You do not edit product code,
JSON deliverables or shared files; you report. Repo root:
`/Users/Sushil/Documents/Documents/IMT2/Side hustle/myTalk_conference app` (quote the space).

## Read first
1. `Conference_masterlist/wave2d/BRIEF.md`, then `wave2c/BRIEF.md` (rules the builder had).
2. `medconf-scraper/extractors/PLAYBOOK.md` → "Coverage checklist".
3. Your batch key in `wave2d/plan.json` and each `wave2d/<slug>.json` deliverable.

## Per source
- Read `medconf-scraper/extractors/<slug>.py` end to end. Check: hard fields deterministic;
  no invented data (unknown → None/[]); `fetch_html` not raw httpx; one small `llm_call`
  at most with deterministic backstops; pricing labels `[Section] · [Category] · [Timeframe]`;
  `currency` on non-GBP tiers; `event_type` per row for mixed societies; only upcoming
  events; junk shells skipped; polite (no parallel fetching, no tight loops);
  imports only from shared helpers or a family module (never from another per-source
  module); no DB, no secrets, `py_compile` clean.
- Re-run the harness ONCE (from `medconf-scraper/`):
  `PYTHONPATH=. ./.venv/bin/python ../Conference_masterlist/wave2c/harness.py <slug> <ClassName> ../Conference_masterlist/wave2d/<slug>.json --details 3`
  Shell count must match `probe_results.shells` in the JSON (± events that legitimately
  appeared/expired since). Keep total requests per site ≤ 25.
- Verify TWO of the builder's `spot_check` rows yourself (curl + grep the live page):
  date, fee or venue. Say which and whether they match.
- Check the JSON: `source_row` keys exactly as the 2c brief; `status` honest versus
  `concerns` and coverage; `extraction_instructions` 2–5 sentences a stranger could act on.
- Coverage checklist: for each empty `pricing_tiers` or missing deadline, confirm the
  builder looked where the checklist says (registration sub-page, external "here" link,
  PDF, image table). Flag any unjustified empty field.
- `git status --short` must show only the batch's extractor files, JSON deliverables, and
  any family/test file the Commander allowed in your prompt. Anything else is a FAIL.

## Report (your final message)
Per source one block: `slug · PASS | PASS-with-notes | FAIL · harness shells (yours/builder's)
· spot checks verified (2) · issues (file:line, one line each) · registration advice:
active | inactive | hold`. Then: cross-cutting issues, and anything the Commander must
decide. Do not append to any board or ledger; do not commit.
