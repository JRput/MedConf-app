// src/lib/analytics/config.ts
//
// Google Analytics is OFF unless NEXT_PUBLIC_GA_MEASUREMENT_ID is set to a
// valid GA4 id (G-XXXXXXX). Set it in Vercel for the PRODUCTION environment
// only, so preview deployments never send data. As a second guard, Vercel
// preview/development builds are refused even if the id is present.
//
// Legal: GA sets non-essential cookies, so it only ever loads after the
// visitor clicks "Accept" in the cookie banner (see CookieConsent.tsx). The
// banner itself is only shown when analytics is enabled — with no
// non-essential cookies there is nothing to ask consent for.

const RAW_ID = process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID ?? ''
const VERCEL_ENV = process.env.NEXT_PUBLIC_VERCEL_ENV ?? ''

export function isValidMeasurementId(id: string): boolean {
  return /^G-[A-Z0-9]{4,20}$/.test(id)
}

export function analyticsEnabled(id: string = RAW_ID, vercelEnv: string = VERCEL_ENV): boolean {
  if (!isValidMeasurementId(id)) return false
  return vercelEnv !== 'preview' && vercelEnv !== 'development'
}

export const GA_MEASUREMENT_ID = RAW_ID

/** GA cookie lifetime: ~13 months instead of GA's default 2 years. */
export const GA_COOKIE_EXPIRES_SECONDS = 395 * 24 * 60 * 60
