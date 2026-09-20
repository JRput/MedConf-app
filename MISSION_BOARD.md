# MISSION BOARD — Masterlist Scale-Up (23 → ~200 sources)

> Commander mission board. Status: **APPROVED 2026-08-15 — executing.**
> Created 2026-08-15. Brief: scrape every source in
> `Conference_masterlist/Medical_Courses_Conferences_Master_Comprehensive_v1(Master list).csv`
> autonomously, keep the MedConf site up to date, with accuracy and nothing missing.

## 1. Brief & ground truth

- Masterlist: 396 rows · 202 unique domains · 85 rows already covered by the 23 active sources.
- **Net-new work: 186 domains** (≈150–170 distinct listing sources after grouping).
- 215/396 rows are root-only URLs → a **discovery step** is mandatory before extraction.
- Unit of scraping = *listing page per domain*, NOT masterlist row. One rcpath.org
  events-listing source covers all 14 rcpath rows.

## 2. Task graph (DAG)

```
P0 Triage (deterministic script)
 └─► P1 Recon fan-out (agents, parallel ×186 domains)
      └─► P2 Wave planning (Commander, no agents)
           └─► P3 Onboarding factory (agent waves of 10–15)  ◄─ loops per wave
                ├─► P4 CI scale-up (once, after wave 1)
                └─► P5 Accuracy gates (per wave, blocking)
```

### P0 — Triage script (no LLM, ~free)
Parse CSV → `Conference_masterlist/triage.json`: dedupe rows by domain, tag
already-covered domains, group by provider, rank by row-count (proxy for value).
Output = ordered work-list of net-new domains.

### P1 — Recon fan-out (Workflow, parallel agents)
Per new domain, one cheap agent answers:
1. Canonical events/courses listing URL (check nav, `/events`, `/courses`, sitemap.xml).
2. Platform family: WordPress + Tribe Events API · EventsAir · Salesforce LWC ·
   Nuxt/SPA · static HTML · PDF-only · none-found.
