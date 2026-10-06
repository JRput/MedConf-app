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
| P3 Wave 1b — RCPE 30 · RCPCH 31 · RCOphth 32 · FPH 33 · FOM 34 · FPM 35 · ESC 36 · ACPGBI 37 · ASGBI 38 | ✅ 2026-09-26 — **GATE PASSED.** 143 active rows. Null desc/specialty 0.7 % (gate <10 %). Cloud run 36267394924 green 39/39, all nine found their full listing from runner IPs. Audit-gate fixes: RCPE boilerplate + abstract phrasing, RCPCH cookie-banner title (fallback path only), ESC venue prose, ACPGBI HTML leak. User decision: ACPGBI junk-title filter OFF (third-party calendar events wanted). Known: audit's "description shares no title token" check gave ~15 false flags — treat as advisory; remediator pricing fixer burns 400+ vision calls on image-less sources (ACPGBI) — needs a cap. |
| P3 Wave 1c — CoSRH 39 · RCoA 40 · FICM 41 | ✅ 2026-09-28 — **GATE PASSED for 39 + 41** (CoSRH 9 events, FICM 12; cloud-green). **Key finding:** the "Cloudflare blocks headless" wall was Playwright's default context (HeadlessChrome UA / no locale / 1280x720), configured per site — `browser.py navigate()` now rotates to a fresh alt-profile context on each challenge (clearance lasts ONE load per context). No headed browser needed. RCoA (40) INACTIVE: clears from a home IP but Cloudflare also blocks GitHub-runner IPs; 30 events kept until they expire. ASTRO blocks both profiles. Housekeeping shipped: grouped scrape matrix (5 groups), remediator split into the same groups (was timing out at 24/41 sources), vision-call budget 40/run, vision log truncation. Known flaky: BTOG SiteGround challenge (4 events). |
| P1 Recon batch 2 (remaining 164 domains, `haiku`) | ✅ 2026-09-21 — 126 resolved · 29 parked · 9 out of scope → `recon.json` now covers all 184 |
| P3 Wave 1d — ARVO 42 · IAS 43 · MDDUS 44 · MDU 45 | ✅ 2026-09-30 — **GATE PASSED** (cloud run green 5/5 groups, 44 active sources). +65 events (MDDUS 57). Cloud access probe (`probe_cloud_access.py` + `probe-cloud-access.yml`) showed only these 4 of 18 Cloudflare-parked domains are readable from runner IPs; the other 14 (ASTRO, AHA, HIMSS, ESSKA, EANS, ABN, USCAP, FACE, ESPNIC, IAS-adjacent…) block datacenter IPs → parked with reason. ARVO clears intermittently → 3-attempt retry. Also this cycle: FICM routing change (/index.php) fixed same day; remediator vision hangs capped (no SDK retries, 60 s, 15 images / 12 min per run). |
| P3 Wave 2 (platform families) | ⬜ planned 2026-09-30 — see §7 |
| P3 Wave 3+ (long tail) | ⬜ |
| P4 CI scale-up | ⬜ |
| P5 Gates | ⬜ per-wave |

---

# MISSION R — LLM resilience (opened 2026-09-20 · approved · delivered 2026-09-21)

