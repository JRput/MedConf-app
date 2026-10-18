import { describe, expect, it } from 'vitest'
import {
  COMMON_COUNTRIES,
  EMPTY_VALUES,
  OTHER_COUNTRY,
  UK,
  buildRawPayload,
  duplicateQuery,
  flagDuplicates,
  missingRequired,
  payloadToValues,
  regionFor,
  shouldCheckDuplicates,
  toMatches,
  validateSubmit,
  type SubmitValues,
} from '../../components/community/submit/logic'
import { clearDraft, draftKey, loadDraft, saveDraft } from '../community/submit-draft'
import { emptyFeesDraft, newTierDraft } from '../community/fees-draft'

const day = (n: number) => {
  const d = new Date()
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

const valid = (over: Partial<SubmitValues> = {}): SubmitValues => ({
  ...EMPTY_VALUES,
  conference_name: 'Leeds Oncology Day',
  organiser_url: 'https://Example.org/event/?utm_source=x',
  event_type: 'conference',
  event_format: 'in_person',
  start_date: day(30),
  country: UK,
  uk_nation: 'England',
  specialty_slug: 'oncology',
  consent: true,
  ...over,
})

describe('region mapping', () => {
  it('stores the UK nation', () => expect(regionFor(valid())).toBe('England'))
  it('UK without a nation has no region', () => expect(regionFor(valid({ uk_nation: '' }))).toBeUndefined())
  it('non-UK uses the country name', () => expect(regionFor(valid({ country: 'Ireland' }))).toBe('Ireland'))
  it('free-text country is used for region', () =>
    expect(regionFor(valid({ country: OTHER_COUNTRY, country_other: ' Norway ' }))).toBe('Norway'))
  it('lists the UK first', () => expect(COMMON_COUNTRIES[0]).toBe(UK))
})

describe('payload builder and validation', () => {
  it('builds a valid, normalised payload with the specialty LABEL', () => {
    const r = validateSubmit(valid(), emptyFeesDraft())
    expect(r.errors).toEqual({})
    expect(r.payload?.specialty).toBe('Oncology')
    expect(r.payload?.organiser_url).toBe('https://example.org/event')
    expect(r.payload?.region).toBe('England')
    expect(r.payload?.fees).toBeUndefined()
  })

  it('drops dependent fields when their toggle is off', () => {
    const raw = buildRawPayload(
      valid({ cpd_accredited: false, cpd_points: '5', abstract_open: false, abstract_deadline: day(5), event_format: 'online', venue_name: 'X' }),
      emptyFeesDraft()
    )
    expect(raw.cpd_points).toBeUndefined()
    expect(raw.abstract_deadline).toBeUndefined()
    expect(raw.venue_name).toBeUndefined()
  })

  it('requires the mandatory fields', () => {
    const r = validateSubmit(EMPTY_VALUES, emptyFeesDraft())
    expect(r.payload).toBeNull()
    for (const k of ['conference_name', 'organiser_url', 'event_type', 'event_format', 'start_date', 'country', 'specialty', 'consent']) {
      expect(r.errors[k], k).toBeTruthy()
    }
    expect(missingRequired(EMPTY_VALUES)).toHaveLength(8)
    expect(missingRequired(valid())).toEqual([])
  })

  it('rejects past start, end before start, deadline after start', () => {
    expect(validateSubmit(valid({ start_date: day(-2) }), emptyFeesDraft()).errors.start_date).toMatch(/today or later/i)
    expect(validateSubmit(valid({ end_date: day(10) }), emptyFeesDraft()).errors.end_date).toMatch(/before the start/i)
    expect(validateSubmit(valid({ abstract_open: true, abstract_deadline: day(40) }), emptyFeesDraft()).errors.abstract_deadline).toMatch(/on or before/i)
  })

  it('rejects a description over 2 000 characters', () => {
    expect(validateSubmit(valid({ description: 'a'.repeat(2001) }), emptyFeesDraft()).errors.description).toBeTruthy()
  })

  it('requires consent and a country name for Other', () => {
    expect(validateSubmit(valid({ consent: false }), emptyFeesDraft()).errors.consent).toBeTruthy()
    expect(validateSubmit(valid({ country: OTHER_COUNTRY }), emptyFeesDraft()).errors.country).toBeTruthy()
  })

  it('includes valid fees and flags invalid ones', () => {
    const ok = emptyFeesDraft('EUR')
    const t = newTierDraft('Member')
    t.price = '90'
    ok.tiers.push(t)
    const good = validateSubmit(valid(), ok)
    expect(good.payload?.fees).toEqual({ currency: 'EUR', tiers: [{ label: 'Member', price: 90, is_early_bird: false }] })

    const bad = emptyFeesDraft()
    const b = newTierDraft('Standard')
    b.price = '-5'
    bad.tiers.push(b)
    const r = validateSubmit(valid(), bad)
    expect(r.feesInvalid).toBe(true)
    expect(r.payload).toBeNull()
  })
})

describe('duplicate check', () => {
  const rows = [
    { id: 1, name: 'Other Meeting', startDate: '2027-01-01', organiserUrl: 'https://different.org/x' },
    { id: 2, name: 'Leeds Oncology Day', start_date: '2027-03-01', organiser_url: 'https://www.example.org/old' },
    { id: 3, conference_name: 'Snake case', source_url: 'https://example.org/z' },
    { nope: true },
  ]
  it('normalises both row shapes and skips junk', () => {
    const m = toMatches(rows)
    expect(m.map((x) => x.id)).toEqual([1, 2, 3])
    expect(m[2].organiserUrl).toBe('https://example.org/z')
    expect(toMatches(null)).toEqual([])
  })
  it('flags same-domain matches first', () => {
    const f = flagDuplicates(toMatches(rows), 'https://example.org/event')
    expect(f.map((x) => [x.id, x.sameSite])).toEqual([
      [2, true],
      [3, true],
      [1, false],
    ])
  })
  it('checks only with 4+ chars or a valid URL', () => {
    expect(shouldCheckDuplicates('abc', '')).toBe(false)
    expect(shouldCheckDuplicates('abcd', '')).toBe(true)
    expect(shouldCheckDuplicates('', 'https://example.org')).toBe(true)
    expect(shouldCheckDuplicates('', 'not a url')).toBe(false)
    expect(duplicateQuery('Leeds Day', '')).toBe('Leeds Day')
    expect(duplicateQuery('', 'https://www.example.org/a')).toBe('example.org')
  })
})

describe('resubmit prefill', () => {
  it('round-trips a stored payload, resetting consent', () => {
    const fees = emptyFeesDraft('GBP')
    const t = newTierDraft('Nurse')
    t.custom = true
    t.price = '40'
    fees.tiers.push(t)
    const r = validateSubmit(valid({ city: 'Leeds', cpd_accredited: true, cpd_points: '6' }), fees)
    expect(r.payload).not.toBeNull()
    const back = payloadToValues(r.payload!)
    expect(back.values.consent).toBe(false)
    expect(back.values.specialty_slug).toBe('oncology')
    expect(back.values.uk_nation).toBe('England')
    expect(back.values.cpd_points).toBe('6')
    expect(back.fees.tiers[0]).toMatchObject({ label: 'Nurse', custom: true, price: '40' })
    expect(validateSubmit({ ...back.values, consent: true }, back.fees).payload).toEqual(r.payload)
  })
  it('maps an unknown country to Other', () => {
    const { values } = payloadToValues({ country: 'Norway', region: 'Norway' })
    expect(values.country).toBe(OTHER_COUNTRY)
    expect(values.country_other).toBe('Norway')
  })
})

describe('draft storage', () => {
  const mem = () => {
    const m = new Map<string, string>()
    return {
      getItem: (k: string) => m.get(k) ?? null,
      setItem: (k: string, v: string) => void m.set(k, v),
      removeItem: (k: string) => void m.delete(k),
    }
  }
  it('saves, loads per user and clears', () => {
    const s = mem()
    expect(saveDraft('u1', { values: { a: 1 }, fees: { b: 2 } }, s, 123)).toBe(true)
    expect(loadDraft('u1', s)).toEqual({ values: { a: 1 }, fees: { b: 2 }, savedAt: 123 })
    expect(loadDraft('u2', s)).toBeNull()
    expect(draftKey('u1')).not.toBe(draftKey('u2'))
    clearDraft('u1', s)
    expect(loadDraft('u1', s)).toBeNull()
  })
  it('never throws on broken storage or corrupt data', () => {
    const boom = {
      getItem: () => { throw new Error('x') },
      setItem: () => { throw new Error('x') },
      removeItem: () => { throw new Error('x') },
    }
    expect(saveDraft('u', { values: 1, fees: 1 }, boom)).toBe(false)
    expect(loadDraft('u', boom)).toBeNull()
    expect(() => clearDraft('u', boom)).not.toThrow()
    const s = mem()
    s.setItem(draftKey('u'), '{not json')
    expect(loadDraft('u', s)).toBeNull()
  })
})
