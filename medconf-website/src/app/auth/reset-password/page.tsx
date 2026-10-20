// src/app/auth/reset-password/page.tsx
'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { CheckCircle2 } from 'lucide-react'
import type { User } from '@supabase/supabase-js'
import { createSupabaseClient } from '@/lib/supabase'
import { useAuth } from '@/hooks/useAuth'
import { validateNewPassword } from '@/lib/auth/password'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { AuthCard, AuthError, AuthField } from '@/components/auth/AuthCard'

// Reached from /auth/callback after a recovery link has been verified, which
// leaves a session in the cookies. No session means the link was never opened
// on this device, was already used, or expired.
export default function ResetPasswordPage() {
  const { updatePassword } = useAuth()
  const router = useRouter()
  const [user, setUser] = useState<User | null>(null)
  const [checking, setChecking] = useState(true)
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [fieldErrors, setFieldErrors] = useState<{ password?: string; confirm?: string }>({})
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)

  useEffect(() => {
    const supabase = createSupabaseClient()
    let active = true
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!active) return
      setUser(session?.user ?? null)
      setChecking(false)
    })
    // Pick up a session that arrives late (cookie hydration, token refresh).
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!active) return
      if (session?.user) {
        setUser(session.user)
        setChecking(false)
      }
    })
    return () => {
      active = false
      subscription.unsubscribe()
    }
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const errors = validateNewPassword(password, confirm)
    setFieldErrors(errors)
    if (errors.password || errors.confirm) {
      setError('')
      return
    }
    setLoading(true)
    setError('')
    const { error: updateError } = await updatePassword(password)
    setLoading(false)
    if (updateError) {
      setError(updateError.message)
      return
    }
    setDone(true)
  }

  if (checking) {
    return (
      <AuthCard title="Choose a new password">
        <div className="space-y-4" aria-busy="true" aria-label="Checking your reset link">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      </AuthCard>
    )
  }

  if (!user) {
    return (
      <AuthCard
        title="This link has expired"
        intro="Reset links work once and expire after an hour. Request a new one and open it on the same device."
      >
        <Button className="w-full" asChild>
          <Link href="/auth/forgot-password">Request a new link</Link>
        </Button>
      </AuthCard>
    )
  }

  if (done) {
    return (
      <AuthCard title="Password updated">
        <div className="flex items-start gap-3 rounded-md border border-border bg-surface-muted px-3 py-3">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-surface">
            <CheckCircle2 className="size-4 text-fg-muted" aria-hidden />
          </span>
          <p className="text-[0.8125rem] leading-relaxed text-fg-muted">
            You&apos;re signed in on this device. Other devices stay signed in until their sessions expire.
          </p>
        </div>
        <Button className="mt-4 w-full" onClick={() => router.push('/dashboard')}>
          Continue to dashboard
        </Button>
      </AuthCard>
    )
  }

  return (
    <AuthCard
      title="Choose a new password"
      intro={
        <>
          You&apos;re signed in as <span className="font-medium text-fg">{user.email}</span>. Pick a new password to
          finish.
        </>
      }
      footer={
        <Link href="/auth/login" className="font-medium text-brand-text hover:underline">
          Back to sign in
        </Link>
      }
    >
      <form onSubmit={handleSubmit} noValidate className="space-y-4">
        <AuthField
          id="password"
          label="New password"
          type="password"
          autoComplete="new-password"
          hint="At least 8 characters."
          value={password}
          onChange={(e) => {
            setPassword(e.target.value)
            if (fieldErrors.password) setFieldErrors((f) => ({ ...f, password: undefined }))
          }}
          error={fieldErrors.password}
        />

        <AuthField
          id="confirm"
          label="Confirm new password"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => {
            setConfirm(e.target.value)
            if (fieldErrors.confirm) setFieldErrors((f) => ({ ...f, confirm: undefined }))
          }}
          error={fieldErrors.confirm}
        />

        {error && <AuthError message={error} />}

        <Button type="submit" disabled={loading} className="w-full">
          {loading ? 'Updating…' : 'Update password'}
        </Button>
      </form>
    </AuthCard>
  )
}
