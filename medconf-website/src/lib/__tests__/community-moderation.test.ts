import { describe, expect, it } from 'vitest'
import {
  ageLabel,
  buildFieldRows,
  buildFinalPayload,
  canApprove,
  disagreementFields,
  domainLabel,
  domainSignals,
  duplicateCandidates,
  finalProblems,
  flattenEnrichment,
  needsOverride,
  normalizePayload,
  rejectedUrls,
  foundTiers,
  significantWords,
  validReason,
  type DuplicateRow,
} from '../community/moderation'

const newEvent = {
  conference_name: 'North Sea Oncology Summit 2027',
  event_type: 'conference',
  event_format: 'in_person',
  start_date: '2027-03-10',
  country: 'United Kingdom',
  city: 'Leeds',
  specialty: 'Oncology',
  organiser_url: 'https://www.example.org/nsos/?utm_source=x',
  cpd_accredited: false,
  abstract_open: false,
}

const enrichment = {
  city: { value: 'Leeds', method: 'text', agrees: true },
  venue_name: { value: 'Royal Armouries', method: 'jsonld', agrees: null },
  description: { value: 'A two day meeting.', method: 'meta', agrees: null },
  cpd_points: { value: 12, method: 'text_regex', agrees: false },
  event_format: { value: 'hybrid', method: 'text', agrees: false },
  abstract_status: {
    value: { abstract_open: true, abstract_deadline: '2026-12-01' },
    method: 'programme_deadline',
    agrees: null,
  },
  pricing: {
    value: [{ tier_label: 'Standard', price_gbp: 250, currency: 'GBP', is_early_bird: false }],
    method: 'text_regex',
    agrees: false,
  },
  _error: 'ignored',
}

describe('buildFinalPayload', () => {
  it('defaults to the user value, not the organiser value, when both exist', () => {
    const { final } = buildFinalPayload(newEvent, enrichment)
    expect(final.event_format).toBe('in_person')
    expect(final.city).toBe('Leeds')
  })

  it('prefills user-empty fields from the organiser site and marks them', () => {
    const { final, prefilled } = buildFinalPayload(newEvent, enrichment)
    expect(final.venue_name).toBe('Royal Armouries')
    expect(final.description).toBe('A two day meeting.')
    expect(final.abstract_deadline).toBe('2026-12-01')
    expect(prefilled).toEqual(expect.arrayContaining(['venue_name', 'description', 'cpd_points', 'abstract_deadline', 'fees']))
    expect(prefilled).not.toContain('city')
    expect(prefilled).not.toContain('event_format')
  })

  it('prefills found fee tiers for a new event with none, but keeps user fees when present', () => {
    const a = buildFinalPayload(newEvent, enrichment)
    expect(a.final.fees).toEqual({ currency: 'GBP', tiers: [{ label: 'Standard', price: 250, is_early_bird: false }] })
    const mine = { currency: 'EUR', tiers: [{ label: 'Member', price: 90, is_early_bird: false }] }
    const b = buildFinalPayload({ ...newEvent, fees: mine }, enrichment)
    expect(b.final.fees).toEqual(mine)
    expect(b.prefilled).not.toContain('fees')
  })

  it('normalises URLs and applies edits over both sources', () => {
    const { final, prefilled } = buildFinalPayload(newEvent, enrichment, { city: 'York', venue_name: '', cpd_points: '8' })
    expect(final.organiser_url).toBe('https://www.example.org/nsos')
    expect(final.city).toBe('York')
    expect(final.venue_name).toBeUndefined()
    expect(final.cpd_points).toBe(8)
    expect(prefilled).not.toContain('venue_name')
    expect(prefilled).not.toContain('cpd_points')
  })

  it('lets the moderator clear fees', () => {
    const { final } = buildFinalPayload(newEvent, enrichment, { fees: null })
    expect(final.fees).toBeUndefined()
  })

  it('never auto-applies organiser values to an add_info contribution', () => {
    const addInfo = { fields: { city: 'Leeds' }, note: 'hello' }
    const { final, prefilled } = buildFinalPayload(addInfo, enrichment)
    expect(final.fields).toEqual({ city: 'Leeds' })
    expect(final.fees).toBeUndefined()
    expect(final.note).toBe('hello')
    expect(prefilled).toEqual([])
    // ...but a conscious edit does apply.
    const used = buildFinalPayload(addInfo, enrichment, { venue_name: 'Royal Armouries' })
    expect((used.final.fields as Record<string, unknown>).venue_name).toBe('Royal Armouries')
  })

  it('keeps booleans and drops blank strings', () => {
    const { final } = buildFinalPayload({ ...newEvent, is_flagship: true, booking_url: '  ' }, null)
    expect(final.is_flagship).toBe(true)
    expect(final.cpd_accredited).toBe(false)
    expect('booking_url' in final).toBe(false)
  })
})

