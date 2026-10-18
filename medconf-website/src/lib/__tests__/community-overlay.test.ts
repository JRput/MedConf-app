import { describe, expect, it } from 'vitest'
import { emptySections, overlayConference, pickTiers } from '../community/overlay'
import type { CommunityFact, CommunityTier, FactField } from '../community/types'
import type { Conference, PricingTier } from '../types'

const base: Conference = {
  id: 1,
  source_id: 5,
  source_url: 'https://x.org/e',
  conference_name: 'Test',
  specialty: 'Oncology',
  event_type: 'conference',
  start_date: null,
  end_date: null,
  start_time: null,
  venue_name: null,
  city: null,
  region: null,
  event_format: null,
  is_sold_out: false,
  cpd_accredited: false,
  cpd_points: null,
  abstract_open: false,
  abstract_deadline: null,
  abstract_deadline_note: null,
  organiser_url: null,
  booking_url: null,
  description: null,
  is_on_demand: false,
  on_demand_original_date: null,
  is_flagship: false,
  archived: false,
  created_at: '',
  updated_at: '',
}

let n = 0
const fact = (field: FactField, value: unknown, created_at = `2026-10-0${(n++ % 9) + 1}`): CommunityFact => ({
  id: `f${n}`,
  contribution_id: 'c',
  conference_id: 1,
  field,
  value,
  is_published: true,
  created_at,
})

const tier = (over: Partial<PricingTier> = {}): PricingTier => ({
  id: 1,
  conference_id: 1,
  session_id: null,
  tier_label: 'Standard',
  price_gbp: 50,
  currency: 'GBP',
  is_early_bird: false,
  early_bird_deadline: null,
  ...over,
})

describe('overlayConference', () => {
  it('fills empty fields and reports them as community-sourced', () => {
    const r = overlayConference(base, [
      fact('start_date', '2027-03-01'),
      fact('city', ' Leeds '),
      fact('event_format', 'hybrid'),
      fact('organiser_url', 'https://example.org/e'),
    ])
    expect(r.conference.start_date).toBe('2027-03-01')
    expect(r.conference.city).toBe('Leeds')
    expect(r.conference.event_format).toBe('hybrid')
    expect(r.communityFields).toEqual(new Set(['start_date', 'city', 'event_format', 'organiser_url']))
  })

  it('scraped values always win', () => {
    const scraped = { ...base, start_date: '2027-01-01', city: 'York', organiser_url: 'https://real.org' }
    const r = overlayConference(scraped, [
      fact('start_date', '2027-03-01'),
      fact('city', 'Leeds'),
      fact('organiser_url', 'https://fake.org'),
    ])
    expect(r.conference.start_date).toBe('2027-01-01')
    expect(r.conference.city).toBe('York')
    expect(r.conference.organiser_url).toBe('https://real.org')
    expect(r.communityFields.size).toBe(0)
  })

  it('treats an empty string as empty', () => {
    const r = overlayConference({ ...base, venue_name: '' }, [fact('venue_name', 'Town Hall')])
    expect(r.conference.venue_name).toBe('Town Hall')
  })

  it('ignores unpublished facts and wrongly-typed values', () => {
    const unpublished = { ...fact('city', 'Leeds'), is_published: false }
    const r = overlayConference(base, [unpublished, fact('start_date', 'not-a-date'), fact('event_format', 'carrier-pigeon')])
    expect(r.communityFields.size).toBe(0)
    expect(r.conference.event_format).toBeNull()
  })

  it('uses the newest fact when there are several for a field', () => {
    const r = overlayConference(base, [fact('city', 'Old', '2026-10-01'), fact('city', 'New', '2026-10-09')])
    expect(r.conference.city).toBe('New')
  })

  it('does not mutate the input conference', () => {
    const copy = { ...base }
    overlayConference(base, [fact('city', 'Leeds')])
    expect(base).toEqual(copy)
  })

  describe('abstracts', () => {
    it('fills when the listing has no abstract info', () => {
      const r = overlayConference(base, [fact('abstract_deadline', '2027-02-01')])
      expect(r.conference.abstract_deadline).toBe('2027-02-01')
      expect(r.conference.abstract_open).toBe(true)
      expect(r.communityFields.has('abstract_deadline')).toBe(true)
    })
    it('respects an explicit abstract_open=false fact', () => {
      const r = overlayConference(base, [fact('abstract_deadline_note', 'See programme'), fact('abstract_open', false)])
      expect(r.conference.abstract_open).toBe(false)
      expect(r.conference.abstract_deadline_note).toBe('See programme')
    })
    it('never overrides scraped abstract info', () => {
      const scraped = { ...base, abstract_deadline: '2027-01-15' }
      const r = overlayConference(scraped, [fact('abstract_deadline', '2027-02-01'), fact('abstract_deadline_note', 'x')])
      expect(r.conference.abstract_deadline).toBe('2027-01-15')
      expect(r.conference.abstract_deadline_note).toBeNull()
      expect(r.communityFields.size).toBe(0)
    })
  })

  describe('cpd', () => {
    it('fills points and flips accreditation when scraped is false/null', () => {
      const r = overlayConference(base, [fact('cpd_points', 6)])
      expect(r.conference.cpd_points).toBe(6)
      expect(r.conference.cpd_accredited).toBe(true)
    })
    it('fills accreditation alone', () => {
      const r = overlayConference(base, [fact('cpd_accredited', true)])
      expect(r.conference.cpd_accredited).toBe(true)
      expect(r.conference.cpd_points).toBeNull()
    })
    it('does nothing when the scraper already has points', () => {
      const r = overlayConference({ ...base, cpd_points: 3 }, [fact('cpd_points', 9), fact('cpd_accredited', true)])
      expect(r.conference.cpd_points).toBe(3)
      expect(r.communityFields.size).toBe(0)
    })
    it('does nothing when the scraper says accredited', () => {
      const r = overlayConference({ ...base, cpd_accredited: true }, [fact('cpd_points', 9)])
      expect(r.conference.cpd_points).toBeNull()
      expect(r.communityFields.size).toBe(0)
    })
    it('a community "not accredited" fact changes nothing', () => {
      const r = overlayConference(base, [fact('cpd_accredited', false)])
      expect(r.conference.cpd_accredited).toBe(false)
      expect(r.communityFields.size).toBe(0)
    })
  })
})

