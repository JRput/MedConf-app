// src/lib/directory-query.ts
//
// Server-callable query layer for the directory. Replaces the
// "download everything, filter in JS" pattern in useConferences.ts (see
// ../../../reports/website-audit/code.md §2 items 1-2) with DB-side
// filtering/sorting/pagination against the `directory_events` view and
// `directory_facets()` RPC added by
// supabase/migrations/20261002000000_directory_query_layer.sql.
//
// Pure functions over a SupabaseClient — callable from a server component,
// a route handler (see src/app/api/directory/route.ts), or the browser
// client, since none of this depends on cookies/headers.
//
// Text search: uses Postgres `textSearch` against the generated
// `search_vector` tsvector column (name + description + specialty + city —
// see the migration) with `type: 'websearch'` so users can type natural
// phrases ("asco 2026 oncology"). Falls back to `.or(ilike...)` on
// name/specialty/city ONLY if `search_vector` is reported missing (e.g. the
// migration hasn't been applied yet to the project this code is pointed
// at) — see `queryDirectory`'s catch block. Once the migration is
// confirmed applied in all environments this fallback can be deleted.

import type { SupabaseClient } from '@supabase/supabase-js'
import { directoryEventFromRow, type DirectoryEvent, type DirectoryEventRow } from './directory'
import { canonicalSpecialty, rawValuesForParent } from './taxonomy/specialties'

export type DirectoryFormat = 'in_person' | 'online' | 'hybrid'
export type DirectoryType = 'conference' | 'course' | 'workshop'
export type DatePreset = 'this-month' | 'next-3-months' | 'this-year'
export type PriceFilter = 'free' | 'under-100' | 'under-300' | 'any'
export type DirectorySort = 'date' | 'newest' | 'price'
export type CountryFilter = 'uk' | 'international'

export interface DirectoryFilters {
  q: string
  dateFrom: string | null // ISO YYYY-MM-DD
  dateTo: string | null
  datePreset: DatePreset | null
  format: DirectoryFormat[]
  type: DirectoryType[]
  /** Canonical PARENT slugs (src/lib/taxonomy/specialties.ts), not raw DB values. */
  specialty: string[]
  region: string[]
  country: CountryFilter | null
  /** "no pricing row" is a distinct, unknown state — NEVER coerced to free. */
  price: PriceFilter
  /** scraper_sources.society short codes (see taxonomy/societies.ts), not source_id. */
  society: string[]
  cpd: boolean
  abstractsOpen: boolean
  sort: DirectorySort
  page: number
  pageSize: number
}

export const DEFAULT_FILTERS: DirectoryFilters = {
  q: '',
  dateFrom: null,
  dateTo: null,
  datePreset: null,
  format: [],
  type: [],
  specialty: [],
  region: [],
  country: null,
  price: 'any',
  society: [],
  cpd: false,
  abstractsOpen: false,
  sort: 'date',
  page: 1,
  pageSize: 30,
}

/** Resolve a datePreset into a concrete [from, to] ISO range, "today" anchored. */
export function resolveDatePreset(preset: DatePreset, today = new Date()): { from: string; to: string } {
  const y = today.getFullYear()
  const m = today.getMonth()
  const d = today.getDate()
  const iso = (dt: Date) => dt.toISOString().slice(0, 10)
  switch (preset) {
    case 'this-month':
      return { from: iso(new Date(y, m, d)), to: iso(new Date(y, m + 1, 0)) }
    case 'next-3-months':
      return { from: iso(new Date(y, m, d)), to: iso(new Date(y, m + 3, 0)) }
    case 'this-year':
      return { from: iso(new Date(y, m, d)), to: iso(new Date(y, 11, 31)) }
  }
}

function effectiveDateRange(f: DirectoryFilters): { from: string | null; to: string | null } {
  if (f.datePreset) return resolveDatePreset(f.datePreset)
  return { from: f.dateFrom, to: f.dateTo }
}

/**
 * The DB column stores raw free-text specialty values; the taxonomy only
 * exists in TypeScript (specialties.ts). So filtering by a chosen parent
 * slug means expanding it to every raw value that maps to it BEFORE the
 * query goes out — the DB never sees "oncology", only
 * ["Oncology","Clinical Oncology","Surgical Oncology", ...].
 */
