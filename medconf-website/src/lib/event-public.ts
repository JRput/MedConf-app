// src/lib/event-public.ts
//
// The ONLY fields an anonymous visitor's event page may be built from. The
// detail page renders from this selector when there is no session, so locked
// values (fees, CPD, deadlines, venue, links, sessions) never enter the
// anonymous component tree or the RSC payload. Add a key here only if it is
// fine to show on a public, indexable page.

import type { Conference } from '@/lib/types'

export const DESCRIPTION_EXCERPT_MAX = 300

export interface PublicEventFields {
  id: number
  conference_name: string
  specialty: string | null
  event_type: Conference['event_type']
  event_format: Conference['event_format']
  is_flagship: boolean
  is_on_demand: boolean
  start_date: string | null
  end_date: string | null
  city: string | null
  region: string | null
  society: string | null
  description_excerpt: string | null
}

/** Trim to at most `max` chars on a word boundary, with an ellipsis when cut. */
export function excerpt(text: string | null | undefined, max = DESCRIPTION_EXCERPT_MAX): string | null {
  const t = text?.replace(/\s+/g, ' ').trim()
  if (!t) return null
  if (t.length <= max) return t
  const cut = t.slice(0, max - 1)
  const lastSpace = cut.lastIndexOf(' ')
  return `${(lastSpace > max * 0.6 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`
}

export function publicEventFields(row: Conference, society: string | null = null): PublicEventFields {
  return {
    id: row.id,
    conference_name: row.conference_name,
    specialty: row.specialty,
    event_type: row.event_type,
    event_format: row.event_format,
    is_flagship: row.is_flagship,
    is_on_demand: row.is_on_demand,
    start_date: row.start_date,
    end_date: row.end_date,
    city: row.city,
    region: row.region,
    society,
    description_excerpt: excerpt(row.description),
  }
}