describe('pickTiers', () => {
  const ct: CommunityTier = {
    id: 'uuid-1',
    contribution_id: 'c',
    conference_id: 1,
    tier_label: 'Member',
    price: '45.50',
    currency: 'EUR',
    is_early_bird: true,
    early_bird_deadline: '2027-01-01',
    is_published: true,
    created_at: '',
  }
  it('returns scraped tiers untouched when any exist', () => {
    const scraped = [tier()]
    expect(pickTiers(scraped, [ct])).toBe(scraped)
  })
  it('maps community tiers into the PricingTier shape, flagged', () => {
    const [t] = pickTiers([], [ct])
    expect(t).toMatchObject({
      tier_label: 'Member',
      price_gbp: 45.5,
      currency: 'EUR',
      is_early_bird: true,
      early_bird_deadline: '2027-01-01',
      session_id: null,
      fromCommunity: true,
    })
    expect(t.id).toBeLessThan(0)
  })
  it('skips unpublished community tiers', () => {
    expect(pickTiers([], [{ ...ct, is_published: false }])).toEqual([])
  })
})

describe('emptySections', () => {
  it('offers everything for a bare listing, fees included', () => {
    expect(emptySections(base, [])).toEqual(['dates', 'venue', 'fees', 'abstracts', 'cpd', 'links', 'note'])
  })
  it('always offers a note, even for a complete listing', () => {
    const full: Conference = {
      ...base,
      start_date: '2027-01-01',
      event_format: 'in_person',
      venue_name: 'Hall',
      cpd_accredited: true,
      abstract_deadline: '2026-12-01',
      organiser_url: 'https://x.org',
    }
    expect(emptySections(full, [tier()])).toEqual(['note'])
  })
  it('never offers fees for course rows', () => {
    expect(emptySections({ ...base, event_type: 'course' }, [])).not.toContain('fees')
  })
  it('does not offer venue for online events', () => {
    expect(emptySections({ ...base, event_format: 'online' }, [])).not.toContain('venue')
  })
  it('offers venue when the format is unknown even if a city exists', () => {
    expect(emptySections({ ...base, city: 'Leeds' }, [])).toContain('venue')
  })
  it('offers cpd only when neither accreditation nor points exist', () => {
    expect(emptySections({ ...base, cpd_points: 2 }, [])).not.toContain('cpd')
    expect(emptySections({ ...base, cpd_accredited: true }, [])).not.toContain('cpd')
  })
  it('offers abstracts only without a deadline or note', () => {
    expect(emptySections({ ...base, abstract_deadline_note: 'see site' }, [])).not.toContain('abstracts')
  })
})
