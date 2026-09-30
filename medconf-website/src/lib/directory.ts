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
  }
}

/** "Bristol" / "Bristol, South West" / "Online" — one place line, never blank. */
export function locationLine(e: Pick<DirectoryEvent, 'city' | 'region' | 'format'>): string | null {
  if (e.format === 'online') return null // FormatBadge already says "Online"
  const parts = [e.city, e.region].filter(Boolean) as string[]
  // A region that just repeats the city adds nothing.
  const deduped = parts.filter((p, i) => parts.findIndex((q) => q.toLowerCase() === p.toLowerCase()) === i)
  return deduped.length ? deduped.join(', ') : null
}
