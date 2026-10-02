// src/lib/directory-url.ts
// Serialise/parse DirectoryFilters ⇄ URLSearchParams so directory links stay
// shareable/bookmarkable — the same pattern useConferences.ts already uses
// (readFiltersFromUrl/writeFiltersToUrl), extended for the new filter
// fields. Existing param names (`q`, `specialty`, `maxPrice`, `source`,
// `society`, `sort`, `type`, `scope`, `region`) are kept so old links don't
// break; `maxPrice`/`source`/`scope` are the ones NOT part of
// DirectoryFilters (they belonged to the old client-side-filter model) and
// are intentionally dropped here rather than carried forward — see the W2a
// report for how the UI agent should handle them if old links need to
// resolve to something.

import type { CountryFilter, DatePreset, DirectoryFilters, DirectoryFormat, DirectorySort, DirectoryType, PriceFilter } from './directory-query'
import { DEFAULT_FILTERS } from './directory-query'

const FORMATS: DirectoryFormat[] = ['in_person', 'online', 'hybrid']
const TYPES: DirectoryType[] = ['conference', 'course', 'workshop']
const PRESETS: DatePreset[] = ['this-month', 'next-3-months', 'this-year']
const PRICES: PriceFilter[] = ['free', 'under-100', 'under-300', 'any']
const SORTS: DirectorySort[] = ['date', 'newest', 'price']
const COUNTRIES: CountryFilter[] = ['uk', 'international']

function isOneOf<T extends string>(value: string, allowed: readonly T[]): value is T {
  return (allowed as readonly string[]).includes(value)
}

function csv(params: URLSearchParams, key: string): string[] {
  const v = params.get(key)
  if (!v) return []
  return v.split(',').map((s) => s.trim()).filter(Boolean)
}

/** Parse a URLSearchParams (or query string) into a full DirectoryFilters, filling in defaults. */
export function parseDirectoryUrl(params: URLSearchParams | string): DirectoryFilters {
  const p = typeof params === 'string' ? new URLSearchParams(params) : params

  const datePresetRaw = p.get('datePreset')
  const datePreset = datePresetRaw && isOneOf(datePresetRaw, PRESETS) ? datePresetRaw : null

  const priceRaw = p.get('price')
  const price = priceRaw && isOneOf(priceRaw, PRICES) ? priceRaw : DEFAULT_FILTERS.price

  const sortRaw = p.get('sort')
  const sort = sortRaw && isOneOf(sortRaw, SORTS) ? sortRaw : DEFAULT_FILTERS.sort

  const countryRaw = p.get('country')
  const country = countryRaw && isOneOf(countryRaw, COUNTRIES) ? countryRaw : null

  const pageRaw = Number(p.get('page'))
  const pageSizeRaw = Number(p.get('pageSize'))

  return {
    q: p.get('q') ?? DEFAULT_FILTERS.q,
    // Explicit from/to are ignored when a preset is set — resolveDatePreset()
    // in directory-query.ts takes precedence.
    dateFrom: datePreset ? null : p.get('dateFrom'),
    dateTo: datePreset ? null : p.get('dateTo'),
    datePreset,
    format: csv(p, 'format').filter((v): v is DirectoryFormat => isOneOf(v, FORMATS)),
    type: csv(p, 'type').filter((v): v is DirectoryType => isOneOf(v, TYPES)),
    specialty: csv(p, 'specialty'),
    region: csv(p, 'region'),
    country,
    price,
    society: csv(p, 'society'),
    cpd: p.get('cpd') === '1',
    abstractsOpen: p.get('abstractsOpen') === '1',
    sort,
    page: Number.isFinite(pageRaw) && pageRaw > 0 ? pageRaw : DEFAULT_FILTERS.page,
    pageSize: Number.isFinite(pageSizeRaw) && pageSizeRaw > 0 ? pageSizeRaw : DEFAULT_FILTERS.pageSize,
  }
}

/** Serialise a DirectoryFilters back to URLSearchParams, omitting anything at its default. */
export function serializeDirectoryFilters(f: DirectoryFilters): URLSearchParams {
  const p = new URLSearchParams()
  if (f.q) p.set('q', f.q)
  if (f.datePreset) p.set('datePreset', f.datePreset)
  else {
    if (f.dateFrom) p.set('dateFrom', f.dateFrom)
    if (f.dateTo) p.set('dateTo', f.dateTo)
  }
  if (f.format.length) p.set('format', f.format.join(','))
  if (f.type.length) p.set('type', f.type.join(','))
  if (f.specialty.length) p.set('specialty', f.specialty.join(','))
  if (f.region.length) p.set('region', f.region.join(','))
  if (f.country) p.set('country', f.country)
  if (f.price !== DEFAULT_FILTERS.price) p.set('price', f.price)
  if (f.society.length) p.set('society', f.society.join(','))
  if (f.cpd) p.set('cpd', '1')
  if (f.abstractsOpen) p.set('abstractsOpen', '1')
  if (f.sort !== DEFAULT_FILTERS.sort) p.set('sort', f.sort)
  if (f.page !== DEFAULT_FILTERS.page) p.set('page', String(f.page))
  if (f.pageSize !== DEFAULT_FILTERS.pageSize) p.set('pageSize', String(f.pageSize))
  return p
}
