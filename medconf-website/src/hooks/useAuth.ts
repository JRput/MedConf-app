// src/hooks/useAuth.ts
'use client'

import { useState, useEffect } from 'react'
import { createSupabaseClient } from '@/lib/supabase'
import type { User } from '@supabase/supabase-js'
import { safeNextPath } from '@/lib/auth/password'
import { clearNextCookie } from '@/lib/auth/next-cookie'

export function useAuth() {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const supabase = createSupabaseClient()

  useEffect(() => {
    // Get initial session
    const getInitialSession = async () => {
      const { data: { session } } = await supabase.auth.getSession()
      setUser(session?.user ?? null)
      setLoading(false)
    }
    
    getInitialSession()

    // Listen for auth state changes (login, logout, session restore)
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_, session) => {
      setUser(session?.user ?? null)
      setLoading(false)
    })

    return () => subscription.unsubscribe()
  }, [])

  const signUp = async (email: string, password: string, next?: string) => {
    const safeNext = safeNextPath(next, '')
    const callback = `${window.location.origin}/auth/callback${safeNext ? `?next=${encodeURIComponent(safeNext)}` : ''}`
    const { data, error } = await supabase.auth.signUp({ 
      email, 
      password,
      options: {
        emailRedirectTo: callback
      }
    })
    return { data, error }
  }

  // Re-sends the signup confirmation email. Callers must show the same copy
  // whether or not the account exists (Supabase does not reveal it either).
  const resendConfirmation = async (email: string, next?: string) => {
    const safeNext = safeNextPath(next, '')
    // NOTE: the token_hash email templates build their own link from SiteURL and
    // ignore this redirect's `next`; same-device continuity relies on mc_next.
    const callback = `${window.location.origin}/auth/callback${safeNext ? `?next=${encodeURIComponent(safeNext)}` : ''}`
    const { error } = await supabase.auth.resend({
      type: 'signup',
      email,
      options: { emailRedirectTo: callback },
    })
    return { error }
  }

  const signIn = async (email: string, password: string) => {
    const { data, error } = await supabase.auth.signInWithPassword({ email, password })
    return { data, error }
  }

  const requestPasswordReset = async (email: string) => {
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent('/auth/reset-password')}`,
    })
    return { error }
  }

  const updatePassword = async (password: string) => {
    const { error } = await supabase.auth.updateUser({ password })
    return { error }
  }

  const signOut = async (opts?: { scope?: 'local' | 'global' | 'others' }) => {
    clearNextCookie()
    const { error } = opts?.scope ? await supabase.auth.signOut({ scope: opts.scope }) : await supabase.auth.signOut()
    if (error) {
      const e = error as { status?: number; name?: string }
      console.warn('[auth] signOut failed', e.status, e.name)
      await supabase.auth.signOut({ scope: 'local' })
    }
  }

  return { user, loading, signUp, resendConfirmation, signIn, signOut, requestPasswordReset, updatePassword }
}

