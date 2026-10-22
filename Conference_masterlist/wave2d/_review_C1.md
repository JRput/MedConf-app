# Wave 2d review: batch "2d-C1 intl_multi" (ids 134-138)

Reviewer: w2d-review-C1. Date: 2026-10-22. Harness run once per source (`--details 3`), live checks by curl.
Class names confirmed: EularExtractor, PcronlineExtractor, SiuUrologyExtractor, EshreExtractor, NihrExtractor.
All five files `py_compile` clean. No FAILs.

## Summary

| slug | verdict | shells (mine/builder) | registration |
|---|---|---|---|
| eular (134) | PASS-with-notes | 19/19 | active (fix items 1-3 first if cheap) |
| pcronline (135) | PASS | 12/12 | active |
| siu_urology (136) | PASS-with-notes | 2/2 | active |
| eshre (137) | PASS | 10/10 | active |
| nihr (138) | PASS (placeholder) | 0/0 | inactive |

## eular · PASS-with-notes · harness shells 19/19 · spot checks verified: 4

Verified live:
- Antalya "Intermediate MSUS Course": listing says `2026-10-27 23:00:00` UTC, event page says Wednesday 28 October 2026 to Friday 30 October 00:00 (Europe/Zurich). Extractor gives 28 Oct start and 29 Oct end (exclusive midnight end handled). UTC to Zurich conversion is correct (CET after 25 Oct).
- Belgrade MSUS Basic: 22-24 Oct 2026, Belgrade, Serbia. Organiser page reumatologija.org.rs prints "Registration fee 850 EUR" and "Registration fee & accommodation 1250 EUR". Harness output matches (2 tiers, EUR).
- 9th EULAR Imaging Course 2027 on edu.eular.org (id 857): "Cost: EUR 300" and "8 April 2027". Matches the stored single date and tier.
- Listing walk: 2 pages, 19 cards, same titles, places and UTC datetimes as the builder's list.

Security convention: OK. External hops go through `check_url_safe` then `fetch_validated` with a 30 s deadline and 2 MB cap (eular.py:296). Hostname checked with `urlparse().hostname` (eular.py:265). No `fetch_html` or browser on external hosts. Organiser cap is 20 per run (eular.py:224, 292). The edu.eular.org hops are not counted against the cap but are bounded by the 19 events. No cross-imports (only `safe_fetch`, `.base`, `.http_fetch`, `.pricing_tables`). No rejected organiser host appeared in the harness, so no safe_fetch IPv6 issue was seen.

Request count on eular.org: 2 listing pages plus 19 event pages, about 21 (under 25).

Judgements:
- Template description ("EULAR-endorsed course: X from 22 October to 24 October 2026 in Belgrade, Serbia."): factual, built only from badge, title, dates and place. For placeholder events it reads "EULAR event: ... on 9 April 2027." Acceptable. Not invented.
- Real descriptions (5): none is a venue or contact line, the filters work. Quality is uneven: Belgrade is a "speakers will come from..." sentence, CECR Budapest is the opening of a welcome letter ("Dear Fellow Rheumatologists ... One year from now, we warmly invite you"), Athens and SARD-ILD are real course intros. Acceptable, not great.
- Placeholder courses (Epidemiology, Imaging, Postgraduate HP, Immunology 2027): they ARE emitted, with a single day (8 or 9 April 2027), no city, no venue, event_format empty. The date is not made up by the extractor: it is what the EULAR page shows and, for Imaging, what edu.eular.org prints ("8 April 2027"). But a multi-day course is collapsed to one day, and TBC/TBD location is correctly left empty. The builder disclosed this. Fine to register; the dates are indicative.

