// next-cookie.ts is new, so every test here fails on the previous code (module missing).
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { clearNextCookie, parseNextCookie, readNextCookie, setNextCookie } from '@/lib/auth/next-cookie'

function fakeDocument(protocol = 'http:') {
  const jar = new Map<string, string>()
  const written: string[] = []
  const doc = {
    get cookie() {
      return [...jar].map(([k, v]) => `${k}=${v}`).join('; ')
    },
    set cookie(line: string) {
      written.push(line)
      const [pair, ...attrs] = line.split(';').map((x) => x.trim())
      const eq = pair.indexOf('=')
      const name = pair.slice(0, eq)
      const value = pair.slice(eq + 1)
      if (attrs.some((a) => a === 'Max-Age=0')) jar.delete(name)
      else jar.set(name, value)
    },
  }
  vi.stubGlobal('document', doc)
  vi.stubGlobal('location', { protocol })
  return { written }
}

describe('next cookie', () => {
  beforeEach(() => vi.unstubAllGlobals())

  it('sets, reads and clears', () => {
    const { written } = fakeDocument()
    setNextCookie('/conferences?q=a b'.replace(' ', '+'))
    expect(written[0]).toContain('mc_next=')
    expect(written[0]).toContain('Path=/')
    expect(written[0]).toContain('Max-Age=3600')
    expect(written[0]).toContain('SameSite=Lax')
    expect(written[0]).not.toContain('Secure')
    expect(readNextCookie()).toBe('/conferences?q=a+b')
    clearNextCookie()
    expect(readNextCookie()).toBe('')
  })
  it('adds Secure on https', () => {
    const { written } = fakeDocument('https:')
    setNextCookie('/saved')
    expect(written[0]).toContain('; Secure')
  })
  it('refuses to set an unsafe value', () => {
    const { written } = fakeDocument()
    setNextCookie('//evil.com')
    setNextCookie('https://evil.com')
    setNextCookie('')
    expect(written).toHaveLength(0)
  })
  it('rejects an unsafe value found in the cookie', () => {
    expect(parseNextCookie('mc_next=' + encodeURIComponent('//evil.com'))).toBe('')
    expect(parseNextCookie('a=1; mc_next=%E0%A4%A')).toBe('')
    expect(parseNextCookie('other=/saved')).toBe('')
    expect(parseNextCookie('a=1; mc_next=%2Fsaved; b=2')).toBe('/saved')
    expect(parseNextCookie(null)).toBe('')
  })
})
