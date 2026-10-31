import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { AuthTerms } from '../AuthCard'

const html = (v?: 'signup' | 'login') => renderToStaticMarkup(createElement(AuthTerms, v ? { variant: v } : {}))

describe('AuthTerms', () => {
  it('signup carries the 18+ wording and both links', () => {
    const h = html('signup')
    expect(h).toContain('you confirm you&#x27;re 18 or over')
    expect(h).toContain('href="/terms"')
    expect(h).toContain('href="/privacy"')
  })
  it('login (default) is the lighter wording with the same links', () => {
    for (const h of [html(), html('login')]) {
      expect(h).toContain('By signing in you agree to our')
      expect(h).not.toContain('18 or over')
      expect(h).toContain('href="/terms"')
      expect(h).toContain('href="/privacy"')
    }
  })
})