export function expandSpecialtyFilter(parentSlugs: string[]): string[] {
  return parentSlugs.flatMap((slug) => rawValuesForParent(slug))
}

export type PriceBucket = 'unknown' | 'free' | 'under-100' | 'under-300' | 'over-300'

/**
 * Mirrors the `bucket` CASE expression in directory_facets() (the
 * migration) exactly — kept here as a plain TS function purely so the
 * semantics have a unit-testable home. Not called by queryDirectory/
 * queryFacets themselves (those push the equivalent logic into SQL via
 * .eq/.lt on `price_from`); this exists so a behaviour change to the
 * bucket boundaries gets caught by a test even though the two
 * implementations live in different languages.
 *
 * `priceFrom === null` means "no pricing_tiers row for this event" per
 * the data audit (../../../reports/website-audit/data.md §6 item 3) —
 * that is NEVER the same as free (price 0), and must never silently
 * match a 'free' or 'under-X' filter.
 */
export function classifyPriceBucket(priceFrom: number | null): PriceBucket {
  if (priceFrom === null) return 'unknown'
  if (priceFrom === 0) return 'free'
  if (priceFrom < 100) return 'under-100'
  if (priceFrom < 300) return 'under-300'
  return 'over-300'
}

export interface DirectoryPage {
  rows: DirectoryEvent[]
  total: number
  page: number
  pageSize: number
}

/**
 * Apply every DirectoryFilters field except pagination/sort to a
 * `directory_events` query builder. Shared between queryDirectory (which
 * also paginates/sorts) and the facet RPC's parameter list (which needs
 * the same expanded specialty + date-range values).
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function applyFilters(query: any, f: DirectoryFilters, rawSpecialty: string[], useIlikeSearch = false): any {
  let q = query

  if (f.format.length) q = q.in('event_format', f.format)
  if (f.type.length) q = q.in('event_type', f.type)
  if (rawSpecialty.length) q = q.in('specialty', rawSpecialty)
  if (f.region.length) q = q.in('region', f.region)
  if (f.country) q = q.eq('country_guess', f.country)
  if (f.society.length) q = q.in('society', f.society)
  if (f.cpd) q = q.eq('cpd_accredited', true)
  if (f.abstractsOpen) q = q.eq('abstract_open', true)

  const { from, to } = effectiveDateRange(f)
  // Overlap semantics, not "starts inside the window": an event that started
  // before `from` but is still running through it (end_date >= from) must
  // stay — otherwise a long-running course/on-demand window vanishes from
  // "This month" the moment it's already begun. A null end_date is a
  // single/unknown-length event, so its own start_date stands in for its end.
  if (to) q = q.lte('start_date', to)
  if (from) q = q.or(`end_date.gte.${from},and(end_date.is.null,start_date.gte.${from})`)

  // Pricing: "no pricing row" (price_from IS NULL) is unknown, never free.
  // 'any' applies no price filter at all, including rows with no pricing.
  if (f.price === 'free') q = q.eq('price_from', 0)
  else if (f.price === 'under-100') q = q.not('price_from', 'is', null).lt('price_from', 100)
  else if (f.price === 'under-300') q = q.not('price_from', 'is', null).lt('price_from', 300)

  if (f.q.trim()) {
    q = useIlikeSearch
      ? q.or(`conference_name.ilike.%${f.q.trim()}%,specialty.ilike.%${f.q.trim()}%,city.ilike.%${f.q.trim()}%`)
      : q.textSearch('search_vector', f.q.trim(), { type: 'websearch', config: 'english' })
  }

  return q
}

export interface DatePageSplit {
  upcoming: { start: number; end: number } | null
  ongoing: { start: number; end: number } | null
}

/**
 * The default 'date' sort puts events that haven't started yet first
 * (ascending by start_date), then events that HAVE started but haven't
 * ended yet — "ongoing" — ordered by end_date. Before this, a long-running
 * course window (e.g. "1 Jul 2026 – 30 Jun 2027") sorted by its start_date
 * like anything else, so it could out-rank events starting next week and
 * make the directory's first page look stale (see the W2 owner's fix
 * request). Postgres can express the ordering in one query as
 * `ORDER BY (start_date < current_date), start_date` — the general-purpose
 * Postgres client used here can't send that expression as an `.order()`
 * call (it takes a column name, not an expression), so queryDirectory runs
 * the two groups as separate counted/ranged queries and concatenates them.
 *
 * This function is the pure arithmetic for where a given page/pageSize
 * window falls across that 2-group split, kept separate so it's
 * unit-testable without a database — see __tests__/directory-query.test.ts.
 */
