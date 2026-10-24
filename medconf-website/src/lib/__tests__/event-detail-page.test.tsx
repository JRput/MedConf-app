// Anonymous render of /conferences/[id]: the page is a server component, so
// we call it directly with mocked cookies + Supabase and inspect the element
// tree it returns (including every prop handed to every component). The
// anonymous tree must hold the event name but none of the locked values, and
// must never even query the tables that hold them.

import { beforeEach, describe, expect, it, vi } from 'vitest'

const h = vi.hoisted(() => {
  const FULL = {
    id: 548,
    source_id: 3,
    source_url: 'https://organiser.example/secret-source',
    conference_name: 'Cardiology Update 2027',
    specialty: 'Cardiology',
    event_type: 'conference',
    start_date: '2027-03-01',
    end_date: '2027-03-03',
    start_time: '09:00:00',
    venue_name: 'Secret Venue Hall',
    city: 'Leeds',
    region: 'Yorkshire',
    event_format: 'in_person',
    is_sold_out: false,
    cpd_accredited: true,
    cpd_points: 12,
    abstract_open: true,
    abstract_deadline: '2026-12-15',
    abstract_deadline_note: 'see page',
    organiser_url: 'https://organiser.example/event',
    booking_url: 'https://organiser.example/book',
    description: 'A short public description of the event.',
    price_gbp: 99,
    is_on_demand: false,
    on_demand_original_date: null,
    is_flagship: false,
    archived: false,
    created_at: '2026-01-01',
    updated_at: '2026-01-01',
  }
  return { FULL, tables: [] as string[], user: null as unknown }
})

vi.mock('next/headers', () => ({ cookies: async () => ({ getAll: () => [], set() {} }) }))
vi.mock('next/navigation', () => ({
  notFound: () => {
    throw new Error('NEXT_NOT_FOUND')
  },
}))
vi.mock('@supabase/ssr', () => ({
  createServerClient: () => ({
    auth: { getUser: async () => ({ data: { user: h.user }, error: null }) },
    from(table: string) {
      h.tables.push(table)
      const result = {
        data: table === 'conferences' ? h.FULL : table === 'scraper_sources' ? { society: 'RCP' } : [],
        error: null,
      }
      const q: Record<string, unknown> = {}
      for (const m of ['select', 'eq', 'order', 'in', 'limit']) q[m] = () => q
      q.single = async () => result
      q.then = (res: (v: unknown) => unknown) => Promise.resolve(result).then(res)
      return q
    },
  }),
}))

import ConferenceDetailPage from '@/app/conferences/[id]/page'

/**
 * Serialise an element tree with every prop. Element `type`s can be circular
 * module references, so only their display name is kept; functions are skipped.
 */
function walk(node: unknown): unknown {
  if (node === null || typeof node !== 'object') return typeof node === 'function' || typeof node === 'symbol' ? undefined : node
  if (Array.isArray(node)) return node.map(walk)
  const rec = node as Record<string, unknown>
  if ('$$typeof' in rec) {
    const t = rec.type as { displayName?: string; name?: string } | string
    return { type: typeof t === 'string' ? t : (t?.displayName ?? t?.name ?? 'Component'), props: walk(rec.props) }
  }
  return Object.fromEntries(Object.entries(rec).map(([k, v]) => [k, walk(v)]))
}
const serialise = (node: unknown) => JSON.stringify(walk(node))

describe('ConferenceDetailPage (anonymous)', () => {
  beforeEach(() => {
    h.tables.length = 0
    h.user = null
  })

  it('renders the event name but none of the locked values', async () => {
    const el = await ConferenceDetailPage({ params: Promise.resolve({ id: '548' }) })
    const out = serialise(el)
    expect(out).toContain('Cardiology Update 2027')
    for (const secret of ['Secret Venue Hall', '2026-12-15', 'organiser.example', 'cpd_points', 'price_gbp']) {
      expect(out).not.toContain(secret)
    }
  })

  it('never queries the tables that hold locked data', async () => {
    await ConferenceDetailPage({ params: Promise.resolve({ id: '548' }) })
    for (const t of ['pricing_tiers', 'course_sessions', 'community_facts', 'community_tiers']) {
      expect(h.tables).not.toContain(t)
    }
    expect(h.tables).toContain('conferences')
  })

  it('does fetch pricing for a signed-in visitor (the guard is the session, not a blanket skip)', async () => {
    h.user = { id: 'u1' }
    await ConferenceDetailPage({ params: Promise.resolve({ id: '548' }) })
    expect(h.tables).toContain('pricing_tiers')
  })
})
