import { describe, expect, it } from 'vitest'
import { buildAddInfoRaw, buildResubmitPatch, sectionsFromPayload, valuesFromPayload } from '../community/add-info-form'
import { feesPayloadToDraft } from '../community/moderation'
import { makeAddInfoSchema } from '../community/schema'
import type { AddInfoPayload } from '../community/types'

const payload: AddInfoPayload = {
  fields: {
    start_date: '2099-05-01',
    end_date: '2099-05-02',
    event_format: 'in_person',
    venue_name: 'City Hall',
    city: 'Leeds',
    abstract_deadline: '2099-03-01',
    abstract_open: true,
    cpd_accredited: true,
    cpd_points: 6,
    organiser_url: 'https://example.org/e',
    note: 'Public note',
  },
  fees: { currency: 'GBP', tiers: [{ label: 'Standard', price: 120, is_early_bird: false }] },
  note: 'For the moderator',
  evidence_url: 'https://example.org/evidence',
}

describe('resubmit round trip', () => {
  it('payload -> form -> payload is lossless and still validates', () => {
    const open = new Set(sectionsFromPayload(payload))
    expect([...open].sort()).toEqual(['abstracts', 'cpd', 'dates', 'fees', 'links', 'note', 'venue'])
    const raw = buildAddInfoRaw(valuesFromPayload(payload), feesPayloadToDraft(payload.fees), open, true)
    const parsed = makeAddInfoSchema({}).safeParse(raw)
    expect(parsed.success).toBe(true)
    if (parsed.success) expect(parsed.data).toEqual(payload)
  })

  it('keeps the moderator message and evidence link', () => {
    const v = valuesFromPayload(payload)
    expect(v.moderator_note).toBe('For the moderator')
    expect(v.evidence_url).toBe('https://example.org/evidence')
  })

  it('empty payload gives empty form', () => {
    expect(valuesFromPayload(undefined).start_date).toBe('')
    expect(valuesFromPayload(undefined).abstract_open).toBe(true)
  })
})

describe('buildResubmitPatch', () => {
  it('sends payload, note, evidence_url and status pending', () => {
    const patch = buildResubmitPatch(payload as never)
    expect(patch).toEqual({
      payload,
      note: 'For the moderator',
      evidence_url: 'https://example.org/evidence',
      status: 'pending',
    })
  })
  it('nulls blank note and evidence', () => {
    expect(buildResubmitPatch({ fields: {} } as never)).toMatchObject({ note: null, evidence_url: null, status: 'pending' })
  })
})
