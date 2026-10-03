import { describe, expect, it } from 'vitest'
import { parseDirectoryUrl, serializeDirectoryFilters } from '../directory-url'
import { DEFAULT_FILTERS, type DirectoryFilters } from '../directory-query'

describe('directory-url round-trip', () => {
  it('round-trips the default filters to an empty query string', () => {
    const params = serializeDirectoryFilters(DEFAULT_FILTERS)
    expect(params.toString()).toBe('')
    expect(parseDirectoryUrl(params)).toEqual(DEFAULT_FILTERS)
  })

  it('round-trips a fully-populated filter set', () => {
    const filters: DirectoryFilters = {
      q: 'asco oncology',
      dateFrom: null,
      dateTo: null,
      datePreset: 'next-3-months',
      format: ['online', 'hybrid'],
      type: ['conference', 'course'],
      specialty: ['oncology', 'cardiology'],
      region: ['Scotland', 'London'],
      country: 'international',
      price: 'under-100',
      society: ['ASCO', 'ESMO'],
      cpd: true,
      abstractsOpen: true,
      sort: 'newest',
      page: 3,
      pageSize: 50,
    }
    const params = serializeDirectoryFilters(filters)
    expect(parseDirectoryUrl(params)).toEqual(filters)
  })

  it('an explicit date range is dropped once a datePreset is also present', () => {
    const params = new URLSearchParams('datePreset=this-month&dateFrom=2026-01-01&dateTo=2026-01-31')
    const parsed = parseDirectoryUrl(params)
    expect(parsed.datePreset).toBe('this-month')
    expect(parsed.dateFrom).toBeNull()
    expect(parsed.dateTo).toBeNull()
  })

  it('ignores unknown enum values and falls back to defaults', () => {
    const params = new URLSearchParams('price=super-cheap&sort=random&format=carrier-pigeon,online')
    const parsed = parseDirectoryUrl(params)
    expect(parsed.price).toBe(DEFAULT_FILTERS.price)
    expect(parsed.sort).toBe(DEFAULT_FILTERS.sort)
    expect(parsed.format).toEqual(['online'])
  })

  it('page/pageSize fall back to defaults when non-numeric or <= 0', () => {
    const parsed = parseDirectoryUrl('page=0&pageSize=-5')
    expect(parsed.page).toBe(DEFAULT_FILTERS.page)
    expect(parsed.pageSize).toBe(DEFAULT_FILTERS.pageSize)
  })

  it('serialization omits default values to keep URLs short', () => {
    const params = serializeDirectoryFilters({ ...DEFAULT_FILTERS, cpd: true })
    expect(params.toString()).toBe('cpd=1')
  })
})
