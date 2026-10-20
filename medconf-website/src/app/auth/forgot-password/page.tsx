// src/app/auth/forgot-password/page.tsx
'use client'

import { Suspense, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { Mail } from 'lucide-react'
import { useAuth } from '@/hooks/useAuth'
import { Button } from '@/components/ui/button'
import { AuthCard, AuthError, AuthField } from '@/components/auth/AuthCard'

// Always shows the same "sent" state whether or not the account exists, so the
// page cannot be used to find out who has an account. Only rate limiting and
// network failures surface as errors. ?error=expired comes from /auth/callback.
const RATE_LIMIT = 'Too many reset emails have been sent recently. Try again in a few minutes.'
const NETWORK = 'Could not reach MedConf. Check your connection and try again.'

export default function ForgotPasswordPage() {
  // useSearchParams needs a Suspense boundary for static prerender.
  return (
    <Suspense fallback={null}>
      <ForgotPasswordForm />
    </Suspense>
  )
}

function ForgotPasswordForm() {
  const { requestPasswordReset } = useAuth()
  const [email, setEmail] = useState('')
  const [fieldError, setFieldError] = useState('')
  const [error, setError] = useState('')
  const [dismissed, setDismissed] = useState(false)
  const expired = useSearchParams().get('error') === 'expired' && !dismissed
  const [sent, setSent] = useState(false)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = email.trim()
    if (!trimmed) {
      setFieldError('Enter your email address')
      return
    }
    setFieldError('')
    setError('')
    setDismissed(true)
    setLoading(true)

    try {
      const { error: resetError } = await requestPasswordReset(trimmed)
      if (resetError) {
        const status = (resetError as { status?: number }).status
        if (status === 429 || /rate limit|too many/i.test(resetError.message)) {
          setError(RATE_LIMIT)
        } else if (status === undefined || status === 0 || /fetch|network/i.test(resetError.message)) {
          setError(NETWORK)
        } else {
          // Any other server answer (including "user not found" variants)
          // must look identical to success.
          setSent(true)
        }
      } else {
        setSent(true)
      }
    } catch {
      setError(NETWORK)
    }
    setLoading(false)
  }

  if (sent) {
    return (
      <AuthCard
        title="Check your email"
        intro={
          <>
            If an account exists for <span className="font-medium text-fg">{email.trim()}</span>, we&apos;ve sent a link
            to reset your password. Open it on this device to continue.
          </>
        }
        footer={
          <Link href="/auth/login" className="font-medium text-brand-text hover:underline">
            Back to sign in
          </Link>
        }
      >
        <div className="flex items-start gap-3 rounded-md border border-border bg-surface-muted px-3 py-3">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-surface">
            <Mail className="size-4 text-fg-muted" aria-hidden />
          </span>
          <p className="text-[0.8125rem] leading-relaxed text-fg-muted">
            Nothing after a few minutes? Check your spam or quarantine folder — NHS mail filters are strict. The link
            expires after an hour.
          </p>
        </div>

        <Button variant="outline" className="mt-4 w-full" onClick={() => setSent(false)}>
          Use a different email
        </Button>
      </AuthCard>
    )
  }

  return (
    <AuthCard
      title="Reset your password"
      intro="Enter the email you signed up with and we'll send you a link to choose a new password."
      footer={
        <>
          Remembered it?{' '}
          <Link href="/auth/login" className="font-medium text-brand-text hover:underline">
            Back to sign in
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} noValidate className="space-y-4">
        {expired && !error && (
          <AuthError message="That reset link has expired or was already used. Request a new one below." />
        )}

        <AuthField
          id="email"
          label="Email address"
          type="email"
          autoComplete="email"
          placeholder="you@nhs.net"
          value={email}
          onChange={(e) => {
            setEmail(e.target.value)
            if (fieldError) setFieldError('')
          }}
          error={fieldError || undefined}
        />

        {error && <AuthError message={error} />}

        <Button type="submit" disabled={loading} className="w-full">
          {loading ? 'Sending…' : 'Send reset link'}
        </Button>
      </form>
    </AuthCard>
  )
}
