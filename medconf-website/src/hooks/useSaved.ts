// src/hooks/useSaved.ts
'use client'

import { useState, useEffect, useCallback } from 'react'
import { createSupabaseClient } from '@/lib/supabase'
import { useAuth } from '@/hooks/useAuth'

export function useSaved() {
  const [savedIds, setSavedIds] = useState<Set<number>>(new Set())
  const { user } = useAuth()
  const supabase = createSupabaseClient()

  useEffect(() => {
    if (!user) {
      setSavedIds(new Set())
      return
    }

    async function fetchSaved() {
      const { data } = await supabase
        .from('saved_conferences')
        .select('conference_id')
        .eq('user_id', user!.id)

      if (data) setSavedIds(new Set(data.map(r => r.conference_id)))
    }

    fetchSaved()
  }, [user])

  const isSaved = useCallback((conferenceId: number) => savedIds.has(conferenceId), [savedIds])

  const toggleSave = async (conferenceId: number) => {
    if (!user) return

    if (isSaved(conferenceId)) {
      // Remove from saved
      await supabase.from('saved_conferences').delete()
        .eq('user_id', user.id).eq('conference_id', conferenceId)
      
      setSavedIds(prev => { 
        const next = new Set(prev)
        next.delete(conferenceId)
        return next 
      })
    } else {
      // Add to saved
      await supabase.from('saved_conferences').insert({
        user_id: user.id, conference_id: conferenceId
      })
      
      setSavedIds(prev => new Set([...prev, conferenceId]))
    }
  }

  return { savedIds, isSaved, toggleSave }
}


