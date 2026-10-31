// Home, the two auth entry points, and every non-archived event page. Event
// pages are public teasers (header + locked panel), so they are indexable;
// /conferences and /societies are members-only and deliberately absent.

import type { MetadataRoute } from 'next'
import { createSupabaseServerClient } from '@/lib/supabase-server'
import { fetchSitemapEvents } from '@/lib/preview'

export const revalidate = 3600

const BASE = process.env.NEXT_PUBLIC_SITE_URL ?? 'https://medconf.vercel.app'
const CAP = 5000
const CHUNK = 1000

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const entries: MetadataRoute.Sitemap = [
    { url: `${BASE}/`, changeFrequency: 'daily', priority: 1 },
    { url: `${BASE}/auth/login`, changeFrequency: 'yearly', priority: 0.3 },
    { url: `${BASE}/auth/signup`, changeFrequency: 'yearly', priority: 0.5 },
    { url: `${BASE}/terms`, changeFrequency: 'yearly', priority: 0.3 },
    { url: `${BASE}/privacy`, changeFrequency: 'yearly', priority: 0.3 },
    { url: `${BASE}/cookies`, changeFrequency: 'yearly', priority: 0.3 },
  ]

  const supabase = createSupabaseServerClient()
  const viaFunction = await fetchSitemapEvents(supabase)
  // A real error must not be cached as a near-empty sitemap for an hour:
  // throw (outside any try) so ISR keeps serving the last good copy.
  if (viaFunction.status === 'error') throw new Error('sitemap_events failed')
  if (viaFunction.status === 'ok') {
    for (const r of viaFunction.data.slice(0, CAP)) {
      entries.push({
        url: `${BASE}/conferences/${r.id}`,
        lastModified: r.updated_at ? new Date(r.updated_at) : undefined,
        changeFrequency: 'weekly',
        priority: 0.6,
      })
    }
    return entries
  }

  try {
    const ids: number[] = []
    // TODO(access-gate): remove after Phase 2b is applied (function missing -> direct read)
    for (let from = 0; from < CAP; from += CHUNK) {
      const { data, error } = await supabase
        .from('directory_events')
        .select('id')
        .order('id', { ascending: true })
        .range(from, Math.min(from + CHUNK, CAP) - 1)
      if (error || !data) {
        console.error('[sitemap]', error?.code ?? error)
        break
      }
      ids.push(...data.map((r: { id: number }) => r.id))
      if (data.length < CHUNK) break
    }
    for (const id of ids) entries.push({ url: `${BASE}/conferences/${id}`, changeFrequency: 'weekly', priority: 0.6 })
  } catch (err) {
    console.error('[sitemap]', err instanceof Error ? err.message : err)
    // Database unreachable: ship the static entries rather than failing the sitemap.
  }

  return entries
}
