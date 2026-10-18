// src/hooks/useCommunity.ts
'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { createSupabaseClient } from '@/lib/supabase'
import type {
  AddInfoPayload,
  CommunityFact,
  CommunityTier,
  Contribution,
  ContributionKind,
  NewEventPayload,
} from '@/lib/community/types'

/** Published community facts + fee tiers for one listing (anon read, RLS exposes published only). */
export function usePublishedCommunity(conferenceId: number | null | undefined) {
  const supabase = useMemo(() => createSupabaseClient(), [])
  const [facts, setFacts] = useState<CommunityFact[]>([])
  const [tiers, setTiers] = useState<CommunityTier[]>([])
  const [loading, setLoading] = useState(conferenceId != null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (conferenceId == null) return
    let cancelled = false
    ;(async () => {
      const [f, t] = await Promise.all([
        supabase.from('community_facts').select('*').eq('conference_id', conferenceId).eq('is_published', true),
        supabase.from('community_tiers').select('*').eq('conference_id', conferenceId).eq('is_published', true),
      ])
      if (cancelled) return
      if (f.error || t.error) {
        // Tables may not exist yet on a fresh environment; degrade to "nothing from the community".
        setError((f.error ?? t.error)?.message ?? 'Could not load community information.')
        setFacts([])
        setTiers([])
      } else {
        setFacts((f.data ?? []) as CommunityFact[])
        setTiers((t.data ?? []) as CommunityTier[])
        setError(null)
      }
      setLoading(false)
    })()
    return () => {
      cancelled = true
    }
  }, [conferenceId, supabase])

  return { facts, tiers, loading, error }
}

export interface SubmitContributionInput {
  kind: ContributionKind
  conference_id?: number | null
  payload: AddInfoPayload | NewEventPayload
  note?: string | null
  evidence_url?: string | null
}

export type SubmitResult = { ok: true; id: string } | { ok: false; message: string }

/** Friendly copy for the failures a submitter can actually recover from. */
export function friendlySubmitError(err: { code?: string; message?: string } | null | undefined): string {
  const msg = err?.message ?? ''
  if (/too many pending contributions/i.test(msg)) {
    return 'You already have 10 contributions waiting for review. Please wait for a moderator to review some before adding more.'
  }
  if (err?.code === '23514') {
    return 'That submission was rejected by our checks (it may be too long or incomplete). Please review the fields and try again.'
  }
  if (err?.code === '42501' || /row-level security/i.test(msg)) {
    return 'Your session has expired. Please sign in again and resend.'
  }
  if (/failed to fetch|network/i.test(msg)) {
    return 'Could not reach the server. Check your connection and try again.'
  }
  return 'Something went wrong sending this. Please try again in a moment.'
}

export function useSubmitContribution() {
  const supabase = useMemo(() => createSupabaseClient(), [])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = useCallback(
    async (input: SubmitContributionInput): Promise<SubmitResult> => {
      setSubmitting(true)
      setError(null)
      try {
        const { data: auth } = await supabase.auth.getUser()
        if (!auth.user) {
          const message = 'Please sign in to send a contribution.'
          setError(message)
          return { ok: false, message }
        }
        const { data, error: insertError } = await supabase
          .from('community_contributions')
          .insert({
            user_id: auth.user.id,
            kind: input.kind,
            conference_id: input.conference_id ?? null,
            payload: input.payload,
            note: input.note?.trim() || null,
            evidence_url: input.evidence_url?.trim() || null,
          })
          .select('id')
          .single()
        if (insertError || !data) {
          const message = friendlySubmitError(insertError)
          setError(message)
          return { ok: false, message }
        }
        return { ok: true, id: (data as { id: string }).id }
      } catch (e) {
        const message = friendlySubmitError({ message: e instanceof Error ? e.message : String(e) })
        setError(message)
        return { ok: false, message }
      } finally {
        setSubmitting(false)
      }
    },
    [supabase]
  )

  return { submit, submitting, error, clearError: () => setError(null) }
}

/** The signed-in user's own contributions, newest first. */
export function useMyContributions() {
  const supabase = useMemo(() => createSupabaseClient(), [])
  const [contributions, setContributions] = useState<Contribution[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [tick, setTick] = useState(0)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const { data: auth } = await supabase.auth.getUser()
      if (cancelled) return
      if (!auth.user) {
        setContributions([])
        setLoading(false)
        return
      }
      const { data, error: selError } = await supabase
        .from('community_contributions')
        .select('*')
        .eq('user_id', auth.user.id)
        .order('created_at', { ascending: false })
      if (cancelled) return
      if (selError) {
        setError('Could not load your contributions.')
        setContributions([])
      } else {
        setError(null)
        setContributions((data ?? []) as Contribution[])
      }
      setLoading(false)
    })()
    return () => {
      cancelled = true
    }
  }, [supabase, tick])

  /** Re-query (e.g. after a resubmit). */
  const refresh = useCallback(() => {
    setLoading(true)
    setTick((n) => n + 1)
  }, [])

  return { contributions, loading, error, refresh }
}
