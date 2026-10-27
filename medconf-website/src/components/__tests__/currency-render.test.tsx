import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { PricingTable } from '@/components/conferences/PricingTable'
import { SidebarPrice } from '@/components/event/EventSidebar'
import type { PricingTier } from '@/lib/types'

const mk = (id: string, label: string, price: number, currency: string | null) =>
  ({ id, tier_label: label, price_gbp: price, currency, is_early_bird: false, early_bird_deadline: null }) as unknown as PricingTier

const text = (html: string) => html.replace(/<[^>]+>/g, '|')

describe('PricingTable currencies', () => {
  it('EUR table: euro symbol, grouping, no forced .00', () => {
    const html = renderToStaticMarkup(<PricingTable tiers={[mk('1', 'Member', 1250, 'EUR'), mk('2', 'Non-member', 1800.5, 'EUR')]} />)
    expect(html).toContain('€1,250')
    expect(html).toContain('€1,800.50')
    expect(html).not.toContain('€1250.00')
    expect(html).not.toContain('£')
  })
  it('mixed table: each row uses its own currency', () => {
    const html = renderToStaticMarkup(<PricingTable tiers={[mk('1', 'UK', 100, 'GBP'), mk('2', 'US', 795, 'USD'), mk('3', 'Asia', 2500, 'SGD'), mk('4', 'Mystery', 40, null)]} />)
    expect(html).toContain('£100')
    expect(html).toContain('$795')
    expect(html).toContain('SGD 2,500')
    expect(html).toContain('40 (currency unknown)')
  })
})

describe('SidebarPrice', () => {
  it('shows the other-currency hint only when tiers were left out', () => {
    const mixed = text(renderToStaticMarkup(<SidebarPrice min={100} max={200} currency="GBP" otherCount={4} />))
    expect(mixed).toContain('from')
    expect(mixed).toContain('£100')
    expect(mixed).toContain('+ 4 in other currencies')
    const one = text(renderToStaticMarkup(<SidebarPrice min={100} max={200} currency="GBP" otherCount={1} />))
    expect(one).toContain('+ 1 in other currency')
    const single = renderToStaticMarkup(<SidebarPrice min={100} max={200} currency="EUR" otherCount={0} />)
    expect(single).not.toContain('other currenc')
    expect(single).toContain('€100')
  })
})
