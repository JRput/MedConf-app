# single_congress.py family gaps (found by batch 2d-S, 2026-10-21)

Input for a later family fix. Nothing in `single_congress.py` was edited; each gap lists the sources hit, the failing input, and the workaround used.

## 1. parse_place on "Venue, City, Country"
- Sources: ean, rsna, bofas, bpna, acc, ueg, aaic, asahq (also chestnet/auanet via "City, ST").
- Input: `Gothia Towers, Gothenburg, Sweden` gave `(None, None, 'Sweden', False)`; venue and city lost.
- Workaround: `list_shells_override` sets `shell["venue_raw"]`; subclass `parse_place` splits 3 comma parts (venue, city, country or 2-letter state -> United States). Fix: have `parse_place` return all three parts.

## 2. Listing path ignores meta-description dates, detail path reads them
- Sources: auanet (also ean).
- Input: home page has no dated body line; only `<meta name="description" content="The OFFICIAL site of the AUA Annual Meeting 2027, May 21 – 24, 2027 in San Diego,CA. ... Be sure to register ...">`. `find_edition(html, lines + meta)` returned None because the segment also contains "register" (matches `_NOT_EVENT_SEG_RE`), so 0 shells.
- Workaround: `_edition_from` override extracts `Month d – d, yyyy in City, ST` and feeds a synthetic header line. Fix: let `_edition_from` try meta lines and strip trailing sentences before the not-event test.

## 3. Year-less, "to"-form or oddly spaced date lines; body sessions before the congress dates
- ean: body line `Sunday, 13 June 2027, 10:30 – 12:30 (CEST)` (Presidential Symposium) is found before the real dates, which only occur in the meta description `will be on 12-15 June 2027, in Gothenburg, Sweden`. Result: 13 Jun, one-day. Workaround: synthetic line from og:description.
- chestnet: `October 18 to 21 | CHEST Annual Meeting` with year only in `CHEST 2026: See What's on the Horizon`; family found nothing and followed a "CHEST 2026" link to chestphysician.org (news site). Workaround: bespoke `_edition_from` (header + year, then "save the dates" list `2027: October 24-27 | Vancouver, BC, Canada`).
- bofas: `BOFAS 2026 will be held in Wales from 4th to 6th of November` (day-first, ordinals, year before dates). Workaround: regex -> synthetic `4-6 November 2026 | Wales`.
- asahq: `ANESTHESIOLOGY 2027 | October 15- 19 | Boston, MA | Thomas M. Menino Convention & Exhibition Center` (space after hyphen, pipe-separated). Workaround: regex -> synthetic line + venue_raw.
- aao: current page is the finished edition (`Thank you for joining us at AAO 2026`); a content-access date `March 1, 2027` was taken as the edition (one-day, wrong). Workaround: bespoke parser of the "Future Meetings" list (`AAO 2027` / `Las Vegas, Venetian Expo & Hotel` / `Nov. 12-15: AAO 2027`). Fix idea: reject single-day "edition" dates that sit inside access/recording sentences.
- aaic: first header line `AAIC | July 18-21, 2027 | Alzheimer's Association` is chosen, so the organiser became the city; real place is the next line `Chicago, United States, and Online`. Workaround: venue_raw from header lines + "Conference Location" block.

## 4. "Abstract Submission Opening" read as a deadline
- Sources: ean.
- Input: key-date table rows `Public Abstract Submission Opening | 29 October 2026` and `Abstract Submission Deadline | 14 January 2027`. The apply_abstracts filter only drops single-date entries whose label matches `\bopens?\b`; "Opening" slips through, giving abstract_open True, deadline 2026-10-29.
- Workaround: ean `apply_abstracts` reads opening/deadline explicitly. Fix: match `open(?:s|ing)?`.

