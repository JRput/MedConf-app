import { describe, expect, it } from 'vitest'
import { sanitizeReferrer, sanitizeUrl } from '@/lib/analytics/sanitize'
import { analyticsEnabled, isValidMeasurementId } from '@/lib/analytics/config'
import {
  CONSENT_COOKIE,
  CONSENT_VERSION,
  analyticsCookieNames,
  parseConsentCookie,
  serializeConsentCookie,
} from '@/lib/analytics/consent'

const O = 'https://medconf.vercel.app'

describe('sanitizeUrl', () => {
  it('drops every param under /auth (emails, tokens, next)', () => {
    expect(sanitizeUrl(`${O}/auth/verify?email=a%40nhs.net&reason=signup`, O)).toBe(`${O}/auth/verify`)
    expect(sanitizeUrl(`${O}/auth/callback?token_hash=abc&type=signup&next=/saved`, O)).toBe(`${O}/auth/callback`)
  })
  it('drops free-text search and unknown params but keeps directory filters', () => {
    expect(sanitizeUrl(`${O}/conferences?q=dr+smith&specialty=oncology&page=2&next=/x`, O)).toBe(
      `${O}/conferences?specialty=oncology&page=2`,
    )
  })
  it('drops email-looking values even in allowed params, and the hash', () => {
    expect(sanitizeUrl(`${O}/conferences?country=a@b.com&region=london#top`, O)).toBe(`${O}/conferences?region=london`)
  })
  it('reduces other sites to their origin', () => {
    expect(sanitizeUrl('https://www.google.com/search?q=me%40x.com', O)).toBe('https://www.google.com/')
  })
  it('returns empty for garbage', () => {
    expect(sanitizeUrl('not a url', O)).toBe('')
    expect(sanitizeReferrer('', O)).toBe('')
  })
})

describe('analytics config', () => {
  it('validates GA4 ids', () => {
    expect(isValidMeasurementId('G-ABC123XYZ9')).toBe(true)
    expect(isValidMeasurementId('UA-1234-1')).toBe(false)
    expect(isValidMeasurementId('')).toBe(false)
  })
  it('is off without an id and on Vercel previews', () => {
    expect(analyticsEnabled('', 'production')).toBe(false)
    expect(analyticsEnabled('G-ABC123XYZ9', 'preview')).toBe(false)
    expect(analyticsEnabled('G-ABC123XYZ9', 'development')).toBe(false)
    expect(analyticsEnabled('G-ABC123XYZ9', 'production')).toBe(true)
    expect(analyticsEnabled('G-ABC123XYZ9', '')).toBe(true)
  })
})

describe('consent cookie', () => {
  it('round-trips a choice', () => {
    const c = serializeConsentCookie('granted', true)
    expect(c).toContain(`${CONSENT_COOKIE}=${CONSENT_VERSION}.granted`)
    expect(c).toContain('Secure')
    expect(parseConsentCookie(`foo=1; ${CONSENT_COOKIE}=${CONSENT_VERSION}.denied`)).toBe('denied')
  })
  it('ignores missing, malformed and old-version values', () => {
    expect(parseConsentCookie('')).toBeNull()
    expect(parseConsentCookie(`${CONSENT_COOKIE}=v0.granted`)).toBeNull()
    expect(parseConsentCookie(`${CONSENT_COOKIE}=${CONSENT_VERSION}.maybe`)).toBeNull()
  })
  it('finds GA cookie names only', () => {
    expect(analyticsCookieNames('_ga=1; _ga_ABC=2; mc_consent=v1.granted; _gid=3; sb-x-auth-token=4')).toEqual([
      '_ga',
      '_ga_ABC',
      '_gid',
    ])
  })
})
