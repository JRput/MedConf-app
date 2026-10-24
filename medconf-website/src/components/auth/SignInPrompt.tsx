// src/components/auth/SignInPrompt.tsx
//
// The shared inline "sign in to continue" card (promoted from the pattern in
// community/AddInfoDialog). Server-safe: plain links, no hooks. Flat card,
// 1px border, no shadow, no gradient.

import Link from 'next/link'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { PRESS } from '@/components/community/press'
import { signInHref, signUpHref } from '@/lib/auth/urls'

/** The two CTAs, shared by the inline card, the dialog and the locked panel. */
export function SignInActions({ next, className }: { next?: string; className?: string }) {
  return (
    <div className={cn('flex flex-wrap gap-2', className)}>
      <Button asChild size="lg" className={PRESS}>
        <Link href={signUpHref(next)} data-gate-primary>Create a free account</Link>
      </Button>
      <Button asChild size="lg" variant="outline" className={PRESS}>
        <Link href={signInHref(next)}>Sign in</Link>
      </Button>
    </div>
  )
}

export function SignInPrompt({
  next,
  title = 'Sign in to see the full directory',
  body = 'A free account unlocks search, fees, CPD points and abstract deadlines for every event.',
  className,
}: {
  next?: string
  title?: string
  body?: string
  className?: string
}) {
  return (
    <div className={cn('space-y-3 rounded-lg border border-border bg-surface p-5', className)}>
      <h3 className="type-h3 text-fg-strong">{title}</h3>
      <p className="type-body text-fg-muted">{body}</p>
      <SignInActions next={next} />
    </div>
  )
}
