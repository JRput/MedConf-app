// src/app/conferences/page.tsx
//
// Server component: resolves the FIRST page straight from `queryDirectory`/
// `queryFacets` (or the dev fixture — see directory-source.ts) using the
// incoming `searchParams`, so the directory is fast and indexable on first
// load. Every filter/sort/page change after that is handled client-side by
// DirectoryClient, which re-fetches via /api/directory and keeps the URL in
// sync. Gated: middleware sends signed-out visitors to /auth/login?next=...,
// and the page re-checks the session itself (defence in depth) and is noindex (event detail pages stay the public, indexable surface).

import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'
import { loginHrefFor } from '@/lib/auth/gate'
import { parseDirectoryUrl } from '@/lib/directory-url'
import { resolveDirectory, wantsFixture } from '@/lib/directory-source'
import { DirectoryClient } from '@/components/directory/DirectoryClient'

export const metadata = {
  title: 'Conference directory — MedConf',
  description: 'Search medical conferences, courses and CPD opportunities by specialty, date, format, price and society.',
  robots: { index: false, follow: false },
}

export default async function ConferencesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>
}) {
  const rawParams = await searchParams
  const urlParams = new URLSearchParams()
  for (const [key, value] of Object.entries(rawParams)) {
    if (value == null) continue
    urlParams.set(key, Array.isArray(value) ? value.join(',') : value)
  }

  const filters = parseDirectoryUrl(urlParams)
  const fixture = wantsFixture(urlParams)

  // Session-gated directory (middleware); request cookies are forwarded so
  // reads run as the signed-in user. A server component can't set cookies,
  // so getAll-only is correct.
  const cookieStore = await cookies()
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    { cookies: { getAll: () => cookieStore.getAll(), setAll: () => {} } }
  )

  const { data: { user }, error: userError } = await supabase.auth.getUser()
  if (userError) console.warn('[gate] getUser failed', userError.status, userError.name)
  if (!user) redirect(loginHrefFor('/conferences', rawParams))

  const { page, facets, usedFixture } = await resolveDirectory(supabase, filters, { fixture, wantFacets: true })

  return (
    <DirectoryClient
      initialFilters={filters}
      initialData={{ rows: page.rows, total: page.total, page: page.page, pageSize: page.pageSize, facets }}
      fixture={fixture || usedFixture}
    />
  )
}
