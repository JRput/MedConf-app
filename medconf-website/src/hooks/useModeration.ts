// src/hooks/useModeration.ts
'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createSupabaseClient } from '@/lib/supabase'
import type { Contribution } from '@/lib/community/types'
import { TAB_ORDER, TAB_STATUSES, type QueueTab } from '@/lib/community/moderation'

export interface Submitter {
  email: string | null
  full_name: string | null
}

export interface QueueItem extends Contribution {
  /** Event name: payload.conference_name for new events, the listing's name for add_info. */
  eventName: string
  submitter: Submitter | null
}

export type TabCounts = Record<QueueTab, number>
const ZERO_COUNTS: TabCounts = { pending: 0, needs_info: 0, published: 0, rejected: 0, expired: 0, hidden: 0 }

const PAGE_LIMIT = 100

function newEventName(c: Contribution): string {
  const p = c.payload as unknown as Record<string, unknown>
  return typeof p?.conference_name === 'string' && p.conference_name ? p.conference_name : 'Untitled submission'
}

/** One query for every conference name the visible rows need. */
async function fetchConferenceNames(supabase: ReturnType<typeof createSupabaseClient>, ids: number[]) {
  const names = new Map<number, string>()
  if (ids.length === 0) return names
  const { data } = await supabase.from('conferences').select('id, conference_name').in('id', ids)
  for (const r of (data ?? []) as { id: number; conference_name: string }[]) names.set(r.id, r.conference_name)
  return names
}

/**
 * Submitter identity for admins. An admin SELECT policy on user_profiles is
 * added in a follow-up migration; until then (or if the email column is
 * absent) this resolves to an empty map and the UI shows a short id.
 */
async function fetchSubmitters(supabase: ReturnType<typeof createSupabaseClient>, userIds: string[]) {
  const map = new Map<string, Submitter>()
  if (userIds.length === 0) return map
  type Row = { id: string; email?: string | null; full_name?: string | null }
  let res: { data: unknown; error: unknown } = await supabase.from('user_profiles').select('id, email, full_name').in('id', userIds)
  if (res.error) res = await supabase.from('user_profiles').select('id, full_name').in('id', userIds)
  if (res.error) return map
  for (const r of (res.data ?? []) as Row[]) {
    map.set(r.id, { email: r.email ?? null, full_name: r.full_name ?? null })
  }
  return map
}
async function decorate(supabase: ReturnType<typeof createSupabaseClient>, rows: Contribution[]): Promise<QueueItem[]> {
  const confIds = [...new Set(rows.filter((r) => r.conference_id != null).map((r) => r.conference_id as number))]
  const userIds = [...new Set(rows.map((r) => r.user_id))]
  const [names, subs] = await Promise.all([fetchConferenceNames(supabase, confIds), fetchSubmitters(supabase, userIds)])
  return rows.map((r) => ({
    ...r,
    eventName:
      r.kind === 'new_event' && r.status !== 'merged'
        ? newEventName(r)
        : (r.conference_id != null ? names.get(r.conference_id) : undefined) ?? (r.kind === 'new_event' ? newEventName(r) : 'Listing removed'),
    submitter: subs.get(r.user_id) ?? null,
  }))
}

/** Rows for one tab (newest first) plus the count on every tab. */
export function useModerationQueue(tab: QueueTab) {
  const supabase = useMemo(() => createSupabaseClient(), [])
  const [tick, setTick] = useState(0)
  const key = `${tab}:${tick}`
  // Loading is derived: the stored result belongs to a different tab/refresh than the one requested.
  const [data, setData] = useState<{ key: string; items: QueueItem[]; counts: TabCounts; error: string | null } | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const [list, ...countRes] = await Promise.all([
        supabase
          .from('community_contributions')
          .select('*')
          .in('status', TAB_STATUSES[tab])
          .order('created_at', { ascending: false })
          .limit(PAGE_LIMIT),
        ...TAB_ORDER.map((t) =>
          supabase.from('community_contributions').select('id', { count: 'exact', head: true }).in('status', TAB_STATUSES[t])
        ),
      ])
      if (cancelled) return
      if (list.error) {
        setData({ key, items: [], counts: ZERO_COUNTS, error: list.error.message })
        return
      }
      const next: TabCounts = { ...ZERO_COUNTS }
      TAB_ORDER.forEach((t, i) => {
        next[t] = countRes[i].count ?? 0
      })
      const decorated = await decorate(supabase, (list.data ?? []) as Contribution[])
      if (cancelled) return
      setData({ key, items: decorated, counts: next, error: null })
    })()
    return () => {
      cancelled = true
    }
  }, [supabase, tab, key])

  const refresh = useCallback(() => setTick((n) => n + 1), [])
  return {
    items: data?.items ?? [],
    counts: data?.counts ?? ZERO_COUNTS,
    loading: data?.key !== key,
    error: data?.key === key ? data.error : null,
    refresh,
  }
}

