// src/components/auth/AuthCard.tsx
//
// The shell every auth page uses: a single centred card, max 420px, sitting on
// the page background. No blur orbs, no glass, no grid pattern — the three
// things the old auth pages stacked behind this card (see
// reports/website-audit/ux.md "AI-look removal list" items 1-2).

import Link from 'next/link'
import { AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Input } from '@/components/ui/input'

export function AuthCard({
  title,
  intro,
  children,
  footer,
}: {
  title: string
  intro?: React.ReactNode
  children: React.ReactNode
  /** The login↔signup cross-link, or "back to sign in" — outside the card. */
  footer?: React.ReactNode
}) {
  return (
    <div className="mx-auto flex min-h-[calc(100vh-4rem)] w-full max-w-[420px] flex-col justify-center px-4 py-12">
      <Link href="/" className="mb-7 inline-flex items-center gap-2 self-start">
        <span className="flex size-7 items-center justify-center rounded-md bg-brand">
          <span className="text-[0.8125rem] font-bold text-fg-onbrand">M</span>
        </span>
        <span className="type-h3 text-fg-strong">MedConf</span>
      </Link>

      <div className="rounded-lg border border-border bg-surface p-6 shadow-xs sm:p-7">
        <h2 className="type-h2 text-fg-strong">{title}</h2>
        {intro && <div className="mt-2 text-[0.875rem] leading-relaxed text-fg-muted">{intro}</div>}
        <div className="mt-6">{children}</div>
      </div>

      {footer && <div className="mt-5 text-[0.875rem] text-fg-muted">{footer}</div>}
    </div>
  )
}

/** Label + field + per-field message, so every form field is laid out alike. */
export function AuthField({
  id,
  label,
  hint,
  error,
  ...inputProps
}: React.ComponentProps<'input'> & { id: string; label: string; hint?: string; error?: string }) {
  const describedBy = [error ? `${id}-error` : null, !error && hint ? `${id}-hint` : null].filter(Boolean).join(' ')

  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-[0.8125rem] font-medium text-fg">
        {label}
      </label>
      <Input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        className="h-10"
        {...inputProps}
      />
      {error ? (
        <p id={`${id}-error`} className="mt-1.5 text-[0.8125rem] text-danger-text">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="mt-1.5 text-[0.8125rem] text-fg-subtle">
          {hint}
        </p>
      ) : null}
    </div>
  )
}

/** Form-level failure (bad credentials, network, Supabase error text). */
export function AuthError({ message, className }: { message: string; className?: string }) {
  return (
    <div
      role="alert"
      className={cn(
        'flex items-start gap-2 rounded-md border border-danger-border bg-danger-subtle px-3 py-2.5 text-[0.8125rem] text-danger-text',
        className
      )}
    >
      <AlertCircle className="mt-px size-4 shrink-0" aria-hidden />
      <span>{message}</span>
    </div>
  )
}

/** The "By continuing…" line. Same wording on login and signup. */
export function AuthTerms() {
  return (
    <p className="mt-4 text-[0.75rem] leading-relaxed text-fg-subtle">
      By continuing you accept that MedConf lists third-party events and handles no registration or payment — fees and
      CPD points are shown as the organiser publishes them.
    </p>
  )
}