Issues (should-fix, none blocking):
1. Coverage miss on fees. Three unpriced events have public fee pages one click below the organiser landing page that the single hop does not reach: CECR Budapest `/registration-costs/` (delegate 400/500/600 EUR by period, non-member 500+, students 250-350), Athens MITOS course `/en/content/registration-information` (Basic and Intermediate 750 EUR), SARD-ILD Antalya `/registration-accommodation/` (package 1,350 EUR, one day 350 EUR). The PLAYBOOK checklist says to look at registration sub-pages. Not a FAIL (budget-capped, builder stated 11/19 priced), but 8 empty `pricing_tiers` are not fully justified. The remediator explorer may pick these up.
2. Athens description/date conflict. The two Athens courses (eular.org dates Wed 18 Nov 2026 to Fri 20 Nov 2026) get an organiser description reading "...in Athens, Greece, from 18th to 20st November 2027", and the organiser page also mentions "1 until 10 November 2027" for name changes while the URL is `mitoscourse2027`. So the EULAR listing year (2026) probably disagrees with the organiser's real year (2027), or the organiser has a typo. The stored date follows EULAR, the description says 2027. Suggest: drop an organiser description that contains a four-digit year different from the stored start year, and have the Commander flag these two rows to the owner.
3. Stale text in the deliverable: the module docstring (eular.py:1-16) and `source_row.extraction_instructions` still say "Third-party organiser sites are not followed" and "No prose description exists", but the code follows organiser links for descriptions and fees (up to 20 per run). The instructions are what a stranger acts on, so they should be rewritten (JSON edit only).
4. Minor: `event_format` is left empty for TBC/TBD events (fine), `venue_name` is never filled (the Odoo page has none). The 2 conference rows (CECR, SARD-ILD symposium) are classified by title regex; reasonable.

Registration advice: active. Items 1-3 are improvements, not blockers; do 2 and 3 if the file is still open before registering.

## pcronline · PASS · harness shells 12/12 · spot checks verified: 4

Verified live:
- Listing: 17 cards, 12 upcoming and dated. Undated "PCR Fellows Course | Paris", "The Physiology Course 2026" and the past Chengdu (11-13 Sep) and Transseptal (15-16 Sep) cards are skipped. `/Courses/PCR-Gulf-Valves` returns `302 -> /Courses/GulfPCR-GIM` (checked today).
- Alfieri's Bootcamp: card says 9-11 November 2026, page JSON-LD `startDate` is `2026-10-22T01:07:09+02:00` (stale). Extractor uses the card (2026-11-09..11). Correct.
- Fellows Course Singapore Register page: "1,020 SGD" (Fellow) and "1,270 SGD" (Physicians), Early column sold out, Regular on sale. Harness gives two SGD tiers, labels `Registration · Fellow · Regular` and `Registration · Physicians · Regular`. Correct.
- Alfieri `/Register-now`: "3400€ HT - 4148€ TTC". Extractor stores 4148 EUR. London Valves: Late 775 / 1490 / Digital 500 EUR in the harness, matches the builder's spot check.

Judgements:
- Hard-coded alias for PCR Gulf Valves: acceptable. The redirect is real today. Risk: if PCR later makes that card a distinct event, it stays dropped. A comment already says to extend `_ALIASES` for new redirects.
- Typing Fellows Course / Bootcamp / Pre-course / Innovators Day (<=3 days) as `workshop`: defensible under the 3-way rule, and the builder flagged it. I would prefer `course` for "Fellows Course" and "Pre-course on cardiogenic shock" (teaching programmes) and `workshop` for the Bootcamp. Low stakes, no change needed.
- Alfieri VAT-inclusive 4148: reasonable (it is the amount the delegate pays and London Valves is also printed VAT-included). Note that SIU in this batch is stored VAT-exclusive as printed (22% VAT extra). Each is "as printed"; no sibling convention in the brief.
- Registration href regex also matches `/user/register`, but the `startswith(course path + "/")` check rejects it. Fine.

Request count: 1 listing, 12 course pages, 7 Register pages, about 20 (under 25). Security: all same-site `fetch_html`, no external hops.

Registration advice: active.

## siu_urology · PASS-with-notes · harness shells 2/2 · spot checks verified: 3

