// src/app/auth/login/page.tsx
'use client'

import { Suspense, useState } from 'react'
import { useAuth } from '@/hooks/useAuth'
import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { authErrorMessage, isUnconfirmedError, mapAuthError } from '@/lib/auth/errors'
import { resolveNext } from '@/lib/auth/gate'
import { AuthCard, AuthError, AuthField, AuthTerms } from '@/components/auth/AuthCard'

// Auth behaviour is unchanged from the pre-W5 page: useAuth().signIn, the
// error message straight from Supabase, and a push to /conferences on
// success (now to the validated ?next=, default /conferences). Only the presentation moved onto the design system — plus
// per-field validation messages in place of the single "Please fill in all
// fields" banner.
export default function LoginPage() {
  // useSearchParams needs a Suspense boundary for static prerender.
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  )
}

function LoginForm() {
  const { signIn } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({})
  // /auth/callback sends failures here as ?error=<code>; unknown codes render nothing.
  const searchParams = useSearchParams()
  const urlError = authErrorMessage(searchParams.get('error')) ?? ''
  const nextPath = resolveNext(searchParams)
  const rawNext = searchParams.get('next')
  const [localError, setLocalError] = useState<string | null>(null)
  const [unconfirmed, setUnconfirmed] = useState(false)
  const error = localError ?? urlError
  const setError = (m: string) => {
    setLocalError(m)
    if (!m) setUnconfirmed(false)
  }
  const [loading, setLoading] = useState(false)
  const safeRawNext = rawNext && nextPath === rawNext ? rawNext : ''
  const nextQuery = safeRawNext ? `?next=${encodeURIComponent(safeRawNext)}` : ''
  const resendHref = `/auth/verify?email=${encodeURIComponent(email.trim())}&reason=unconfirmed${
    safeRawNext ? `&next=${encodeURIComponent(safeRawNext)}` : ''
  }`

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()

    const next: { email?: string; password?: string } = {}
    if (!email) next.email = 'Enter your email address'
    if (!password) next.password = 'Enter your password'
    setFieldErrors(next)
    if (next.email || next.password) {
      setError('')
      return
    }

    setLoading(true)
    setError('')

    const { error } = await signIn(email, password)

    if (error) {
      setError(mapAuthError(error.message))
      setUnconfirmed(isUnconfirmedError(error.message))
      setLoading(false)
      return
    }

    // Full document navigation on purpose (2026-10-29). While the visitor was
    // signed out, Next prefetched the gated Navbar links (/conferences,
    // /societies, ...) and the middleware answered each with a redirect to
    // this login page; the client router keeps those prefetched answers (the
    // login page is static, so they stay fresh for minutes). A client-side
    // router.push(nextPath) therefore replayed the stale redirect and bounced
    // the freshly signed-in user straight back here on production, where
    // prefetching is on. A hard navigation drops the client router cache and
    // sends the new session cookies with the very first request, so the
    // middleware sees the user. `loading` stays true until the page unloads.
    window.location.assign(nextPath)
  }

  return (
    <AuthCard
      title="Sign in"
      intro="Your saved events, calendar and specialty alerts."
      footer={
        <>
          Don&apos;t have an account?{' '}
          <Link href={rawNext && nextPath === rawNext ? `/auth/signup?next=${encodeURIComponent(nextPath)}` : '/auth/signup'} className="font-medium text-brand-text hover:underline">
            Create one
          </Link>
        </>
      }
    >
      <form onSubmit={handleLogin} noValidate className="space-y-4">
        <AuthField
          id="email"
          label="Email address"
          type="email"
          autoComplete="email"
          placeholder="you@nhs.net"
          value={email}
          onChange={(e) => {
            setEmail(e.target.value)
            if (error) setError('')
            if (fieldErrors.email) setFieldErrors((f) => ({ ...f, email: undefined }))
          }}
          error={fieldErrors.email}
        />

        <AuthField
          id="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          labelAction={<Link href={nextQuery ? `/auth/forgot-password${nextQuery}` : '/auth/forgot-password'}>Forgot password?</Link>}
          value={password}
          onChange={(e) => {
            setPassword(e.target.value)
            if (error) setError('')
            if (fieldErrors.password) setFieldErrors((f) => ({ ...f, password: undefined }))
          }}
          error={fieldErrors.password}
        />

        {error && <AuthError message={error} />}
        {unconfirmed && (
          <Link href={resendHref} className="block text-[0.8125rem] font-medium text-brand-text hover:underline">
            Resend confirmation email
          </Link>
        )}

        <Button type="submit" disabled={loading} className="w-full">
          {loading ? 'Signing in…' : 'Sign in'}
        </Button>

        <AuthTerms />
      </form>
    </AuthCard>
  )
}
