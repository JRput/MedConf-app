import { describe, expect, it } from 'vitest'
import { signInHref, signUpHref } from '../auth/urls'

describe('signInHref / signUpHref', () => {
  it('builds the bare URLs without next', () => {
    expect(signInHref()).toBe('/auth/login')
    expect(signUpHref()).toBe('/auth/signup')
  })

  it('encodes a safe relative next', () => {
    expect(signInHref('/conferences?q=heart%20failure&x=1')).toBe(
      `/auth/login?next=${encodeURIComponent('/conferences?q=heart%20failure&x=1')}`
    )
    expect(signUpHref('/conferences/548')).toBe('/auth/signup?next=%2Fconferences%2F548')
  })

  it.each([
    'https://evil.example/x',
    '//evil.example',
    '/\\evil.example',
    '/a//b',
    'javascript:alert(1)',
    '/javascript:alert(1)',
    'conferences',
    '/ok\nnewline',
    '',
  ])('drops an unsafe next: %j', (next) => {
    expect(signInHref(next)).toBe('/auth/login')
    expect(signUpHref(next)).toBe('/auth/signup')
  })
})
