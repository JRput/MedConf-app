'use client'

// src/components/analytics/GoogleAnalytics.tsx
//
// Loads GA4 — rendered ONLY after the visitor has accepted analytics cookies
// (see CookieConsent.tsx). "Basic" consent mode: nothing is sent to Google
// before consent, not even cookieless pings.
//
// Privacy settings applied here:
//  - ad storage / ad personalisation / ad user data: denied
//  - Google signals and ad-personalisation signals: off
//  - _ga cookies last ~13 months instead of 2 years
//  - automatic page_view is OFF; we send our own page_view with a sanitised
//    URL (see lib/analytics/sanitize.ts) so emails, sign-in tokens and search
//    text never reach Google. In the GA web stream's Enhanced measurement,
//    "Page changes based on browser history events" and "Site search" must
//    stay OFF or GA would record the raw URL.

import Script from 'next/script'
import { Suspense, useEffect, useRef } from 'react'
import { usePathname, useSearchParams } from 'next/navigation'
import { GA_COOKIE_EXPIRES_SECONDS } from '@/lib/analytics/config'
import { sanitizeReferrer, sanitizeUrl } from '@/lib/analytics/sanitize'

declare global {
  interface Window {
    dataLayer: unknown[]
    gtag?: (...args: unknown[]) => void
  }
}

let initialisedFor: string | null = null

function initGtag(id: string) {
  if (initialisedFor === id) return
  initialisedFor = id
  window.dataLayer = window.dataLayer || []
  // gtag.js expects the `arguments` object itself, not an array.
  window.gtag = function gtag() {
    // eslint-disable-next-line prefer-rest-params
    window.dataLayer.push(arguments)
  }
  window.gtag('consent', 'default', {
    ad_storage: 'denied',
    ad_user_data: 'denied',
    ad_personalization: 'denied',
    analytics_storage: 'granted',
  })
  window.gtag('js', new Date())
  window.gtag('set', {
    page_location: sanitizeUrl(window.location.href),
    page_referrer: sanitizeReferrer(document.referrer),
  })
  window.gtag('config', id, {
    send_page_view: false,
    allow_google_signals: false,
    allow_ad_personalization_signals: false,
    cookie_expires: GA_COOKIE_EXPIRES_SECONDS,
  })
}

function PageViews() {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const last = useRef<string>('')

  useEffect(() => {
    // Let the App Router update document.title before we read it.
    const t = window.setTimeout(() => {
      if (!window.gtag) return
      const location = sanitizeUrl(window.location.href)
      if (!location || location === last.current) return
      const referrer = last.current || sanitizeReferrer(document.referrer)
      window.gtag('set', { page_location: location, page_referrer: referrer })
      window.gtag('event', 'page_view', { page_location: location, page_referrer: referrer, page_title: document.title })
      last.current = location
    }, 50)
    return () => window.clearTimeout(t)
  }, [pathname, searchParams])

  return null
}

export function GoogleAnalytics({ id }: { id: string }) {
  // Initialise synchronously on first client render so the queue is ready
  // before gtag.js arrives and before PageViews fires.
  if (typeof window !== 'undefined') initGtag(id)

  return (
    <>
      <Script id="ga-gtag" src={`https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(id)}`} strategy="afterInteractive" />
      <Suspense fallback={null}>
        <PageViews />
      </Suspense>
    </>
  )
}