3. Volume estimate (# upcoming events), pagination style, JS-render needed?
4. Red flags: login-wall, no dated events, courses-as-PDF, dead site.
Output: structured recon record per domain → `Conference_masterlist/recon.json`.
Domains with "none-found / dead / login-wall" → parked list for manual review, not silently dropped.

### P2 — Wave planning
Rank into onboarding waves:
- **Wave 1 — royal colleges & faculties** (rcpath 14 rows, rcsed 12, resus 12, rcpe,
  rcophth, rcpch, rcpsych, rcpsg, ficm, fph, fom, fsem, fpm, rcoa, e-lfh, alsg…): ~20 domains, covers ~150 rows.
- **Wave 2 — platform-family batches**: all Tribe-Events/WordPress domains share the
  proven BOPA/BTOG extractor path; EventsAir domains share RCOG path; etc.
- **Wave 3+ — long tail**: single-event society sites (baus, bofas, bssh, …ca. 60 domains,
  1 row each) via generic/LLM-fallback extractor.

### P3 — Onboarding factory (the autonomy core)
Architecture rule: **platform-family extractors, not 186 bespoke modules.**
- New `extractors/families/`: `tribe_events.py` (exists via BOPA — generalise),
  `eventsair.py`, `wordpress_generic.py`, `static_listing.py`; bespoke only for
  flagship/high-volume sources. `fallback.py` (LLM) remains the last resort.
- Per source, follow `extractors/PLAYBOOK.md` 4-step protocol:
  add `scraper_sources` row → extractor (family or bespoke) → local test run →
  audit gate pass → remediator pass.
- Waves of 10–15 sources; each wave ends with the P5 gate before the next starts.

**LESSONS enforced** (from HQ LESSONS.md + project memory):
- #4: every LLM-soft field gets a deterministic heuristic backstop (specialty_classifier etc.).
- #5: `listing_hash` stamped only when soft-field extraction succeeded.
- Rate limits: 150+ new sources × LLM calls will hit NVIDIA per-IP limits in CI —
  stagger scrape schedule + keep LLM calls minimal (families are deterministic).
- feedback-scope-fixes-narrowly: source-specific bugs get source-specific fixes.

### P4 — CI scale-up (once)
- `scrape-daily.yml`: move from 1-job-per-source (23) to **grouped matrix**
  (~8–10 sources per job, alphabetical bucket) — stays under GH free-tier
  concurrency (20 jobs) at 200 sources; stagger 01:00–03:00 UTC.
- Remediator (04:00) + alerts (03:00) + reminders (08:00) already `--all`; they pick
  up new sources automatically.
- New: weekly **source-health report** job — sources with 0 successful scrapes in
  7 days or audit score regression → flagged in a committed markdown report.

### P5 — Accuracy gates (per wave, blocking)
1. SQL null-audit on LLM-derived fields — >10% NULL = wave fails (LESSON #4 rule).
2. Audit-gate score per source ≥ existing threshold; failing source → `active=false`
   quarantine, never silently-wrong data.
3. Spot-check: 5 random events per new source vs live site (dates, price, venue).
4. Frontend check: new specialties/currencies render correctly on localhost:3001.

## 3. Agent & model routing

| Task | Executor | Model tier (ENFORCED via explicit `model:` override — LESSONS #7) |
|---|---|---|
| P0 triage script | direct (no agent) | — |
| P1 recon (×186) | Workflow fan-out, cheap agents | `haiku`, low effort |
| P2 wave plan | Commander (main loop) | session model |
| P3 extractor code | coding agents, 1 per source/family | `sonnet`; `opus` where genuinely hard (anti-bot, multi-layout — e.g. FICM/RCoA Cloudflare) |
| P3 test/audit runs | Bash (local venv) | — |
| P5 gates | script + 1 verifier agent per wave | `haiku`, low effort |

> ⚠ Deviation log: P1 recon batch 1 (top-20) ran on the session model at low effort, not Haiku — caught by user 2026-08-15, correction logged as HQ LESSONS #7. Wave-1a build fleet restarted on `sonnet`. All later stages must carry explicit model overrides.

## 4. Cost & credentials

- No new credentials. Existing: NVIDIA (KIMI_API_KEY), Supabase service key, GH Actions secrets.
- £0 external spend. Cost = tokens + GH Actions minutes (grouped matrix keeps
  free tier viable). NVIDIA rate limits are the binding constraint, not money.

## 5. Risk flags

- **Root-URL discovery failure** (~10–20% of domains expected): parked list + manual review, not guesswork.
- **e-lfh.org.uk (10 rows)** is an e-learning platform, not events — likely out of scope; recon will confirm.
- **onexamination.com** is exam prep — likely out of scope.
- **Provider-type rows (38)** point at course catalogues without dates — may need
  `event_type='course'` + course_sessions model (proven on RCSEng source 5).
- GH Actions total runtime: 200 sources × ~2–4 min ≈ 10–13 h serial → grouped
  parallel ≈ 45–90 min wall-clock. Acceptable.

## 6. Status ledger

| Phase | Status |
|---|---|
| P0 Triage | ✅ 2026-08-15 — `triage.py` → `triage.json`: 202 domains = 16 covered / 184 new / 2 out-of-scope |
| P1 Recon (batch 1: top-20) | ✅ 2026-08-15 — 20/20 returned: **18 resolved · 1 parked (fsem) · 1 out-of-scope (rcemlearning)** → `recon.json`. Remaining 164 domains deferred (resume `wf_62a1042e-bd3` with higher N). |
| P2 Wave plan (batch 1) | ✅ see recon summary below — 15 easy server-rendered + 3 needing Playwright/stealth (cosrh, rcoa, ficm) |
| P3 Wave 1a (ALSG 24 · RCPSG 25 · RCPath 26 · RCPsych 27 · RCSEd 28 · Resus 29) | ✅ 2026-08-16 — **GATE PASSED.** 328 active events/courses live. Soft-field nulls 0–3% (LESSON #4 gate <10%). All feeless rows live-£-screened (RCSEd 3 TBC, RCPath 47 free/external — verified). Fixes shipped: RCPSG browser-reuse + fail-honest override; RCSEd 6 fee layouts + competition skip; shared abstract-classifier keyword guard (HEST/Expedition false positives). User decisions: rcemlearning=out, fsem=parked. |
| P3 Wave 2 (platform families) | ⬜ |
| P3 Wave 3+ (long tail) | ⬜ |
| P4 CI scale-up | ⬜ |
| P5 Gates | ⬜ per-wave |

---

# MISSION R — LLM resilience (opened 2026-09-20, status: APPROVED 2026-09-20 — executing)

**Brief:** scrape must run reliably without silent failure. Trigger: all 4 configured
NVIDIA models (text, 2 backups, vision) EOL'd 2026-08-26 → every LLM call has 410'd
for 25 days while CI stayed green. 4th EOL in 5 months (LESSONS #6) → architecture fix, not another swap (LESSONS #3).

| # | Task | Executor / model | Status |
|---|---|---|---|
| R1 | Rotate: text `nvidia/nemotron-3-super-120b-a12b`, vision `meta/llama-3.2-11b-vision-instruct` (config.py, vision.py, .env, 2 workflows) | direct | ⬜ |
| R2 | Model fallback chain: `KIMI_MODEL_CHAIN` env, on 410/404 advance to next model and remember it for the run | coding agent · `sonnet` | ⬜ |
| R3 | Fail loud: `probe_models.py` + daily pre-scrape workflow step; whole chain dead → job fails red (GitHub emails owner) | coding agent · `sonnet` | ⬜ |
| R4 | Verify: local run source 2 (RCSEng) + source 11 (vision fees) → push → manual CI run → SQL null-audit on soft fields (LESSONS #4) | direct + `haiku` verifier | ⬜ |
| R5 | Backfill: clear `listing_hash` on rows created/changed since 2026-08-26 with NULL soft fields so they re-extract (LESSONS #5) | direct (SQL, user-approved) | ⬜ |
| R6 | Docs: CLAUDE.md banner (29 sources, new models), memory, LESSONS #6 addendum | direct | ⬜ |

Cost: £0 — stays on NVIDIA free tier. No new credentials. Optional later: second free provider as last link in the chain (needs one new key).
Risk: 11B vision model may be weaker on complex fee tables than the retired one → R4 tests it on the RCR fee image before trusting it.
