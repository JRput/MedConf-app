// Contract test: the URL a notification generates must survive the directory's
// own parser as a real filter. On 2026-10-22 the alert link carried
// `specialty=Oncology&sort=recently_added` — neither value was valid, both fell
// back silently, and the click landed on the unfiltered directory (HQ LESSONS #26).
import { describe, it, expect } from 'vitest'
import { notificationHref } from '@/lib/notifications'
import { parseDirectoryUrl } from '@/lib/directory-url'
import { SPECIALTY_PARENTS } from '@/lib/taxonomy/specialties'

describe('specialty alert links parse back into a directory filter', () => {
  const titles = [
    '2 new Oncology workshops',
    '2 new oncology workshops',
    '3 new Emergency Medicine events',
    '1 new Cardiology conference',
    ...SPECIALTY_PARENTS.filter((p) => p.slug !== 'other').map((p) => `4 new ${p.label} courses`),
  ]
  for (const title of titles) {
    it(title, () => {
      const href = notificationHref({ type: 'new_in_specialty', conference_id: null, title })
      const filters = parseDirectoryUrl(href.split('?')[1] ?? '')
      expect(filters.specialty).toHaveLength(1)
      expect(SPECIALTY_PARENTS.some((p) => p.slug === filters.specialty[0])).toBe(true)
      expect(filters.sort).toBe('newest')
    })
  }

  it('an unknown specialty still lands on a valid newest-sorted directory', () => {
    const href = notificationHref({ type: 'new_in_specialty', conference_id: null, title: '2 new Basket Weaving events' })
    const filters = parseDirectoryUrl(href.split('?')[1] ?? '')
    expect(filters.specialty).toHaveLength(0)
    expect(filters.sort).toBe('newest')
  })
})
