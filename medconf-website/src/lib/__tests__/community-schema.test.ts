import { describe, expect, it } from 'vitest'
import {
  CURRENCIES,
  FACT_FIELDS,
  FEE_LABELS,
  UK_NATIONS,
  addInfoPayloadSchema,
  feesSchema,
  makeAddInfoSchema,
  newEventPayloadSchema,
  todayUtc,
} from '../community/schema'

const day = (offset: number) => {
  const d = new Date()
  d.setUTCDate(d.getUTCDate() + offset)
  return d.toISOString().slice(0, 10)
}

const validEvent = () => ({
  conference_name: 'Test Oncology Day',
  event_type: 'conference' as const,
  event_format: 'in_person' as const,
  start_date: day(30),
  end_date: day(31),
  country: 'United Kingdom',
  region: 'England',
  city: 'Leeds',
  specialty: 'Oncology',
  organiser_url: 'https://Example.org/event/?utm_source=x',
  cpd_accredited: true,
  cpd_points: 6,
  abstract_open: false,
  fees: {
    currency: 'GBP',
    tiers: [{ label: 'Standard', price: 120, is_early_bird: false }],
  },
})

describe('exports', () => {
  it('exposes the lists other agents use', () => {
    expect(FEE_LABELS).toContain('Early bird')
    expect(CURRENCIES).toEqual(['GBP', 'USD', 'EUR', 'AUD', 'CAD', 'INR', 'CHF', 'HKD', 'SGD'])
    expect(UK_NATIONS).toEqual(['England', 'Scotland', 'Wales', 'Northern Ireland'])
    expect(FACT_FIELDS).toContain('abstract_deadline')
    expect(FACT_FIELDS).toHaveLength(16)
  })
})

describe('feesSchema', () => {
  const tier = { label: 'Standard', price: 10, is_early_bird: false }
  it('accepts a normal block', () => {
    expect(feesSchema.safeParse({ currency: 'EUR', tiers: [tier] }).success).toBe(true)
  })
  it('rejects 13 tiers', () => {
    const r = feesSchema.safeParse({ currency: 'GBP', tiers: Array.from({ length: 13 }, () => tier) })
    expect(r.success).toBe(false)
  })
  it('accepts exactly 12 tiers', () => {
    expect(feesSchema.safeParse({ currency: 'GBP', tiers: Array.from({ length: 12 }, () => tier) }).success).toBe(true)
  })
  it('rejects a currency outside the whitelist', () => {
    expect(feesSchema.safeParse({ currency: 'JPY', tiers: [tier] }).success).toBe(false)
  })
  it('rejects negative price and over-long label', () => {
    expect(feesSchema.safeParse({ currency: 'GBP', tiers: [{ ...tier, price: -1 }] }).success).toBe(false)
    expect(feesSchema.safeParse({ currency: 'GBP', tiers: [{ ...tier, label: 'x'.repeat(41) }] }).success).toBe(false)
  })
  it('rejects a past early-bird deadline', () => {
    const r = feesSchema.safeParse({
      currency: 'GBP',
      tiers: [{ ...tier, is_early_bird: true, early_bird_deadline: day(-2) }],
    })
    expect(r.success).toBe(false)
  })
})

describe('newEventPayloadSchema', () => {
  it('accepts a valid payload and normalises the organiser url', () => {
    const r = newEventPayloadSchema.safeParse(validEvent())
    expect(r.success).toBe(true)
    if (r.success) expect(r.data.organiser_url).toBe('https://example.org/event')
  })
  it('rejects a start date in the past', () => {
    expect(newEventPayloadSchema.safeParse({ ...validEvent(), start_date: day(-1), end_date: undefined }).success).toBe(false)
  })
  it('accepts a start date of today (UTC)', () => {
    expect(newEventPayloadSchema.safeParse({ ...validEvent(), start_date: todayUtc(), end_date: undefined }).success).toBe(true)
  })
  it('rejects end before start', () => {
    expect(newEventPayloadSchema.safeParse({ ...validEvent(), end_date: day(10) }).success).toBe(false)
  })
  it('rejects abstract deadline after the start', () => {
    expect(newEventPayloadSchema.safeParse({ ...validEvent(), abstract_deadline: day(40) }).success).toBe(false)
  })
  it('rejects non-http(s) and malformed urls', () => {
    expect(newEventPayloadSchema.safeParse({ ...validEvent(), organiser_url: 'javascript:alert(1)' }).success).toBe(false)
    expect(newEventPayloadSchema.safeParse({ ...validEvent(), organiser_url: 'not a url' }).success).toBe(false)
    expect(newEventPayloadSchema.safeParse({ ...validEvent(), organiser_url: 'ftp://example.org/x' }).success).toBe(false)
  })
  it('rejects an unknown specialty label and an over-long name', () => {
    expect(newEventPayloadSchema.safeParse({ ...validEvent(), specialty: 'Basket Weaving' }).success).toBe(false)
    expect(newEventPayloadSchema.safeParse({ ...validEvent(), conference_name: 'x'.repeat(201) }).success).toBe(false)
  })
  it('rejects a description over 2000 characters', () => {
    expect(newEventPayloadSchema.safeParse({ ...validEvent(), description: 'x'.repeat(2001) }).success).toBe(false)
  })
  it('rejects CPD points without accreditation', () => {
    expect(newEventPayloadSchema.safeParse({ ...validEvent(), cpd_accredited: false, cpd_points: 3 }).success).toBe(false)
  })
})

describe('addInfoPayloadSchema', () => {
  it('accepts a fields-only payload', () => {
    expect(addInfoPayloadSchema.safeParse({ fields: { city: 'Leeds', cpd_accredited: true, cpd_points: 4 } }).success).toBe(true)
  })
  it('accepts a fees-only payload', () => {
    const r = addInfoPayloadSchema.safeParse({
      fields: {},
      fees: { currency: 'USD', tiers: [{ label: 'Free', price: 0, is_early_bird: false }] },
    })
    expect(r.success).toBe(true)
  })
  it('rejects an empty submission', () => {
    expect(addInfoPayloadSchema.safeParse({ fields: {} }).success).toBe(false)
  })
  it('rejects unknown field keys', () => {
    expect(addInfoPayloadSchema.safeParse({ fields: { favourite_colour: 'blue' } }).success).toBe(false)
  })
  it('rejects a past start date and a bad url', () => {
    expect(addInfoPayloadSchema.safeParse({ fields: { start_date: day(-3) } }).success).toBe(false)
    expect(addInfoPayloadSchema.safeParse({ fields: { organiser_url: 'mailto:a@b.c' } }).success).toBe(false)
  })
  it('checks an abstract deadline against the listing start via context', () => {
    const schema = makeAddInfoSchema({ startDate: day(20) })
    expect(schema.safeParse({ fields: { abstract_deadline: day(10) } }).success).toBe(true)
    expect(schema.safeParse({ fields: { abstract_deadline: day(25) } }).success).toBe(false)
  })
  it('checks end vs start inside the payload', () => {
    expect(addInfoPayloadSchema.safeParse({ fields: { start_date: day(10), end_date: day(9) } }).success).toBe(false)
    expect(addInfoPayloadSchema.safeParse({ fields: { start_date: day(10), end_date: day(11) } }).success).toBe(true)
  })
  it('rejects a note over 1000 characters', () => {
    expect(addInfoPayloadSchema.safeParse({ fields: { note: 'x'.repeat(1001) } }).success).toBe(false)
  })
})
