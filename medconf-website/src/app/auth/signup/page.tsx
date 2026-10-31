// src/app/auth/signup/page.tsx
'use client'

import { Suspense, useState } from 'react'
import { useAuth } from '@/hooks/useAuth'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { Check } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { resolveNext } from '@/lib/auth/gate'
import { mapAuthError } from '@/lib/auth/errors'
import { clearNextCookie, setNextCookie } from '@/lib/auth/next-cookie'
import { AuthCard, AuthError, AuthField, AuthTerms } from '@/components/auth/AuthCard'

// Auth behaviour is unchanged from the pre-W5 page: useAuth().signUp (which
// sets emailRedirectTo /auth/callback), the same 8-character minimum, and a
// push to /auth/verify on success. The copy now states what an account
// actually gives you. The directory and societies pages require a free account.
const BENEFITS = [
  'Save events to a personal calendar',
  'In-app alerts for new events in your specialty',
  'Reminders before an abstract deadline closes',
]

export default function SignUpPage() {
  // useSearchParams needs a Suspense boundary for static prerender.
  return (
    <Suspense fallback={null}>
      <SignUpForm />
    </Suspense>
  )
}

function SignUpForm() {
  const { signUp } = useAuth()
  const router = useRouter()
  const searchParams = useSearchParams()
  const rawNext = searchParams.get('next')
  const nextPath = resolveNext(searchParams, '')

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({})
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    const next: { email?: string; password?: string } = {}
    if (!email) next.email = 'Enter your email address'
    if (!password) next.password = 'Choose a password'
    else if (password.length < 8) next.password = 'Password must be at least 8 characters'
    setFieldErrors(next)
    if (next.email || next.password) {
      setError('')
      return
    }

    setLoading(true)
    setError('')
    // Same-device continuity: callback/onboarding read this to honour `next`.
    if (nextPath) setNextCookie(nextPath)

    const { data, error } = await signUp(email, password, nextPath || undefined)

    if (error) {
      clearNextCookie()
      setError(mapAuthError(error.message, 'signup'))
      setLoading(false)
      return
    }

    setLoading(false)
    // A session came back (confirmations off): honour next, else finish the
    // profile. Otherwise show the verify page with the address and `next`;
    // existing addresses take the same path (anti-enumeration).
    if (data?.session) {
      // Hard navigation, as on the login page: the client router may hold
      // gated links prefetched while signed out (each a redirect back to the
      // auth pages), and a client-side push would replay that redirect.
      window.location.assign(nextPath || '/onboarding')
      return
    }
    const q = new URLSearchParams({ email: email.trim() })
    if (nextPath) q.set('next', nextPath)
    router.push(`/auth/verify?${q.toString()}`)
  }

  return (
    <AuthCard
      title="Create a free account"
      intro={
        <ul className="space-y-1.5">
          {BENEFITS.map((benefit) => (
            <li key={benefit} className="flex items-start gap-2">
              <Check className="mt-0.5 size-3.5 shrink-0 text-brand-text" aria-hidden />
              <span>{benefit}</span>
            </li>
          ))}
        </ul>
      }
      footer={
        <>
          Already have an account?{' '}
          <Link href={nextPath && nextPath === rawNext ? `/auth/login?next=${encodeURIComponent(nextPath)}` : '/auth/login'} className="font-medium text-brand-text hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} noValidate className="space-y-4">
        <AuthField
          id="email"
          label="Email address"
          type="email"
          autoComplete="email"
          placeholder="you@nhs.net"
          value={email}
          onChange={(e) => {
            setEmail(e.target.value)
            if (fieldErrors.email) setFieldErrors((f) => ({ ...f, email: undefined }))
          }}
          error={fieldErrors.email}
          hint="We'll send a verification link here."
        />

        <AuthField
          id="password"
          label="Password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value)
            if (fieldErrors.password) setFieldErrors((f) => ({ ...f, password: undefined }))
          }}
          error={fieldErrors.password}
          hint="At least 8 characters."
        />

        {error && <AuthError message={error} />}

        <Button type="submit" disabled={loading} className="w-full">
          {loading ? 'Creating account…' : 'Create account'}
        </Button>

        <AuthTerms variant="signup" />
      </form>
    </AuthCard>
  )
}
