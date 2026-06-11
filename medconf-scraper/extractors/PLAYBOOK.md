# Per-Source Extractor Playbook

A working notes file capturing the patterns we keep hitting when building per-source detail-page extractors. Every new source we onboard goes through roughly the same checklist; this document codifies it so the next extractor takes 15 minutes, not an hour of trial-and-error.

---

## When to add a new extractor

Whenever `scraper_sources` gets a new active row that the FallbackExtractor doesn't handle accurately. Symptoms in the DB:

- `pricing_tiers` empty when the source clearly publishes prices
- `venue_name` / `city` / `region` null on most rows
- `event_format` stuck on `null` or wrong
- `cpd_points` always null while the source page shows them
- `description` is fabricated rather than summarised from page text

Each is a sign the source's HTML structure isn't being read correctly by the generic LLM path.

---

## Two layouts: single-page vs multi-page detail

Before building, classify the source's detail URLs into ONE of two layouts:

### Single-page detail (the usual)
Each event's detail URL renders a self-contained page with all the info — pricing tables, venue, dates, abstract status, all on one URL. Example: `engage.rcgp.org.uk/event/<id>`, `rsm.ac.uk/events/<faculty>/<year>/<slug>/`, `rcseng.ac.uk/news-and-events/events/calendar/<slug>/`.

**No special configuration needed.** Build a normal per-source extractor.

### Multi-page detail (flagship conferences with their own subsite)
Each event has a homepage that's mostly marketing — the actual data is on sub-pages like `/tickets`, `/programme`, `/programme/poster-abstract-submissions`, `/overview/why-attend`. Example: `rcgpac.org.uk` (RCGP Annual Conference).

**Configuration:**
1. In the `scraper_sources` row, set `detail_is_multipage = TRUE`.
2. The `FallbackExtractor` automatically walks same-domain sub-pages and concatenates text. URL allowlist:
   - **Visit**: `programme`, `ticket`, `venue`, `location`, `abstract`, `poster`, `overview`, `speakers`, `registration`, `whats-on`, `faqs`, `info`, `highlights`
   - **Skip**: `cookie`, `privacy`, `terms`, `accessibility`, `sponsor`, `exhibit`, `contact`
3. Capped at 8 pages per event. Adds ~15-30 sec per event in the cloud.

**How to detect during the probe phase:**
- Homepage has <2K chars of *real* content after stripping nav/footer
- Has 10+ same-domain navigation links with "info-looking" paths
- Things like prices/dates/abstracts are absent from the homepage but the page has a "Tickets" / "Programme" link

If a source has BOTH layouts within one site (like RCGP — most events are single-page via engage.*, but the Annual Conference is multi-page via rcgpac.*), handle the split inside the per-source extractor with URL-based branching, as `extractors/rcgp.py:_extract_rcgpac` does.

---

## The four-step build

### 1. Probe the listing page

Goal: confirm `browser.get_event_cards()` already extracts shells correctly for this source, OR identify what selectors need adding to it.

```bash
./.venv/bin/python -c "
from browser import BrowserController
b = BrowserController(); b.launch()
b.navigate('<source listing URL>')
b.page.wait_for_timeout(5000)
cards = b.get_event_cards()
print(f'{len(cards)} cards')
for c in cards[:3]: print(c)
b.close()
"
```

Check for:
- Card count matches what's visible on the page
- Each card has a real per-event `booking_url` (not the listing URL itself)
- `start_date`, `start_time`, `is_sold_out`, `location_hint` populate where the listing displays them
- No false positives (page-header containers, footer items)

If something's missing, the fix is usually in `browser.py:get_event_cards()` rather than the per-source extractor — that function is shared across all sources.

### 2. Probe ONE event detail page

Look at the rendered DOM for the fields that matter. Write a small probe script:

```python
diag = page.evaluate("""() => {
    return {
        # Pricing markup
        priceTables: document.querySelectorAll('.<source-pricing-class>').length,
        priceItems: document.querySelectorAll('.<source-item-class>').length,
        # Venue
        locationHeading: !!Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6'))
                          .find(h => /^location$/i.test(h.textContent.trim())),
        # CPD
        cpdMentions: (document.body.textContent.match(/CPD/gi) || []).length,
    };
}""")
```