## 5. Dates before labels in key-date tables (early-registration date taken as abstract deadline)
- Sources: asn_online.
- Input: Important Dates table lists `Wednesday, September 9` then `Early Registration Rate Ends (11:59 p.m. EDT)`, and `Wednesday, May 13` then `Abstract Submission Site Closes`. `key_date_entries` pairs the other way, so the family output abstract_deadline 2026-09-09 (early registration end).
- Workaround: asn_online `apply_abstracts` pairs date-line-then-label. Fix: detect table orientation (date lines matching weekday/month first) in `key_date_entries`.

## 6. abstract_open True when the closing date is future but submission has not opened
- Sources: aaic (opens Dec. 7, 2026, closes Jan. 18, 2027), ean (after #4), asahq (Scientific Abstracts: January 5 - March 30, 2027).
- Family sets `abstract_open = deadline >= today` only. Workaround: per-source override comparing the opening date with today. Fix: carry an opening date from key_date_entries.

## 7. Fee matrices mislabelled by generic_fees
- rsna: three matrices (member packages as text, tables with columns In Person & Virtual / In Person Only / Virtual Only / Technical Exhibits Only). Generic output labels such as `Registration · Members in Discount-Eligible Countries` repeated with different prices, `for Non-Members · Scientist · Virtual Access Only`. Workaround: `fees_from_pages` over raw `<table>` cells.
- chestnet: `/registration-information` stacks 2025 and 2026 blocks with tier names as rows and price inside the label. Output: `$689 Registration Only (Nonmember) · Member Rate · July 14 - Oct. 5 at 11:59 pm ET` = 1339 (price/label crossed). Workaround: return [] (partial). Needs a bespoke parser once the next table is live.
- acc, asn_online, bpna, bofas: no usable generic output (0 tiers or none found); bespoke table/PDF parsers used. acc: `<h2>` package + `<table>` with `<th scope=row>` categories; asn_online: `<h4>` + table Early/Standard/Onsite; bpna: one cell per line, MEMBER/NON-MEMBER markers; bofas: fee table is a PDF (read with pypdf via abstract_classifier._default_fetcher).

## 8. html_lines drops repeated consecutive cells
- Sources: rsna (`$600 | $600` collapsed to one line, hiding a column).
- Workaround: parse raw `<table>`. Fix: don't `dedupe_consecutive` amount-only lines.

## 9. Relative nav links under a path without trailing slash
- Sources: auanet (`/AUA2027` with nav links `key-dates`, `register/join-and-save`, `for-exhibitors`).
- `_discover` resolves them against the site root: `https://www.auanet.org/for-exhibitors` and `/abstracts/abstract-guidelines` 404 (3 retries each). Workaround: explicit REG_URLS/ABSTRACT_URLS. Fix: join against `url + "/"` when the last path segment has no dot.

## 10. Nav-link discovery misses "Booking Details" and year-specific sub-pages
- bpna: nav link `../2027/index.php?contentid=1381` text "Booking Details" not matched by `_REG_LINK_RE` -> 0 tiers. asn_online: `2026/register-overview.aspx`, `2026/important-dates.aspx`. Workaround: detail_from_html sets `self.REG_URLS` / `ABSTRACT_URLS` from the page links. Fix: widen link text patterns (booking details, register overview, important dates).

## 11. Stale-edition text leaks into the next edition's row
- Sources: ueg, asahq, chestnet, aao. When the home page is the finished edition and the next one is a footer block, description, CME, abstract and fee pages belong to the old edition (e.g. `UEG Week 2026 is accredited by the EACCME for 26.5 credits`; `AUA...` n/a). Workaround: per-source fees_from_pages guards (require the edition name+year on the fee page), dropping cpd/abstract fields, one-sentence descriptions. Fix: a family-level "page year != edition year" guard on description, CPD, abstracts and fee pages.

## 12. Description picks legal or nav text
- auanet: first paragraph is "Restrictions on use of AUA ... content in third party applications, including artificial intelligence". Workaround: meta-description sentence. Fix: extend the disclaimer filter (restrictions on use, prohibited from using, artificial intelligence).
- ueg: platform blurb `This is your hub for UEG Week during October 15 (14:00 CEST) until November 13`; asahq/bofas generic nav copy. Workarounds per source.
