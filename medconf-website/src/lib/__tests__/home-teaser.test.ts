import { describe, expect, it } from 'vitest'
import { homeStats, relativeDeadline, splitTeaser } from '../home-teaser'

const TODAY = '2026-10-24'

describe('relativeDeadline', () => {
  it('words today, tomorrow and N days', () => {
    expect(relativeDeadline('2026-10-24', TODAY)).toBe('closes today')
    expect(relativeDeadline('2026-10-25', TODAY)).toBe('closes tomorrow')
    expect(relativeDeadline('2026-11-03', TODAY)).toBe('closes in 10 days')
  })
  it('is null for past, missing or malformed dates', () => {
    expect(relativeDeadline('2026-10-23', TODAY)).toBeNull()
    expect(relativeDeadline(null, TODAY)).toBeNull()
    expect(relativeDeadline('soon', TODAY)).toBeNull()
  })
  it('never contains the exact date', () => {
    expect(relativeDeadline('2026-11-03', TODAY)).not.toMatch(/2026|Nov|03/)
  })
  it('accepts a Date for today', () => {
    expect(relativeDeadline('2026-10-25', new Date('2026-10-24T09:00:00Z'))).toBe('closes tomorrow')
  })
})

describe('splitTeaser', () => {
  it('splits at 6 by default', () => {
    const r = splitTeaser([1, 2, 3, 4, 5, 6, 7, 8, 9])
    expect(r.visible).toEqual([1, 2, 3, 4, 5, 6])
    expect(r.blurred).toEqual([7, 8, 9])
  })
  it('keeps a short list entirely visible', () => {
    expect(splitTeaser([1, 2], 6)).toEqual({ visible: [1, 2], blurred: [] })
  })
  it('honours a custom size', () => {
    expect(splitTeaser([1, 2, 3], 1).blurred).toEqual([2, 3])
  })
})

describe('homeStats', () => {
  it('counts live societies/specialties and deadlines inside the window', () => {
    const s = homeStats({
      total: 1200,
      societyCounts: { RCP: 10, ESMO: 4, Empty: 0 },
      specialtyCounts: { oncology: 3, cardiology: 0 },
      deadlines: ['2026-10-24', '2026-11-07', '2026-11-08', '2026-10-01', null],
      today: TODAY,
      windowDays: 14,
    })
    expect(s).toEqual({ events: 1200, societies: 2, specialties: 1, closingSoon: 2 })
  })
})
