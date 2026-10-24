// src/lib/preview.ts
//
// Typed wrappers for the three narrow, anonymous-callable database functions
// (supabase/migrations/20261024000001_access_gate_phase2.sql). After Phase 2b
// the anon role can no longer read the directory tables, so every anonymous
// surface (homepage, event teaser, sitemap) reads through these instead.
//
// Failure policy: only PGRST202 (function missing, the state before Phase 2a
// is applied) permits a fallback to direct reads. Any other error is reported
// as `error` and the caller must NOT fall back or cache an empty result:
// pages and the sitemap throw, so ISR keeps serving the last good copy and the
// event page shows Next's error boundary. Error logs carry the code only.

import { cache } from 'react'
import type { PublicEventFields } from '@/lib/event-public'

/** Minimal client surface so tests can pass a stub. */
type RpcResponse = { data: unknown; error: { code?: string; message?: string } | null }
export interface RpcClient {
  rpc(
    fn: string,
    args?: Record<string, unknown>
  ): PromiseLike<RpcResponse> & { range?: (from: number, to: number) => PromiseLike<RpcResponse> }
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
    /** Optional until the Phase 2a function that adds it is applied. */
    active_sources?: number
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

/**
 * ok = data returned; missing = function not deployed (PGRST202, fallback
 * allowed); error = anything else (no fallback). Event lookups add not_found.
 */
export type PreviewResult<T> = { status: 'ok'; data: T } | { status: 'missing' } | { status: 'error' }
export type EventPreviewResult = PreviewResult<EventPreview> | { status: 'not_found' }

const warned = new Set<string>()

/** Test hook: forget which functions have already warned. */
export function resetPreviewWarnings() {
  warned.clear()
}

async function call(
  supabase: RpcClient,
  fn: string,
  args?: Record<string, unknown>,
  range?: [number, number]
): Promise<PreviewResult<unknown>> {
  try {
    const builder = supabase.rpc(fn, args)
    const { data, error } = await (range && builder.range ? builder.range(range[0], range[1]) : builder)
    if (!error) return { status: 'ok', data }
    if (error.code === 'PGRST202') {
      // TODO(access-gate): remove after Phase 2b is applied
      if (!warned.has(fn)) {
        warned.add(fn)
        console.warn(`[preview] ${fn} missing — falling back to direct reads`)
      }
      return { status: 'missing' }
    }
    console.error(`[preview] ${fn} failed`, error.code ?? 'unknown')
  } catch {
    console.error(`[preview] ${fn} threw`)
  }
  return { status: 'error' }
}

export async function fetchHomePreview(supabase: RpcClient): Promise<PreviewResult<HomePreview>> {
  const r = await call(supabase, 'home_preview')
  if (r.status !== 'ok') return r
  if (!r.data || typeof r.data !== 'object') return { status: 'error' }
  return { status: 'ok', data: r.data as HomePreview }
}

const EVENT_KEYS = [
  'id',
  'conference_name',
  'specialty',
  'event_type',
  'event_format',
  'is_flagship',
  'is_on_demand',
  'start_date',
  'end_date',
  'city',
  'region',
  'society',
  'description_excerpt',
] as const satisfies ReadonlyArray<keyof PublicEventFields>

/** Copy ONLY the public keys, so a function that over-returns cannot leak into the tree. */
export function toEventPreview(raw: unknown): EventPreview {
  const src = (raw ?? {}) as Record<string, unknown>
  const out: Record<string, unknown> = {}
  for (const k of EVENT_KEYS) out[k] = src[k] ?? null
  out.id = src.id
  out.is_flagship = src.is_flagship === true
  out.is_on_demand = src.is_on_demand === true
  return out as unknown as EventPreview
}

async function eventPreviewImpl(supabase: RpcClient, id: number): Promise<EventPreviewResult> {
  const r = await call(supabase, 'event_preview', { p_id: id })
  if (r.status !== 'ok') return r
  if (r.data === null || r.data === undefined) return { status: 'not_found' }
  if (typeof r.data !== 'object') return { status: 'error' }
  return { status: 'ok', data: toEventPreview(r.data) }
}

/**
 * `cache()` dedupes per server request when called with the same client and id
 * (generateMetadata and the page share one RPC if they share a client). Outside
 * a React server render it is a plain pass-through.
 */
export const fetchEventPreview = cache(eventPreviewImpl)

const SITEMAP_PAGE = 1000
const SITEMAP_MAX_PAGES = 10

/**
 * PostgREST caps a set-returning function at 1000 rows per response, so page
 * through with Range. Any failure (including on a later page) is reported as a
 * whole; a partial list is never returned.
 */
export async function fetchSitemapEvents(supabase: RpcClient): Promise<PreviewResult<SitemapEvent[]>> {
  const rows: SitemapEvent[] = []
  for (let page = 0; page < SITEMAP_MAX_PAGES; page++) {
    const from = page * SITEMAP_PAGE
    const r = await call(supabase, 'sitemap_events', undefined, [from, from + SITEMAP_PAGE - 1])
    if (r.status !== 'ok') return r
    if (!Array.isArray(r.data)) return { status: 'error' }
    rows.push(...(r.data as SitemapEvent[]))
    if (r.data.length < SITEMAP_PAGE) break
  }
  return { status: 'ok', data: rows }
}
