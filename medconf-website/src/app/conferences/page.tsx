// src/app/conferences/page.tsx
//
// Server component: resolves the FIRST page straight from `queryDirectory`/
// `queryFacets` (or the dev fixture — see directory-source.ts) using the
// incoming `searchParams`, so the directory is fast and indexable on first
// load. Every filter/sort/page change after that is handled client-side by
// DirectoryClient, which re-fetches via /api/directory and keeps the URL in
// sync.

import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
import { parseDirectoryUrl } from '@/lib/directory-url'
import { resolveDirectory, wantsFixture } from '@/lib/directory-source'
import { DirectoryClient } from '@/components/directory/DirectoryClient'

export const metadata = {
  title: 'Conference directory — MedConf',
  description: 'Search medical conferences, courses and CPD opportunities by specialty, date, format, price and society.',
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

  // Public, read-only directory — no session needed, but a server component
  // can't set cookies anyway, so getAll-only is correct here either way.
  const cookieStore = await cookies()
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    { cookies: { getAll: () => cookieStore.getAll(), setAll: () => {} } }
  )

  const { page, facets, usedFixture } = await resolveDirectory(supabase, filters, { fixture, wantFacets: true })

  return (
    <DirectoryClient
      initialFilters={filters}
      initialData={{ rows: page.rows, total: page.total, page: page.page, pageSize: page.pageSize, facets }}
      fixture={fixture || usedFixture}
    />
  )
}