describe('buildFieldRows / flattenEnrichment', () => {
  it('expands abstract_status into per-field rows and drops internal keys', () => {
    const flat = flattenEnrichment(enrichment, newEvent)
    expect(flat.abstract_open.value).toBe(true)
    expect(flat.abstract_deadline.value).toBe('2026-12-01')
    expect(flat._error).toBeUndefined()
  })

  it('gives one row per user or organiser field and flags disagreement', () => {
    const rows = buildFieldRows(newEvent, enrichment)
    const byField = Object.fromEntries(rows.map((r) => [r.field, r]))
    expect(byField.event_format.disagrees).toBe(true)
    expect(byField.city.disagrees).toBe(false)
    expect(byField.venue_name.user).toBeUndefined()
    expect(byField.venue_name.fromEnrichment).toBe(true)
    expect(byField.pricing).toBeUndefined()
  })

  it('maps pricing tiers', () => {
    expect(foundTiers(enrichment)?.tiers[0]).toMatchObject({ label: 'Standard', price: 250 })
    expect(foundTiers(null)).toBeNull()
  })
})

describe('disagreementFields', () => {
  it('lists fields with agrees === false, fees included', () => {
    expect(disagreementFields(enrichment)).toEqual(['event_format', 'cpd_points', 'fees'])
  })
  it('is empty for no enrichment', () => {
    expect(disagreementFields(null)).toEqual([])
    expect(disagreementFields({})).toEqual([])
  })
})

describe('canApprove', () => {
  it('refuses when the enrichment job rejected the URL as unsafe', () => {
    const r = canApprove({ status: 'pending', enrichment_status: 'skipped' })
    expect(r.ok).toBe(false)
    expect(r.reason).toMatch(/unsafe/i)
  })
  it('refuses items that are no longer open', () => {
    expect(canApprove({ status: 'published', enrichment_status: 'fetched' }).ok).toBe(false)
    expect(canApprove({ status: 'rejected', enrichment_status: 'fetched' }).ok).toBe(false)
  })
  it('warns but allows blocked, failed and waiting', () => {
    for (const es of ['blocked', 'failed', 'waiting'] as const) {
      const r = canApprove({ status: 'pending', enrichment_status: es })
      expect(r.ok).toBe(true)
      expect(r.warning).toBeTruthy()
    }
  })
  it('allows fetched and needs_info with no warning', () => {
    expect(canApprove({ status: 'needs_info', enrichment_status: 'fetched' })).toEqual({ ok: true })
  })
})

describe('duplicateCandidates', () => {
  const rows: DuplicateRow[] = [
    { id: 1, name: 'Unrelated Cardiology Update', startDate: '2027-03-10', organiserUrl: 'https://other.org/x' },
    { id: 2, name: 'Something Else Entirely', startDate: '2028-01-01', organiserUrl: 'https://example.org/other-page' },
    { id: 3, name: 'North Sea Oncology Summit', startDate: '2027-03-25', organiserUrl: null },
    { id: 4, name: 'North Sea Oncology Summit', startDate: '2027-06-25', organiserUrl: null },
    { id: 5, name: 'Oncology Summit Edinburgh', startDate: '2027-03-11', organiserUrl: 'https://different.org' },
    { id: 6, name: 'North Sea Oncology Summit 2027', startDate: '2027-03-10', organiserUrl: 'https://example.org/nsos' },
  ]

  it('matches on same domain even with www and different names or dates', () => {
    const ids = duplicateCandidates(newEvent, rows).map((r) => r.id)
    expect(ids).toContain(2)
    expect(duplicateCandidates(newEvent, rows).find((r) => r.id === 2)?.reasons).toEqual(['same_domain'])
  })

  it('matches names sharing two significant words within 30 days only', () => {
    const ids = duplicateCandidates(newEvent, rows).map((r) => r.id)
    expect(ids).toContain(3) // 15 days
    expect(ids).not.toContain(4) // 107 days
    expect(ids).not.toContain(5) // "summit" is a stop word, so only "oncology" is shared
  })

  it('does not match one shared word or unrelated rows', () => {
    const ids = duplicateCandidates(newEvent, rows).map((r) => r.id)
    expect(ids).not.toContain(1)
  })

  it('ranks the double match first', () => {
    expect(duplicateCandidates(newEvent, rows)[0].id).toBe(6)
    expect(duplicateCandidates(newEvent, rows)[0].reasons).toEqual(['same_domain', 'similar_name'])
  })

  it('returns nothing without usable input', () => {
    expect(duplicateCandidates({}, rows)).toEqual([])
    expect(duplicateCandidates(newEvent, [])).toEqual([])
  })
})