The questions that always matter:
- What's the CSS class of the pricing container? (BEM-style classes like `m-price-table` are gold)
- Are prices in nested cells with labels, or flat in `<td>` with `data-th` for the role? (The two layouts we've seen on RSM)
- Where's the venue/address? (Almost always under a `Location` heading or in an `<address>` tag)
- Is there a tabbed UI for member/non-member? Are tabs in DOM at once or lazy-loaded?

### 3. Probe TWO MORE event detail pages with DIFFERENT shapes

This is the step we've been burned by skipping. **One source can have multiple layouts.** RSM uses:
- **Layout A** for multi-day events: `<div class="m-price-table__item">` + `<small class="__label">` per cell
- **Layout B** for single-fee events: `<td data-th="RoleName">£X</td>` flat, no item wrapper

Always probe at least:
- A multi-day priced event (Trauma Symposium pattern)
- A single-fee event (Cybersecurity pattern)
- A **free** event (e.g. a free webinar or member-only lecture) — pricing tables may exist but contain only £0 / "Free"
- An **online** webinar — venue handling may differ

If Step 2 only checked one shape, Step 3 will usually surface a new layout. Build the extractor to handle all of them.

### 4. Write the extractor module

File: `extractors/<source_slug>.py`. Subclass `BaseExtractor`. Implement `extract_detail()`.

Structure that has worked well:

```python
class XYZExtractor(BaseExtractor):
    def extract_detail(self, page, shell, llm_call):
        return {
            **self._extract_pricing(page),       # deterministic
            **self._extract_venue(page),         # deterministic
            **self._extract_cpd(page),           # regex
            **self._extract_dates(page, shell),  # regex / fallback to shell
            **self._extract_soft_fields(page, shell, llm_call),  # LLM (description + specialty)
        }
```

Each `_extract_*` method should be small, testable, and return a partial dict (so `**` merging works). The LLM call is one method, focused only on the genuinely-unstructured fields.

Then add to the registry in `extractors/__init__.py`:
```python
EXTRACTOR_REGISTRY = {
    1: RCGPExtractor,
    2: RCSEngExtractor,
    3: RSMExtractor,
    4: XYZExtractor,   # ← new line
}
```

---

## Patterns we keep needing — copy these

### UK postcode regex (catches almost all of them)

```python
UK_POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$")
```

Always strip postcodes before picking the city from a comma-split address. Otherwise "London, W1G 0AE, United Kingdom" picks "W1G 0AE" as the city.

### Heading-based DOM lookup beats text-flatten regex

If the field has a clear semantic heading on the page, find that heading and walk forward through siblings. Far more robust than `body.textContent.match(/Label.../)` because flattened text has multiple "Location" / "Date" / etc. occurrences from different page sections.

```js
const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6'));
for (const h of headings) {
    if (/^location$/i.test((h.textContent || '').trim())) {
        // Walk forward
        let cursor = h.nextElementSibling;
        let collected = '';
        while (cursor && !/^H[1-6]$/.test(cursor.tagName)) {
            collected += cursor.textContent.trim() + ' ';
            cursor = cursor.nextElementSibling;
        }
        return collected.trim();
    }
}
```

### `textContent` vs `innerText`

`innerText` respects CSS visibility — it skips collapsed `<details>`, hidden tabs, `display:none` content. `textContent` reads everything. **Always use `textContent` for pricing/venue/CPD extraction** — these often live behind tabs or accordions that aren't open by default.

### URL-depth check for non-event pages

Some sources have listing-page cards that link to faculty/year/topic pages instead of an actual event. Filter by URL depth in `get_event_cards`:

```js
// RSM real events: /events/<faculty>/<year>/<slug>/  (4+ segments)
// RSM faculty pages: /events/<faculty>/<year>/        (3 segments — skip)
const segs = u.pathname.split('/').filter(Boolean);
const eventsIdx = segs.indexOf('events');
if (eventsIdx >= 0 && segs.length - eventsIdx <= 3) continue;
```

### Two pricing layouts coexist within a source

Always check `len(items_layout_A) == 0` and try Layout B as a fallback in the same extractor. Don't write two separate extractors for the same source.

### Region inference for UK cities

The schema has a `region` field but most source pages don't print it explicitly. A small lookup table (`London → London`, `Manchester → North West England`, etc.) covers ~80% of UK cities. See `RSMExtractor._infer_uk_region` for the canonical list.

---

## Course-type sources (event_type = 'course')

Most existing sources publish ONE event per row — a conference on fixed
dates. Course-type sources publish ONE offering that runs on MANY dates
("Trauma Refresher: 14 Oct · 21 Nov · 12 Feb"). The data model splits
the parent (the course's shared metadata) from its child rows (the
scheduled sessions).

### Data shape

```
conferences (event_type = 'course') — the course itself
  + course_sessions[]                 — one row per scheduled run
    - start_date / end_date / start_time
    - duration_text         ("3 days", "Half day", "6 evenings")
    - availability_status   ('available' | 'limited' | 'sold_out' | 'unknown')
    - spots_left            (only when the source publishes a number)
    - booking_url           (per-session if it differs from the parent)
  + pricing_tiers[]                   — one of two shapes:
    - session_id = NULL → tier applies to ALL sessions (flat course pricing)
    - session_id = <uuid> → tier scoped to that one session (e.g. variable pricing)
```

The parent row's `start_date` should be set to the **earliest upcoming session's start_date** so the row sorts sensibly in the directory list view. The full date picture lives in `course_sessions`.

### When to flag a source as a course source

Add a row to `scraper_sources` with `default_event_type = 'course'`. The
per-source extractor then emits course parents + sessions. A source that
serves BOTH conferences and courses uses `'mixed'` and the extractor sets
`event_type` per row.

### What the extractor returns

In addition to the usual conference fields, a course extractor returns:

```python
{
    # ... all the usual conference fields (name, description, specialty,
    # CPD, format, venue, organiser_url, source_url) ...
    "event_type": "course",
    "sessions": [
        {
            "start_date": "2026-10-14",
            "end_date": None,
            "start_time": "09:00",
            "duration_text": "3 days",
            "availability_status": "available",   # or 'limited' / 'sold_out' / 'unknown'
            "spots_left": None,                   # set only when a number is published
            "booking_url": None,                  # only if it differs from parent
            "notes": None,
        },
        # ... more sessions
    ],
    # Pricing same shape as conferences. Add session_id only if the
    # source has per-session pricing.
    "pricing_tiers": [
        {"tier_label": "Member", "price_gbp": 295.0, "session_id": None},
        # ...
    ],
}
```

The scraper's upsert logic will:
1. Upsert the parent into `conferences` (by `source_url`).
2. Delete + insert child `course_sessions` rows for that course.
3. Delete + insert `pricing_tiers` rows (mixing flat and per-session as emitted).

### How to read availability text from a source page

Three patterns, in order of common-ness:

| Pattern | Example text | Map to |
|---|---|---|
| Plain labels | "Sold out" / "Book now" / "Fully booked" | `sold_out` / `available` |
| Limited-spots note | "Only 3 places left", "Last few spots" | `limited` + parse `spots_left` if possible |
| Live capacity widget | Booking iframe with seat count | `available`/`limited`/`sold_out` based on a numeric threshold (e.g. ≤5 → `limited`) |

If none of the above is unambiguously present on a session row, set
`availability_status = 'unknown'` — better than guessing.

### How to handle flat vs per-session pricing

- **Flat** (the common case): emit pricing tiers with `session_id = None`. One set of tier rows covers all sessions.
- **Per-session** (e.g. early bird per session): emit each tier row with the relevant session UUID. The frontend will display the tiers under the chosen session.

If unsure, start with **flat** and revisit if the source clearly shows different prices on different sessions.

### Reminders + saving

User-facing: a user **saves the course** (not a session), but **sets reminders on a specific session**. The schema already supports this — `saved_conferences.conference_id` references the parent; `user_reminders.conference_id` does too, with session info implicit in the reminder type/date. No schema changes needed when onboarding a course source.

---

## Soft-field architecture — every LLM-only field needs a deterministic fallback

The scraper used to treat `description` and `specialty` as LLM-only. That
broke any time NVIDIA's gateway 504'd: rows ended up with null fields,
and (worse) the listing-hash machinery stamped them as "done" so they
never retried. The cure is the same in every extractor:

| Field | Primary | Deterministic fallback |
|---|---|---|
| `description` | LLM summary (~50 words) | First paragraph of detail-page Overview, OR the listing card's `description_hint` (set automatically in the merge — RCGP, RSM, RCSEng all benefit) |
| `specialty` | LLM | `specialty_classifier.classify_specialty(title, body)` — already wired in every extractor |
| `venue_name` / `city` / `region` | Detail-page structured field (e.g. RCP `event-panel__item` Location, RCGP `Primary venue`) | Title-based city detection (RCP "Update in medicine – Exeter 2026") |
| `event_format` | Same detail-page field, OR listing-hint "Online" | Title regex for `online|webinar|virtual`; default to null only when genuinely unknown |
| `abstract_open` / `abstract_deadline` | `abstract_classifier.extract_abstract_info(text)` — already deterministic |

**Rule of thumb for new extractors:** when you reach for `llm_call`, also write
the fallback in the same method. Never `return {"description": None}` and
hope it'll get retried — the row will lock in.

## Self-healing for late-published source data

Sources often publish details progressively — RCGP, for instance, posts an
event months ahead with the venue still TBC, then fills `Primary venue`
later. The listing-hash check in `scraper.py` would normally skip those
rows forever (the listing card text doesn't change when the detail page
updates). It now re-fetches whenever:

- `event_format IS NULL`, OR
- `event_format = 'in_person' AND (venue_name IS NULL OR city IS NULL)`

So **as long as your extractor leaves these fields null when the data
isn't on the page yet**, the next nightly run will pick up the update
automatically. Don't fabricate values to "complete" a row — null means
"come back next time," and that's now first-class behaviour.

For online events you should set `event_format = 'online'` even when
venue/city are correctly null, so the row fast-skips on subsequent runs.

## Common mistakes we've made (don't repeat)

1. **Picking second-to-last comma part as the city** — that's the postcode in UK addresses. Always filter postcodes first.
2. **Regex on flat textContent for fields that have semantic headings** — too many false matches. Use DOM heading lookup.
3. **Probing only one event detail page per source** — every source has multiple layouts. Always probe 3+.
4. **Trusting `innerText` for tabbed/accordion content** — it doesn't see hidden text. Use `textContent`.
5. **Trusting any `<a>` in a listing card as the booking URL** — some cards link to faculty pages. Add URL-depth filters.
6. **Asking the LLM to extract pricing from prose** — it fabricates. Give it the rendered HTML structure or skip the LLM entirely for that field.
7. **Hardcoding selectors deeply nested in `if`/`else`** — split each field into its own `_extract_X()` method so unit tests can cover them individually.
8. **Forgetting to deduplicate** — pricing tables often have responsive shadow copies in DOM (mobile + desktop versions). De-dupe by `(tier_label, price_gbp)` after extraction.

---

## Testing a new extractor before re-scraping

Always run a unit-style probe first:

```python
from browser import BrowserController
from extractors.<source_slug> import <Source>Extractor

ex = <Source>Extractor({"id": <id>, "source_name": "..."})
b = BrowserController(); b.launch()

for url in [test_url_1, test_url_2, test_url_3]:
    b.navigate(url); b.page.wait_for_timeout(3500)
    print(f"--- {url} ---")
    print(f"  Pricing: {len(ex._extract_pricing(b.page))} tiers")
    print(f"  Venue: {ex._extract_venue(b.page)}")
    print(f"  CPD: {ex._extract_cpd(b.page)}")
b.close()
```

If all three pages return reasonable data, run the full `python main.py --run-now`. If one page returns garbage, fix before scraping the whole source.
