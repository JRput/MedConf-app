// src/lib/preview.ts
//
// Typed wrappers for the three narrow, anonymous-callable database functions
// (supabase/migrations/20261024000001_access_gate_phase2.sql). After Phase 2b
// the anon role can no longer read the directory tables, so every anonymous
// surface (homepage, event teaser, sitemap) reads through these instead.
//
// Failure policy (Level 2 decision): an anonymous page must never 500 because
// of a preview call. Every wrapper therefore returns `null` on any error and
// the caller falls back to its existing direct-read path.
//   - PGRST202 (function missing: the state on a database where Phase 2a has
//     not been applied) logs a one-time warning per function.
//   - Any other error is logged with console.error and also returns null.
// `fetchEventPreview` additionally returns NOT_FOUND when the function ran and
// found no (or an archived) event, so "missing" is not confused with "fall back".

import type { PublicEventFields } from '@/lib/event-public'

/** Minimal client surface so tests can pass a stub. */
export interface RpcClient {
  rpc(fn: string, args?: Record<string, unknown>): PromiseLike<{ data: unknown; error: { code?: string; message?: string } | null }>
}

export interface HomePreview {
  counts: {
    events: number
    societies: number
    /** Distinct RAW specialty strings — map to parents before showing. */
    specialties: number
    closing_soon: number
    this_month: number
    online_this_month: number
  }
  closing_soon: Array<{ id: number; name: string; society: string | null; days_left: number }>
  this_month: Array<{ id: number; name: string; society: string | null; start_date: string | null; end_date: string | null }>
  specialties: Array<{ specialty: string; count: number }>
  societies: Array<{ society: string; count: number }>
}

export type EventPreview = PublicEventFields

export interface SitemapEvent {
  id: number
  updated_at: string | null
}

export const NOT_FOUND = 'not_found' as const

const warned = new Set<string>()

/** Test hook: forget which functions have already warned. */
export function resetPreviewWarnings() {
  warned.clear()
}

async function call(supabase: RpcClient, fn: string, args?: Record<string, unknown>): Promise<{ ok: true; data: unknown } | { ok: false }> {
  try {
    const { data, error } = await supabase.rpc(fn, args)
    if (!error) return { ok: true, data }
    if (error.code === 'PGRST202') {
      // TODO(access-gate): remove after Phase 2b is applied
      if (!warned.has(fn)) {
        warned.add(fn)
        console.warn(`[preview] ${fn} missing — falling back to direct reads`)
      }
    } else {
      console.error(`[preview] ${fn} failed`, error.code ?? error.message ?? error)
    }
  } catch (err) {
    console.error(`[preview] ${fn} threw`, err instanceof Error ? err.message : err)
  }
  return { ok: false }
}

export async function fetchHomePreview(supabase: RpcClient): Promise<HomePreview | null> {
  const r = await call(supabase, 'home_preview')
  if (!r.ok || !r.data || typeof r.data !== 'object') return null
  return r.data as HomePreview
}

/** EventPreview when found, NOT_FOUND when the function says there is no such event, null to fall back. */
export async function fetchEventPreview(supabase: RpcClient, id: number): Promise<EventPreview | typeof NOT_FOUND | null> {
  const r = await call(supabase, 'event_preview', { p_id: id })
  if (!r.ok) return null
  if (r.data === null || r.data === undefined) return NOT_FOUND
  return r.data as EventPreview
}

export async function fetchSitemapEvents(supabase: RpcClient): Promise<SitemapEvent[] | null> {
  const r = await call(supabase, 'sitemap_events')
  if (!r.ok || !Array.isArray(r.data)) return null
  return r.data as SitemapEvent[]
}
