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

/** Longest encoded `next` we will put in a login URL; longer values are dropped. */
export const MAX_NEXT_LENGTH = 2048

function usableNext(raw: string): string {
  const next = safeNextPath(raw, '')
  return next && encodeURIComponent(next).length <= MAX_NEXT_LENGTH ? next : ''
}

/**
 * Log a getUser() failure (status + name only, never tokens). The
 * no-session case is normal for anonymous visitors and is not logged.
 */
export function logGetUserError(where: string, error: unknown): void {
  if (!error) return
  const e = error as { name?: string; status?: number }
  if (e.name === 'AuthSessionMissingError') return
  console.warn(`[gate] getUser failed ${where} ${e.status} ${e.name}`)
}

/** `<origin>/auth/login?next=<pathname+search>`; `next` omitted when unsafe. */
export function loginRedirectFor(url: URL): URL {
  const target = new URL('/auth/login', url.origin)
  const next = usableNext(url.pathname + url.search)
  if (next) target.searchParams.set('next', next)
  return target
}

/**
 * Login href for a server page: `next` is built from the page's own pathname
 * and its `searchParams` prop and validated with safeNextPath; unsafe -> no next.
 */
export function loginHrefFor(pathname: string, searchParams?: URLSearchParams | Record<string, string | string[] | undefined>): string {
  let qs = ''
  if (searchParams instanceof URLSearchParams) qs = searchParams.toString()
  else if (searchParams) {
    const sp = new URLSearchParams()
    for (const [k, v] of Object.entries(searchParams)) {
      if (v == null) continue
      sp.set(k, Array.isArray(v) ? v.join(',') : v)
    }
    qs = sp.toString()
  }
  const next = usableNext(pathname + (qs ? `?${qs}` : ''))
  return next ? `/auth/login?next=${encodeURIComponent(next)}` : '/auth/login'
}

/** Validated `next` from a query string / params, else the fallback. */
export function resolveNext(params: URLSearchParams | string | null, fallback = '/conferences'): string {
  if (params == null) return fallback
  const sp = typeof params === 'string' ? new URLSearchParams(params) : params
  return safeNextPath(sp.get('next'), fallback)
}

/**
 * Redirect target for the profile-completion bounce: `/onboarding?next=<where
 * the user was going>`; `next` omitted when unsafe, oversized, or itself
 * /onboarding.
 */
export function onboardingRedirectFor(url: URL): URL {
  const target = new URL('/onboarding', url.origin)
  const next = usableNext(url.pathname + url.search)
  if (next && !isUnder(next.split(/[?#]/)[0], ['/onboarding'])) target.searchParams.set('next', next)
  return target
}

/**
 * Where /auth/callback sends a user after a successful verification.
 * - recovery -> /auth/reset-password (always).
 * - A PKCE reset link (`next` is the reset page) keeps that destination.
 * - email / email_change confirm an existing account: straight to `next`
 *   (default /onboarding, whose guard bounces completed profiles on).
 * - signup, invite, magiclink, and the `?code=` path (type null: cannot tell
 *   a new user from a returning one) go through /onboarding?next=<next> so a
 *   new account finishes its profile first; onboarding forwards completed
 *   profiles to `next` or /dashboard.
 */
export function landingFor(type: string | null | undefined, next: string | null | undefined): string {
  if (type === 'recovery') return '/auth/reset-password'
  const n = safeNextPath(next, '')
  if (n === '/auth/reset-password') return n
  if (type === 'email' || type === 'email_change') return n || '/onboarding'
  if (!n || isUnder(n.split(/[?#]/)[0], ['/onboarding'])) return n || '/onboarding'
  return `/onboarding?next=${encodeURIComponent(n)}`
}
