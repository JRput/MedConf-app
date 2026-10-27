import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { PriceLabel } from '@/components/domain/PriceLabel'
import { isCourseLike } from '@/lib/conference-helpers'
import { emptySections } from '@/lib/community/overlay'
import type { Conference } from '@/lib/types'

vi.mock('@/components/conferences/SessionsTable', () => ({ SessionsTable: () => null }))

const base = {
  id: 1, conference_name: 'MSc', event_type: 'degree', start_date: '2027-01-01',
  event_format: 'online', cpd_accredited: true, cpd_points: 1, organiser_url: 'https://x.example',
} as unknown as Conference

describe('degree is course-like', () => {
  it('isCourseLike covers course and degree only', () => {
    expect(isCourseLike('course')).toBe(true)
    expect(isCourseLike('degree')).toBe(true)
    expect(isCourseLike('conference')).toBe(false)
    expect(isCourseLike('workshop')).toBe(false)
  })
  it('emptySections offers no abstracts prompt for a degree', () => {
    expect(emptySections(base, [])).not.toContain('abstracts')
    expect(emptySections({ ...base, event_type: 'conference' } as Conference, [])).toContain('abstracts')
  })
})

describe('PriceLabel currency', () => {
  it('undefined currency does not render a pound sign', () => {
    const html = renderToStaticMarkup(<PriceLabel min={250} />)
    expect(html).not.toContain('£')
    expect(html).toContain('currency unknown')
  })
  it('explicit GBP still renders the pound sign', () => {
    expect(renderToStaticMarkup(<PriceLabel min={250} currency="GBP" />)).toContain('£250')
  })
})
