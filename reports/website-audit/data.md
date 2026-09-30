# MedConf Data & Feature-Opportunity Audit

Generated 2026-09-30. Read-only query against Supabase project `zcpszfbmvfylicpxgsfc` via the scraper's service-role client (`medconf-scraper/database.py`). All figures below are live counts, not samples.

**Scope:** `conferences` where `archived = FALSE` → **N = 1,194** live listings. Supporting tables: `pricing_tiers` (5,056 rows), `course_sessions` (706 rows), `scraper_sources` (45 rows, 45 active sources — higher than the 23 quoted in CLAUDE.md; the project has grown since that doc was last updated), `user_profiles` (1 row), `saved_conferences` (3 rows), `notification_preferences` (1 row), `notifications` (39 rows), `user_reminders` (0 rows).

---

## 1. Live inventory

### By `event_type`
| type | count | % |
|---|---|---|
| conference | 708 | 59.3% |
| course | 288 | 24.1% |
| workshop | 198 | 16.6% |

### By `event_format`
| format | count | % |
|---|---|---|
| in_person | 656 | 54.9% |
| online | 446 | 37.4% |
| null | 57 | 4.8% |
| hybrid | 35 | 2.9% |

### By month of `start_date`, next 12 months (today = 2026-09-30)
81 rows have null `start_date` (mostly courses whose real dates live in `course_sessions`, not the parent row).

| month | count |
|---|---|
| 2026-10 | 282 |
| 2026-11 | 320 |
| 2026-12 | 107 |
| 2027-01 | 72 |
| 2027-02 | 68 |
| 2027-03 | 63 |
| 2027-04 | 38 |
| 2027-05 | 32 |
| 2027-06 | 26 |
| 2027-07 | 13 |
| 2027-08 | 7 |
| 2027-09 | 11 |
| (2026-03/06/07/08 + 2027-10..2028-12) | 52 (long tail, mostly stragglers/on-demand) |

Heavily front-loaded: Oct+Nov 2026 alone = 602 events (50.4% of all live listings).

### City (top 15; 43.3% null — 517/1194)
London 258, Glasgow 54, Edinburgh 53, Liverpool 16, Manchester 15, Lugano 12, Singapore 10, Birmingham 9, Cardiff 9, Sheffield 9, Belfast 8, Leeds 7, Bristol 7, Milan 7, San Diego 7.

### Region (top 15; 60.0% null — 716/1194)
London 216, Scotland 96, North West England 31, Yorkshire & Humber 19, Wales 13, California 12, West Midlands 9, South West England 9, South East England 7, Northern Ireland 7, East Midlands 6, Canada 5, England 5, Italy 4, North East England 3.

