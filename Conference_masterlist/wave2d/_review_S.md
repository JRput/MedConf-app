# Wave 2d review, batch "2d-S single_congress" (ids 103-115)

Reviewer: independent. Date of review: 2026-10-21. No product file, JSON or shared file edited; nothing committed.

## Scope and global checks
- git status: no shared helper (single_congress.py, wordpress_generic.py, tribe_events.py, http_fetch.py, pricing_tables.py, abstract_classifier.py, __init__.py, base.py, browser.py, validator.py) and no workflow is modified. Tracked modifications are wave1d/mddus.json, wave2d/PLAN.md, reports/remediation/learned_patterns.json (not this batch).
- All 13 extractors py_compile clean. No LLM call, DB access or secret in any of them (specialty is a constant everywhere except baaps, which uses the shared classifier).
- source_row keys match the 2c brief for all 13 JSONs.
- Harness run once per source (aao skipped as instructed). Shell counts match the builders' for every source. Requests per site stayed well under 25.

## Per source

**ean** · PASS-with-notes · shells 1/1 · spot checks verified 3 · registration: active
- Verified live: fees 999 / 1,122 / 364 EUR (early / regular / virtual, non-member high income); abstract opening 29 Oct 2026; abstract deadline 14 Jan 2027.
- ean.py apply_abstracts correctly separates "Public Abstract Submission Opening" from the deadline.
- Note: description is call-for-abstracts promo text ("Submit an abstract!"), low quality.

**aaic** · FAIL · shells 1/1 · spot checks verified 1 of 2 · registration: hold until fixed
- Wrong abstract_deadline. Harness gives 2027-01-18. The live table at aaic.alz.org/abstracts/overview.asp is Date | Event: "Jan. 11, 2027 / Abstract and session submission closes (general deadline)" and "Jan. 18, 2027 / ... closes (ISTAART deadline)". The family key-date reader pairs a label with the date after it, so the general deadline is read as 18 Jan; the true general deadline is 11 Jan. Users would plan around a date a week late.
- Builder's spot check and extraction_instructions are also wrong ("opens 7 Dec 2026, closes 18 Jan 2027"). Submission opens "Mid November 2026"; 7 Dec is the Ambassador Program row.
- aaic.py:39 apply_abstracts takes the date after the "opens" label, which is 7 Dec (a different row). abstract_open is False today only by coincidence and would stay wrong from mid-November until 7 Dec.
- Fix: read the table's <tr> cells (date, event) directly. Dates, venue (McCormick Place, Chicago), hybrid format and the empty fees are correct and justified.

**auanet** · PASS · shells 1/1 (curl and harness both returned 200 from this IP, so the 403 caveat did not apply) · spot checks verified 2 · registration: active
- Verified live on /AUA2027/key-dates: "Abstract Submissions Due Monday, November 2, 2026, Noon EST" and "Registration Opens Wednesday, December 2, 2026". Dates and city match the meta description.
- No venue name and no fees published; both justified.

**aao** · PASS (static review only; aao.org not fetched) · harness not run · spot checks 0 (blocked) · registration: inactive
- JSON says status blocked, active false, as required. Edition parser reads the "Future Meetings" list and is sound.
- Note: list_shells_override re-fetches the same page it already read; harmless while inactive.

**rsna** · PASS · shells 1/1 · spot checks verified 3 · registration: active
- Re-parsed the live pricing page offline into 32 tiers. Verified 2,525 USD (non-member physician, in person + virtual), 1,315 USD (Basic member), 710 USD (discount-eligible countries).
- The Medical Imaging Professional and Resident rows have three prices because the fourth cell is a note; the mapping is correct. The $0 Full Access tiers are genuine (included in dues).
- Labels follow [Section] · [Category] · [Timeframe]; currency USD on every tier. No stale 2025 data (stale JSON-LD is ignored).

**chestnet** · PASS-with-notes · shells 1/1 (2026 edition, ends today) · spot checks verified 2 · registration: active
- Patched today to 22 Oct 2026 against the live HTML: parser returns 2027-10-24 to 2027-10-27 Vancouver via the save-the-dates list with future flag set. Switch logic is correct; the 02:00 UTC run tomorrow produces the 2027 row.
- In that state the row keeps dates and place only; fees_from_pages returns [] so nothing is invented. The 2027 fee table still needs a bespoke parser once published.

