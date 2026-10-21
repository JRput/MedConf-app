# Wave 2d review, batch "2d-D js_browser_first" (bsg 130, boa 131, escrs 132, ics 133)

Reviewer: independent. No product file edited, nothing committed. test_ems_calendar.py: 9 passed. All five modules py_compile clean.
Harness run once per source (`--details 3 --coverage`), plus BOA `--force-fallback` (31 shells, same as normal).

Overall: registration blocked only by one stray file (medconf-scraper/boa_full.html). Otherwise 1 PASS, 3 PASS-with-notes, 0 FAIL on code.

## bsg · PASS-with-notes · harness shells 19 / builder 19 · spot checks verified 2
- Verified: Clinical Endoscopist Conference (09-11-2026; in-person members 50, non-members 50, virtual 25 GBP, all match the live "Registration fees" block). HPB symposium (13 Nov, 50 / 100) matches output.
- Issues:
  - bsg.py:21 imports private `_UK_PLACES` from ems_calendar although BSG is not an Eventfolio site; move to a neutral helper later.
  - Coverage checker SINGLE_DAY_SUSPECT on the HPB symposium; live page shows only 13 Nov, judged a false positive.
- Registration: active.

## boa · PASS-with-notes · harness shells 31 (normal) / 31 (force-fallback) / builder 31 · spot checks verified 2
- Verified: New Consultants Course (13-14 Nov 2026, Smith & Nephew, BOA Member 100 GBP in widget); 2027 Annual Congress line (14-17 Sep, ACC Liverpool).
- Measured coverage over all 31 shells (about 35 requests, above the brief's 25 cap): date 31, pricing 9, venue-or-online 31 (25 physical venues), description 25, specialty 31, cpd 1, organiser_url 22. Builder estimated venue 24 and description 24; correct the JSON to venue 25, description 25.
- Filter judgement: sound for purpose (cardiology forum and probiotics expo rightly dropped). The deconditioning course and falls-prevention summit are ortho-geriatric and BOA lists them itself: recommend RELAX. boa.py already has a second regex (`_ORTHO_RE`) containing falls/deconditioning used only for specialty; reuse it in `is_relevant` and add osteoporosis, frailty, rehabilitation, amputee, limb. A keyword whitelist silently drops unseen relevant titles, so log dropped titles each run (count only is logged now).
- Issues:
  - boa.py:34 and :38 two overlapping regexes; `_RELEVANCE_DESC` unused.
  - Foundations in Surgical Leadership and Core Skills in Orthopaedic Surgery typed `conference`; they are a multi-week programme and a course.
  - Consultants-course page text says "£95 course fee" but widget says "£100"; extractor uses the widget. Site inconsistency, noted only.
  - Stray untracked medconf-scraper/boa_full.html (not an allowed file): delete. Also untracked in medconf-scraper/: all.json, probe_headed_results.json (not traced; may belong to other batches).
- Registration: active after boa_full.html removed and JSON counts corrected.

## escrs · PASS-with-notes · harness shells 5 / builder 5 · spot checks: harness output compared with builder rows only, live pages not re-fetched
- Output seen: Vision to Venture Budapest 30 Oct-1 Nov, 3 EUR tiers; Winter Meeting Cairo 17-20 Mar 2027, no fees.
- Load-more path (escrs.py:152-163) read: live default page has 7 cards and no button (the string LoadNextButton occurs only in a script). The check uses the id attribute so the script does not trigger it. `browser.navigate` and `browser.page` exist (browser.py:78-93). Loop capped at 8 clicks, exits when the button is removed, any exception falls back to the first page with a warning. No obvious error; only weak point is the fixed 2.5 s wait, and a click on a hidden button would wait the full default timeout before falling back.
- Issues: Hellenic congress SUBMISSION_NO_DEADLINE warning (external organiser, organiser_url set, accepted). "Marriot" spelling copied from the site. Status `partial` is honest (no fees for annual events).
- Registration: active.

## ics · PASS · harness shells 13 / builder 13 · spot checks verified 2
- Verified: Leadership Programme 11 Nov 2026 members 215, non-members 315 GBP (live widget). SOA27: 29 Jun-1 Jul 2027 ICC Birmingham, abstract deadline 2027-02-15 match.
- Image fees: SOA27 detail has `pricing_tiers == []` (no invented fee) and `organiser_url = https://ics.ac.uk/events/soa27/tickets.html` (returns 200). Confirmed.
- Notes: abstract_open True is correct (opens 15 Oct 2026). Coverage checker SINGLE_DAY_SUSPECT on the FUSIC HD assessment day not traced.
- Registration: active.

## Cross-cutting
- No shared-helper or workflow edits seen from this batch.
- Family module ems_calendar.py is coherent; BOA and ICS share it cleanly.
- Single-day warnings on one ICS and one BOA row not traced.

## Commander decisions
1. Delete medconf-scraper/boa_full.html (and decide on all.json, probe_headed_results.json).
2. Approve relaxing the BOA relevance filter (recommended) and logging dropped titles.
3. Correct boa.json with_* counts to venue 25, description 25.
4. Optional: move `_UK_PLACES` out of ems_calendar so bsg.py does not import a private name from another family.
