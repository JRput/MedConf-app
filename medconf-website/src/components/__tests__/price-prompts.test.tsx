import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { PriceLabel } from '@/components/domain/PriceLabel'
import { PricingTable } from '@/components/conferences/PricingTable'
import type { PricingTier } from '@/lib/types'

const URL_ = 'https://organiser.example/register'

const tier = {
  id: 't1',
  tier_label: 'Standard',
  price_gbp: 100,
  currency: 'GBP',
  is_early_bird: false,
  early_bird_deadline: null,
} as unknown as PricingTier

describe('PriceLabel unknown state', () => {
  it('renders plain text without an anchor when no href', () => {
    const html = renderToStaticMarkup(<PriceLabel min={null} />)
    expect(html).toContain('See organiser site')
    expect(html).not.toContain('<a')
    expect(html).not.toContain('TBC')
  })

  it('renders an external link when href is given', () => {
    const html = renderToStaticMarkup(<PriceLabel min={null} href={URL_} />)
    expect(html).toContain('<a')
    expect(html).toContain(`href="${URL_}"`)
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noopener noreferrer"')
  })

  it('ignores href when a price is known', () => {
    const html = renderToStaticMarkup(<PriceLabel min={50} href={URL_} />)
    expect(html).not.toContain('<a')
  })
})

describe('PricingTable organiser prompts', () => {
  it('empty tiers with link shows panel and anchor', () => {
    const html = renderToStaticMarkup(<PricingTable tiers={[]} organiserUrl={URL_} />)
    expect(html).toContain('Registration fees are listed on the organiser')
    expect(html).toContain(`href="${URL_}"`)
    expect(html).toContain('Visit organiser site')
  })

  it('empty tiers without link shows fallback text, no anchor', () => {
    const html = renderToStaticMarkup(<PricingTable tiers={[]} />)
    expect(html).toContain('Visit the organiser')
    expect(html).not.toContain('<a')
  })

  it('tiers present show footer with link', () => {
    const html = renderToStaticMarkup(<PricingTable tiers={[tier]} organiserUrl={URL_} />)
    expect(html).toContain('may change')
    expect(html).toContain(`href="${URL_}"`)
  })

  it('tiers present without url show footer, no anchor', () => {
    const html = renderToStaticMarkup(<PricingTable tiers={[tier]} />)
    expect(html).toContain('confirm before booking')
    expect(html).not.toContain('<a')
  })
})
