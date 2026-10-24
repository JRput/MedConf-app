// src/lib/home-teaser.ts
//
// Pure helpers behind the anonymous homepage teaser. Nothing here touches the
// network; the page feeds in rows it has already fetched.

/** Window for "abstract deadlines closing soon" — shared by the page, the stats row and its label. */
export const CLOSING_SOON_DAYS = 14

function toUtcDay(d: Date | string): number | null {
  if (typeof d === 'string') {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d)
    if (!m) return null
    return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  }
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate())
}

/** "closes today" / "closes tomorrow" / "closes in N days" from a whole-day count. Null when negative or not a number. */
export function relativeDaysLeft(days: number | null | undefined): string | null {
  if (typeof days !== 'number' || !Number.isFinite(days) || days < 0) return null
  if (days === 0) return 'closes today'
  if (days === 1) return 'closes tomorrow'
  return `closes in ${Math.round(days)} days`
}

/**
 * Relative-only deadline wording for anonymous visitors — never the date
 * itself. Null when there is no deadline or it has already passed.
 */
export function relativeDeadline(dateIso: string | null | undefined, today: Date | string = new Date()): string | null {
  if (!dateIso) return null
  const target = toUtcDay(dateIso)
  const base = toUtcDay(today)
  if (target === null || base === null) return null
  return relativeDaysLeft(Math.round((target - base) / 86_400_000))
}

/** First `visible` rows render normally; the rest sit behind the blur. */
export function splitTeaser<T>(rows: T[], visible = 6): { visible: T[]; blurred: T[] } {
  return { visible: rows.slice(0, visible), blurred: rows.slice(visible) }
}

export interface HomeStats {
  events: number
  societies: number
  specialties: number
  closingSoon: number
}

/** Counts only. `closingSoon` = abstract deadlines from today up to `windowDays` ahead. */
export function homeStats(input: {
  total: number
  societyCounts: Record<string, number>
  specialtyCounts: Record<string, number>
  deadlines: Array<string | null | undefined>
  today?: Date | string
  windowDays?: number
}): HomeStats {
  const base = toUtcDay(input.today ?? new Date())
  const windowDays = input.windowDays ?? CLOSING_SOON_DAYS
  const closingSoon = input.deadlines.filter((d) => {
    const t = d ? toUtcDay(d) : null
    if (t === null || base === null) return false
    const days = Math.round((t - base) / 86_400_000)
    return days >= 0 && days <= windowDays
  }).length
  const live = (r: Record<string, number>) => Object.values(r).filter((n) => n > 0).length
  return {
    events: input.total,
    societies: live(input.societyCounts),
    specialties: live(input.specialtyCounts),
    closingSoon,
  }
}

/**
 * Sum raw specialty counts into parent buckets using the supplied canonicaliser
 * (the page passes taxonomy `canonicalSpecialty`). Pure so it can be tested.
 */
export function sumByParent(
  raw: Array<{ specialty: string; count: number }>,
  parentOf: (rawValue: string) => string
): Record<string, number> {
  const out: Record<string, number> = {}
  for (const { specialty, count } of raw) {
    const parent = parentOf(specialty)
    out[parent] = (out[parent] ?? 0) + count
  }
  return out
}

/** Society tiles: the featured list (when given and present), else the top `limit` by count. */
export function pickSocieties(
  list: Array<{ society: string; count: number }>,
  opts: { featured?: string[]; limit?: number } = {}
): Array<{ society: string; count: number }> {
  const limit = opts.limit ?? 8
  if (opts.featured?.length) {
    const byCode = new Map(list.map((x) => [x.society, x.count]))
    const picked = opts.featured.filter((c) => (byCode.get(c) ?? 0) > 0).map((c) => ({ society: c, count: byCode.get(c)! }))
    if (picked.length) return picked.slice(0, limit)
  }
  return [...list].sort((a, b) => b.count - a.count || a.society.localeCompare(b.society)).slice(0, limit)
}
