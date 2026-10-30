import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { PricingTable } from '@/components/conferences/PricingTable'
import type { PricingTier } from '@/lib/types'

const mk = (id: number, evidence_url?: string | null) =>
  ({
    id,
    tier_label: `Tier ${id}`,
    price_gbp: 100 + id,
    currency: 'GBP',
    is_early_bird: false,
    early_bird_deadline: null,
    evidence_url,
  }) as unknown as PricingTier

const URL_ = 'https://www.example.org/congress/fees'

describe('PricingTable fee provenance', () => {
  it('links the shared evidence url', () => {
    const html = renderToStaticMarkup(<PricingTable tiers={[mk(1, URL_), mk(2, URL_)]} />)
    expect(html).toContain('Fees as published on example.org/congress/fees')
    expect(html).toContain(`href="${URL_}"`)
    expect(html).toContain('rel="noopener noreferrer"')
    expect(html).toContain('target="_blank"')
  })

  it('shows no link when urls differ, are missing, or the key is absent', () => {
    for (const tiers of [
      [mk(1, URL_), mk(2, 'https://other.example/fees')],
      [mk(1, URL_), mk(2, null)],
      [mk(1), mk(2)],
    ]) {
      expect(renderToStaticMarkup(<PricingTable tiers={tiers} />)).not.toContain('Fees as published on')
    }
  })
})
