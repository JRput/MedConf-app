// src/lib/fetch-pages.ts
// Supabase's `db_max_rows` caps every SELECT at 1000 rows by default and the
// project setting can't be raised on the free plan. A `.range(0, 9999)` from
// the client is silently truncated to the first 1000 — which started showing
// as mass "Price TBC" on the directory the moment per-session course pricing
// pushed pricing_tiers past 1000 rows.
//
// fetchAllPages walks the query in 1000-row chunks until it gets a short page,
// returning the full set. The builder callable is invoked once per page so
// we can re-execute the same query with a fresh `.range()` (PostgrestBuilder
// instances aren't reusable after .then() / .execute()).

const PAGE_SIZE = 1000
const SAFETY_CAP = 50_000  // refuse to spin past this many rows

interface PageQueryLike<T> {
  range(from: number, to: number): PromiseLike<{ data: T[] | null; error: unknown }>
}

export async function fetchAllPages<T>(
  builder: () => PageQueryLike<T>
): Promise<T[]> {
  const out: T[] = []
  let start = 0
  while (start < SAFETY_CAP) {
    const { data, error } = await builder().range(start, start + PAGE_SIZE - 1)
    if (error || !data) break
    out.push(...data)
    if (data.length < PAGE_SIZE) break  // short page = last page
    start += PAGE_SIZE
  }
  return out
}