export function splitDatePage(countUpcoming: number, page: number, pageSize: number): DatePageSplit {
  const start = (page - 1) * pageSize
  const end = start + pageSize - 1

  const upcoming = start < countUpcoming ? { start, end: Math.min(end, countUpcoming - 1) } : null

  const ongoingStart = Math.max(start, countUpcoming) - countUpcoming
  const ongoingEnd = end - countUpcoming
  const ongoing = ongoingEnd >= 0 && ongoingEnd >= ongoingStart ? { start: ongoingStart, end: ongoingEnd } : null

  return { upcoming, ongoing }
}

/**
 * One page of directory rows, matching `filters`, with DB-side filtering/
 * sorting/pagination. No client-side filtering happens anywhere in this
 * function — every predicate above is a Postgres `.eq/.in/.gte/.lte/.textSearch`.
 */
export async function queryDirectory(
  supabase: SupabaseClient,
  filters: Partial<DirectoryFilters> = {}
): Promise<DirectoryPage> {
  const f: DirectoryFilters = { ...DEFAULT_FILTERS, ...filters }
  const rawSpecialty = expandSpecialtyFilter(f.specialty)

  const pageSize = f.pageSize > 0 ? f.pageSize : DEFAULT_FILTERS.pageSize
  const page = f.page > 0 ? f.page : 1
  const start = (page - 1) * pageSize

  if (f.sort !== 'date') {
    function build(useIlikeSearch: boolean) {
      let query = supabase.from('directory_events').select('*', { count: 'exact' })
      query = applyFilters(query, f, rawSpecialty, useIlikeSearch)

      if (f.sort === 'newest') {
        query = query.order('created_at', { ascending: false })
      } else {
        // Unknown pricing sorts last regardless of direction — Postgres
        // puts NULLs last on ASC by default, which is exactly "cheapest
        // known price first, unpriced events at the bottom".
        query = query.order('price_from', { ascending: true, nullsFirst: false })
      }
      return query.range(start, start + pageSize - 1)
    }

    let { data, error, count } = await build(false)
    // search_vector / directory_events may not exist yet if the migration
    // hasn't been applied to this environment — degrade to ilike rather
    // than hard-failing the whole directory. See module doc comment.
    if (error && f.q.trim() && /search_vector|column .* does not exist/i.test(error.message)) {
      ;({ data, error, count } = await build(true))
    }
    if (error) throw error

    const rows = ((data ?? []) as DirectoryEventRow[]).map(directoryEventFromRow)
    return { rows, total: count ?? 0, page, pageSize }
  }

  // --- Default 'date' sort: upcoming group, then ongoing group — see splitDatePage's doc comment.
  const today = new Date().toISOString().slice(0, 10)
  let useIlikeSearch = false

  function withGroup(query: ReturnType<typeof applyFilters>, which: 'upcoming' | 'ongoing') {
    // Undated rows (start_date IS NULL — "Date TBC") match NEITHER
    // `gte(start_date, today)` NOR `lt(start_date, today)`, so without the
    // explicit `.is.null` branch here they silently vanished from both
    // groups entirely (and from `total`). They belong in "upcoming" (never
    // "ongoing" — there's no start to have passed), sorted after every dated
    // row via `nullsFirst: false` on the fetch below, same as before this split existed.
    return which === 'upcoming' ? query.or(`start_date.gte.${today},start_date.is.null`) : query.lt('start_date', today).gte('end_date', today)
  }

  async function countGroup(which: 'upcoming' | 'ongoing'): Promise<number> {
    function build(useIlike: boolean) {
      let query = supabase.from('directory_events').select('*', { count: 'exact', head: true })
      query = applyFilters(query, f, rawSpecialty, useIlike)
      return withGroup(query, which)
    }
    let { count, error } = await build(useIlikeSearch)
    if (error && f.q.trim() && /search_vector|column .* does not exist/i.test(error.message)) {
      useIlikeSearch = true
      ;({ count, error } = await build(true))
    }
    if (error) throw error
    return count ?? 0
  }

  async function fetchGroup(which: 'upcoming' | 'ongoing', range: { start: number; end: number } | null): Promise<DirectoryEventRow[]> {
    if (!range) return []
    let query = supabase.from('directory_events').select('*')
    query = applyFilters(query, f, rawSpecialty, useIlikeSearch)
    query = withGroup(query, which)
    query = query.order(which === 'upcoming' ? 'start_date' : 'end_date', { ascending: true, nullsFirst: false })
    const { data, error } = await query.range(range.start, range.end)
    if (error) throw error
    return (data ?? []) as DirectoryEventRow[]
  }

  // Count upcoming first so it decides `useIlikeSearch` before ongoing's
  // count/fetch run — both groups share the same search term either way.
  const countUpcoming = await countGroup('upcoming')
  const countOngoing = await countGroup('ongoing')
  const total = countUpcoming + countOngoing
  const split = splitDatePage(countUpcoming, page, pageSize)

  const [upcomingRows, ongoingRows] = await Promise.all([fetchGroup('upcoming', split.upcoming), fetchGroup('ongoing', split.ongoing)])

  const rows = [...upcomingRows, ...ongoingRows].map(directoryEventFromRow)
  return { rows, total, page, pageSize }
}

