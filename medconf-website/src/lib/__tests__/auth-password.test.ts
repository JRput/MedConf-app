import { describe, expect, it } from 'vitest'
import { safeNextPath, validateNewPassword } from '../auth/password'
import { SAFE_NEXT, UNSAFE_NEXT } from '../auth/__fixtures__/next-paths'

describe('validateNewPassword', () => {
  it('accepts a valid matching pair', () => {
    expect(validateNewPassword('longenough', 'longenough')).toEqual({})
  })
  it('accepts exactly 8 characters', () => {
    expect(validateNewPassword('12345678', '12345678')).toEqual({})
  })
  it('flags an empty password', () => {
    expect(validateNewPassword('', 'x').password).toBe('Choose a password')
  })
  it('flags a short password', () => {
    expect(validateNewPassword('1234567', '1234567').password).toBe('Password must be at least 8 characters')
  })
  it('flags an empty confirmation', () => {
    expect(validateNewPassword('longenough', '').confirm).toBe('Re-enter your new password')
  })
  it('flags a mismatch', () => {
    expect(validateNewPassword('longenough', 'different1').confirm).toBe('Passwords do not match')
  })
  it('reports both errors independently', () => {
    expect(validateNewPassword('', '')).toEqual({
      password: 'Choose a password',
      confirm: 'Re-enter your new password',
    })
  })
})

describe('safeNextPath', () => {
  const fb = '/fallback'
  it('uses the fallback for null, undefined and empty', () => {
    expect(safeNextPath(null, fb)).toBe(fb)
    expect(safeNextPath(undefined, fb)).toBe(fb)
    expect(safeNextPath('', fb)).toBe(fb)
  })
  it('allows relative paths, with query and hash', () => {
    expect(safeNextPath('/auth/reset-password', fb)).toBe('/auth/reset-password')
    expect(safeNextPath('/conferences?q=a:b#x', fb)).toBe('/conferences?q=a:b#x')
    expect(safeNextPath('/', fb)).toBe('/')
  })
  it('rejects paths without a leading slash', () => {
    expect(safeNextPath('dashboard', fb)).toBe(fb)
    expect(safeNextPath('https://evil.example', fb)).toBe(fb)
  })
  it('rejects protocol-relative URLs', () => {
    expect(safeNextPath('//evil.example', fb)).toBe(fb)
  })
  it('rejects backslashes', () => {
    expect(safeNextPath('/\\evil.example', fb)).toBe(fb)
    expect(safeNextPath('/a\\b', fb)).toBe(fb)
  })
  it('rejects a scheme-like first segment', () => {
    expect(safeNextPath('/javascript:alert(1)', fb)).toBe(fb)
  })
  it('rejects whitespace and control characters', () => {
    expect(safeNextPath('/a b', fb)).toBe(fb)
    expect(safeNextPath('/a\tb', fb)).toBe(fb)
    expect(safeNextPath('/a\nb', fb)).toBe(fb)
    expect(safeNextPath('/a\u0000b', fb)).toBe(fb)
  })
})

describe('safeNextPath shared fixtures', () => {
  it.each(SAFE_NEXT)('keeps safe %j', (n) => expect(safeNextPath(n, '/fb')).toBe(n))
  it.each(UNSAFE_NEXT)('rejects unsafe %j', (n) => expect(safeNextPath(n, '/fb')).toBe('/fb'))
})
