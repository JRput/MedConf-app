import { describe, expect, it } from 'vitest'
import { authErrorMessage, isUnconfirmedError, mapAuthError } from '../auth/errors'

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
