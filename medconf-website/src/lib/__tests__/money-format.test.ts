import { describe, it, expect } from 'vitest'
import { formatMoney } from '@/lib/format'
import { currencySymbol, summarisePrices } from '@/lib/conference-helpers'

describe('formatMoney', () => {
  it.each([
    [185, 'GBP', '£185'],
    [1250, 'EUR', '€1,250'],
    [795, 'USD', '$795'],
    [2500, 'SGD', 'SGD 2,500'],
    [2500, 'HKD', 'HK$2,500'],
    [2500, 'CHF', 'CHF 2,500'],
    [150000, 'JPY', '¥150,000'],
    [2500000, 'KRW', '₩2,500,000'],
    [12000, 'INR', '₹12,000'],
    [2500, 'SEK', 'SEK 2,500'],
    [2500, 'XXX', 'XXX 2,500'],
    [2500, 'ZZZ', 'ZZZ 2,500'],
    [2500, 'sek', 'SEK 2,500'],
  ])('%s %s -> %s', (amt, cur, out) => {
    expect(formatMoney(amt, cur)).toBe(out)
  })

  it('keeps two decimals for fractional amounts', () => {
    expect(formatMoney(185.5, 'GBP')).toBe('£185.50')
  })
  it('JPY has no minor units even for fractions', () => {
    expect(formatMoney(1500.4, 'JPY')).toBe('¥1,500')
  })
  it('null / empty currency shows the bare amount with a hint, never £', () => {
    for (const c of [null, undefined, '', '  ']) {
      const out = formatMoney(1200, c)
      expect(out).toBe('1,200 (currency unknown)')
      expect(out).not.toContain('£')
    }
    expect(formatMoney(1200, null, { hint: false })).toBe('1,200')
  })
  it('malformed codes degrade readably', () => {
    expect(formatMoney(10, '£')).toBe('£ 10')
  })
})

describe('currencySymbol', () => {
  it('maps common codes and keeps alphabetic ones readable', () => {
    expect(currencySymbol('GBP')).toBe('£')
    expect(currencySymbol('eur')).toBe('€')
    expect(currencySymbol('SGD')).toBe('SGD ')
    expect(currencySymbol('XXX')).toBe('XXX ')
    expect(currencySymbol(null)).toBe('')
  })
})

describe('summarisePrices', () => {
  const t = (price: number, currency: string | null) => ({ price_gbp: price, currency })
  it('single currency: plain range, nothing left out', () => {
    expect(summarisePrices([t(100, 'EUR'), t(300, 'EUR')])).toEqual({ min: 100, max: 300, currency: 'EUR', otherCount: 0 })
  })
  it('mixed with GBP: GBP range, others counted', () => {
    expect(summarisePrices([t(500, 'USD'), t(100, 'GBP'), t(200, 'GBP'), t(900, 'EUR'), t(800, 'EUR'), t(700, 'EUR')]))
      .toEqual({ min: 100, max: 200, currency: 'GBP', otherCount: 4 })
  })
  it('mixed without GBP: most frequent currency wins', () => {
    expect(summarisePrices([t(5, 'USD'), t(900, 'EUR'), t(800, 'EUR')]))
      .toEqual({ min: 800, max: 900, currency: 'EUR', otherCount: 1 })
  })
  it('null currency is its own group and stays unknown', () => {
    const s = summarisePrices([t(10, null), t(20, null)])
    expect(s.currency).toBeNull()
    expect(s.min).toBe(10)
  })
  it('no usable prices', () => {
    expect(summarisePrices([])).toEqual({ min: null, max: null, currency: null, otherCount: 0 })
  })
})
