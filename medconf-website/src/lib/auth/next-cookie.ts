// src/lib/auth/next-cookie.ts
// Short-lived `mc_next` cookie: remembers where a new user was heading across
// the signup -> email link -> /auth/callback -> /onboarding hop (same device
// only; a cross-device confirmation falls back to /dashboard). The value is
// never trusted: every read goes through safeNextPath, the only `next` validator.
import { safeNextPath } from '@/lib/auth/password'

export const NEXT_COOKIE = 'mc_next'
const MAX_AGE = 3600

/** Parse the cookie out of a `document.cookie`-style header; '' when absent/unsafe. */
export function parseNextCookie(cookieHeader: string | null | undefined): string {
  if (!cookieHeader) return ''
  for (const part of cookieHeader.split(';')) {
    const eq = part.indexOf('=')
    if (eq < 0) continue
    if (part.slice(0, eq).trim() !== NEXT_COOKIE) continue
    let value = part.slice(eq + 1).trim()
    try {
      value = decodeURIComponent(value)
    } catch {
      return ''
    }
    return safeNextPath(value, '')
  }
  return ''
}

export function setNextCookie(next: string | null | undefined): void {
  if (typeof document === 'undefined') return
  const safe = safeNextPath(next, '')
  if (!safe) return
  const secure = typeof location !== 'undefined' && location.protocol === 'https:' ? '; Secure' : ''
  document.cookie = `${NEXT_COOKIE}=${encodeURIComponent(safe)}; Path=/; Max-Age=${MAX_AGE}; SameSite=Lax${secure}`
}

export function readNextCookie(): string {
  if (typeof document === 'undefined') return ''
  return parseNextCookie(document.cookie)
}

export function clearNextCookie(): void {
  if (typeof document === 'undefined') return
  document.cookie = `${NEXT_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`
}
