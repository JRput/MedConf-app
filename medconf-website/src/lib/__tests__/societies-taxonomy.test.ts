import { describe, it, expect } from 'vitest'
import { SOCIETIES } from '@/lib/taxonomy/societies'

// The societies page and the filter chips look counts up with `facets.society[s.short]`,
// where the facet keys are the `scraper_sources.society` codes — i.e. the keys of SOCIETIES.
// A `short` that differs from its key silently shows "0 upcoming events" (Digital Health
// Rewired, 2026-11-09).
describe('SOCIETIES taxonomy', () => {
  it('every entry has short equal to its key', () => {
    const mismatched = Object.entries(SOCIETIES).filter(([key, info]) => info.short !== key)
    expect(mismatched.map(([k, i]) => `${k} -> ${i.short}`)).toEqual([])
  })
  it('codes are at most 25 characters', () => {
    expect(Object.keys(SOCIETIES).filter((k) => k.length > 25)).toEqual([])
  })
})
