import { describe, expect, it } from 'vitest'
import { excerpt, publicEventFields } from '../event-public'
import type { Conference } from '../types'

const FULL: Conference = {
  id: 548,
  source_id: 3,
  source_url: 'https://organiser.example/secret-source',
  conference_name: 'Cardiology Update 2027',
  specialty: 'Cardiology',
  event_type: 'conference',
  start_date: '2027-03-01',
  end_date: '2027-03-03',
  start_time: '09:00:00',
  venue_name: 'Secret Venue Hall',
  city: 'Leeds',
  region: 'Yorkshire',
  event_format: 'in_person',
  is_sold_out: false,
  cpd_accredited: true,
  cpd_points: 12,
  abstract_open: true,
  abstract_deadline: '2026-12-15',
  abstract_deadline_note: 'see page',
  organiser_url: 'https://organiser.example/event',
  booking_url: 'https://organiser.example/book',
  description: 'x'.repeat(900),
  is_on_demand: false,
  on_demand_original_date: null,
  is_flagship: false,
  archived: false,
  created_at: '2026-01-01',
  updated_at: '2026-01-01',
}

const LOCKED_KEYS = [
  'price',
  'pricing',
  'cpd_points',
  'cpd_accredited',
  'abstract_deadline',
  'abstract_open',
  'venue_name',
  'booking_url',
  'organiser_url',
  'source_url',
  'course_sessions',
  'sessions',
]

describe('publicEventFields', () => {
  const out = publicEventFields(FULL, 'RCP')

  it('has none of the locked keys', () => {
    for (const k of LOCKED_KEYS) expect(Object.keys(out)).not.toContain(k)
  })

  it('carries none of the locked values anywhere in its serialisation', () => {
    const json = JSON.stringify(out)
    for (const v of ['Secret Venue Hall', '2026-12-15', 'organiser.example', '"cpd_points"']) {
      expect(json).not.toContain(v)
    }
  })

  it('keeps the public header fields', () => {
    expect(out).toMatchObject({
      id: 548,
      conference_name: 'Cardiology Update 2027',
      specialty: 'Cardiology',
      start_date: '2027-03-01',
      end_date: '2027-03-03',
      city: 'Leeds',
      event_format: 'in_person',
      society: 'RCP',
    })
  })

  it('caps the description excerpt at 300 characters', () => {
    expect(out.description_excerpt!.length).toBeLessThanOrEqual(300)
    expect(excerpt('short text')).toBe('short text')
    expect(excerpt('   ')).toBeNull()
  })
})
