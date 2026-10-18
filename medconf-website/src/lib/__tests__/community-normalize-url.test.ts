import { describe, expect, it } from 'vitest'
import { normalizeUrl, sameDomain } from '../community/normalize-url'

describe('normalizeUrl', () => {
  it('lower-cases scheme and host, keeps path case', () => {
    expect(normalizeUrl('HTTPS://Example.COM/Events/Annual')).toBe('https://example.com/Events/Annual')
  })
  it('drops fragment', () => {
    expect(normalizeUrl('https://example.com/a#register')).toBe('https://example.com/a')
  })
  it('drops utm_*, fbclid and gclid but keeps other params', () => {
    expect(normalizeUrl('https://example.com/a?id=7&utm_source=x&UTM_Medium=y&fbclid=1&gclid=2')).toBe(
      'https://example.com/a?id=7'
    )
  })
  it('removes the query entirely when only tracking params remain', () => {
    expect(normalizeUrl('https://example.com/a?utm_campaign=z')).toBe('https://example.com/a')
  })
  it('drops trailing slash on non-root paths only', () => {
    expect(normalizeUrl('https://example.com/events/')).toBe('https://example.com/events')
    expect(normalizeUrl('https://example.com/')).toBe('https://example.com/')
    expect(normalizeUrl('https://example.com')).toBe('https://example.com/')
  })
  it('strips embedded credentials', () => {
    expect(normalizeUrl('https://user:pw@example.com/a')).toBe('https://example.com/a')
  })
  it('returns null for non-http(s) and invalid input', () => {
    expect(normalizeUrl('javascript:alert(1)')).toBeNull()
    expect(normalizeUrl('ftp://example.com/x')).toBeNull()
    expect(normalizeUrl('example.com')).toBeNull()
    expect(normalizeUrl('')).toBeNull()
    expect(normalizeUrl(null)).toBeNull()
    expect(normalizeUrl(undefined)).toBeNull()
  })
  it('is idempotent', () => {
    const once = normalizeUrl('https://Example.com/a/?utm_x=1&b=2#f')!
    expect(normalizeUrl(once)).toBe(once)
  })
})

describe('sameDomain', () => {
  it('matches across www and paths', () => {
    expect(sameDomain('https://www.esmo.org/a', 'http://esmo.org/b?x=1')).toBe(true)
  })
  it('does not match different hosts or subdomains', () => {
    expect(sameDomain('https://esmo.org', 'https://asco.org')).toBe(false)
    expect(sameDomain('https://congress.esmo.org', 'https://esmo.org')).toBe(false)
  })
  it('is false when either side is invalid', () => {
    expect(sameDomain('nope', 'https://esmo.org')).toBe(false)
    expect(sameDomain(null, 'https://esmo.org')).toBe(false)
  })
})
