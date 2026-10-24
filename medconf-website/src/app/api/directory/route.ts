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
import { publicDirectoryError, resolveDirectory, wantsFixture } from '@/lib/directory-source'

export async function GET(request: Request) {
  const url = new URL(request.url)
  const filters = parseDirectoryUrl(url.searchParams)
  const wantFacets = url.searchParams.get('facets') === '1'
  const fixture = wantsFixture(url.searchParams)

  // No auth/session needed for a public, anon-key-read endpoint — use a
  // bare server client (no cookie plumbing) so this route works for both
  // signed-in and anonymous visitors identically.
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    { cookies: { getAll: () => [], setAll: () => {} } }
  )

  try {
    const { page, facets, usedFixture } = await resolveDirectory(supabase, filters, { fixture, wantFacets })

    return NextResponse.json(
      { ...page, facets, usedFixture },
      { headers: { 'Cache-Control': 'public, s-maxage=300, stale-while-revalidate=600' } }
    )
  } catch (err) {
    const { body, status } = publicDirectoryError(err)
    return NextResponse.json(body, { status })
  }
}
