// src/lib/auth/urls.ts
//
// Builders for the sign-in / sign-up URLs used by every "sign in to see this"
// surface. `next` is where the visitor lands after authenticating, so it must
// be a same-origin relative path. An unsafe value is DROPPED (not repaired):
// the auth pages validate it again with safeNextPath, this is the first of
// two checks.

/** A single leading "/", no scheme, no "//" anywhere, no backslash or whitespace/control chars. */
export function isSafeNext(next: string | null | undefined): next is string {
  if (!next) return false
  if (!next.startsWith('/') || next.startsWith('//')) return false
  if (next.includes('//') || next.includes('\\')) return false
  if (/[\s\u0000-\u001f\u007f]/.test(next)) return false
  if (/^\/[^/?#]*:/.test(next)) return false
  return true
}

function withNext(base: string, next?: string): string {
  return isSafeNext(next) ? `${base}?next=${encodeURIComponent(next)}` : base
}

export function signInHref(next?: string): string {
  return withNext('/auth/login', next)
}

export function signUpHref(next?: string): string {
  return withNext('/auth/signup', next)
}
