# Wave 2d review, batch "2d-B uk_static_lo" (ids 123-129)

Reviewer: independent. No product file edited, nothing committed. Today 2026-10-21. All 7 modules py_compile clean.
Harness run once per source (`--details 3`); no `--force-fallback` re-run by me (builder reports identical shell counts).
Result: 0 FAIL, 6 PASS-with-notes, 1 inactive placeholder (endocrinology). One substantive data-quality issue (SBNS "Free" tier).

## endocrinology (123) · PASS (as blocked placeholder) · harness not run (blocked) · spot checks n/a
- JSON: status "blocked", source_row.active false, concerns state Cloudflare managed challenge on runner and home IP. Not fetched by me.
- endocrinology.py compiles; constants-only WordPressGenericExtractor subclass (class EndocrinologyExtractor confirmed), docstring says untested.
- Registration advice: INACTIVE. Register only as an inactive row (or skip) so id 123 is reserved; retry from a runner later.

## bsir (124) · PASS-with-notes · harness shells 6 / builder 6 · spot checks verified 2 (+2 extra)
- Verified live: ASM "4th-6th November 2026, Birmingham" matches 2026-11-04..06; ASC 2027 "Monday 26th & Tuesday 27th April" matches 2027-04-26..27 (Monday confirmed); webinar "Thursday 12th November 18:30" matches.
- IOUK 2027: page says "Thursday 10th and Friday 12th June"; 10 June 2027 is a Thursday, 12 June a Saturday, so the page is wrong (almost certainly the 11th). Storing only 2027-06-10 with end=start is the safe choice; PASS. The source will self-correct when the society fixes the page.
- VITALS fee spot check (builder row) and ASM grid (Early 450 until 17 Sep / regular 510) consistent with the extractor output seen in the harness.
- Issues:
  - bsir.py (detail_from_html, region assignment): `region` is "United Kingdom" for every city; siblings use the nation (England/Scotland/...). Minor.
  - Webinar "Unpacking Drug-Coated Technology in PAD" typed `conference`; webinars elsewhere in this wave are `workshop`. Minor.
  - The crawl is hub + about 12 series/sub pages + details, roughly 20-25 requests per scrape at 1 s gap: at the edge of the 25 cap, acceptable for a daily job. My own review (harness + one list re-run) exceeded 25 on this site.
  - VASIG-UK ends today and drops out tomorrow (correct behaviour).
- Registration: active.

## bmfms (125) · PASS-with-notes · harness shells 14 / builder 14 · spot checks verified 2
- URLs confirmed: /professionals/events and /date/2026/ both give 12 rows, /date/2027/ gives 4 rows, /date/2028/ gives 0 rows. 12 + 4 = 16 rows; minus the 15 Oct webinar (past) and the duplicate "Recognising & Responding to Maternal Deterioration" on 10 Dec = 14. Count correct. `?page=` indeed absent.
- Verified: Beyond the CTG 21 Nov 08:30 - 22 Nov (extractor 2026-11-21..22); Annual Conference 5-7 May 2027 Edinburgh matches. Perinatal Symposium 7 Dec 14:00-18:00 listed, builder's GBP 10 fee not re-fetched.
- Commercial Paris rows: "5th International Conference on Primary Care and Global Healthcare" (19-20 Apr 2027) is NOT maternal-fetal medicine and is a generic promoter conference: recommend dropping it (title filter or per-URL skip). "5th International Conference on Gynecology and Obstetrics" (22-23 Apr 2027, Paris) is on-topic specialty but the same promoter style: borderline, my advice is drop both or keep only the second with the Commander's explicit OK. Other third-party rows (BICS, ISOM/MOMS, Advances in Fetal Medicine, Advanced Fetal Anomaly Scan Valencia) are on-topic and fine.
- Issues:
  - bmfms.py:184 event_type from title only: "Recognising & Responding to Maternal Deterioration" and "Fetal Imaging & Beyond" come out `conference`; acceptable, no better signal on the page.
  - 3 of 14 rows have pricing (rest fees on external organiser sites, organiser_url set): justified.
- Registration: active, after the Primary Care Paris row is excluded (hold if the Commander wants it done first).

## brit_thoracic (126) · PASS-with-notes · harness shells 25 / builder 25 · spot checks verified 2
- Shell list reproduced: 25 shells, 25 distinct source_urls (dedupe by URL works; hub carousel duplicates are gone). Mix: 15 short courses, 3 meetings (Winter 2026 page, Summer 2027 and Winter 2027 from the dates page), 2 webinars, 5 third-party rows.
- Verified live: Advanced Practice in Pulmonary Rehabilitation fees "BTS Members: £130 / Non-Members: £130" (extractor 130/130); meeting-dates page "2027: Summer Meeting 24-25 June, Newcastle; Winter Meeting 24-26 November, London" matches.
- Third-party table: live page "Other Respiratory Courses" says BTS advertises events by relevant worldwide professional societies, UK lung charities and healthcare establishments, and states "BTS does not accredit or endorse courses ... unable to promote commercially organised events". The 5 rows (Canadian Long-Term Ventilation conference, World Congress of Bronchology, three Kettering General Hospital courses) are genuinely respiratory and non-promoter. Keep; but they are listed, not endorsed, so make sure no description wording says "endorsed".
- Issues:
  - 2028/2029 meeting dates deliberately not emitted (18-month horizon): fine.
  - First webinar is dated today (21 Oct) and expires tomorrow: fine.
- Registration: active.

