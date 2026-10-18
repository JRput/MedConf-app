// src/lib/community/overlay.ts
// Pure functions that merge published community facts onto a scraped
// conference. The one rule: scraped (organiser) data always wins — a
// community value only fills a field the scraper left empty.

import type { Conference, PricingTier } from '../types'
import { hasAbstractInfo } from '../conference-helpers'
import { normalizeUrl } from './normalize-url'
import { CURRENCIES } from './schema'
import type { AddInfoSection, CommunityFact, CommunityTier, FactField } from './types'

export type DisplayTier = PricingTier & { fromCommunity?: true }

export interface OverlayResult {
  conference: Conference
  /** Fields whose displayed value came from the community, not the organiser. */
  communityFields: Set<FactField>
}

const isEmpty = (v: unknown) => v === null || v === undefined || v === ''

// Community values were validated client-side at submit time, but rows can be
// inserted directly or mistyped by a moderator, so everything is re-checked
// here at render time. Each cleaner returns a safe value or null (= ignore).
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/
const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$/
// eslint-disable-next-line no-control-regex
const CONTROL_RE = /[\u0000-\u001f\u007f-\u009f  ​-‏‪-‮⁠⁦-⁩﻿]/g

function cleanText(v: unknown, max: number, keepNewlines = false): string | null {
  if (typeof v !== 'string') return null
  const stripped = keepNewlines
    ? v.replace(/\r\n?/g, '\n').replace(/[^\S\n]/g, ' ').replace(CONTROL_RE, (c) => (c === '\n' ? c : ''))
    : v.replace(CONTROL_RE, ' ')
  const t = stripped.trim().slice(0, max).trim()
  return t === '' ? null : t
}
function cleanUrl(v: unknown): string | null {
  return typeof v === 'string' ? normalizeUrl(v) : null
}
function cleanDate(v: unknown): string | null {
  if (typeof v !== 'string' || !DATE_RE.test(v)) return null
  const d = new Date(`${v}T00:00:00Z`)
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === v ? v : null
}
function cleanTime(v: unknown): string | null {
  if (typeof v !== 'string' || !TIME_RE.test(v)) return null
  return v.length === 5 ? `${v}:00` : v
}
function cleanPoints(v: unknown): number | null {
  return typeof v === 'number' && Number.isInteger(v) && v >= 0 && v <= 500 ? v : null
}
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

  const fillString = (
    field: 'venue_name' | 'city' | 'region' | 'organiser_url' | 'booking_url' | 'start_time',
    clean: (v: unknown) => string | null
  ) => {
    if (!isEmpty(conference[field])) return
    const v = clean(latest.get(field))
    if (v !== null) {
      merged[field] = v
      communityFields.add(field)
    }
  }
  const fillDate = (field: 'start_date' | 'end_date') => {
    if (!isEmpty(conference[field])) return
    const v = cleanDate(latest.get(field))
    if (v !== null) {
      merged[field] = v
      communityFields.add(field)
    }
  }
  const short = (v: unknown) => cleanText(v, 120)

  fillDate('start_date')
  fillDate('end_date')
  fillString('start_time', cleanTime)
  fillString('venue_name', short)
  fillString('city', short)
  fillString('region', short)
  fillString('organiser_url', cleanUrl)
  fillString('booking_url', cleanUrl)

  const fmt = latest.get('event_format')
  if (isEmpty(conference.event_format) && typeof fmt === 'string' && FORMATS.includes(fmt)) {
    merged.event_format = fmt as Conference['event_format']
    communityFields.add('event_format')
  }

  // Abstracts: all-or-nothing, only when the scraper has no abstract info at all.
  if (!hasAbstractInfo(conference)) {
    const dl = cleanDate(latest.get('abstract_deadline'))
    const note = cleanText(latest.get('abstract_deadline_note'), 200)
    const open = latest.get('abstract_open')
    let used = false
    if (dl !== null) {
      merged.abstract_deadline = dl
      communityFields.add('abstract_deadline')
      used = true
    }
    if (note !== null) {
      merged.abstract_deadline_note = note
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
    const pts = cleanPoints(latest.get('cpd_points'))
    if (pts !== null && acc !== false) {
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
  const out: DisplayTier[] = []
  for (const t of community) {
    if (!t.is_published) continue
    const price = typeof t.price === 'string' && t.price.trim() !== '' ? Number(t.price) : t.price
    const label = cleanText(t.tier_label, 40)
    if (label === null || typeof price !== 'number' || !Number.isFinite(price) || price < 0) continue
    if (!(CURRENCIES as readonly string[]).includes(t.currency)) continue
    out.push({
      // Negative ids can never collide with real pricing_tiers ids.
      id: -(out.length + 1),
      conference_id: t.conference_id,
      session_id: null,
      tier_label: label,
      price_gbp: price,
      currency: t.currency,
      is_early_bird: t.is_early_bird === true,
      early_bird_deadline: cleanDate(t.early_bird_deadline),
      fromCommunity: true as const,
    })
  }
  return out
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
