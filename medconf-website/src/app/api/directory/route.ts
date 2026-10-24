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
// Auth: sign-in required. No session -> 401 { error: "sign_in_required" }
// (private, no-store). Session-gated responses are never shared-cached:
// signed-in payloads use `private, max-age=0, must-revalidate`. The client
// directory's same-origin fetch() sends cookies by default.

import { NextResponse } from 'next/server'
import { cookies } from 'next/headers'
import { createServerClient } from '@supabase/ssr'
import { logGetUserError } from '@/lib/auth/gate'
import { parseDirectoryUrl } from '@/lib/directory-url'
import { publicDirectoryError, resolveDirectory, wantsFixture } from '@/lib/directory-source'

export async function GET(request: Request) {
  const url = new URL(request.url)
  const filters = parseDirectoryUrl(url.searchParams)
  const wantFacets = url.searchParams.get('facets') === '1'
  const fixture = wantsFixture(url.searchParams)

  const cookieStore = await cookies()
  // Refreshed session tokens from getUser() are buffered here and written onto
  // whichever response goes out, so a token refresh is never discarded.
  type CookieToSet = { name: string; value: string; options?: Parameters<NextResponse['cookies']['set']>[2] }
  let refreshed: CookieToSet[] = []
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll: () => cookieStore.getAll(),
        setAll: (cookiesToSet: CookieToSet[]) => { refreshed = cookiesToSet },
      },
    }
  )
  const finish = (res: NextResponse) => {
    refreshed.forEach(({ name, value, options }) => res.cookies.set(name, value, options))
    return res
  }

  const { data: { user }, error: userError } = await supabase.auth.getUser()
  logGetUserError('api/directory', userError)
  if (!user) {
    return finish(NextResponse.json(
      { error: 'sign_in_required' },
      { status: 401, headers: { 'Cache-Control': 'private, no-store' } }
    ))
  }

  try {
    const { page, facets, usedFixture } = await resolveDirectory(supabase, filters, { fixture, wantFacets })

    return finish(NextResponse.json(
      { ...page, facets, usedFixture },
      { headers: { 'Cache-Control': 'private, max-age=0, must-revalidate' } }
    ))
  } catch (err) {
    const { body, status } = publicDirectoryError(err)
    return finish(NextResponse.json(body, { status, headers: { 'Cache-Control': 'private, no-store' } }))
  }
}
