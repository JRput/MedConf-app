import { toDuplicateRow, type DuplicateRow } from '@/lib/community/moderation'

/** Directory search for duplicates and the merge picker (public endpoint, camelCase rows). */
export async function searchDirectory(q: string, signal?: AbortSignal, pageSize = 8): Promise<DuplicateRow[]> {
  const term = q.trim()
  if (term.length < 2) return []
  const res = await fetch(`/api/directory?q=${encodeURIComponent(term)}&pageSize=${pageSize}`, { signal })
  if (!res.ok) throw new Error('Directory search failed')
  const json = (await res.json()) as { rows?: Record<string, unknown>[] }
  return (json.rows ?? []).map(toDuplicateRow).filter((r): r is DuplicateRow => r !== null)
}
