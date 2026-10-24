// src/lib/auth/gate.ts
// Pure route-gate helpers shared by middleware and the auth pages. No React.
//
// Gated = needs a signed-in user. The personal surfaces, the directory list
// (exactly /conferences) and the societies pages are gated; the event detail
// page (/conferences/<id>) stays a public teaser, as do /, /auth/*, /api/*
// (the API route gates itself) and /design.
import { safeNextPath } from '@/lib/auth/password'

export const PROTECTED_PATHS = ['/saved', '/settings', '/dashboard', '/onboarding', '/calendar', '/submit', '/admin']
const GATED_PREFIXES = [...PROTECTED_PATHS, '/societies']

export function isUnder(path: string, candidates: string[]): boolean {
  return candidates.some(p => path === p || path.startsWith(p + '/'))
}

export function isGatedPath(pathname: string): boolean {
  if (pathname === '/conferences' || pathname === '/conferences/') return true
  return isUnder(pathname, GATED_PREFIXES)
}

/** Pages that also require a completed profile (and the admin check). The
 * directory list and societies need sign-in only, so they are excluded. */
export function isProfileGatedPath(pathname: string): boolean {
  return isUnder(pathname, PROTECTED_PATHS)
}

/** `<origin>/auth/login?next=<pathname+search>`; `next` omitted when unsafe. */
export function loginRedirectFor(url: URL): URL {
  const target = new URL('/auth/login', url.origin)
  const next = safeNextPath(url.pathname + url.search, '')
  if (next) target.searchParams.set('next', next)
  return target
}

/** Validated `next` from a query string / params, else the fallback. */
export function resolveNext(params: URLSearchParams | string | null, fallback = '/conferences'): string {
  if (params == null) return fallback
  const sp = typeof params === 'string' ? new URLSearchParams(params) : params
  return safeNextPath(sp.get('next'), fallback)
}