describe('significantWords', () => {
  it('drops stop words, years and short tokens', () => {
    expect(significantWords('The 2027 Annual Leeds Oncology Conference of UK')).toEqual(['leeds', 'oncology'])
  })
})

describe('finalProblems', () => {
  it('requires name, start date and a valid organiser url for new events', () => {
    expect(finalProblems(newEvent, buildFinalPayload(newEvent, null).final)).toEqual([])
    const bad = buildFinalPayload({ ...newEvent, conference_name: '', organiser_url: 'ftp://x' }, null)
    expect(finalProblems(newEvent, bad.final).length).toBe(2)
  })
  it('flags an empty add_info', () => {
    const f = buildFinalPayload({ fields: {} }, null).final
    expect(finalProblems({ fields: {} }, f).length).toBe(1)
  })
})

describe('helpers', () => {
  it('validReason needs 5 characters after trimming', () => {
    expect(validReason('  no ')).toBe(false)
    expect(validReason('Too vague')).toBe(true)
  })
  it('ageLabel', () => {
    const now = Date.parse('2026-10-18T12:00:00Z')
    expect(ageLabel('2026-10-18T11:58:00Z', now)).toBe('2 min')
    expect(ageLabel('2026-10-18T07:00:00Z', now)).toBe('5 h')
    expect(ageLabel('2026-10-10T12:00:00Z', now)).toBe('8 d')
  })
})

describe('needsOverride (mirrors the database publish gate)', () => {
  const checked = { _checked_url: 'https://example.org/nsos', _submitted_url: 'https://example.org/nsos?utm_source=x' }
  it('is needed while enrichment is waiting', () => {
    const r = needsOverride({ enrichment_status: 'waiting', enrichment: null }, 'https://example.org/nsos')
    expect(r.needed).toBe(true)
    expect(r.reason).toMatch(/not been safety-checked/)
  })
  it('is not needed for a fetched row whose URL matches the checked or submitted URL', () => {
    expect(needsOverride({ enrichment_status: 'fetched', enrichment: checked }, 'https://example.org/nsos').needed).toBe(false)
    expect(needsOverride({ enrichment_status: 'fetched', enrichment: checked }, 'https://EXAMPLE.org/nsos/?utm_medium=y').needed).toBe(false)
  })
  it('is needed when the moderator changed the URL to an unchecked one', () => {
    const r = needsOverride({ enrichment_status: 'fetched', enrichment: checked }, 'https://other.org/page')
    expect(r.needed).toBe(true)
    expect(r.reason).toMatch(/changed/)
  })
  it('does not check the URL when the job recorded none, or the final has none', () => {
    expect(needsOverride({ enrichment_status: 'fetched', enrichment: {} }, 'https://other.org').needed).toBe(false)
    expect(needsOverride({ enrichment_status: 'fetched', enrichment: checked }, undefined).needed).toBe(false)
  })
  it('skipped is never overridable, and blocked/failed need no override', () => {
    expect(needsOverride({ enrichment_status: 'skipped', enrichment: null }, 'https://x.org').needed).toBe(false)
    expect(needsOverride({ enrichment_status: 'blocked', enrichment: null }, 'https://x.org').needed).toBe(false)
  })
})

describe('rejected links', () => {
  const enr = { ...enrichment, _rejected_urls: ['https://bad.example/evil?utm_source=a', { url: 'http://10.0.0.1/x' }, 42] }
  it('lists normalised rejected URLs', () => {
    expect(rejectedUrls(enr)).toEqual(['https://bad.example/evil', 'http://10.0.0.1/x'])
    expect(rejectedUrls({})).toEqual([])
    expect(rejectedUrls(null)).toEqual([])
  })
  it('strips rejected URLs from the final payload', () => {
    const p = { ...newEvent, booking_url: 'https://bad.example/evil', evidence_url: 'http://10.0.0.1/x' }
    const r = buildFinalPayload(p, enr)
    expect(r.final.booking_url).toBeUndefined()
    expect(r.final.evidence_url).toBeUndefined()
    expect(r.stripped).toEqual(['booking_url'])
    expect(r.final.organiser_url).toBe('https://www.example.org/nsos')
  })
  it('strips a rejected organiser URL, which then blocks approval', () => {
    const r = buildFinalPayload(newEvent, { ...enrichment, _rejected_urls: ['https://www.example.org/nsos'] })
    expect(r.final.organiser_url).toBeUndefined()
    expect(finalProblems(newEvent, r.final).join(' ')).toMatch(/organiser URL/)
  })
})

