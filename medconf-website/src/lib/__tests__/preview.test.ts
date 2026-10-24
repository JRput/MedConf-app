import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Server clients used by the homepage and the sitemap. `mode` picks the rpc outcome.
const h = vi.hoisted(() => ({ mode: 'missing' as 'missing' | 'error', tables: [] as string[] }))
vi.mock('@supabase/ssr', () => ({
  createServerClient: () => ({
    rpc: async (fn: string) => {
      if (!['home_preview', 'event_preview', 'sitemap_events'].includes(fn)) return { data: {}, error: null } // directory_facets etc.
      return h.mode === 'missing'
        ? { data: null, error: { code: 'PGRST202', message: 'nf' } }
        : { data: null, error: { code: '42501', message: 'denied' } }
    },
    from(table: string) {
      h.tables.push(table)
      const result = { data: [], error: null, count: 0 }
      const q: unknown = new Proxy(() => q, {
        get: (_t, prop) => (prop === 'then' ? (res: (v: unknown) => unknown) => Promise.resolve(result).then(res) : () => q),
      })
      return q
    },
  }),
}))

import { fetchEventPreview, fetchHomePreview, fetchSitemapEvents, resetPreviewWarnings, toEventPreview, type RpcClient } from '../preview'
import { canonicalSpecialty } from '../taxonomy/specialties'
import { pickSocieties, splitTeaser, sumByParent } from '../home-teaser'
import sitemap from '@/app/sitemap'
import HomePage from '@/app/page'

const ok = (data: unknown): RpcClient => ({ rpc: async () => ({ data, error: null }) })
const fail = (code: string): RpcClient => ({ rpc: async () => ({ data: null, error: { code, message: 'x' } }) })

let warn: ReturnType<typeof vi.spyOn>
let err: ReturnType<typeof vi.spyOn>
beforeEach(() => {
  resetPreviewWarnings()
  warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
  err = vi.spyOn(console, 'error').mockImplementation(() => {})
})
afterEach(() => vi.restoreAllMocks())

describe('preview wrappers', () => {
  it('return ok with the typed payload and pass the id', async () => {
    const calls: Array<[string, unknown]> = []
    const client: RpcClient = {
      rpc: async (fn, args) => {
        calls.push([fn, args])
        return { data: fn === 'sitemap_events' ? [{ id: 1, updated_at: null }] : { id: 7, conference_name: 'X' }, error: null }
      },
    }
    expect(await fetchHomePreview(client)).toMatchObject({ status: 'ok', data: { id: 7 } })
    expect(await fetchEventPreview(client, 7)).toMatchObject({ status: 'ok', data: { id: 7, conference_name: 'X' } })
    expect(await fetchSitemapEvents(client)).toEqual({ status: 'ok', data: [{ id: 1, updated_at: null }] })
    expect(calls[1]).toEqual(['event_preview', { p_id: 7 }])
  })

  it('PGRST202 is "missing" and warns once per function', async () => {
    const c = fail('PGRST202')
    expect(await fetchHomePreview(c)).toEqual({ status: 'missing' })
    expect(await fetchHomePreview(c)).toEqual({ status: 'missing' })
    expect(await fetchEventPreview(c, 1)).toEqual({ status: 'missing' })
    expect(await fetchSitemapEvents(c)).toEqual({ status: 'missing' })
    expect(warn).toHaveBeenCalledTimes(3)
    expect(warn.mock.calls[0][0]).toBe('[preview] home_preview missing — falling back to direct reads')
    expect(err).not.toHaveBeenCalled()
  })

  it('any other code (or a thrown client) is "error", logs the code only, never throws', async () => {
    expect(await fetchHomePreview(fail('42501'))).toEqual({ status: 'error' })
    expect(await fetchSitemapEvents({ rpc: async () => { throw new Error('secret-detail') } })).toEqual({ status: 'error' })
    expect(err).toHaveBeenCalledTimes(2)
    expect(JSON.stringify(err.mock.calls)).not.toContain('secret-detail')
    expect(warn).not.toHaveBeenCalled()
  })

  it('event_preview distinguishes not_found, missing and error', async () => {
    expect(await fetchEventPreview(ok(null), 9)).toEqual({ status: 'not_found' })
    expect(await fetchEventPreview(fail('PGRST202'), 9)).toEqual({ status: 'missing' })
    expect(await fetchEventPreview(fail('500'), 9)).toEqual({ status: 'error' })
  })

  it('rejects malformed payloads as error', async () => {
    expect(await fetchSitemapEvents(ok({ nope: true }))).toEqual({ status: 'error' })
    expect(await fetchHomePreview(ok('str'))).toEqual({ status: 'error' })
  })

  it('toEventPreview keeps only the 13 public keys', () => {
    const out = toEventPreview({ id: 1, conference_name: 'N', venue_name: 'Secret', price_gbp: 9, organiser_url: 'u', society: 'RCP' })
    expect(Object.keys(out).sort()).toEqual(
      ['id', 'conference_name', 'specialty', 'event_type', 'event_format', 'is_flagship', 'is_on_demand', 'start_date', 'end_date', 'city', 'region', 'society', 'description_excerpt'].sort()
    )
    expect(JSON.stringify(out)).not.toMatch(/Secret|organiser_url|price_gbp/)
  })
})

