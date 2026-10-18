// src/hooks/useIsAdmin.ts
'use client'

import { useEffect, useMemo, useState } from 'react'
import { createSupabaseClient } from '@/lib/supabase'
import { useAuth } from '@/hooks/useAuth'

/**
 * True when the signed-in user has user_profiles.is_admin. `null` while the
 * session or lookup is loading, `false` for signed-out users and on any
 * lookup failure (UI-only gate; the server enforces admin via RLS/RPC).
 */
export function useIsAdmin(): boolean | null {
  const { user, loading } = useAuth()
  const supabase = useMemo(() => createSupabaseClient(), [])
  const [state, setState] = useState<{ uid: string | null; value: boolean } | null>(null)

  useEffect(() => {
    if (loading || !user) return
    let cancelled = false
    ;(async () => {
      const { data, error } = await supabase.from('user_profiles').select('is_admin').eq('id', user.id).maybeSingle()
      if (!cancelled) setState({ uid: user.id, value: !error && data?.is_admin === true })
    })()
    return () => {
      cancelled = true
    }
  }, [loading, user, supabase])

  if (loading) return null
  if (!user) return false
  return state?.uid === user.id ? state.value : null
}
