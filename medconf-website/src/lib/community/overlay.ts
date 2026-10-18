// src/lib/community/overlay.ts
// Pure functions that merge published community facts onto a scraped
// conference. The one rule: scraped (organiser) data always wins — a
// community value only fills a field the scraper left empty.

import type { Conference, PricingTier } from '../types'
import { hasAbstractInfo } from '../conference-helpers'
import type { AddInfoSection, CommunityFact, CommunityTier, FactField } from './types'

export type DisplayTier = PricingTier & { fromCommunity?: true }

export interface OverlayResult {
  conference: Conference
  /** Fields whose displayed value came from the community, not the organiser. */
  communityFields: Set<FactField>
}

const isEmpty = (v: unknown) => v === null || v === undefined || v === ''
const isStr = (v: unknown): v is string => typeof v === 'string' && v.trim() !== ''
const isDate = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const FORMATS = ['in_person', 'online', 'hybrid']

/** Newest published fact per field (later created_at wins). */
function latestByField(facts: CommunityFact[]): Map<FactField, unknown> {
  const sorted = facts
    .filter((f) => f.is_published)
    .slice()
    .sort((a, b) => (a.created_at ?? '').localeCompare(b.created_at ?? ''))
  const out = new Map<FactField, unknown>()
  for (const f of sorted) out.set(f.field, f.value)
  return out
}

export function overlayConference(conference: Conference, facts: CommunityFact[]): OverlayResult {
  const merged: Conference = { ...conference }
  const communityFields = new Set<FactField>()
  const latest = latestByField(facts)

  const fillString = (field: 'venue_name' | 'city' | 'region' | 'organiser_url' | 'booking_url' | 'start_time') => {
    const v = latest.get(field)
    if (isEmpty(conference[field]) && isStr(v)) {
      merged[field] = v.trim()
      communityFields.add(field)
    }
  }
  const fillDate = (field: 'start_date' | 'end_date') => {
    const v = latest.get(field)
    if (isEmpty(conference[field]) && isDate(v)) {
      merged[field] = v
      communityFields.add(field)
    }
  }

  fillDate('start_date')
  fillDate('end_date')
  fillString('start_time')
  fillString('venue_name')
  fillString('city')
  fillString('region')
  fillString('organiser_url')
  fillString('booking_url')

  const fmt = latest.get('event_format')
  if (isEmpty(conference.event_format) && typeof fmt === 'string' && FORMATS.includes(fmt)) {
    merged.event_format = fmt as Conference['event_format']
    communityFields.add('event_format')
  }

  // Abstracts: all-or-nothing, only when the scraper has no abstract info at all.
  if (!hasAbstractInfo(conference)) {
    const dl = latest.get('abstract_deadline')
    const note = latest.get('abstract_deadline_note')
    const open = latest.get('abstract_open')
    let used = false
    if (isDate(dl)) {
      merged.abstract_deadline = dl
      communityFields.add('abstract_deadline')
      used = true
    }
    if (isStr(note)) {
      merged.abstract_deadline_note = note.trim()
      communityFields.add('abstract_deadline_note')
      used = true
    }
    if (used) {
      merged.abstract_open = typeof open === 'boolean' ? open : true
      if (typeof open === 'boolean') communityFields.add('abstract_open')
    }
  }

  // CPD: only when the scraper says "not accredited" AND has no points.
  if (!conference.cpd_accredited && conference.cpd_points == null) {
    const acc = latest.get('cpd_accredited')
    const pts = latest.get('cpd_points')
    if (isNum(pts) && acc !== false) {
      merged.cpd_points = pts
      merged.cpd_accredited = true
      communityFields.add('cpd_points')
      communityFields.add('cpd_accredited')
    } else if (acc === true) {
      merged.cpd_accredited = true
      communityFields.add('cpd_accredited')
    }
  }

  return { conference: merged, communityFields }
}

/** Scraped tiers if there are any, otherwise the published community tiers. */
export function pickTiers(scraped: PricingTier[], community: CommunityTier[]): DisplayTier[] {
  if (scraped.length > 0) return scraped
  return community
    .filter((t) => t.is_published)
    .map((t, i) => ({
      // Negative ids can never collide with real pricing_tiers ids.
      id: -(i + 1),
      conference_id: t.conference_id,
      session_id: null,
      tier_label: t.tier_label,
      price_gbp: Number(t.price),
      currency: t.currency,
      is_early_bird: !!t.is_early_bird,
      early_bird_deadline: t.early_bird_deadline,
      fromCommunity: true as const,
    }))
}

/** Which AddInfo sections to offer: only the ones the listing is missing. */
export function emptySections(conference: Conference, tiers: PricingTier[]): AddInfoSection[] {
  const out: AddInfoSection[] = []
  if (isEmpty(conference.start_date)) out.push('dates')
  if (
    isEmpty(conference.event_format) ||
    (conference.event_format !== 'online' && isEmpty(conference.venue_name) && isEmpty(conference.city))
  ) {
    out.push('venue')
  }
  if (tiers.length === 0 && conference.event_type !== 'course') out.push('fees')
  if (!hasAbstractInfo(conference)) out.push('abstracts')
  if (!conference.cpd_accredited && conference.cpd_points == null) out.push('cpd')
  if (isEmpty(conference.organiser_url)) out.push('links')
  out.push('note')
  return out
}