/** One contribution with its decorations. */
export function useContribution(id: string) {
  const supabase = useMemo(() => createSupabaseClient(), [])
  const [item, setItem] = useState<QueueItem | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const { data, error: err } = await supabase.from('community_contributions').select('*').eq('id', id).maybeSingle()
      if (cancelled) return
      if (err || !data) {
        setItem(null)
        setError(err ? err.message : 'This contribution was not found.')
        setLoading(false)
        return
      }
      const [decorated] = await decorate(supabase, [data as Contribution])
      if (cancelled) return
      setItem(decorated)
      setError(null)
      setLoading(false)
    })()
    return () => {
      cancelled = true
    }
  }, [supabase, id, tick])

  const refresh = useCallback(() => setTick((n) => n + 1), [])
  return { item, loading, error, refresh }
}

export type ModerationAction = 'approve' | 'needs_info' | 'reject' | 'merge' | 'hide'

export type ModerationResult =
  | { ok: true; status: string; conferenceId: number | null }
  | { ok: false; code: 'duplicate'; conferenceId: number }
  | { ok: false; code: 'error'; message: string }

/** Friendly text for the errors the RPC can raise. */
export function moderationErrorMessage(message: string | undefined, code?: string): string {
  const m = message ?? ''
  // 22023: the database publish gate (unsafe URL, unchecked URL, changed URL). Its text is written for moderators.
  if (code === '22023' && m) return m
  if (/admin only/i.test(m)) return 'Only admins can do this. Your account is not flagged as an admin.'
  if (/only pending items/i.test(m) || /only published items/i.test(m)) return 'Someone already handled this item. Refresh to see its current status.'
  if (/not found/i.test(m)) return 'The item or the listing it points to no longer exists.'
  if (/failed to fetch|network/i.test(m)) return 'Could not reach the server. Check your connection and try again.'
  return m || 'Something went wrong. Please try again.'
}

/**
 * `rpc('moderate_contribution', { p_id, p_action, p_note, p_final })`.
 * Returns {ok:false, code:'duplicate'} when the organiser URL is already listed.
 */
export function useModerate() {
  const supabase = useMemo(() => createSupabaseClient(), [])
  const [busy, setBusy] = useState(false)

  const run = useCallback(
    async (
      id: string,
      action: ModerationAction,
      opts: { note?: string | null; final?: Record<string, unknown> | null } = {}
    ): Promise<ModerationResult> => {
      setBusy(true)
      try {
        const { data, error } = await supabase.rpc('moderate_contribution', {
          p_id: id,
          p_action: action,
          p_note: opts.note?.trim() || null,
          p_final: opts.final ?? null,
        })
        if (error) return { ok: false, code: 'error', message: moderationErrorMessage(error.message, error.code) }
        const res = (data ?? {}) as { ok?: boolean; code?: string; status?: string; conference_id?: number | null }
        if (res.ok === false && res.code === 'duplicate' && typeof res.conference_id === 'number') {
          return { ok: false, code: 'duplicate', conferenceId: res.conference_id }
        }
        if (res.ok === false) return { ok: false, code: 'error', message: 'The action was not applied.' }
        return { ok: true, status: res.status ?? '', conferenceId: res.conference_id ?? null }
      } catch (e) {
        return { ok: false, code: 'error', message: moderationErrorMessage(e instanceof Error ? e.message : String(e)) }
      } finally {
        setBusy(false)
      }
    },
    [supabase]
  )

  return { run, busy }
}

/**
 * Pending count for the Navbar badge. Only queries when `enabled` (admin);
 * refreshes every 60 s while the tab is visible and on window focus.
 */
export function usePendingCount(enabled: boolean): number | null {
  const supabase = useMemo(() => createSupabaseClient(), [])
  const [count, setCount] = useState<number | null>(null)
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    if (!enabled) return
    const load = async () => {
      const { count: c, error } = await supabase
        .from('community_contributions')
        .select('id', { count: 'exact', head: true })
        .eq('status', 'pending')
      if (alive.current && !error) setCount(c ?? 0)
    }
    load()
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') load()
    }, 60_000)
    window.addEventListener('focus', load)
    return () => {
      alive.current = false
      window.clearInterval(timer)
      window.removeEventListener('focus', load)
    }
  }, [enabled, supabase])

  return enabled ? count : null
}