### Specialty
**138 distinct values**, 1.3% null (16/1194). Full breakdown and a proposed normalization map are in [Section 5](#specialty-normalisation-map).

### Source society (top 20 of 45 active sources)
RCGP 241, RSM 81, RCPsych 75, RCP 68, RCPSG 68, RCPath 62, ESMO 61, RCSEd 58, MDDUS 57, RCR 42, RCSEng 41, AACR 35, RCPCH 34, RCEM 33, RCPE 31, RCoA 27, ACPGBI 25, RCOG 24, Resus Council UK 21, FPH 14.

### UK vs. international (heuristic on region/city text — no explicit country column)
- UK-ish: 481 (40.3%)
- International/other: 713 (59.7%)

This is a meaningful shift from the "UK-first" framing in CLAUDE.md — **60% of live listings are already non-UK**, driven by the international oncology flagships (ASCO, ESMO, AACR, ESTRO, SABCS, ESGO, SITC) plus growing society coverage (ARVO, IAS, MDDUS/MDU as of the wave-1d sources on main).

### Flags & feature fields
| field | count | % |
|---|---|---|
| is_flagship | 55 | 4.6% |
| is_on_demand | 16 | 1.3% |
| cpd_accredited | 541 | 45.3% |
| cpd_points not null | 423 | 35.4% |
| abstract_open = true | 38 | 3.2% |
| abstract_deadline set | 57 | 4.8% |
| is_sold_out | 39 | 3.3% |
| has ≥1 pricing_tier | 744 | 62.3% |
| course_sessions (on 288 course parents) | 706 rows | — |

### Pricing currency mix (5,056 `pricing_tiers` rows)
GBP 4,236 (83.8%), EUR 451 (8.9%), USD 338 (6.7%), SGD 21 (0.4%), HKD 10 (0.2%). No CHF/BRL rows despite schema supporting them.

---

## 2. Field completeness (% non-null, over the 1,194 live rows)

| column | % non-null |
|---|---|
| conference_name | 100.0% |
| source_url / organiser_url / booking_url | 100.0% |
| event_type / is_sold_out / cpd_accredited / abstract_open / is_on_demand / is_flagship | 100.0% (booleans/NOT NULL, default-heavy) |
| description | 99.6% |
| specialty | 98.7% |
| event_format | 95.2% |
| start_date / end_date | 93.2% |
| city | 56.7% |
| venue_name | 51.6% |
| region | 40.0% |
| cpd_points | 35.4% |
| start_time | 30.1% |
| abstract_deadline | 4.8% |
| abstract_deadline_note | 0.9% |
| on_demand_original_date | 0.0% |

**Reliable card fields:** name, description, specialty, format, dates (for non-course rows). **Unreliable, need graceful fallback:** city/venue/region (>40% null), cpd_points (65% null), start_time (70% null), abstract_deadline (95% null).

---

## 3. Text quality

### Description
- n = 1,189 non-null (99.6%)
- Length distribution: min 16, p25 141, **median 233**, p75 297, max 700 chars.
- <60 chars: 2 rows (0.2%) — negligible.
- Junk markers (cookie/css/js/disclaimer/copyright substrings): 5 rows — negligible, extraction pipeline is clean here.

Median 233 chars is close to 2 short sentences — too long for a card teaser as-is but not garbage; cards need a truncate-to-1-line (~80-100 char) treatment, not a raw dump.

### conference_name
- Length: min 6, p25 34, **median 48**, p75 62, max 181.
- ALL CAPS names: 9 (negligible).
- Names with a trailing year (e.g. "...2026"): **220 (18.4%)** — card titles need either de-duplication of the year against the date badge, or accept the redundancy.

p75/max (62/181 chars) means card layouts must handle 2-3 line titles gracefully — a single-line-with-ellipsis title is not enough for ~25% of rows.

---

## 4. Users & personal features

The product has **exactly 1 real user** (the builder's own test account, specialty=Oncology, role=Registrar, region=East of England, profile completed 2026-06-11).

- `saved_conferences`: 3 rows, all from that 1 user.
- `user_reminders`: 0 rows — the reminder feature has never been used.
- `notification_preferences`: 1 row, defaults untouched (email toggles are UI-disabled anyway per CLAUDE.md).
- `notifications`: 39 rows, all `type='new_in_specialty'` (the daily 03:00 UTC specialty-alert cron), 32 unread (82%) — the user isn't opening the bell.

**This means every "personalization" number below is a sample size of 1** — there is no real usage signal yet on which personal features matter. Any redesign decision about dashboard/saved/reminders is a bet on the concept, not validated by data.

---

## 5. Specialty normalisation map

138 distinct values with clear duplication from free-text extraction (UK vs US spelling, "&" vs "and", parenthetical variants, singular/plural). Proposed canonical taxonomy (raw → canonical), covering every near-duplicate cluster found:

| raw value(s) | canonical | combined count |
|---|---|---|
| Child and Adolescent Psychiatry | Child & Adolescent Psychiatry | 7 |
| Surgery (12), Surgery (General) (7), Surgery (RCS) (6) | General Surgery | 34 (merges into existing 34 "General Surgery" bucket → 68 total under one label) |
| Minor Surgery (11), Minor Surgery & Procedures (7) | Minor Surgery & Procedures | 18 |
| Sexual and Reproductive Health (5), Sexual & Reproductive Health (2) | Sexual & Reproductive Health | 7 |
| Obstetrics & Gynaecology (24), Obstetrics and Gynaecology (1), Obstetrics and Gynecology (2) | Obstetrics & Gynaecology | 27 |
| Otolaryngology (5), Otolaryngology (ENT) (1), ENT (2), ENT (Ear, Nose, and Throat) (1), ENT Surgery (2) | ENT / Otolaryngology | 11 |
| Respiratory (3), Respiratory Medicine (1), Paediatrics and Respiratory Medicine (1) | Respiratory Medicine | 5 |
| Gastroenterology (6), Gastroenterology & Hepatology (1) | Gastroenterology | 7 |
| Geriatric Medicine (4), Geriatrics (2) | Geriatric Medicine | 6 |
| Rehabilitation Medicine (1), Rehabilitation (1) | Rehabilitation Medicine | 2 |
| Palliative Medicine (3), Palliative Care (1) | Palliative Medicine | 4 |
| General (4), General Medicine (4), General Internal Medicine (1), Internal Medicine (2) | General Medicine | 11 |
| Trauma & Orthopaedics (4), Orthopaedics (5), Orthopaedic Surgery (1) | Trauma & Orthopaedics | 10 |
| Dental and Maxillofacial Radiology (2), Dentistry and Maxillofacial Imaging (1) | Dental & Maxillofacial Radiology | 3 |
| Medical Leadership (34), Leadership & Management (51) | Leadership & Management | 85 (kept as one bucket — both describe non-clinical CPD content) |
| 心血管内科 (1, Chinese for "Cardiovascular Medicine") | Cardiology | 13 (merges into existing 12 "Cardiology") |

After merging, the ~138 raw values collapse to roughly **95-100 canonical specialties**, plus the true long tail of single-occurrence subspecialties (Cardio-Oncology, Uropathology, Craniofacial Surgery, etc.) that should map to a broader parent for filtering (e.g. "Oncology" superset already exists at 125, with Clinical Oncology/Surgical Oncology/Radiation Oncology/Gynaecological Oncology/Cardio-Oncology as children).

**Recommendation:** build a two-level taxonomy — ~20-25 parent specialties (matching medical college structure: Surgery, Medicine, Oncology, Psychiatry, Paediatrics, O&G, etc.) each with an optional subspecialty tag, plus an explicit "Other" bucket for the singleton values. Filter UI shows parents; detail page can show the raw/sub value.

---

## 6. Ten data-driven product observations

1. **Non-UK is now the majority (59.7%)** — the "UK CPD directory" framing in the product brain is stale. Filters, copy, and onboarding (which still defaults `country = 'United Kingdom'`) should treat international as a first-class case, not an add-on.
2. **Format matters but isn't a clean 3-way split** — in_person 54.9% / online 37.4% / hybrid 2.9% / null 4.8%. A hybrid-aware filter (not just in-person-vs-online toggle) is warranted, and the null 4.8% needs an "unspecified" state rather than being silently excluded.
3. **62.3% of events have pricing data, 37.7% don't** — a price filter/sort needs an explicit "price not available" bucket rather than treating null as $0 or hiding the event.
4. **Specialty has 138 raw values with heavy near-duplication** — ship the normalization map in Section 5 before building a specialty filter chip UI, or ~40% of the long tail will look like noise/typos to users.
5. **City/region are the weakest location fields (43%/60% null)** — location-based filtering/search cannot rely on structured city/region alone; needs a fallback to free-text venue_name or a "location TBC" state, especially for the 37% of events that are online anyway (where location is meaningless).
6. **cpd_points is null on 65% of rows** — CPD point tracking (a stated core value prop) only has data for a third of listings. Either push harder on extraction for this field or reframe the CPD feature as "accredited: yes/no" (cpd_accredited is populated at 100%, cpd_points is not) rather than promising point totals everywhere.
7. **Events are heavily front-loaded into the next 8 weeks** (Oct+Nov 2026 = 50.4% of all live listings) — the "browse everything" list view will feel imbalanced; a calendar/timeline view or default sort-by-soonest matters more than long-range date filtering.
8. **Median description is 233 characters** — long enough to need truncation on cards (1-line summary, ~80-100 chars) but short enough that full descriptions are fine on detail pages without a "read more" affordance being critical.
9. **18.4% of titles already contain a trailing year** — card design must not duplicate the year in both title and date badge, or dedupe it (e.g. strip trailing "20XX" from title display when a date badge is shown).
10. **Personal features have essentially zero real usage** (1 user, 3 saves, 0 reminders, 82% of alert notifications unread) — a redesign should not assume dashboard/saved/reminders are validated must-haves; treat them as unproven bets and prioritize the directory/discovery experience (which has 1,194 real rows of signal) over personalization polish (which has none).

---

## Data files
Raw pulled rows are cached at `/private/tmp/claude-501/.../scratchpad/raw.json` for this session only (not committed, not part of the repo).
