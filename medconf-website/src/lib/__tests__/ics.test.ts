// src/lib/__tests__/ics.test.ts
// The multi-event feed added in W3 shares its VEVENT builder with the
// single-event download the detail page has always used, so these cover the
// things that break when a feed is bolted onto a one-event generator: one
// VCALENDAR wrapper rather than N, unique UIDs, and undated saves skipped
// instead of landing on a wrong date.
import { describe, expect, it } from 'vitest'
import { generateIcsFeed, icsFeedCount } from '../ics'
import type { DirectoryEvent } from '../directory'

function event(partial: Partial<DirectoryEvent> & { id: number }): DirectoryEvent {
  return {
    name: `Event ${partial.id}`,
    href: `/conferences/${partial.id}`,
    specialty: null,
    eventType: 'conference',
    isFlagship: false,
    isOnDemand: false,
    isSoldOut: false,
    startDate: null,
    endDate: null,
    format: 'in_person',
    city: null,
    region: null,
    society: null,
    priceMin: null,
    priceMax: null,
    currency: 'GBP',
    cpdAccredited: false,
    cpdPoints: null,
    abstractDeadline: null,
    abstractDeadlineNote: null,
    abstractOpen: false,
    ...partial,
  }
}

const count = (ics: string, token: string) => ics.split(token).length - 1

describe('generateIcsFeed', () => {
  it('wraps every event in a single VCALENDAR', () => {
    const ics = generateIcsFeed([
      event({ id: 1, startDate: '2026-11-11' }),
      event({ id: 2, startDate: '2026-12-02' }),
      event({ id: 3, startDate: '2027-01-05' }),
    ])
    expect(count(ics, 'BEGIN:VCALENDAR')).toBe(1)
    expect(count(ics, 'END:VCALENDAR')).toBe(1)
    expect(count(ics, 'BEGIN:VEVENT')).toBe(3)
    expect(count(ics, 'END:VEVENT')).toBe(3)
    expect(ics.startsWith('BEGIN:VCALENDAR')).toBe(true)
    expect(ics.endsWith('END:VCALENDAR')).toBe(true)
  })

  it('uses CRLF line endings as RFC 5545 requires', () => {
    const ics = generateIcsFeed([event({ id: 1, startDate: '2026-11-11' })])
    expect(ics).toContain('\r\n')
    expect(/[^\r]\n/.test(ics)).toBe(false)
  })

  it('emits a distinct UID per event and per deadline', () => {
    const ics = generateIcsFeed([
      event({ id: 1, startDate: '2026-11-11', abstractDeadline: '2026-08-01' }),
      event({ id: 2, startDate: '2026-12-02' }),
    ])
    expect(ics).toContain('UID:medconf-1@medconf')
    expect(ics).toContain('UID:medconf-1-abstract@medconf')
    expect(ics).toContain('UID:medconf-2@medconf')
    const uids = ics.match(/^UID:.*$/gm) ?? []
    expect(new Set(uids).size).toBe(uids.length)
  })

  it('makes DTEND exclusive, so a 4-day congress ends on the day after it finishes', () => {
    const ics = generateIcsFeed([event({ id: 1, startDate: '2026-11-10', endDate: '2026-11-13' })])
    expect(ics).toContain('DTSTART;VALUE=DATE:20261110')
    expect(ics).toContain('DTEND;VALUE=DATE:20261114')
  })

  it('treats a single-day event as one all-day block', () => {
    const ics = generateIcsFeed([event({ id: 1, startDate: '2026-11-11' })])
    expect(ics).toContain('DTSTART;VALUE=DATE:20261111')
    expect(ics).toContain('DTEND;VALUE=DATE:20261112')
  })

  it('skips undated saves rather than inventing a date for them', () => {
    const events = [
      event({ id: 1, startDate: '2026-11-11' }),
      event({ id: 2 }), // no date at all
      event({ id: 3, abstractDeadline: '2026-09-01' }), // deadline only — still worth exporting
    ]
    const ics = generateIcsFeed(events)
    expect(icsFeedCount(events)).toBe(2)
    expect(ics).toContain('UID:medconf-1@medconf')
    expect(ics).not.toContain('UID:medconf-2@medconf')
    expect(ics).toContain('UID:medconf-3-abstract@medconf')
    expect(count(ics, 'BEGIN:VEVENT')).toBe(2)
  })

  it('escapes commas, semicolons and newlines in titles', () => {
    const ics = generateIcsFeed([event({ id: 1, name: 'Cardiology; Update, 2026\nDay one', startDate: '2026-11-11' })])
    expect(ics).toContain('Cardiology\\; Update\\, 2026\\nDay one')
  })

  it('names the calendar so it imports as something recognisable', () => {
    expect(generateIcsFeed([event({ id: 1, startDate: '2026-11-11' })])).toContain('X-WR-CALNAME:MedConf')
    expect(generateIcsFeed([event({ id: 1, startDate: '2026-11-11' })], 'November 2026')).toContain('X-WR-CALNAME:November 2026')
  })

  it('still produces a valid empty calendar for an empty selection', () => {
    const ics = generateIcsFeed([])
    expect(count(ics, 'BEGIN:VEVENT')).toBe(0)
    expect(ics).toContain('BEGIN:VCALENDAR')
    expect(ics).toContain('END:VCALENDAR')
    expect(icsFeedCount([])).toBe(0)
  })

  it('folds a title longer than the 75-octet line limit', () => {
    const long = 'A'.repeat(200)
    const ics = generateIcsFeed([event({ id: 1, name: long, startDate: '2026-11-11' })])
    expect(ics).toContain('\r\n ') // continuation lines start with a space
    expect(ics.split('\r\n').every((line) => line.length <= 75)).toBe(true)
  })
})
