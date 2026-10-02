// src/hooks/useSaved.ts
'use client'

import { useState, useEffect, useCallback } from 'react'
import { createSupabaseClient } from '@/lib/supabase'
import { useAuth } from '@/hooks/useAuth'

// Stable reference for the logged-out case, so callers relying on identity
// (e.g. a useMemo/useEffect keyed on `savedIds`) don't re-run every render.
const EMPTY_SET: Set<number> = new Set()

export function useSaved() {
  const [fetchedIds, setFetchedIds] = useState<Set<number>>(EMPTY_SET)
  const { user } = useAuth()
  const supabase = createSupabaseClient()

  useEffect(() => {
    // Resetting to the empty set on sign-out is handled by the `user ?`
    // fallback below rather than a setState call here — an effect whose
    // only job in a branch is "set state back to its default" is better
    // expressed as derived state than as a synchronous setState-in-effect.
    if (!user) return

    let cancelled = false

    async function fetchSaved() {
      const { data } = await supabase
        .from('saved_conferences')
        .select('conference_id')
        .eq('user_id', user!.id)

      if (!cancelled && data) setFetchedIds(new Set(data.map(r => r.conference_id)))
    }

    fetchSaved()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user])

  const savedIds = user ? fetchedIds : EMPTY_SET

  const isSaved = useCallback((conferenceId: number) => savedIds.has(conferenceId), [savedIds])

  const toggleSave = async (conferenceId: number) => {
    if (!user) return

    if (isSaved(conferenceId)) {
      // Remove from saved
      await supabase.from('saved_conferences').delete()
        .eq('user_id', user.id).eq('conference_id', conferenceId)

      setFetchedIds(prev => {
        const next = new Set(prev)
        next.delete(conferenceId)
        return next
      })
    } else {
      // Add to saved
      await supabase.from('saved_conferences').insert({
        user_id: user.id, conference_id: conferenceId
      })

      setFetchedIds(prev => new Set([...prev, conferenceId]))
    }
  }

  return { savedIds, isSaved, toggleSave }
}