describe('domainSignals', () => {
  const rows: DuplicateRow[] = [{ id: 1, name: 'x', startDate: null, organiserUrl: 'https://www.esmo.org/meeting-calendar/a' }]
  it('extracts domains without www', () => {
    const s = domainSignals({ organiser_url: 'https://www.Example.org/a', booking_url: 'https://tickets.example.org/b' }, null)
    expect(s.organiserDomain).toBe('example.org')
    expect(s.bookingDomain).toBe('tickets.example.org')
  })
  it('flags a booking domain that differs from the organiser domain', () => {
    expect(domainSignals({ organiser_url: 'https://a.org', booking_url: 'https://b.com' }, null).mismatch).toBe(true)
    expect(domainSignals({ organiser_url: 'https://www.a.org', booking_url: 'https://a.org/x' }, null).mismatch).toBe(false)
    expect(domainSignals({ organiser_url: 'https://a.org' }, null).mismatch).toBe(false)
  })
  it('unseen: null until rows load, true when no row shares the domain, false when one does', () => {
    expect(domainSignals({ organiser_url: 'https://esmo.org/x' }, null).unseen).toBeNull()
    expect(domainSignals({ organiser_url: 'https://new-site.org/x' }, rows).unseen).toBe(true)
    expect(domainSignals({ organiser_url: 'https://esmo.org/other' }, rows).unseen).toBe(false)
    expect(domainSignals({ organiser_url: 'https://esmo.org/x' }, []).unseen).toBe(true)
  })
  it('reads add_info fields and ignores invalid urls', () => {
    expect(domainSignals({ fields: { organiser_url: 'https://a.org' } }, null).organiserDomain).toBe('a.org')
    expect(domainSignals({ organiser_url: 'javascript:alert(1)' }, rows)).toEqual({ organiserDomain: null, bookingDomain: null, mismatch: false, unseen: null })
  })
  it('domainLabel picks the registrable label', () => {
    expect(domainLabel('www.rcseng.ac.uk')).toBe('rcseng')
    expect(domainLabel('esmo.org')).toBe('esmo')
    expect(domainLabel('tickets.example.com')).toBe('example')
    expect(domainLabel(null)).toBeNull()
  })
})

describe('normalizePayload (shape comes from kind)', () => {
  it('passes a well-formed add_info and new_event unchanged in shape', () => {
    const a = normalizePayload('add_info', { fields: { city: 'Leeds' }, note: 'n', evidence_url: 'https://e.org' })
    expect(a).toEqual({ payload: { fields: { city: 'Leeds' }, note: 'n', evidence_url: 'https://e.org' }, mismatch: false })
    expect(normalizePayload('new_event', newEvent).mismatch).toBe(false)
  })
  it('add_info row with a flat new-event payload: flagged, flat keys ignored, nothing publishable', () => {
    const r = normalizePayload('add_info', newEvent)
    expect(r.mismatch).toBe(true)
    expect(r.payload).toEqual({ fields: {} })
    const built = buildFinalPayload(r.payload, null).final
    expect(built).toEqual({ fields: {} })
    expect(finalProblems(r.payload, built).length).toBe(1)
  })
  it('add_info keeps only fields/fees/note/evidence_url even alongside flat keys', () => {
    const r = normalizePayload('add_info', { ...newEvent, fields: { city: 'York' } })
    expect(r.mismatch).toBe(false)
    expect(Object.keys(r.payload)).toEqual(['fields'])
    expect(buildFinalPayload(r.payload, null).final).toEqual({ fields: { city: 'York' } })
  })
  it('new_event row with an add_info-shaped payload is flagged and the nested fields ignored', () => {
    const r = normalizePayload('new_event', { fields: { city: 'York' }, conference_name: 'X' })
    expect(r.mismatch).toBe(true)
    expect(r.payload).toEqual({ conference_name: 'X' })
    expect(buildFinalPayload(r.payload, null).final.fields).toBeUndefined()
  })
  it('garbage payloads normalise to empty', () => {
    expect(normalizePayload('add_info', null)).toEqual({ payload: { fields: {} }, mismatch: true })
    expect(normalizePayload('new_event', 'x')).toEqual({ payload: {}, mismatch: false })
  })
})
