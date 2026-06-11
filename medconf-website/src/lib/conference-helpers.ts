// src/lib/conference-helpers.ts
// Tiny derived helpers so the UI is robust against stale stored flags.
//
// abstract_open in the DB can drift out of sync — the scraper sets it
// from the source page's text ("abstracts open"), but the source rarely
// updates that text the moment the deadline passes. The deadline DATE
// is the source of truth, so we treat the stored bool as a hint and
// gate it on the date when rendering.

import type { Conference } from './types'

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
