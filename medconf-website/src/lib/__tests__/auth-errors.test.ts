import { describe, expect, it } from 'vitest'
import { authErrorMessage, isLikelyEmail, isUnconfirmedError, mapAuthError } from '../auth/errors'

describe('authErrorMessage', () => {
  it('maps verify_failed', () => {
    expect(authErrorMessage('verify_failed')).toMatch(/couldn't verify that link/)
  })
  it('maps expired', () => {
    expect(authErrorMessage('expired')).toBe(
      'That reset link has expired or was already used. Request a new one below.'
    )
  })
  it('returns null for an unknown code', () => {
    expect(authErrorMessage('nope')).toBeNull()
  })
  it('returns null for inherited object keys', () => {
    expect(authErrorMessage('toString')).toBeNull()
    expect(authErrorMessage('__proto__')).toBeNull()
  })
  it('returns null for empty, null and undefined', () => {
    expect(authErrorMessage('')).toBeNull()
    expect(authErrorMessage(null)).toBeNull()
    expect(authErrorMessage(undefined)).toBeNull()
  })
  it('returns null for a string containing HTML', () => {
    expect(authErrorMessage('<script>alert(1)</script>')).toBeNull()
  })
  it('returns null for an overlong string', () => {
    expect(authErrorMessage('a'.repeat(5000))).toBeNull()
  })
})

// mapAuthError / isUnconfirmedError are new: on the previous code these imports do not exist,
// so every assertion below fails (the login page rendered error.message verbatim).
describe('mapAuthError', () => {
  it('maps invalid credentials', () => {
    expect(mapAuthError('Invalid login credentials')).toBe('Email or password is incorrect.')
  })
  it('maps unconfirmed email', () => {
    expect(mapAuthError('Email not confirmed')).toBe('Confirm your email before signing in.')
    expect(isUnconfirmedError('Email not confirmed')).toBe(true)
    expect(isUnconfirmedError('Invalid login credentials')).toBe(false)
  })
  it('never returns raw text for anything else', () => {
    for (const raw of ['User is banned', '<script>alert(1)</script>', 'AuthRetryableFetchError: 502 secret', '']) {
      const out = mapAuthError(raw)
      expect(out).toBe('Sign-in failed. Try again.')
      expect(out).not.toContain(raw || '\u0000')
    }
  })
})

// isLikelyEmail and the signup/rate-limit mappings are new: on the previous code the import is
// missing / the signup context returns the generic sign-in text, so these fail.
describe('isLikelyEmail', () => {
  it('accepts plain addresses', () => {
    for (const e of ['a@b.co', 'first.last@nhs.net', 'x+tag@sub.example.org']) expect(isLikelyEmail(e)).toBe(true)
  })
  it('rejects markup, spaces, prose and overlong values', () => {
    for (const e of ['<b>x</b>@y.z', 'a b@c.d', 'Click here', 'a'.repeat(300), '', null]) expect(isLikelyEmail(e as string)).toBe(false)
  })
})
describe('mapAuthError signup context', () => {
  it('maps weak password and rate limits', () => {
    expect(mapAuthError('Password should be at least 6 characters', 'signup')).toBe('Password does not meet the requirements.')
    expect(mapAuthError('Password is known to be weak and easy to guess', 'signup')).toBe('Password does not meet the requirements.')
    expect(mapAuthError('email rate limit exceeded', 'signup')).toBe('Too many attempts. Wait a few minutes and try again.')
    expect(mapAuthError('Too many requests')).toBe('Too many attempts. Wait a few minutes and try again.')
  })
  it('falls back to a generic signup message', () => {
    expect(mapAuthError('database exploded <x>', 'signup')).toBe('Sign-up failed. Try again.')
  })
})
