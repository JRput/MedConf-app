# MedConf — Visual + UX Audit

Scope: `/`, `/conferences` (unfiltered, filtered, mobile), `/conferences/[id]`, `/auth/login`, `/auth/signup`. Desktop 1440×900, mobile 390×844. Playwright, full-page PNGs. Source read: `src/app/page.tsx`, `src/app/conferences/page.tsx`, `src/app/conferences/[id]/page.tsx`, `src/components/conferences/{ConferenceCard,FilterPanel}.tsx`, `src/hooks/useConferences.ts`, `src/app/globals.css`.

Live data at audit time: **1,194 active rows** (707 conferences / 288 courses / 183 workshops / 16 on-demand) across **~44 sources**.

## Screenshot index

All files in this folder.

| File | Page | Viewport |
|---|---|---|
| `01-home-desktop.png` | `/` | 1440×900 (full page) |
| `02-conferences-desktop.png` | `/conferences`, unfiltered | 1440×900 (full page — **152,704px tall**) |
| `02b-conferences-desktop-viewport.png` | `/conferences`, unfiltered | 1440×900 (above-the-fold only) |
| `03-conferences-filtered-desktop.png` | `/conferences?specialty=Cardiology&q=conference&maxPrice=300` | 1440×900 (full page) |
| `04-detail-desktop.png` | `/conferences/[id]` | 1440×900 (full page) |
| `05-login-desktop.png` | `/auth/login` | 1440×900 |
| `06-signup-desktop.png` | `/auth/signup` | 1440×900 |
| `07-home-mobile.png` | `/` | 390×844 (full page) |
| `08-conferences-mobile.png` | `/conferences`, unfiltered | 390×844 (full page — **403,400px tall**) |
| `08b-conferences-mobile-viewport.png` | `/conferences`, unfiltered | 390×844 (above-the-fold only) |
| `09-detail-mobile.png` | `/conferences/[id]` | 390×844 |
| `10-login-mobile.png` | `/auth/login` | 390×844 |
| `11-signup-mobile.png` | `/auth/signup` | 390×844 |
| `metrics.json` | raw measurements from the crawl | — |

**Measured:**
- Time-to-first-content (networkidle): home 2.3s, `/conferences` 2.7s (client-fetches all 1,194 rows + all pricing tiers + all sessions before first paint — see Problem 1), detail page 4.4s (waits for its own round trip after navigating from an already-loaded list), login/signup ~2.1–2.6s.
- Cards above the fold, desktop 1440×900: **3** (stat tiles + search + first row of source chips eat the rest).
- Cards above the fold, mobile 390×844: **0** — the viewport is entirely the header, page title, 3 stat tiles, and the start of a 33-chip source-filter wall (`08b-conferences-mobile-viewport.png`).
- Clicks to filter by specialty: 1 (chip). Clicks to filter by date: **not possible — no date/date-range control exists anywhere in `FilterPanel.tsx` or the top filter bar.** Clicks to filter by format (online/in-person/hybrid): **not possible — no control exists**, despite every card and the detail page displaying format prominently.
- Filters **do** persist in the URL (`useConferences.ts:46-71`) — `?specialty=Cardiology&q=conference&maxPrice=300` round-trips correctly. This is a genuine strength, don't lose it in a redesign.
- Empty state exists and is reasonable (`conferences/page.tsx:307-322`) — icon, message, "Clear all filters". Loading state is a centered spinner + "Loading conferences...", shown even though the list is client-fetched as one 1,194-row blob (no skeleton, no progressive reveal).

## Top 10 problems, ranked by user impact

