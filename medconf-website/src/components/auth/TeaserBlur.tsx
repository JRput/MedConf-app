'use client'

// src/components/auth/TeaserBlur.tsx
//
// Wraps the "rest of the list" rows. Signed out: the rows are blurred (6px),
// faded out toward the bottom, hidden from assistive tech and from focus
// (aria-hidden + inert), unselectable, and a sign-in card sits over them.
// Signed in: the rows render normally and interactive, no overlay. The rows
// handed in must carry only teaser-class fields (name, society, dates) —
// blur is presentation, not protection, so nothing sensitive may be in them.

import { useGate } from './GateProvider'
import { SignInPrompt } from './SignInPrompt'

export function TeaserBlur({
  children,
  total,
  next,
  noun = 'events this month',
}: {
  children: React.ReactNode
  /** Total behind the gate, for the CTA copy. */
  total: number
  next: string
  noun?: string
}) {
  const { user, loading } = useGate()

  if (user) return <>{children}</>

  return (
    <div className="relative min-h-[26rem]">
      <div
        aria-hidden="true"
        inert
        className="pointer-events-none select-none [filter:blur(6px)] [mask-image:linear-gradient(to_bottom,black_0%,black_25%,transparent_100%)] [-webkit-mask-image:linear-gradient(to_bottom,black_0%,black_25%,transparent_100%)]"
      >
        {children}
      </div>
      {/* While the session lookup is pending the card is hidden (not removed),
          so layout is identical and a signed-in visitor never sees it flash. */}
      <div className={`absolute inset-0 flex items-center justify-center px-2${loading ? ' invisible' : ''}`}>
        <SignInPrompt
          next={next}
          title={`See all ${total.toLocaleString('en-GB')} ${noun}`}
          body="Unlock the full list with a free account: search, fees, CPD points and deadlines."
          className="w-full max-w-md"
        />
      </div>
    </div>
  )
}
