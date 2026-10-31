// src/lib/analytics/sanitize.ts
//
// Google's terms forbid sending personal information to Analytics, and some
// of our URLs carry it: /auth/verify?email=…, ?next=…, sign-in tokens, and
// free-text searches (?q=) that can contain names. Every URL we hand to GA
// goes through sanitizeUrl(): only an allow-list of directory filter params
// survives, nothing at all is kept under /auth, the hash is dropped, and any
// value that looks like an email address is dropped.

const ALLOWED_PARAMS = new Set([
  'datePreset', 'dateFrom', 'dateTo', 'format', 'type', 'specialty', 'region', 'country',
  'price', 'society', 'cpd', 'abstractsOpen', 'sort', 'page', 'pageSize', 'view', 'm',
])

const EMAIL_LIKE = /@|%40/i

export function sanitizeUrl(href: string, siteOrigin?: string): string {
  let u: URL
  try {
    u = new URL(href)
  } catch {
    return ''
  }
  const origin = siteOrigin ?? (typeof window !== 'undefined' ? window.location.origin : u.origin)
  // Another site: keep only its origin.
  if (u.origin !== origin) return u.origin + '/'
  const kept = new URLSearchParams()
  if (!u.pathname.startsWith('/auth')) {
    for (const [k, v] of u.searchParams) {
      if (ALLOWED_PARAMS.has(k) && !EMAIL_LIKE.test(v)) kept.append(k, v)
    }
  }
  const qs = kept.toString()
  return `${u.origin}${u.pathname}${qs ? `?${qs}` : ''}`
}

/** document.referrer → sanitised, or '' when there is none. */
export function sanitizeReferrer(referrer: string, siteOrigin?: string): string {
  return referrer ? sanitizeUrl(referrer, siteOrigin) : ''
}
