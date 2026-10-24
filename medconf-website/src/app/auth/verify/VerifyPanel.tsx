// src/app/auth/verify/VerifyPanel.tsx
'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Mail } from 'lucide-react'
import { useAuth } from '@/hooks/useAuth'
import { Button } from '@/components/ui/button'
import { setNextCookie } from '@/lib/auth/next-cookie'
import { CONFIRM_FIRST } from '@/lib/auth/errors'
import { signUpHref } from '@/lib/auth/urls'
import { AuthCard, AuthError, AuthField } from '@/components/auth/AuthCard'

const COOLDOWN_SECONDS = 60
const RATE_LIMIT = 'Too many requests. Wait a few minutes and try again.'
const NETWORK = 'Could not reach MedConf. Check your connection and try again.'
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

// Resend always ends in the same "sent" copy whether or not the account exists
// (anti-enumeration, same pattern as forgot-password). Only rate limiting and
// network failures surface as errors.
export function VerifyPanel({
  email: initialEmail,
  reason,
  next,
}: {
  email: string
  reason: 'unconfirmed' | 'expired' | null
  next: string
}) {
  const { resendConfirmation } = useAuth()
  const [email, setEmail] = useState(initialEmail)
  const [fieldError, setFieldError] = useState('')
  const [error, setError] = useState('')
  const [sentTo, setSentTo] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  // Arriving straight from signup means an email was just sent: start cooling down.
  const [cooldown, setCooldown] = useState(!reason && initialEmail ? COOLDOWN_SECONDS : 0)

  useEffect(() => {
    if (cooldown <= 0) return
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000)
    return () => clearTimeout(t)
  }, [cooldown])

  const known = initialEmail.length > 0
  const target = (known ? initialEmail : email).trim()

  const handleResend = async (e: React.FormEvent) => {
    e.preventDefault()
    if (cooldown > 0 || sending) return
    if (!EMAIL_RE.test(target)) {
      setFieldError('Enter a valid email address')
      return
    }
    setFieldError('')
    setError('')
    setSending(true)
    try {
      if (next) setNextCookie(next)
      const { error: resendError } = await resendConfirmation(target, next || undefined)
      if (resendError) {
        const status = (resendError as { status?: number }).status
        if (status === 429 || /rate limit|too many|security purposes/i.test(resendError.message)) {
          setError(RATE_LIMIT)
        } else if (status === undefined || status === 0 || /fetch|network/i.test(resendError.message)) {
          setError(NETWORK)
        } else {
          // Looks identical to success; log status/name only, never the address.
          console.warn('[verify] resend failed', status, (resendError as { name?: string }).name)
          setSentTo(target)
          setCooldown(COOLDOWN_SECONDS)
        }
      } else {
        setSentTo(target)
        setCooldown(COOLDOWN_SECONDS)
      }
    } catch {
      setError(NETWORK)
    }
    setSending(false)
  }

  const reasonLine =
    reason === 'expired' ? 'That link has expired or was already used.' : reason === 'unconfirmed' ? CONFIRM_FIRST : null

  const intro = (
    <>
      {reasonLine && <p className="mb-1.5 font-medium text-fg">{reasonLine}</p>}
      {known ? (
        <p>
          We sent a link to <span className="font-medium text-fg">{initialEmail}</span>. It expires in 1 hour.
        </p>
      ) : (
        <p>Enter your email address and we&apos;ll send you a new confirmation link. It expires in 1 hour.</p>
      )}
    </>
  )

  return (
    <AuthCard
      title={known && !reason ? 'Check your email' : 'Confirm your email'}
      intro={intro}
      footer={
        <span className="flex flex-wrap gap-x-4 gap-y-1">
          <Link href={signUpHref(next)} className="font-medium text-brand-text hover:underline">
            Use a different address
          </Link>
          <Link href="/" className="font-medium text-brand-text hover:underline">
            Back to home
          </Link>
        </span>
      }
    >
      <div className="flex items-start gap-3 rounded-md border border-border bg-surface-muted px-3 py-3">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-surface">
          <Mail className="size-4 text-fg-muted" aria-hidden />
        </span>
        <p className="text-[0.8125rem] leading-relaxed text-fg-muted">
          Nothing after a few minutes? Check your spam or quarantine folder. NHS mail filters are strict.
        </p>
      </div>

      <form onSubmit={handleResend} noValidate className="mt-4 space-y-3">
        {!known && (
          <AuthField
            id="email"
            name="email"
            label="Email address"
            type="email"
            autoComplete="email"
            placeholder="you@nhs.net"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value)
              if (fieldError) setFieldError('')
            }}
            error={fieldError}
          />
        )}

        {sentTo && (
          <p role="status" className="text-[0.8125rem] text-fg-muted">
            If an account needs confirming for <span className="font-medium text-fg">{sentTo}</span>, a new link is on its
            way.
          </p>
        )}
        {error && <AuthError message={error} />}
        {known && fieldError && <AuthError message={fieldError} />}

        <Button type="submit" variant="outline" className="w-full" disabled={sending || cooldown > 0}>
          {sending ? 'Sending…' : cooldown > 0 ? `Resend email (${cooldown}s)` : 'Resend email'}
        </Button>
      </form>
    </AuthCard>
  )
}