### 1. The directory renders all 1,194 rows into the DOM at once — no pagination, no virtualization
**Evidence:** `metrics.json` — the unfiltered `/conferences` full-page screenshot is **152,704px tall on desktop** and **403,400px tall on mobile**. `useConferences.ts:114-119` fetches the entire `conferences`, `pricing_tiers`, and `course_sessions` tables client-side on mount (paginated only to defeat Supabase's 1000-row cap, not to limit payload), and `conferences/page.tsx:324-335` maps every filtered row into a `<ConferenceCard>`. There is no `slice`, no "load more", no virtualized list anywhere in this file.
**Why it matters:** this is the single biggest reason the product "feels dumped rather than clean" — a doctor opens the directory and is handed a scroll well over 100 screens long, on both desktop and (far worse, proportionally) mobile. It also means every visit pays for 1,194 rows + every pricing tier + every course session before anything renders, and the browser is holding ~1,200 mounted card components (each doing multiple date/price computations) even when 99% are off-screen.
**Fix:** paginate (25–30 per page, server-side `.range()` query instead of fetch-all-then-filter-client-side) or virtualize (`@tanstack/react-virtual`) the results grid. This alone should be treated as a P0 engineering fix, not just a design one.

### 2. Filters are declared twice, in two different UI patterns, on the same page
**Evidence:** `conferences/page.tsx:127-185` renders a full-width "Source" chip bar (33+ chips) and a separate "Type" chip bar directly under the page header; `FilterPanel.tsx:56-111` then renders **the same source list again** as chips inside the left sidebar, a few hundred pixels below. `03-conferences-filtered-desktop.png` shows both at once. On mobile the top source bar alone is 8 rows of chips before a single conference card appears (`08b-conferences-mobile-viewport.png`).
**Why it matters:** this is exactly the "filtering is not up to scratch" complaint — a user has two places to set the same filter, has to learn which one is canonical, and on mobile must scroll past dozens of institution acronyms (ACPGBI, CoSRH, FICM, IAS…) that mean nothing to them before reaching content.
**Fix:** one filter surface. Put source, specialty, and price in a single sidebar/drawer; drop the top duplicate chip bar entirely, or replace it with a single "Source ▾" multi-select dropdown with search (44 pill buttons is not a scannable UI at any width).

### 3. No date filter and no format filter exist, despite both being core decision criteria
**Evidence:** `FilterPanel.tsx` has exactly three controls: Source, Specialty, Location (region dropdown), Price. `useConferences.ts:17-32` `Filters` interface has no date/date-range field and no `event_format` field. Yet `ConferenceCard.tsx:209-243` and the detail page both treat format (online/in-person/hybrid) as a first-class, colour-coded fact, and the home page marketing copy (`page.tsx:190`) explicitly promises "Find events near you" / specialty / price filters but the product itself has shipped fewer facets than the marketing claims.
**Why it matters:** "is this for me?" for a working clinician is answered by date (can I get the day off), format (do I need to travel), specialty, and price — in that order. Two of the four are entirely absent.
**Fix:** add a date-range picker (or quick chips: This month / Next 3 months / This year) and a format toggle (Online / In-person / Hybrid / Any) to the filter surface.

### 4. The card is trying to be a detail page — 11+ distinct data points crammed into one tile
**Evidence:** `ConferenceCard.tsx` renders, per card: specialty label, up to 4 status pills (Course/Workshop/On-Demand/New/Sold-out), a source badge, a CPD badge, the title, date line, optional time line, location/format line, price line, an abstract-status line (4 different possible states), then a footer with "View details", an external "View course" link, and a Save heart — all inside one `glass-card`. `03-conferences-filtered-desktop.png` shows this at full density.
**Why it matters:** this is the literal "information is dumped" complaint. A scanning list needs 4–5 facts max (title, date, specialty, price, one status signal); everything else belongs behind "View details," which already exists as a destination.
**Fix:** cut the card to title, date, specialty, price/CPD, and at most one status badge (prioritise: deadline urgency > sold-out > new). Move source attribution, abstract-open/closed detail, and the external "View course" link to the detail page or a hover/expand affordance. Consider a denser row/table layout as an alternate view for power users (see IA proposal below) rather than one card format for everyone.

### 5. Textbook "AI-generated" visual language throughout
**Evidence:** `page.tsx:12-13` two `blur-3xl` gradient orbs (cyan→teal, violet→purple) behind the hero; `.gradient-text` (`globals.css:94-99`) cyan-to-teal clip-text headline; `.glass-card` (`globals.css:102-106`) `backdrop-filter: blur(12px)` applied to literally every card, panel, and stat tile on every page; three rotated "floating" decorative cards with fabricated data (`page.tsx:74-117`); every CTA button uses a cyan→teal gradient with a matching colour-glow `shadow-cyan-500/25`; centred hero copy, centred section headers, centred CTA section. This combination (glassmorphism + cyan/teal or purple/blue gradient + blur orbs + pill-shaped everything + centred marketing copy) is the single most recognisable "built by an LLM" visual signature in 2026.
**Why it matters:** directly matches the owner's own verdict ("looks too much like AI"). For a clinical-audience product this also reads as generic SaaS-startup rather than a trustworthy professional tool — compare to how RCP, RCS, BMJ etc. actually present themselves (flat, typographic, low-chroma, information-dense, not glassy).
**Fix:** see "AI-look removal list" below.

### 6. Directory results grid wastes most of the screen on a sparse result set
**Evidence:** `03-conferences-filtered-desktop.png` — after applying specialty + search + price, 2 results render in a 3-column grid, leaving roughly two-thirds of the content area empty, while the sidebar filter panel (duplicated, see #2) fills the left third with dozens of unselected pills.
**Why it matters:** narrowing a search should feel like progress, not like emptying a room. A doctor filtering to their specialty + budget is the target "aha" moment and it currently looks broken/sparse rather than precise.
**Fix:** collapse to fewer columns or switch to a list layout below ~6 results; show "2 results — want to see more?" with one-click filter relaxations (e.g. "+18 if you include Courses").

### 7. Stat tiles and chip bars repeat "count" as the primary metric almost everywhere
**Evidence:** 3 stat tiles at the top (`conferences/page.tsx:94-113`: total tracked, abstracts open, closing in 14 days) plus every single chip across Source, Type, and Scope also shows a `· N` count (`page.tsx:179, 213, 246`, `FilterPanel.tsx` omits counts only on specialty/price — inconsistently). That's 40+ numbers competing for attention on first load.
**Why it matters:** inconsistent (some chip groups show counts, some don't) and noisy — it signals "look how much data we have" rather than "here's what matters to you."
**Fix:** keep the 3 top-line stats (they're genuinely useful — abstracts-open and closing-soon are real hooks). Drop counts from Source/Type chips, or move them to a tooltip/secondary line; they add visual noise without adding decision value at scan time.

### 8. Loading and first-paint experience undersells the product
**Evidence:** `conferences/page.tsx:63-72` — full-screen centred spinner + "Loading conferences..." for ~2.7s (and in practice longer once network latency is added) while the entire 1,194-row dataset is fetched before anything renders (see #1). No skeleton cards, no progressive count, no "here's the directory" shell.
**Why it matters:** compounds #1 — because everything is fetched at once, the loading state is a long, contentless wait rather than a fast shell-then-stream.
**Fix:** once #1 is fixed (server-paginated), this mostly resolves itself — render page 1 with the chrome in place and a few skeleton cards instead of blocking on the full fetch.

### 9. Detail page pricing table is plain and undifferentiated from the rest of the card chrome
**Evidence:** `04-detail-desktop.png` — the pricing table (`PricingTable.tsx`, rendered inside the same `glass-card`) is a flat 5-row table with no visual hierarchy between professional-level bands, no highlighting of the tier most likely to apply to the visitor, and a 3rd "Notes" column that is empty (`—`) for every row shown.
**Why it matters:** pricing is one of the top 3 decision factors and it's currently rendered with the same low-contrast treatment as everything else on the page — no scanning priority.
**Fix:** visually group by professional level (the PricingTable component already tab/group logic per CLAUDE.md conventions — lean into it more directly on this page), drop the Notes column when empty rather than showing em-dashes.

### 10. Accessibility basics not verified and likely at risk from the design language itself
**Evidence:** body text and secondary copy is consistently `text-slate-400`/`text-slate-500` (e.g. `page.tsx:31`, `ConferenceCard.tsx:187`) over a `slate-950`/glass-blur background — this combination is commonly sub-4.5:1 contrast for body text at these Tailwind slate steps. Chips/pills (`FilterPanel.tsx` throughout) are `text-xs px-3 py-1.5`, i.e. well under the 44×44px (or even 24×24 CSS px WCAG 2.2 AA) recommended tap target on the mobile chip wall where dozens are packed edge to edge (`08b-conferences-mobile-viewport.png`). Focus states were not explicitly checked in this pass (no `:focus-visible` overrides found in `globals.css`, meaning they likely fall back to browser default — acceptable but not verified against the dark background).
**Why it matters:** a clinical-professional audience skews older and will include low-vision users; small chip targets are also just bad on any touch device.
**Fix:** run a full contrast pass on `slate-400`/`slate-500` text tokens against `slate-950`, and bump chip min-height to 32–36px with adequate horizontal padding once the chip count problem (#2) is reduced.

## Proposed information architecture — directory row/card

**Card shows (in order):**
1. Title (1 line, truncate)
2. Date (single line — "18 Mar 2027" or "Next: 18 Mar" for courses)
3. Specialty + format icon, inline
4. Price (from £X or Free)
5. One status signal, priority order: sold-out > deadline-in-N-days > abstracts-open > none

**Moves to detail page (drop from card):**
- Source/society badge (still filterable, just not shown per-card)
- Full abstract-status text ("Closed", "Opens <date>")
- CPD point count as a number (keep a small CPD tick/badge if accredited, drop the point count from the card — it's on the detail page)
- "View course" external link (keep only "View details" on the card; external link lives on detail)
- New/Course/Workshop/On-Demand — collapse to a single small type tag, not 4 possible simultaneous badges

**Layout:** switch from a fixed 3-col card grid to a denser row-per-event list (1 row = compact horizontal card: title+specialty left, date/format/price middle, status+save right) as the default, with the current card grid as an optional "gallery" view toggle. A list of hundreds of same-shaped rows scans far faster than a grid of tall cards.

## Proposed filter model

Single filter surface (kill the duplicate top chip bar):
- **Search** (existing, keep)
- **Specialty** — multi-select dropdown with counts, not an unbounded pill wall
- **Date** — quick chips (This week / This month / Next 3 months / This year) + custom range
- **Format** — Online / In-person / Hybrid / Any (new)
- **Type** — Conference / Course / Workshop / On-demand (existing, keep as chips — 4 options is chip-appropriate)
- **Price** — existing band chips, keep
- **Source/Society** — collapse 44 individual sources into a searchable multi-select ("Source ▾ search…"), not 44 always-visible pills
- Keep URL-state persistence (`useConferences.ts` already does this correctly — carry the pattern forward, add `date`/`format` params)
- Add a mobile filter **drawer/sheet** triggered by a "Filters (3)" button, rather than the current inline stack that pushes all content down before any results are visible

## "AI-look" removal list

1. Remove both `blur-3xl` gradient orbs from the hero background (`page.tsx:12-13`).
2. Drop `.glass-card` / `backdrop-filter: blur()` as the default container — use flat surfaces with a single subtle border or shadow; reserve blur (if any) for true overlays (modals, dropdowns).
3. Replace `.gradient-text` cyan→teal headline treatment with solid colour; gradients-on-text read as generic SaaS marketing.
4. Remove the 3 rotated, absolutely-positioned "floating" fake-data cards from the hero (`page.tsx:74-117`) — they contain no real data and exist purely as decoration.
5. Replace every gradient CTA button (`bg-gradient-to-r from-cyan-500 to-teal-500` + colour-matched glow shadow) with a solid brand colour and a plain shadow, or no shadow.
6. De-centre the marketing sections — left-align hero copy, headers, and the CTA section; centred-everything is a strong generic-template tell.
7. Stop pairing every icon with a soft gradient chip background (`iconBg: 'from-cyan-500/20 to-teal-500/20'` etc. in `page.tsx:136-156`) — flat icon tiles read as more considered.
8. Reduce pill/chip density everywhere (filters, badges) — current design defaults to "wrap it in a rounded-full border chip" for nearly every piece of UI, which is the fastest way to make an interface look templated.

## Top 5 in one line each

1. `/conferences` renders all 1,194 rows unpaginated/unvirtualized — 152,704px desktop / 403,400px mobile page height — fix before anything else.
2. Source filters are duplicated (top chip bar + sidebar) and on mobile the user scrolls through 8 rows of institution acronyms before seeing a single conference.
3. No date filter and no format filter exist at all, despite being core "is this for me" decision criteria.
4. The card crams 11+ data points into one tile — cut to title/date/specialty/price/one status badge, push the rest to the detail page.
5. The whole product is built from the most recognisable "AI-generated" visual kit — glassmorphism, cyan/teal gradients, blur orbs, floating fake-data cards, centred marketing copy, gradients on every CTA and icon chip.

Full writeup and all screenshots: `/Users/Sushil/Documents/Documents/IMT2/Side hustle/myTalk_conference app/reports/website-audit/ux.md` (this file) and the accompanying PNGs in the same folder.