export interface DirectoryFacets {
  format: Record<string, number>
  type: Record<string, number>
  region: Record<string, number>
  country: Record<string, number>
  society: Record<string, number>
  priceBucket: Record<string, number>
  cpd: Record<string, number>
  /** Rolled up from raw DB values to canonical parent slugs — see below. */
  specialty: Record<string, number>
}

/**
 * Facet counts via the `directory_facets` RPC (standard faceting: each
 * facet's counts reflect every OTHER active filter, not its own). The RPC
 * returns raw specialty-value counts (it has no concept of the TS-only
 * taxonomy); this function rolls those up into canonical parent slugs
 * before returning, since that's what the specialty filter UI renders.
 */
export async function queryFacets(
  supabase: SupabaseClient,
  filters: Partial<DirectoryFilters> = {}
): Promise<DirectoryFacets> {
  const f: DirectoryFilters = { ...DEFAULT_FILTERS, ...filters }
  const rawSpecialty = expandSpecialtyFilter(f.specialty)
  const { from, to } = effectiveDateRange(f)

  const { data, error } = await supabase.rpc('directory_facets', {
    p_q: f.q.trim() || null,
    p_date_from: from,
    p_date_to: to,
    p_format: f.format.length ? f.format : null,
    p_type: f.type.length ? f.type : null,
    p_specialty_raw: rawSpecialty.length ? rawSpecialty : null,
    p_region: f.region.length ? f.region : null,
    p_country: f.country,
    p_price: f.price,
    p_society: f.society.length ? f.society : null,
    p_cpd: f.cpd ? true : null,
    p_abstracts_open: f.abstractsOpen ? true : null,
  })
  if (error) throw error

  const raw = (data ?? {}) as {
    format?: Record<string, number>
    type?: Record<string, number>
    region?: Record<string, number>
    country?: Record<string, number>
    society?: Record<string, number>
    priceBucket?: Record<string, number>
    cpd?: Record<string, number>
    specialtyRaw?: Record<string, number>
  }

  const specialty: Record<string, number> = {}
  for (const [rawValue, count] of Object.entries(raw.specialtyRaw ?? {})) {
    const { parent } = canonicalSpecialty(rawValue === 'unspecified' ? null : rawValue)
    specialty[parent] = (specialty[parent] ?? 0) + count
  }

  return {
    format: raw.format ?? {},
    type: raw.type ?? {},
    region: raw.region ?? {},
    country: raw.country ?? {},
    society: raw.society ?? {},
    priceBucket: raw.priceBucket ?? {},
    cpd: raw.cpd ?? {},
    specialty,
  }
}
