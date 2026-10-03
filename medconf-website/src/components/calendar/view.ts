// src/components/calendar/view.ts
// The calendar's URL state, kept separate from the components so the parsing
// is testable and both the header and the client agree on the vocabulary.
//
// `/calendar?view=month&m=2026-11` — the view and the month in view are the
// only two things worth putting in the URL: they are what someone would send
// a colleague ("look at November") and what back/forward should step through.

import { monthKey, parseMonthKey, todayIso } from '@/lib/calendar'

export type CalendarView = 'month' | 'agenda'

export interface CalendarUrlState {
  view: CalendarView
  year: number
  /** 1–12 */
  month: number
}

/** Parse the URL into state, falling back to the current month rather than erroring on junk. */
export function parseCalendarUrl(params: URLSearchParams, today = todayIso()): CalendarUrlState {
  const view: CalendarView = params.get('view') === 'agenda' ? 'agenda' : 'month'
  const parsed = parseMonthKey(params.get('m'))
  return {
    view,
    year: parsed?.year ?? Number(today.slice(0, 4)),
    month: parsed?.month ?? Number(today.slice(5, 7)),
  }
}

/**
 * Serialise back to a query string.
 *
 * The agenda is one continuous upcoming list, so `m` would be meaningless
 * there and is dropped — which also means toggling Month → Agenda → Month
 * does not silently move you to a different month.
 */
export function calendarUrl(state: CalendarUrlState): string {
  const params = new URLSearchParams()
  params.set('view', state.view)
  if (state.view === 'month') params.set('m', monthKey(state.year, state.month))
  return `?${params.toString()}`
}
