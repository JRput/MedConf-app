// src/lib/community/add-info-form.ts
// Pure form <-> payload logic for AddInfoDialog, split out so the resubmit
// round trip (payload -> form -> payload) and the UPDATE patch are unit-tested.

import { feesDraftToRaw, isFeesDraftEmpty, type FeesDraft } from './fees-draft'
import type { AddInfoPayload, AddInfoSection } from './types'

export interface AddInfoValues {
  start_date: string
  end_date: string
  start_time: string
  event_format: '' | 'in_person' | 'online' | 'hybrid'
  venue_name: string
  city: string
  region: string
  abstract_open: boolean
  abstract_deadline: string
  abstract_deadline_note: string
  cpd_accredited: boolean
  cpd_points: string
  organiser_url: string
  booking_url: string
  description: string
  note: string
  evidence_url: string
  moderator_note: string
}

export const EMPTY_VALUES: AddInfoValues = {
  start_date: '',
  end_date: '',
  start_time: '',
  event_format: '',
  venue_name: '',
  city: '',
  region: '',
  abstract_open: true,
  abstract_deadline: '',
  abstract_deadline_note: '',
  cpd_accredited: false,
  cpd_points: '',
  organiser_url: '',
  booking_url: '',
  description: '',
  note: '',
  evidence_url: '',
  moderator_note: '',
}

/** Form values from an earlier payload (resubmit mode); empty otherwise. */
export function valuesFromPayload(p: AddInfoPayload | undefined | null): AddInfoValues {
  if (!p) return EMPTY_VALUES
  const f = (p.fields ?? {}) as Record<string, unknown>
  const str = (k: string) => (f[k] === undefined || f[k] === null ? '' : String(f[k]))
  return {
    ...EMPTY_VALUES,
    start_date: str('start_date'),
    end_date: str('end_date'),
    start_time: str('start_time'),
    event_format: (['in_person', 'online', 'hybrid'].includes(str('event_format')) ? str('event_format') : '') as AddInfoValues['event_format'],
    venue_name: str('venue_name'),
    city: str('city'),
    region: str('region'),
    abstract_open: f.abstract_open === undefined ? true : f.abstract_open === true,
    abstract_deadline: str('abstract_deadline'),
    abstract_deadline_note: str('abstract_deadline_note'),
    cpd_accredited: f.cpd_accredited === true,
    cpd_points: str('cpd_points'),
    organiser_url: str('organiser_url'),
    booking_url: str('booking_url'),
    description: str('description'),
    note: str('note'),
    evidence_url: p.evidence_url ?? '',
    moderator_note: p.note ?? '',
  }
}

/** Which sections an earlier payload filled in (so resubmit reopens them). */
export function sectionsFromPayload(p: AddInfoPayload): AddInfoSection[] {
  const f = (p.fields ?? {}) as Record<string, unknown>
  const has = (...ks: string[]) => ks.some((k) => f[k] !== undefined && f[k] !== null && f[k] !== '')
  const out: AddInfoSection[] = []
  if (has('start_date', 'end_date', 'start_time')) out.push('dates')
  if (has('event_format', 'venue_name', 'city', 'region')) out.push('venue')
  if (p.fees) out.push('fees')
  if (has('abstract_deadline', 'abstract_deadline_note')) out.push('abstracts')
  if (has('cpd_accredited', 'cpd_points')) out.push('cpd')
  if (has('organiser_url', 'booking_url')) out.push('links')
  if (has('note', 'description')) out.push('note')
  return out
}

/** The raw (pre-zod) payload for whatever sections are open and filled. */
export function buildAddInfoRaw(
  v: AddInfoValues,
  fees: FeesDraft,
  open: ReadonlySet<AddInfoSection>,
  listingHasDescription: boolean
): Record<string, unknown> {
  const fields: Record<string, string | number | boolean> = {}
  const put = (k: string, val: string) => {
    if (val.trim() !== '') fields[k] = val.trim()
  }
  if (open.has('dates')) {
    put('start_date', v.start_date)
    put('end_date', v.end_date)
    put('start_time', v.start_time)
  }
  if (open.has('venue')) {
    if (v.event_format) fields.event_format = v.event_format
    if (v.event_format !== 'online') {
      put('venue_name', v.venue_name)
      put('city', v.city)
      put('region', v.region)
    }
  }
  if (open.has('abstracts')) {
    put('abstract_deadline', v.abstract_deadline)
    put('abstract_deadline_note', v.abstract_deadline_note)
    if (v.abstract_deadline.trim() || v.abstract_deadline_note.trim()) fields.abstract_open = v.abstract_open
  }
  if (open.has('cpd')) {
    if (v.cpd_points.trim() !== '') {
      fields.cpd_points = Number(v.cpd_points)
      fields.cpd_accredited = true
    } else if (v.cpd_accredited) fields.cpd_accredited = true
  }
  if (open.has('links')) {
    put('organiser_url', v.organiser_url)
    put('booking_url', v.booking_url)
  }
  if (open.has('note')) {
    put('note', v.note)
    if (!listingHasDescription) put('description', v.description)
  }
  const payload: Record<string, unknown> = { fields }
  if (open.has('fees') && !isFeesDraftEmpty(fees)) payload.fees = feesDraftToRaw(fees)
  if (v.moderator_note.trim()) payload.note = v.moderator_note.trim()
  if (v.evidence_url.trim()) payload.evidence_url = v.evidence_url.trim()
  return payload
}

/**
 * Columns the member's resubmit UPDATE writes. RLS only allows needs_info ->
 * pending; the database trigger resets enrichment and keeps everything else.
 */
export function buildResubmitPatch(data: { note?: string; evidence_url?: string } & Record<string, unknown>) {
  return {
    payload: data,
    note: data.note?.trim() || null,
    evidence_url: data.evidence_url?.trim() || null,
    status: 'pending' as const,
  }
}
