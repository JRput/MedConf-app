'use client'

// src/components/analytics/CookieConsent.tsx
//
// Cookie banner + consent gate for Google Analytics.
//  - Renders nothing at all unless analytics is enabled (lib/analytics/config).
//  - Nothing non-essential is set before the visitor chooses; GA loads only on
//    "Accept". "Reject" is offered with equal prominence (ICO guidance).
//  - The choice is stored in the `mc_consent` cookie for 6 months.
//  - "Cookie settings" in the footer re-opens the banner; withdrawing consent
//    deletes the _ga cookies and reloads the page so gtag.js is unloaded.

import Link from 'next/link'
import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'
import { Button } from '@/components/ui/button'
import { GoogleAnalytics } from '@/components/analytics/GoogleAnalytics'
import { GA_MEASUREMENT_ID, analyticsEnabled } from '@/lib/analytics/config'
import {
  CONSENT_CHANGED_EVENT,
  OPEN_SETTINGS_EVENT,
  clearAnalyticsCookies,
  readConsent,
  writeConsent,
  type ConsentChoice,
} from '@/lib/analytics/consent'

export function CookieConsent() {
  if (!analyticsEnabled()) return null
  return <ConsentGate id={GA_MEASUREMENT_ID} />
}

// Server render and the first client render agree on 'server' (no banner,
// no GA); after hydration the real cookie value takes over.
type Snapshot = ConsentChoice | 'none' | 'server'

function subscribe(onChange: () => void) {
  window.addEventListener(CONSENT_CHANGED_EVENT, onChange)
  return () => window.removeEventListener(CONSENT_CHANGED_EVENT, onChange)
}
const getSnapshot = (): Snapshot => readConsent() ?? 'none'
const getServerSnapshot = (): Snapshot => 'server'

function ConsentGate({ id }: { id: string }) {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const choice: ConsentChoice | null = snapshot === 'granted' || snapshot === 'denied' ? snapshot : null

  useEffect(() => {
    const onOpen = () => setSettingsOpen(true)
    window.addEventListener(OPEN_SETTINGS_EVENT, onOpen)
    return () => window.removeEventListener(OPEN_SETTINGS_EVENT, onOpen)
  }, [])

  // Belt and braces: no GA cookies may survive without consent.
  useEffect(() => {
    if (snapshot === 'none' || snapshot === 'denied') clearAnalyticsCookies()
  }, [snapshot])

  const decide = useCallback(
    (next: ConsentChoice) => {
      const previous = choice
      writeConsent(next)
      setSettingsOpen(false)
      if (next === 'denied') {
        window.gtag?.('consent', 'update', { analytics_storage: 'denied' })
        clearAnalyticsCookies()
        // gtag.js can't be unloaded in place — reload so it's gone.
        if (previous === 'granted') window.location.reload()
      }
    },
    [choice],
  )

  const showBanner = snapshot === 'none' || (settingsOpen && snapshot !== 'server')

  return (
    <>
      {choice === 'granted' && <GoogleAnalytics id={id} />}
      {showBanner && (
        <ConsentBanner current={choice} onDecide={decide} onClose={choice ? () => setSettingsOpen(false) : undefined} />
      )}
    </>
  )
}

function ConsentBanner({
  current,
  onDecide,
  onClose,
}: {
  current: ConsentChoice | null
  onDecide: (c: ConsentChoice) => void
  onClose?: () => void
}) {
  return (
    <div role="region" aria-labelledby="cookie-consent-title" className="fixed inset-x-0 bottom-0 z-50 p-3 sm:p-4">
      <div className="mx-auto max-w-[720px] rounded-lg border border-border bg-surface p-4 shadow-lg sm:p-5">
        <p id="cookie-consent-title" className="text-[0.9375rem] font-medium text-fg-strong">
          Cookies
        </p>
        <p className="mt-1.5 text-[0.8125rem] leading-relaxed text-fg-muted">
          We use a few essential cookies to keep you signed in. With your permission, we&apos;d also like to use Google
          Analytics cookies to understand how the site is used so we can improve it. Analytics cookies are only set if you
          accept, and you can change your mind at any time from &ldquo;Cookie settings&rdquo; at the bottom of every page.{' '}
          <Link href="/cookies" className="font-medium text-brand-text underline-offset-4 hover:underline">
            Cookie policy
          </Link>
        </p>
        {current && (
          <p className="mt-2 text-[0.8125rem] text-fg-subtle">
            Current choice: analytics {current === 'granted' ? 'accepted' : 'rejected'}.
          </p>
        )}
        <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:justify-end">
          {onClose && (
            <Button variant="ghost" onClick={onClose} className="sm:mr-auto">
              Close
            </Button>
          )}
          <Button variant="outline" onClick={() => onDecide('denied')}>
            Reject analytics
          </Button>
          <Button variant="outline" onClick={() => onDecide('granted')}>
            Accept analytics
          </Button>
        </div>
      </div>
    </div>
  )
}
