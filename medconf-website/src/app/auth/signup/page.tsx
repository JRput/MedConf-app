// src/app/auth/signup/page.tsx
'use client'

import { useState } from 'react'
import { useAuth } from '@/hooks/useAuth'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { Check } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { AuthCard, AuthError, AuthField, AuthTerms } from '@/components/auth/AuthCard'

// Auth behaviour is unchanged from the pre-W5 page: useAuth().signUp (which
// sets emailRedirectTo /auth/callback), the same 8-character minimum, and a
// push to /auth/verify on success. The copy now states what an account
// actually gives you — the directory itself is public and needs no account.
const BENEFITS = [
  'Save events to a personal calendar',
  'In-app alerts for new events in your specialty',
  'Reminders before an abstract deadline closes',
]

export default function SignUpPage() {
  const { signUp } = useAuth()
  const router = useRouter()

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

    const { error } = await signUp(email, password)

    if (error) {
      setError(error.message)
      setLoading(false)
      return
    }

    setLoading(false)
    router.push('/auth/verify')
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
          <Link href="/auth/login" className="font-medium text-brand-text hover:underline">
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

        <p className="text-[0.8125rem] text-fg-muted">
          Just looking? The{' '}
          <Link href="/conferences" className="font-medium text-brand-text hover:underline">
            directory is public
          </Link>{' '}
          — no account needed to search it.
        </p>

        <AuthTerms />
      </form>
    </AuthCard>
  )
}