Verified live:
- `/events` blocks: 96 and 98 (Residents' Hub, "April 30 2026", Various), 90 (SIU Regional Meeting, "November 20-21, 2026", Wuhan, China), 92 (eGrand Rounds, "February 12,2026", Online), 93 (Urotrainer Uro-Oncology Programme, "August 31-November 21", Remote). The only `/congress-YYYY/` links are for 2026.
- Congress registration page tables: In person regular Member high/upper-middle 950, Non-member 1,150; Virtual Non-member 350. Early column deadline July 15, passed, dropped. Harness gives 22 tiers, regular only, EUR, labels like `In person · Member: High and Upper-Middle Income Country · Regular`. Matches.
- Congress shell: Florence, Italy, 11-14 Nov 2026, 46th, venue "Fortezza da Basso" in harness. Matches the highlights page sentence.

Judgements on filters: sound. Residents' Hub posts are hub posts (past date, "Various"). eGrand Rounds is past. Urotrainer is a 10-week remote programme that started 31 Aug, so it is dropped by the "started and longer than 7 days" rule; the page does not itself say enrolment is closed, but a started 10-week cohort programme is not something a user can join. The rule is somewhat arbitrary but safe. Regional Meeting: event text is only "eGrand Round 2026" so description, venue and fees are empty; justified, no organiser link on the page.

Notes:
- The page says "Fees are quoted in Euros and are subject to 22% VAT"; the stored tiers are the ex-VAT figures and no tier label says so. Minor; consider noting in the description or tier label if the Commander wants consistency with pcronline.
- The Regional Meeting is typed `conference` by default; fine.
- A Congress sentence change on `/highlights` makes the Congress shell vanish with a WARNING (disclosed). Source is thin: 2 events.

Request count: events + highlights + general-information + registration = 4. Security: same-site only.

Registration advice: active (low volume, correct data).

## eshre · PASS · harness shells 10/10 · spot checks verified: 4

Verified live:
- Calendar (`/en/Education/Calendar-Campus-events`, a 301 to `/Education/Calendar-Campus-events` that `fetch_html` follows): 9 workshops with the same titles, dates (e.g. "30-31 October 2026", Florence) and places as the builder. Plus the 2027 Annual Meeting = 10 shells.
- Florence workshop Registration page: Member 305/427, Allied 183/305, Non-member 549/671 EUR; early rate "until 30 September" is over, so only Standard (427 / 305 / 671) is stored. Harness matches. Venue "Grand Hotel Baglioni", "maximum of 8.5 European CME credits" confirmed on the page.
- Malaga "Building safer ART teams" fee table: early "27 April" (350/250/550 standard). Adolescent (Athens) in the harness has early deadline 2027-02-18, early 250/150/450 and standard 350/250/550; Uppsala decimal-comma prices parse as 312.5 / 437.5 and so on.
- Annual Meeting 2027: `/Annual-Meeting` says "43rd ... held from 4 to 7 July 2027 in Stockholm, Sweden." The ESHRE-2027 page names venue Stockholmsmässan and has no fee page or registration link, so empty tiers are justified.

Judgements:
- Hybrid for Campus workshops: justified. The calendar page says "ESHRE Campus workshops are being organised to be in-person events with live broadcast", and the fee tables are headed "inclusive livestream & on-demand". Annual Meeting stored in_person with is_flagship. Good.
- Budapest "fully booked": the card class still says `places-available`, the extractor catches it from the detail page text. Good.
- Fixed specialty "Obstetrics & Gynaecology" is acceptable.

Request count: calendar, Annual-Meeting, 9 workshop pages, 9 Registration pages, Annual Meeting page = 21 (under 25). Same-site only.

Registration advice: active.

## nihr · PASS (placeholder, as intended) · shells n/a · spot checks n/a

- JSON `status` is `blocked`, `source_row.active` is `false`, `spot_check` empty, `probe_results` all zero, concerns state the CloudFront 403 from home and runner and that nothing was tested. Honest.
- `nihr.py` compiles and imports; it is a constants-only `WordPressGenericExtractor` subclass using attributes that exist on the family (LISTING_URL, SOCIETY, DEFAULT_SPECIALTY, PREFER_DEFAULT_SPECIALTY, DEFAULT_CURRENCY, EVENT_LINK_RE). The docstring says untested. I did not fetch nihr.ac.uk.

Registration advice: inactive (register only if wanted as a parked row; do not activate).

## Cross-cutting

- Shared files: `git status` shows no modified helper, `__init__.py` or workflow from this batch. Tracked modifications are `Conference_masterlist/wave1d/mddus.json` and `reports/remediation/learned_patterns.json` (both already dirty at session start). Untracked extras outside the batch are other agents' files. safe_fetch.py, test_safe_fetch.py and enrich_submissions.py are not in the current tracked-diff list (already fixed or committed by the other agent); ignored as instructed.
- No safe_fetch rejection was observed for edu.eular.org or the Belgrade organiser host during the harness run.
- `source_row` keys are exactly the 2c set in all five JSONs.
- VAT convention is not uniform across the batch (PCR inclusive, SIU exclusive, others unstated). Each matches what the site prints.

## For the Commander to decide

1. eular Athens (two rows): EULAR lists 18-20 Nov 2026 but the organiser material points to November 2027. Keep EULAR's date and drop the 2027-dated description, or hold the two rows until checked.
2. Whether to have the eular builder add a second hop to organiser registration/fee sub-pages (CECR, MITOS, SARD-ILD) or leave it to the remediator.
3. Whether to refresh eular's `extraction_instructions` before registration (recommended; it contradicts the code today).
