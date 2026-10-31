// src/lib/analytics/consent.ts
//
// The visitor's analytics choice lives in a first-party cookie, `mc_consent`.
// Remembering a consent choice is itself strictly necessary, so this cookie
// needs no consent. It expires after 6 months, after which we ask again.
// Bump CONSENT_VERSION if what we ask consent for changes (e.g. adding ads) —
// old answers are then ignored and the banner re-appears.

export const CONSENT_COOKIE = 'mc_consent'
export const CONSENT_VERSION = 'v1'
export const CONSENT_MAX_AGE = 180 * 24 * 60 * 60
export const OPEN_SETTINGS_EVENT = 'mc:open-cookie-settings'
export const CONSENT_CHANGED_EVENT = 'mc:consent-changed'

export type ConsentChoice = 'granted' | 'denied'

/** Parse a `document.cookie`-style string. Returns null when no valid, current-version choice. */
export function parseConsentCookie(cookieHeader: string): ConsentChoice | null {
  for (const part of cookieHeader.split(';')) {
    const [rawName, ...rest] = part.trim().split('=')
    if (rawName !== CONSENT_COOKIE) continue
    const value = decodeURIComponent(rest.join('='))
    const [version, choice] = value.split('.')
    if (version !== CONSENT_VERSION) return null
    return choice === 'granted' || choice === 'denied' ? choice : null
  }
  return null
}

export function serializeConsentCookie(choice: ConsentChoice, secure: boolean): string {
  return `${CONSENT_COOKIE}=${CONSENT_VERSION}.${choice}; Path=/; Max-Age=${CONSENT_MAX_AGE}; SameSite=Lax${secure ? '; Secure' : ''}`
}

export function readConsent(): ConsentChoice | null {
  if (typeof document === 'undefined') return null
  return parseConsentCookie(document.cookie)
}

export function writeConsent(choice: ConsentChoice): void {
  if (typeof document === 'undefined') return
  document.cookie = serializeConsentCookie(choice, window.location.protocol === 'https:')
  window.dispatchEvent(new CustomEvent<ConsentChoice>(CONSENT_CHANGED_EVENT, { detail: choice }))
}

export function openCookieSettings(): void {
  window.dispatchEvent(new Event(OPEN_SETTINGS_EVENT))
}

/** Names of Google Analytics cookies currently set (`_ga`, `_ga_<id>`, legacy `_gid`/`_gat*`). */
export function analyticsCookieNames(cookieHeader: string): string[] {
  return cookieHeader
    .split(';')
    .map((p) => p.trim().split('=')[0])
    .filter((n) => n === '_ga' || n.startsWith('_ga_') || n === '_gid' || n.startsWith('_gat'))
}

/** Expire GA cookies on this host and its parent domains (GA sets them on the highest allowed domain). */
export function clearAnalyticsCookies(): void {
  if (typeof document === 'undefined') return
  const host = window.location.hostname
  const labels = host.split('.')
  const domains = new Set<string>([''])
  for (let i = 0; i < labels.length - 1; i++) domains.add(labels.slice(i).join('.'))
  for (const name of analyticsCookieNames(document.cookie)) {
    for (const d of domains) {
      document.cookie = `${name}=; Path=/; Max-Age=0${d ? `; Domain=${d}` : ''}`
      if (d) document.cookie = `${name}=; Path=/; Max-Age=0; Domain=.${d}`
    }
  }
}
