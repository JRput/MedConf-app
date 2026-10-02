// src/app/api/directory/route.ts
// GET /api/directory?<DirectoryFilters as query string>[&facets=1]
//
// Lets the client directory list paginate/filter without re-downloading the
// whole catalogue (see directory-query.ts's module doc comment for why).
// This is a plain Route Handler (not a server component) specifically so
// the EXISTING client-component directory page (app/conferences/page.tsx,
// still 'use client' per the code audit) can call it with fetch() the same
// way it'd call any other API, without the UI agent having to convert the
// page to a server component first.
//
// Caching: `s-maxage=300, stale-while-revalidate=600` — directory data
// changes on a daily cron (02:00 UTC scrape + 04:00 UTC remediator), so a
// 5-minute shared cache is safe and meaningfully cuts DB load for a
// public, unauthenticated, read-only endpoint.

import { NextResponse } from 'next/server'
import { createServerClient } from '@supabase/ssr'
import { parseDirectoryUrl } from '@/lib/directory-url'
import { queryDirectory, queryFacets } from '@/lib/directory-query'

export async function GET(request: Request) {
  const url = new URL(request.url)
  const filters = parseDirectoryUrl(url.searchParams)
  const wantFacets = url.searchParams.get('facets') === '1'

  // No auth/session needed for a public, anon-key-read endpoint — use a
  // bare server client (no cookie plumbing) so this route works for both
  // signed-in and anonymous visitors identically.
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    { cookies: { getAll: () => [], setAll: () => {} } }
  )

  try {
    const [page, facets] = await Promise.all([
      queryDirectory(supabase, filters),
      wantFacets ? queryFacets(supabase, filters) : Promise.resolve(null),
    ])

    return NextResponse.json(
      { ...page, facets },
      { headers: { 'Cache-Control': 'public, s-maxage=300, stale-while-revalidate=600' } }
    )
  } catch (err) {
    console.error('[api/directory]', err)
    // Supabase/PostgREST errors are plain objects ({ code, message, details,
    // hint }), not Error instances — String(err) on one of those collapses
    // to the useless "[object Object]", so pull `.message` explicitly first.
    const detail =
      err instanceof Error
        ? err.message
        : typeof err === 'object' && err !== null && 'message' in err
          ? String((err as { message: unknown }).message)
          : String(err)
    return NextResponse.json({ error: 'Failed to query directory', detail }, { status: 500 })
  }
}