**bofas** · PASS-with-notes · shells 1/1 · spot checks verified 3 · registration: active
- Read the live rates PDF: 420 / 504 GBP (full member), 504 / 604 (non-member), 273 / 330 (trainee) all match.
- Note: expired "Standard rate until 31 Aug" tiers are kept with is_early_bird true and early_bird_deadline None although the date is in the label.
- Note: abstracts closed 1 June 2026 but no past deadline is stored.

**bpna** · PASS · shells 1/1 · spot checks verified 4 · registration: active
- Re-parsed the live Booking Details page into 51 tiers. Verified 561 GBP (physician member early), 727 GBP (non-member standard), 187 GBP (LMIC early), CPD 18 points.
- Abstract deadline 7 Sept 2026 and the "closed" state confirmed on the Call for Abstracts page. Early-bird deadline 2026-11-02 correct.
- Labels are four-part (section, category, member, timeframe); acceptable.

**acc** · PASS · shells 1/1 · spot checks verified 3 · registration: active
- Re-parsed the live rates page into 94 tiers; tables match. Verified 1,399 USD (PLUS physician member early), 999 USD (in-person physician member early), 799 USD (Expo only member). Early-bird year inference gives 2026-12-02 correctly.
- Late-breaking trials window 20 Oct to 1 Dec confirmed, so abstract_open true, deadline 2026-12-01 and the explanatory note are right.

**asn_online** · PASS · shells 1/1 · spot checks verified 3 · registration: active
- Verified 595 / 500 / 50 USD in the live fee tables and that Late-Breaking closes 2 Sept (main call closed 13 May; the reported deadline is the late-breaking close, acceptable).
- The Important Dates table lists the date before its label and the hook handles it. Meeting ends 25 Oct; the row should drop from the listing afterwards.

**asahq** · PASS · shells 1/1 · spot checks verified 3 · registration: active
- Verified the live line "ANESTHESIOLOGY 2027 | October 15- 19 | Boston, MA | Thomas M. Menino Convention & Exhibition Center" and "Scientific Abstracts: January 5 – March 30, 2027".
- The fees filter drops the 2026 registration page; CME text and the 2026 description are stripped. No stale fees leak.

**ueg** · PASS-with-notes · shells 1/1 · spot checks verified 3 · registration: active
- Verified the live block "UEG Week 2027 / October 16 – 19, 2027 / Bella Center Copenhagen, Denmark". The fee filter requires a 2027 mention and no 2026 mention, so no stale fees leak; abstract and CPD fields are stripped.
- Note: ueg.py:30 derives the city from the last word of the venue name; fragile for other venues.

**baaps** · FAIL · shells 4/4 · spot checks verified 3 · registration: active once the import is fixed
- Rule breach at medconf-scraper/extractors/baaps.py:27: `from .rcpath import _UK_REGIONS`. This imports a private name from another per-source module (rcpath.py). Copy the map into baaps.py or move it to a shared helper. Used at baaps.py:132, 134, 135.
- Relevance gate checked against the live /about/events/date/2026, 2027 and 2028 listings (6 upcoming rows): it keeps the four plastic-surgery or BAAPS-run events and drops the Singapore nursing congress and the Dubai healthcare conference. No genuine BAAPS event is dropped today.
- Minor: rhinoplasty tier labels such as "Registration · Booking Friday 6th Nov 2026" are not three-part because they pass through organiser ticket names.

## Cross-cutting issues
1. Family gap: key_date_entries in single_congress.py pairs a label with the date after it, so Date | Event tables are misread (aaic wrong; asn_online and ean needed hooks). Commander to decide whether to fix once in the family (detect a "Date | Event" header) or keep per-source hooks.
2. Builder notes can be wrong: the aaic spot check and extraction_instructions carry the wrong dates and must be corrected with the code.
3. Stray untracked files outside this batch (medconf-scraper/all.json, medconf-scraper/boa_full.html, "medconf moderator acc.rtf") should not be committed with it.

## Commander decisions
- aaic: send back for the table-cell fix, or register inactive.
- baaps: send back for the one-line import fix, then register active.
- family key-date fix versus per-source hooks (item 1).
- chestnet: accept a 2027 row with no fees until a fee parser exists.
