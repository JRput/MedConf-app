'use client'

// Footer link that re-opens the cookie banner. Hidden when analytics is off
// (no non-essential cookies, so there is no setting to change).

import { analyticsEnabled } from '@/lib/analytics/config'
import { openCookieSettings } from '@/lib/analytics/consent'

export function CookieSettingsButton({ className }: { className?: string }) {
  if (!analyticsEnabled()) return null
  return (
    <button type="button" onClick={openCookieSettings} className={className}>
      Cookie settings
    </button>
  )
}
