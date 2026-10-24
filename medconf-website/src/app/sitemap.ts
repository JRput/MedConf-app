// Home, the two auth entry points, and every non-archived event page. Event
// pages are public teasers (header + locked panel), so they are indexable;
// /conferences and /societies are members-only and deliberately absent.

import type { MetadataRoute } from 'next'
import { createSupabaseServerClient } from '@/lib/supabase-server'

export const revalidate = 3600

const BASE = process.env.NEXT_PUBLIC_SITE_URL ?? 'https://medconf.vercel.app'
const CAP = 5000
const CHUNK = 1000

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const entries: MetadataRoute.Sitemap = [
    { url: `${BASE}/`, changeFrequency: 'daily', priority: 1 },
    { url: `${BASE}/auth/login`, changeFrequency: 'yearly', priority: 0.3 },
    { url: `${BASE}/auth/signup`, changeFrequency: 'yearly', priority: 0.5 },
  ]

  try {
    const supabase = createSupabaseServerClient()
    const ids: number[] = []
    for (let from = 0; from < CAP; from += CHUNK) {
      const { data, error } = await supabase
        .from('directory_events')
        .select('id')
        .order('id', { ascending: true })
        .range(from, Math.min(from + CHUNK, CAP) - 1)
      if (error || !data) break
      ids.push(...data.map((r: { id: number }) => r.id))
      if (data.length < CHUNK) break
    }
    for (const id of ids) entries.push({ url: `${BASE}/conferences/${id}`, changeFrequency: 'weekly', priority: 0.6 })
  } catch {
    // Database unreachable: ship the static entries rather than failing the sitemap.
  }

  return entries
}