**Brief:** scrape must run reliably without silent failure. Trigger: all 4 configured
NVIDIA models (text, 2 backups, vision) EOL'd 2026-08-26 → every LLM call 410'd
for 25 days while CI stayed green. 4th EOL in 5 months (LESSONS #6) → architecture fix, not another swap (LESSONS #3).

| # | Task | Executor / model | Status |
|---|---|---|---|
| R1 | Rotate models: text `nvidia/nemotron-3-super-120b-a12b`, vision `meta/muse-glimmer-30b` | coding agent · `sonnet` | ✅ `a6330aa` |
| R2 | Fallback chain `llm_client.py` — advance on 404/410 only, sticky per process, per-model max_tokens floors; 4 call sites wired | coding agent · `sonnet` | ✅ 9 offline tests; live failover from a dead model proven |
| R3 | Fail loud: `probe_models.py` as first job of `scrape-daily.yml`; dead chain → red run, scrape still runs | coding agent · `sonnet` | ✅ passed in CI |
| R4 | Verify in CI (LESSONS #4): full 29-source runs + SQL null-audit | direct | ✅ run 35542582495: 124 LLM calls OK / 1 rate-limited; null description 0.2 %, null specialty 3.1 % (gate <10 %) |
| R4b | **Found by R4:** Resus (403) + BTOG (202 challenge) blocked from runner IPs only → `extractors/http_fetch.py` browser fallback; hung BTOG job burned 6 h → `timeout-minutes: 60` | coding agent · `sonnet` + direct | ✅ Resus 22/22 via fallback in CI. BTOG 4/4 in final run 35566370240 (30/30 green) — but httpx was not challenged on that run, so BTOG's own-page fallback is proven locally (forced) only; watch the next challenged day |
| R5 | Backfill rows extracted while the LLM was dead (clear `listing_hash`) | direct | ✅ user-approved 2026-09-21 — 151 rows reset (other ~115 of the 266 had already re-extracted); backup in `reports/backfill/` |
| R6 | Docs: CLAUDE.md, project memory, HQ LESSONS #9 | direct | ✅ |

Cost: £0 external. GitHub Actions: 4 manual full runs (~30 jobs each) + one hung 6 h job.
Open risks: vision chain verified on a synthetic fee table only; NVIDIA can still retire a whole chain at once — the probe makes that loud, not impossible.

## 7. Wave 2 plan (2026-09-30) — **PAUSED by user 2026-09-30: website layout/UX/features work takes priority. Resume with "resume wave 2" (start 2a + 2b together, 14 sources).**

Pool: **124 resolved domains** not yet built (recon.json). By platform: wordpress_other 53 · static_html 34 · unknown 16 · spa 13 · tribe_events 4 · external_registrar 4. 30 need JS. Estimated volume ≈ 3,400 events (vs ~1,100 live today).

Order by value ÷ effort, gating each sub-wave in the cloud early (RCoA/ARVO lesson):
- **2a — Tribe Events API (4):** baets, aans, aagl, esp-pathology. One shared family extractor (BOPA already proves the API path). Cheapest win.
- **2b — high-volume bespoke (≈10):** uroweb (700), eanm (499), sccm (244), advance-he (210), ifosworld (160), idweek (100), isuog (76), ihi (75), b-s-h (50), acep (50). Each ≥ 50 events → worth a per-source agent.
- **2c — WordPress long tail (≈50):** try a `wordpress_generic` family extractor (post-type `/events/` + common card markup) on 5 sites first; promote to family if ≥ 3/5 need no bespoke code, else per-source agents in batches of 10.
- **2d — static HTML + unknown (≈50):** per-source agents in batches of 10, `sonnet`; CMS hints from recon (Drupal 6, lmsitestarterduke 5, DNN 4, Umbraco 3, EventsAir 6 → EventsAir family via RCOG path).
- **2e — SPA / external registrar (≈17):** browser-first; external registrars (BCS, BSPED, Rewired, Medical Protection) may be out of scope if the org hosts nothing itself.

Gate per sub-wave: harness twice → first scrape → remediator → audit (advisory: title-token and load-more checks) → null-audit < 10 % → cloud run green. Matrix: add a 6th/7th group as needed (≤ 10 sources per job).

---

# MISSION W — Website redesign (opened 2026-09-30 · **DELIVERED 2026-10-03**, merged to main `6690533`)

**Brief:** the site "looks too much like AI", the pill/card layout is inefficient, filtering is not up to scratch, information is dumped rather than presented. Add a personal calendar. Audits: `reports/website-audit/{ux,code,data}.md` + 13 screenshots.

**Decisions (user, 2026-09-30):** light mode default + dark mode toggle · dense rows on desktop, compact cards on mobile · calendar is personal only (saved events, signed-in users) · keep a separate homepage, redesigned · no marketing fakery, honest copy (global, 1,100+ events, 45 societies).

| # | Phase | Executor / model | Status |
|---|---|---|---|
| W1 | Design system: warm-neutral tokens (light+dark), Figtree/Inter/JetBrains Mono, shadcn/ui re-themed, domain primitives, `/design` tile | `opus` | ✅ teal accent chosen |
| W2 | Directory rebuild: `directory_events` view + facets RPC (migration applied via session pooler), server-side pagination, single filter surface, society-first rows, `/societies`, ⌘K | `sonnet` | ✅ 37 tests; undated-rows bug fixed |
| W3 | Personal calendar `/calendar`: custom month engine, spanning bars, interactive abstract-deadline markers, agenda + week strip, ICS feed | `opus` | ✅ 96 tests total |
| W4 | Detail page: sticky essentials, tabbed fees, sessions, related events, JSON-LD | `sonnet` | ✅ |
| W5 | Homepage (live numbers, closing soon, this month, browse by specialty/society) + auth cards | `opus` | ✅ |
| W6 | Dashboard / saved / settings / onboarding on the kit; alerts cron now taxonomy-aware | `sonnet` | ✅ |

Gate per phase: build in a worktree → Playwright screenshots at 390 / 768 / 1440 in both themes → Commander review → user preview on localhost → merge. Cost: £0 external (shadcn/Radix free). Skills: ui-ux-pro-max (design system generated 2026-09-30: accessible/clinical, avoid neon + AI gradients), emil-design-eng (polish), 21st.dev component patterns as reference.

**Mission W close-out:** every route on the token system (sweep: 9 routes × 3 widths × 2 themes, no legacy markup). Throwaway test accounts to delete in Supabase Auth: `medconf-w3-calendar-6a46d3@mailinator.com` + one W6 mailinator account (oncology registrar). Follow-ups parked: `user_reminders` markers on the calendar; tablet row density; W5 noted `country` is unknown for 479 events (recon/scraper gap, affects the UK/International filter counts).

**Next:** resume Wave 2 (§7) — say "resume wave 2".

---

# MISSION P — Pricing & submission coverage (opened 2026-10-04 — executing)

**Brief (owner):** prices are being missed across sources; "Price TBC" must mean the price is truly not published. Examples: KSUOG precongress course (ISUOG) has its fee table as an inline base64 PNG — not detected; BSH International Pathology Day has a poster competition with a submission date — not captured.
**Root causes found:** (a) the audit only flags missing prices when currency text is visible, so image-only fee pages are never flagged; (b) the explorer's image pass needs currency words within 600 chars and skips `data:` URIs; (c) the abstract classifier needs explicit open/deadline wording near abstract/poster; (d) several extractors miss on-page price text (audit: RCPSG 21 rows, Resus 13, Advance HE 8, uroweb 7).

| # | Task | Executor | Status |
|---|---|---|---|
| P1 | Survey every active row with 0 tiers | `sonnet`, read-only | ✅ 2026-10-05 — 675 rows: A text-missed 37 (Resus 13, RCPSG 8, ACEP 6) · B image 3 · C external site 87 (ACPGBI 17, FPH 10, ACEP 10, Advance HE 8, BSH 5) · D linked PDF 106 (SCCM 66) · E member-only 5 · **F truly none 403** (RCGP 135, ESMO 48, RCPath 45, EAU 40) · unfetchable 34 (RCoA/RSM/FICM/EventsAir). `reports/pricing/2026-10-05-survey.*` |
| P2 | Detection: image fee tables (data URIs), same-site registration links, two-hop external sub-pages, currency from image, free-event rule tightened | `sonnet` | ✅ `6ab6b45` (KSUOG 2492 → 2 USD tiers). Incident: 67 false £0 tiers on SCCM from 'complimentary' — reverted |
| P3 | Per-source fixes for text prices missed | `sonnet` ×3 | ✅ Resus `749da3f` (2 real; 11 were centre charges) · RCPSG `063f1c1` (8/8) · ACEP `a3c468b` (microsite fees) |
| P4 | Submissions: poster-competition / "submit posters" wording + submission deadline parsing in `abstract_classifier`; verify BSH 2532; scan all sources for the pattern | `sonnet` | ✅ `957f464` (BSH 2532 → 2026-10-27) |
| P5 | Gate: re-run remediator on affected sources; tiers before/after per source; "Price TBC" count must drop to P1's "truly none" bucket ± noise | direct | ⬜ |
| P6 | **Pipeline-level submission detection** (owner: Advance HE Teaching & Learning Conf 2027 has a call for papers + deadline in a linked PDF — missed; only 3/61 extractors call the abstract classifier): run `classify_submission` on every detail page in the merge step regardless of extractor; follow one call-for-papers PDF/portal link (bounded) and parse its deadline; audit flags "call for papers on page but no deadline" | `sonnet` | ✅ `6f56e50` |
| P7 | Submissions survey | `sonnet` | ✅ 722 conferences w/o deadline: 586 no programme · 35 missed (A 14 on page, B 17 elsewhere, C 4) — RCPsych 13, RCEM 11 · 99 unfetched. **0/35 healed by the remediator** → P8 |
| P8 | Why the 35 didn't heal → fix + re-run | `sonnet` | ✅ `7d83d4d` — 19/30 now carry a deadline/note (11 deadlines, 5 closed, 3 placeholder); 11 were survey false positives (RCEM nav item). 22 tests |
| P9 | PDF/DOCX fee tables in the explorer | `sonnet` | ✅ `acdf905` — bucket D was mostly a false positive (SCCM's 66 rows all linked an endorsement-application PDF; excluded); real fee PDFs (BSH) parse |
| P10 | Harness `--coverage` pre-registration gate reusing the audit detectors | `sonnet` | ✅ `50814f4` + `f8415be` |
| P11 | Remediator row rotation (`remediation_attempted_at`, never-attempted first) | `sonnet` | ✅ `22954c6` — SCCM backlog now drains ~8 rows/night; IFAD reached but still no tiers (JS-rendered fee section → P12) |
| P12 | External-site fees: diagnose + fix | `sonnet` | ✅ `af583fd` — 8/32 bucket-C rows on ACPGBI/FPH/BSH now priced (was 0); causes: fetch budget spent before the external link, link wording not picked, flat-text fees, NameError. Remaining 24: no fees on the external page (9 FPH member portal), JS-rendered or blocked. ESSIC/IFAD re-checked after |
| P13 | ACEP location fallback (API state-only → event page → microsite → organiser) | `sonnet` | ✅ `65e9884` — city 9→18, venue 1→7 of 39; 8 online; ~14 organisers publish no venue |
| P14 | Evidence-based LOCATION_ON_PAGE in coverage_checks + audit (+ linked booking/organiser page lookup) — PLAYBOOK row 9 | `sonnet` | ✅ `56a365e` |
| P15 | Explorer: microsite nav follow (General Info, Abstracts) + matrix fee-grid parser | `sonnet` | ✅ — ESSIC 2184: 0 → 16 EUR tiers, deadline 2026-07-30 |
| P16 | Advance HE £-flags (New Relic script text — fetcher now strips scripts for all sources), programme-page tiers, BAETS event_format | `sonnet` | ✅ — audit 48 → 98/111 |
| P17 | venue prose trimming (tribe/ESP/ISUOG), SCCM JS-rendered fee grid (2572: 21 tiers; 2575: 3), ISBT: no deadline published | `sonnet` | ✅ `8380273` |

**Wave 2a/2b gate (2026-10-06):** audit 46–59 re-run after P8–P15; null-audit 406 rows: 0.2 % null description, 0 % null specialty ✅. Group F added to both matrices; run 1 (37521017822): 13/14 green, AAGL red — AWS WAF 'Human Verification' not in the challenge regex (fixed `c4969a0` + in-page API fetch). Run 2 (37531074749): **all 6 groups green, 14/14 Group F sources succeeded** ✅ — **Wave 2a/2b CLOSED 2026-10-06. Mission P (coverage) closed**; residual audit SUSPECTs are genuine nulls (organiser publishes no venue/fee) or cosmetic.
