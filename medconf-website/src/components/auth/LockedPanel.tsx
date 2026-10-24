// src/components/auth/LockedPanel.tsx
//
// Stands in for the locked sections of an event page. Server-safe. The lock
// icon and the words "Unlock with a free account" carry the meaning, never colour alone.
// It lists what unlocks; it is never handed the locked values themselves.

import { useId } from 'react'
import { Lock, Check } from 'lucide-react'
import { cn } from '@/lib/utils'
import { SignInActions } from './SignInPrompt'

export function LockedPanel({
  items,
  next,
  title = 'Unlock with a free account',
  className,
}: {
  /** What a free account unlocks, e.g. "Fees and early-bird prices". */
  items: string[]
  next?: string
  title?: string
  className?: string
}) {
  const titleId = useId()
  return (
    <section aria-labelledby={titleId} className={cn('space-y-4 rounded-lg border border-border bg-surface p-5', className)}>
      <div className="flex items-center gap-2.5">
        <Lock className="size-4 shrink-0 text-fg-subtle" strokeWidth={1.75} aria-hidden />
        <h2 id={titleId} className="type-h3 text-fg-strong">
          {title}
        </h2>
      </div>
      <ul className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
        {items.map((item) => (
          <li key={item} className="flex items-start gap-2 text-[0.875rem] text-fg-muted">
            <Check className="mt-0.5 size-3.5 shrink-0 text-fg-subtle" strokeWidth={2} aria-hidden />
            {item}
          </li>
        ))}
      </ul>
      <SignInActions next={next} />
    </section>
  )
}
