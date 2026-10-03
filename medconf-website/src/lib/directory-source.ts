// src/lib/directory-source.ts
//
// The ONE place that branches between the real `directory_events`/
// `directory_facets()` query path (directory-query.ts) and the dev fixture
// (__fixtures__/directory.ts). Used by both the API route
// (app/api/directory/route.ts) and the server-rendered first page
// (app/conferences/page.tsx) so they can't drift.
//
// Fixture mode is on when `?fixture=1` is in the URL, or
// NEXT_PUBLIC_DIRECTORY_FIXTURE=1 is set — see the W2b mission brief. Delete
// this branch (and __fixtures__/directory.ts) once the directory query layer
// migration is confirmed applied everywhere and the real path has been
// re-verified against it.

import type { SupabaseClient } from '@supabase/supabase-js'
import { queryDirectory, queryFacets, type DirectoryFacets, type DirectoryFilters, type DirectoryPage } from './directory-query'
import { queryDirectoryFixture, queryFacetsFixture, FIXTURE_EVENTS } from './__fixtures__/directory'

export function wantsFixture(searchParams: URLSearchParams): boolean {
  return searchParams.get('fixture') === '1' || process.env.NEXT_PUBLIC_DIRECTORY_FIXTURE === '1'
}

export async function resolveDirectory(
  supabase: SupabaseClient,
  filters: Partial<DirectoryFilters>,
  opts: { fixture: boolean; wantFacets: boolean }
): Promise<{ page: DirectoryPage; facets: DirectoryFacets | null; usedFixture: boolean }> {
  if (opts.fixture) {
    return {
      page: queryDirectoryFixture(filters),
      facets: opts.wantFacets ? queryFacetsFixture(filters) : null,
      usedFixture: true,
    }
  }

  try {
    const [page, facets] = await Promise.all([
      queryDirectory(supabase, filters),
      opts.wantFacets ? queryFacets(supabase, filters) : Promise.resolve(null),
    ])
    return { page, facets, usedFixture: false }
  } catch (err) {
    // The migration may not be applied yet in this environment (PGRST205
    // "directory_events not found") — degrade to the fixture rather than
    // hard-failing the whole page, so the UI stays reviewable. Once the
    // migration is confirmed live, an error here is a real bug and should
    // propagate; that's a sign this fallback can be deleted.
    const message = err instanceof Error ? err.message : String(err)
    if (/directory_events|directory_facets|PGRST205|schema cache/i.test(message)) {
      console.warn('[directory-source] directory_events not available yet, falling back to fixture:', message)
      return {
        page: queryDirectoryFixture(filters),
        facets: opts.wantFacets ? queryFacetsFixture(filters) : null,
        usedFixture: true,
      }
    }
    throw err
  }
}

/**
 * Soonest upcoming start_date per society short code — used by
 * app/societies/page.tsx's "next event" line. Not something queryDirectory/
 * queryFacets expose (they aggregate counts, not a per-group min), so this
 * does its own narrow query/scan rather than extending either of those.
 */
export async function getSocietyNextDates(
  supabase: SupabaseClient,
  opts: { fixture: boolean }
): Promise<Record<string, string>> {
  const today = new Date().toISOString().slice(0, 10)

  if (opts.fixture) {
    return reduceToEarliest(FIXTURE_EVENTS.filter((e) => e.startDate && e.startDate >= today).map((e) => ({ society: e.society, start_date: e.startDate! })))
  }

  try {
    const { data, error } = await supabase
      .from('directory_events')
      .select('society, start_date')
      .gte('start_date', today)
      .not('society', 'is', null)
      .order('start_date', { ascending: true })
      .limit(2000)
    if (error) throw error
    return reduceToEarliest((data ?? []) as { society: string | null; start_date: string }[])
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    if (/directory_events|PGRST205|schema cache/i.test(message)) {
      return reduceToEarliest(FIXTURE_EVENTS.filter((e) => e.startDate && e.startDate >= today).map((e) => ({ society: e.society, start_date: e.startDate! })))
    }
    throw err
  }
}

function reduceToEarliest(rows: { society: string | null; start_date: string }[]): Record<string, string> {
  const out: Record<string, string> = {}
  for (const r of rows) {
    if (!r.society) continue
    if (!out[r.society] || r.start_date < out[r.society]) out[r.society] = r.start_date
  }
  return out
}
