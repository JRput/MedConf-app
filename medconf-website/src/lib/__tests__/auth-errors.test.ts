import { describe, expect, it } from 'vitest'
import { authErrorMessage } from '../auth/errors'

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
