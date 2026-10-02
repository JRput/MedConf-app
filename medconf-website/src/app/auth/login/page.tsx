// src/app/auth/login/page.tsx
'use client'

import { useState } from 'react'
import { useAuth } from '@/hooks/useAuth'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { AuthCard, AuthError, AuthField, AuthTerms } from '@/components/auth/AuthCard'

// Auth behaviour is unchanged from the pre-W5 page: useAuth().signIn, the
// error message straight from Supabase, and a push to /conferences on
// success. Only the presentation moved onto the design system — plus
// per-field validation messages in place of the single "Please fill in all
// fields" banner.
export default function LoginPage() {
  const { signIn } = useAuth()
  const router = useRouter()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({})
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

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
      setError(error.message)
      setLoading(false)
      return
    }

    setLoading(false)
    router.push('/conferences')
  }

  return (
    <AuthCard
      title="Sign in"
      intro="Your saved events, calendar and specialty alerts."
      footer={
        <>
          Don&apos;t have an account?{' '}
          <Link href="/auth/signup" className="font-medium text-brand-text hover:underline">
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
            if (fieldErrors.email) setFieldErrors((f) => ({ ...f, email: undefined }))
          }}
          error={fieldErrors.email}
        />

        <AuthField
          id="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value)
            if (fieldErrors.password) setFieldErrors((f) => ({ ...f, password: undefined }))
          }}
          error={fieldErrors.password}
        />

        {error && <AuthError message={error} />}

        <Button type="submit" disabled={loading} className="w-full">
          {loading ? 'Signing in…' : 'Sign in'}
        </Button>

        <AuthTerms />
      </form>
    </AuthCard>
  )
}
