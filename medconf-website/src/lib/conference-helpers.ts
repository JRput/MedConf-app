// src/lib/conference-helpers.ts
// Tiny derived helpers so the UI is robust against stale stored flags.
//
// abstract_open in the DB can drift out of sync — the scraper sets it
// from the source page's text ("abstracts open"), but the source rarely
// updates that text the moment the deadline passes. The deadline DATE
// is the source of truth, so we treat the stored bool as a hint and
// gate it on the date when rendering.

import type { Conference, CourseSession } from './types'

/**
 * True only when abstracts are genuinely still being accepted right now.
 * - The stored abstract_open flag must be true
 * - AND a deadline must be set (open with no deadline is meaningless to a user)
 * - AND that deadline must be today or later
 */
export function isAbstractEffectivelyOpen(c: Conference): boolean {
  if (!c.abstract_open) return false
  if (!c.abstract_deadline) return false
  const today = new Date().toISOString().slice(0, 10)
  return c.abstract_deadline >= today
}

/**
 * Days remaining until the abstract deadline. Negative = past, null = no deadline.
 */
export function daysUntilDeadline(c: Conference): number | null {
  if (!c.abstract_deadline) return null
  const diff = (new Date(c.abstract_deadline).getTime() - Date.now()) / 86_400_000
  return Math.ceil(diff)
}

/**
 * Filter and sort a course's sessions to surface the ones a user can act on
 * right now (today or later, sorted soonest first).
 */
export function upcomingSessions(sessions: CourseSession[] | undefined): CourseSession[] {
  if (!sessions) return []
  const today = new Date().toISOString().slice(0, 10)
  return sessions
    .filter(s => s.start_date >= today)
    .sort((a, b) => a.start_date.localeCompare(b.start_date))
}

/**
 * Pick the headline "next session" for a course card. Prefers the soonest
 * non-sold-out upcoming session; falls back to the soonest sold-out session
 * so the card can still surface a date instead of going blank.
 */
export function nextAvailableSession(sessions: CourseSession[] | undefined): CourseSession | null {
  const upcoming = upcomingSessions(sessions)
  if (upcoming.length === 0) return null
  const available = upcoming.find(s => s.availability_status !== 'sold_out')
  return available ?? upcoming[0]
}

export function courseSessionSummary(sessions: CourseSession[] | undefined) {
  const upcoming = upcomingSessions(sessions)
  return {
    upcoming,
    total: upcoming.length,
    available: upcoming.filter(s => s.availability_status !== 'sold_out').length,
    next: nextAvailableSession(sessions),
    allSoldOut: upcoming.length > 0 && upcoming.every(s => s.availability_status === 'sold_out'),
  }
}
