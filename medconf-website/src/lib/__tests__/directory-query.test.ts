// src/lib/__tests__/directory-query.test.ts
//
// Unit coverage for the pure arithmetic behind the default 'date' sort's
// upcoming-then-ongoing split (see splitDatePage's doc comment in
// directory-query.ts for why this can't just be one `.order()` call).

import { describe, expect, it } from 'vitest'
import { splitDatePage } from '../directory-query'

describe('splitDatePage', () => {
  it('fills a page entirely from the upcoming group when it has enough rows', () => {
    expect(splitDatePage(500, 1, 30)).toEqual({ upcoming: { start: 0, end: 29 }, ongoing: null })
    expect(splitDatePage(500, 3, 30)).toEqual({ upcoming: { start: 60, end: 89 }, ongoing: null })
  })

  it('splits a single page across both groups at the boundary', () => {
    // 25 upcoming rows: page 1 (30/page) takes all 25 upcoming + the first 5 ongoing.
    expect(splitDatePage(25, 1, 30)).toEqual({
      upcoming: { start: 0, end: 24 },
      ongoing: { start: 0, end: 4 },
    })
  })

  it('continues correctly into a later page once upcoming is exhausted', () => {
    // Same 25-upcoming corpus: page 2 is entirely ongoing, continuing from index 5.
    expect(splitDatePage(25, 2, 30)).toEqual({ upcoming: null, ongoing: { start: 5, end: 34 } })
  })

  it('returns an entirely-ongoing page when there are no upcoming events at all', () => {
    expect(splitDatePage(0, 1, 30)).toEqual({ upcoming: null, ongoing: { start: 0, end: 29 } })
  })

  it('keeps advancing the ongoing range on later pages (bounding by the actual ongoing count is the caller\'s job via `total`, not this function\'s)', () => {
    expect(splitDatePage(10, 3, 10)).toEqual({ upcoming: null, ongoing: { start: 10, end: 19 } })
  })

  it('handles the exact-boundary case where a page ends precisely at the group split', () => {
    expect(splitDatePage(30, 1, 30)).toEqual({ upcoming: { start: 0, end: 29 }, ongoing: null })
    expect(splitDatePage(30, 2, 30)).toEqual({ upcoming: null, ongoing: { start: 0, end: 29 } })
  })
})
