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
  if (from) q = q.gte('start_date', from)
  if (to) q = q.lte('start_date', to)

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

  function build(useIlikeSearch: boolean) {
    let query = supabase.from('directory_events').select('*', { count: 'exact' })
    query = applyFilters(query, f, rawSpecialty, useIlikeSearch)

    switch (f.sort) {
      case 'newest':
        query = query.order('created_at', { ascending: false })
        break
      case 'price':
        // Unknown pricing sorts last regardless of direction — Postgres
        // puts NULLs last on ASC by default, which is exactly "cheapest
        // known price first, unpriced events at the bottom".
        query = query.order('price_from', { ascending: true, nullsFirst: false })
        break
      case 'date':
      default:
        query = query.order('start_date', { ascending: true, nullsFirst: false })
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
