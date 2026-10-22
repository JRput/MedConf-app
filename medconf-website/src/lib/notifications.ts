// src/lib/notifications.ts
// Single source of truth for where a notification click should go.
import type { NotificationItem } from '@/lib/types'
import { SPECIALTY_PARENTS, canonicalSpecialty } from '@/lib/taxonomy/specialties'

/**
 * The specialty cron emits titles like "3 new Cardiology events" or
 * "2 new Emergency Medicine events". The specialty is the slice between
 * "N new" and the trailing noun.
 */
export function specialtyFromAlertTitle(title: string): string {
  const parts = title.split(' ')
  if (parts.length < 4) return ''
  return parts.slice(2, -1).join(' ')
}

/**
 * Resolve free text (a display label or a slug, any case) to a canonical
 * parent specialty slug, or null if it is not a known specialty.
 */
export function resolveSpecialtySlug(text: string): string | null {
  const t = text.trim().toLowerCase()
  if (!t) return null
  const bySlug = SPECIALTY_PARENTS.find((p) => p.slug.toLowerCase() === t)
  if (bySlug) return bySlug.slug
  const byLabel = SPECIALTY_PARENTS.find((p) => p.label.toLowerCase() === t)
  if (byLabel) return byLabel.slug
  const parent = canonicalSpecialty(text.trim()).parent
  return parent !== 'other' ? parent : null
}

export function notificationHref(item: Pick<NotificationItem, 'type' | 'conference_id' | 'title'>): string {
  if (item.type === 'contribution_update') return '/dashboard/contributions'
  if (item.type === 'moderation') return '/admin/moderation'
  if (item.conference_id) return `/conferences/${item.conference_id}`
  if (item.type === 'new_in_specialty') {
    const slug = resolveSpecialtySlug(specialtyFromAlertTitle(item.title))
    return slug
      ? `/conferences?specialty=${encodeURIComponent(slug)}&sort=newest`
      : '/conferences?sort=newest'
  }
  return '/dashboard/notifications'
}