describe('fetchSitemapEvents paging (PostgREST caps an rpc at 1000 rows)', () => {
  const rows = (n: number, start = 0) => Array.from({ length: n }, (_, i) => ({ id: start + i, updated_at: null }))
  /** rpc() returns a thenable builder that also has .range(from, to). */
  function pagedClient(pages: Array<RpcResponseLike>) {
    const ranges: Array<[number, number]> = []
    const client = {
      rpc: () => {
        const builder = {
          range: (from: number, to: number) => {
            ranges.push([from, to])
            return Promise.resolve(pages[ranges.length - 1])
          },
          then: () => {
            throw new Error('unranged call: would be capped at 1000 rows')
          },
        }
        return builder
      },
    } as unknown as RpcClient
    return { client, ranges }
  }
  type RpcResponseLike = { data: unknown; error: { code?: string } | null }

  it('appends pages until one is short: 1000 + 1000 + 132 = 2132 over three range calls', async () => {
    const { client, ranges } = pagedClient([
      { data: rows(1000, 0), error: null },
      { data: rows(1000, 1000), error: null },
      { data: rows(132, 2000), error: null },
    ])
    const r = await fetchSitemapEvents(client)
    expect(r.status).toBe('ok')
    expect(r.status === 'ok' && r.data.length).toBe(2132)
    expect(ranges).toEqual([[0, 999], [1000, 1999], [2000, 2999]])
  })

  it('a short first page is a single call', async () => {
    const { client, ranges } = pagedClient([{ data: rows(300), error: null }])
    const r = await fetchSitemapEvents(client)
    expect(r.status === 'ok' && r.data.length).toBe(300)
    expect(ranges).toEqual([[0, 999]])
  })

  it('an error on page 2 is an error, not a partial list', async () => {
    const { client } = pagedClient([
      { data: rows(1000), error: null },
      { data: null, error: { code: '57014' } },
    ])
    expect(await fetchSitemapEvents(client)).toEqual({ status: 'error' })
  })

  it('PGRST202 on the first page is missing', async () => {
    const { client } = pagedClient([{ data: null, error: { code: 'PGRST202' } }])
    expect(await fetchSitemapEvents(client)).toEqual({ status: 'missing' })
  })

  it('stops at 10 pages', async () => {
    const full = Array.from({ length: 12 }, () => ({ data: rows(1000), error: null }))
    const { client, ranges } = pagedClient(full)
    const r = await fetchSitemapEvents(client)
    expect(ranges).toHaveLength(10)
    expect(r.status === 'ok' && r.data.length).toBe(10_000)
  })
})

describe('callers: fall back only on "missing"', () => {
  beforeEach(() => {
    h.tables.length = 0
  })

  it('sitemap throws on a real error and does not read tables', async () => {
    h.mode = 'error'
    await expect(sitemap()).rejects.toThrow('sitemap_events failed')
    expect(h.tables).toEqual([])
  })

  it('homepage throws on a real error and does not read tables', async () => {
    h.mode = 'error'
    await expect(HomePage()).rejects.toThrow('home_preview failed')
    expect(h.tables).toEqual([])
  })

  it('sitemap still falls back to direct reads when the function is missing', async () => {
    h.mode = 'missing'
    const entries = await sitemap()
    expect(entries.length).toBeGreaterThanOrEqual(3)
    expect(h.tables).toContain('directory_events')
  })

  it('homepage still falls back to direct reads when the function is missing', async () => {
    h.mode = 'missing'
    await HomePage()
    expect(h.tables.length).toBeGreaterThan(0)
  })
})

describe('homepage mapping helpers', () => {
  it('sums raw specialties per parent (several raw values -> one parent)', () => {
    const raw = [
      { specialty: 'General Surgery', count: 10 },
      { specialty: 'Surgery', count: 5 },
      { specialty: 'Surgery (General)', count: 2 },
      { specialty: 'Cardiology', count: 4 },
    ]
    const sums = sumByParent(raw, (r) => canonicalSpecialty(r).parent)
    expect(sums['surgery-general']).toBe(17)
    expect(Object.values(sums).reduce((a, b) => a + b, 0)).toBe(21)
  })

  it('splits twelve month rows 6 / 6', () => {
    const rows = Array.from({ length: 12 }, (_, i) => i)
    const { visible, blurred } = splitTeaser(rows, 6)
    expect([visible.length, blurred.length]).toEqual([6, 6])
  })

  it('picks the top 8 societies by count, or the featured ones that exist', () => {
    const list = Array.from({ length: 12 }, (_, i) => ({ society: `S${i}`, count: i + 1 }))
    const top = pickSocieties(list)
    expect(top).toHaveLength(8)
    expect(top[0]).toEqual({ society: 'S11', count: 12 })
    const featured = pickSocieties(list, { featured: ['S2', 'Nope', 'S0'] })
    expect(featured.map((x) => x.society)).toEqual(['S2', 'S0'])
  })
})
