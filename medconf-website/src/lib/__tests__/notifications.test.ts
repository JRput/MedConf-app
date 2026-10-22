// src/lib/__tests__/notifications.test.ts
import { describe, expect, it } from 'vitest'
import { notificationHref, resolveSpecialtySlug, specialtyFromAlertTitle } from '../notifications'
import { SPECIALTY_PARENTS } from '../taxonomy/specialties'

describe('specialtyFromAlertTitle', () => {
  it('extracts single and multi-word specialties', () => {
    expect(specialtyFromAlertTitle('2 new Oncology workshops')).toBe('Oncology')
    expect(specialtyFromAlertTitle('3 new Emergency Medicine events')).toBe('Emergency Medicine')
    expect(specialtyFromAlertTitle('1 new oncology workshop')).toBe('oncology')
  })
  it('returns empty for short or odd titles', () => {
    expect(specialtyFromAlertTitle('')).toBe('')
    expect(specialtyFromAlertTitle('New events')).toBe('')
    expect(specialtyFromAlertTitle('2 new events')).toBe('')
  })
})

describe('resolveSpecialtySlug', () => {
  it('resolves slug and label in any case', () => {
    for (const t of ['Oncology', 'oncology', 'ONCOLOGY']) expect(resolveSpecialtySlug(t)).toBe('oncology')
  })
  it('resolves a multi-word parent label and its slug', () => {
    const p = SPECIALTY_PARENTS.find((x) => x.slug === 'emergency-medicine')!
    expect(resolveSpecialtySlug(p.label)).toBe(p.slug)
    expect(resolveSpecialtySlug(p.slug.toUpperCase())).toBe(p.slug)
  })
  it('returns null for unknown or empty text', () => {
    expect(resolveSpecialtySlug('Not A Specialty')).toBeNull()
    expect(resolveSpecialtySlug('')).toBeNull()
  })
})

describe('notificationHref', () => {
  const base = { conference_id: null, title: 'x' }
  it('routes contribution_update and moderation', () => {
    expect(notificationHref({ ...base, type: 'contribution_update' })).toBe('/dashboard/contributions')
    expect(notificationHref({ ...base, type: 'moderation', conference_id: 42 })).toBe('/admin/moderation')
  })
  it('routes items with a conference_id to the conference', () => {
    expect(notificationHref({ ...base, type: 'reminder', conference_id: 42 })).toBe('/conferences/42')
    expect(
      notificationHref({ type: 'new_in_specialty', conference_id: 42, title: '2 new Oncology workshops' })
    ).toBe('/conferences/42')
  })
  it('routes new_in_specialty to the filtered directory', () => {
    expect(notificationHref({ ...base, type: 'new_in_specialty', title: '2 new Oncology workshops' })).toBe(
      '/conferences?specialty=oncology&sort=newest'
    )
    expect(notificationHref({ ...base, type: 'new_in_specialty', title: '2 new oncology workshops' })).toBe(
      '/conferences?specialty=oncology&sort=newest'
    )
    expect(notificationHref({ ...base, type: 'new_in_specialty', title: '2 new Bogus Thing events' })).toBe(
      '/conferences?sort=newest'
    )
  })
  it('falls back to the notifications page', () => {
    expect(notificationHref({ ...base, type: 'system' })).toBe('/dashboard/notifications')
  })
})