## rheumatology (127) · PASS · harness shells 7 / builder 7 · spot checks verified 2
- Verified live: the listing card still says "28-30 April 2026"; the detail page (after redirect to /annualconference) says "Date 28-30 April 2027, Liverpool Experience Campus and Online, 22 credits, Register your interest". Extractor output 2027-04-28..30, hybrid, Liverpool, 22 CPD. Stale-card handling is correct. Empty tiers justified ("Register your interest").
- Case-based conference (3-4 Nov, Southampton Novotel, Members Level 1 £314 ex VAT) matches harness output.
- Notes: scope widened to courses and webinars (documented). Fees are ex VAT and say so in the label. Webinar typed `workshop`, courses `course`.
- Registration: active.

## bapm (128) · PASS-with-notes · harness shells 15 / builder 15 · spot checks verified 3
- Verified live: Spring Conference 9-10 Mar 2027 (extractor 2027-03-09..10); NeoNATE Bristol "18-19 March 2027" matches the inferred "two day" end; EventsAir tiers: In-person Early Nurse/AHP 121, Consultant 204, Late Consultant 264, Virtual Early Consultant 147, Late Consultant 189 all match the live page (more than the 3 requested). Early-bird deadline 2027-01-31 present.
- End dates: all 15 shells either carry a stated duration ("one/two/4 day") or fall back to start=end; none invented. Detail page range overrides the card.
- Issues:
  - Tier "Virtual · BAPM Pub Quiz 0.0" is a social item, not an attendance fee; and the label "Virtual · BAPM Member Consultant 10 March only · Late" mixes date text into the category. Cosmetic, but drop the pub quiz tier.
  - Cross-source overlap with BMFMS (see cross-cutting).
  - Specialty fixed to Neonatology, no classifier rule: acceptable.
- Registration: active.

## sbns (129) · PASS-with-notes · harness shells 11 / builder 11 · spot checks verified 3
- Listing: calendar has 12 event cards; SBNS 100 (ended 16 Oct) is dropped by date, leaving 11. Count correct.
- PDF path verified live on SBNS 100: registration sub-page has an /asset/<id>/ link; GET returns HTTP 200, application/pdf, 161,990 bytes, starts with %PDF-1.7; `pdf_bytes_to_text` + `fee_tiers_from_pdf_text` give 54 tiers, first "Full Meeting Attendance (4 days) · SBNS Full Members & International HIC Consultants · Early until 1 August" 650.0, deadline 2026-08-01. Glasgow 2027 has no registration sub-page yet (only a programme asset), so tiers [] is right.
- Binary fetch judgement (sbns.py:186-191): single httpx.get, timeout=20, follow_redirects, %PDF magic check, exception swallowed, no retry loop, runs once per flagship event. Acceptable in principle (binary asset, fetch_html cannot return bytes), but there is NO size cap: `r.content` buffers whatever the server returns. Condition for PASS: add a cap (stream and stop at about 5 MB, or reject Content-Length above it) before registration. Also it bypasses the browser fallback, so a runner-blocked host just yields [] (safe).
- DATA ISSUE, Neuroradiology Workshop "Free" tier: the SBNS page ticket widget does say "Free" and the page shows 10-11 November 2026, RCSEd Edinburgh, but the Book Now link goes to services.rcsed.ac.uk, which lists "Course Fee £500.00" and "Member/Fellow Course Fee £450.00". Storing a £0 tier is therefore misleading to users. Recommend: when the page has an external Book Now link (organiser_url) and the only tier is "Free", store no tier (or skip the Free tier entirely) and let the remediator follow organiser_url. This is the only shell with pricing, so the fix is one line at sbns.py:252-253.
- Other points: "6th International Neurosurgery and Neurological Surgeons Conference" (14-15 Dec 2026) looks like a generic promoter event, same pattern as the BMFMS Paris rows; Commander may want to filter. Venue for Glasgow "Double Tree by Hilton" (site: "The DoubleTree by Hilton") minor spacing.
- Registration: active after the Free-tier fix and the PDF size cap; hold otherwise.

## Cross-cutting
- git status: no shared helper, __init__.py, workflow, or batch S/D file modified by this batch. Pre-existing modifications not from this batch: wave1d/mddus.json and reports/remediation/learned_patterns.json; untracked medconf-scraper/all.json and probe_headed_results.json (seen in the opening status, not this batch). baaps files were no longer modified when I checked.
- Imports: every module imports only shared helpers or wordpress_generic/tribe_events/pricing_tables/abstract_classifier; no cross-per-source imports, no DB, no secrets. No parallel fetching; one time.sleep gap per fetch (1 s).
- Duplicate events across sources: BMFMS and BAPM both list Beyond the CTG (21-22 Nov), the Perinatal Symposium (7 Dec) and BICS / British Intrapartum Care Conference (12 Nov). Different source_urls so both rows will be inserted. The Commander should decide whether to accept duplicates or dedupe in the merge step.
- Promoter-style conferences slip into BMFMS and SBNS; a shared "known promoter" filter may be worth discussing, per-source filters are the narrower fix (feedback_scope_fixes).
- Politeness: BSIR and BTS crawls each need about 20-25 requests per scrape; fine daily. My cumulative requests per site in this review exceeded 25 for bsir, brit_thoracic, bmfms (harness plus re-listing plus spot checks).
- Commander decisions: (1) drop or keep BMFMS Primary Care Paris row; (2) SBNS Free tier and PDF size cap before registration; (3) accept BMFMS/BAPM duplicates; (4) keep endocrinology as inactive row 123.
