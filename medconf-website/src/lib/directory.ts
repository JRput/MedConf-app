// src/lib/directory.ts
// The view-model the directory primitives render. Keeping it separate from the
// raw `Conference` row means EventRow/EventCardCompact do not have to know how
// pricing tiers are joined, how societies are folded, or where the link points —
// W2 can change all of that without touching a component.

import type { Conference, PricingTier } from './types'
import { isAbstractEffectivelyOpen } from './conference-helpers'

export interface DirectoryEvent {
  id: number
  name: string
  href: string
  specialty: string | null
  eventType: Conference['event_type']
  isFlagship: boolean
  isOnDemand: boolean
  isSoldOut: boolean
  startDate: string | null
  endDate: string | null
  format: Conference['event_format']
  city: string | null
  region: string | null
  society: string | null
  priceMin: number | null
  priceMax: number | null
  currency: string
  cpdAccredited: boolean
  cpdPoints: number | null
  abstractDeadline: string | null
  abstractDeadlineNote: string | null
  abstractOpen: boolean
  // Added in W2a for the server-side directory query layer (directory-query.ts).
  // Optional because toDirectoryEvent() (the original W1 builder, still used
  // by code that already has full Conference + PricingTier[] in hand) doesn't
  // populate them — only directoryEventFromRow() does.
  country?: 'uk' | 'international' | 'unknown'
  sourceShortName?: string | null
  /** Organiser's own site (falls back to the booking URL) — used for "See organiser site" prompts. */
  organiserUrl?: string | null
}

/**
 * Build the view-model from a row plus its pricing tiers.
 *
 * `price_gbp` is a DECIMAL column, and PostgREST can hand `numeric` back as a
 * string — so coerce rather than trusting the declared type (see code audit
 * §2.4). A tier we cannot turn into a finite number is dropped, not rendered
 * as NaN.
 */
export function toDirectoryEvent(
  c: Conference,
  opts: { tiers?: PricingTier[]; society?: string | null } = {}
): DirectoryEvent {
  const prices = (opts.tiers ?? [])
    .map((t) => Number(t.price_gbp))
    .filter((n) => Number.isFinite(n))

  const currency = opts.tiers?.find((t) => t.currency)?.currency ?? 'GBP'

  return {
    id: c.id,
    name: c.conference_name,
    href: `/conferences/${c.id}`,
    specialty: c.specialty,
    eventType: c.event_type,
    isFlagship: c.is_flagship,
    isOnDemand: c.is_on_demand,
    isSoldOut: c.is_sold_out,
    startDate: c.start_date,
    endDate: c.end_date,
    format: c.event_format,
    city: c.city,
    region: c.region,
    society: opts.society ?? null,
    priceMin: prices.length ? Math.min(...prices) : null,
    priceMax: prices.length ? Math.max(...prices) : null,
    currency,
    cpdAccredited: c.cpd_accredited,
    cpdPoints: c.cpd_points,
    abstractDeadline: c.abstract_deadline,
    abstractDeadlineNote: c.abstract_deadline_note,
    abstractOpen: isAbstractEffectivelyOpen(c),
    organiserUrl: c.organiser_url ?? c.booking_url ?? null,
  }
}

/**
 * Build the view-model directly from a `directory_events` DB view row (see
 * supabase/migrations/20261002000000_directory_query_layer.sql) — used by
 * queryDirectory() in directory-query.ts. The view already joins the min
 * price tier and society, so there's no second `tiers` argument like
 * toDirectoryEvent() above needs.
 */
export function directoryEventFromRow(row: DirectoryEventRow): DirectoryEvent {
  const priceFrom = row.price_from == null ? null : Number(row.price_from)
  return {
    id: row.id,
    name: row.conference_name,
    href: `/conferences/${row.id}`,
    specialty: row.specialty,
    eventType: row.event_type,
    isFlagship: row.is_flagship,
    isOnDemand: row.is_on_demand,
    isSoldOut: row.is_sold_out,
    startDate: row.start_date,
    endDate: row.end_date,
    format: row.event_format,
    city: row.city,
    region: row.region,
    society: row.society,
    priceMin: priceFrom != null && Number.isFinite(priceFrom) ? priceFrom : null,
    priceMax: priceFrom != null && Number.isFinite(priceFrom) ? priceFrom : null, // view only carries the MIN tier; see directory-query.ts
    currency: row.price_currency ?? 'GBP',
    cpdAccredited: row.cpd_accredited,
    cpdPoints: row.cpd_points,
    abstractDeadline: row.abstract_deadline,
    abstractDeadlineNote: row.abstract_deadline_note,
    abstractOpen: row.abstract_open && (!row.abstract_deadline || row.abstract_deadline >= new Date().toISOString().slice(0, 10)),
    country: row.country_guess,
    sourceShortName: row.source_short_name,
    organiserUrl: row.organiser_url ?? row.booking_url ?? null,
  }
}

/** Shape of a row selected from the `directory_events` view (see the migration). */
export interface DirectoryEventRow {
  id: number
  conference_name: string
  specialty: string | null
  event_type: Conference['event_type']
  start_date: string | null
  end_date: string | null
  start_time: string | null
  venue_name: string | null
  city: string | null
  region: string | null
  event_format: Conference['event_format']
  is_sold_out: boolean
  cpd_accredited: boolean
  cpd_points: number | null
  abstract_open: boolean
  abstract_deadline: string | null
  abstract_deadline_note: string | null
  organiser_url: string | null
  booking_url: string | null
  source_url: string
  description: string | null
  is_on_demand: boolean
  on_demand_original_date: string | null
  is_flagship: boolean
  created_at: string
  updated_at: string
  source_id: number | null
  society: string | null
  source_short_name: string | null
  price_from: number | string | null // PostgREST may hand DECIMAL back as a string
  price_currency: string | null
  country_guess: 'uk' | 'international' | 'unknown'
}

/** "Bristol" / "Bristol, South West" / "Online" — one place line, never blank. */
export function locationLine(e: Pick<DirectoryEvent, 'city' | 'region' | 'format'>): string | null {
  if (e.format === 'online') return null // FormatBadge already says "Online"
  const parts = [e.city, e.region].filter(Boolean) as string[]
  // A region that just repeats the city adds nothing.
  const deduped = parts.filter((p, i) => parts.findIndex((q) => q.toLowerCase() === p.toLowerCase()) === i)
  return deduped.length ? deduped.join(', ') : null
}
