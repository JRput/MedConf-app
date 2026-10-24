import { describe, it, expect } from 'vitest'
import { isGatedPath, isProfileGatedPath, loginRedirectFor, resolveNext } from '@/lib/auth/gate'

describe('isGatedPath', () => {
  it.each([
    '/saved', '/settings', '/dashboard', '/onboarding', '/calendar', '/submit', '/admin', '/admin/moderation',
    '/conferences', '/conferences/', '/societies', '/societies/', '/societies/RCGP',
  ])('gates %s', (p) => expect(isGatedPath(p)).toBe(true))

  it.each([
    '/', '/conferences/548', '/conferences/548/', '/auth/login', '/auth/signup', '/auth/callback',
    '/api/directory', '/design', '/conferencesx', '/societiesx',
  ])('leaves %s public', (p) => expect(isGatedPath(p)).toBe(false))
})

describe('loginRedirectFor', () => {
  it('carries pathname and search as next', () => {
    const r = loginRedirectFor(new URL('http://localhost:3000/conferences?q=cardio'))
    expect(r.origin).toBe('http://localhost:3000')
    expect(r.pathname).toBe('/auth/login')
    expect(r.searchParams.get('next')).toBe('/conferences?q=cardio')
    expect(r.search).toBe('?next=%2Fconferences%3Fq%3Dcardio')
  })
  it('omits next when it fails safeNextPath', () => {
    const r = loginRedirectFor(new URL('http://localhost:3000//evil.com'))
    expect(r.searchParams.has('next')).toBe(false)
  })
})

describe('resolveNext', () => {
  it('rejects unsafe values', () => {
    expect(resolveNext('next=//evil.com')).toBe('/conferences')
    expect(resolveNext('next=javascript:alert(1)')).toBe('/conferences')
    expect(resolveNext('next=https://x')).toBe('/conferences')
  })
  it('keeps a safe path with query', () => {
    const sp = new URLSearchParams({ next: '/conferences?q=cardio&specialty=oncology' })
    expect(resolveNext(sp)).toBe('/conferences?q=cardio&specialty=oncology')
  })
  it('falls back when absent or null', () => {
    expect(resolveNext(null)).toBe('/conferences')
    expect(resolveNext('')).toBe('/conferences')
    expect(resolveNext('x=1', '/dashboard')).toBe('/dashboard')
  })
})

describe('isProfileGatedPath', () => {
  it('does not profile-gate the directory list or societies', () => {
    expect(isProfileGatedPath('/conferences')).toBe(false)
    expect(isProfileGatedPath('/societies')).toBe(false)
  })
  it('profile-gates personal pages', () => {
    expect(isProfileGatedPath('/dashboard')).toBe(true)
    expect(isProfileGatedPath('/admin/moderation')).toBe(true)
  })
})
