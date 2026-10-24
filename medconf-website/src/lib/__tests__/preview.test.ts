import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchEventPreview, fetchHomePreview, fetchSitemapEvents, NOT_FOUND, resetPreviewWarnings, type RpcClient } from '../preview'
import { canonicalSpecialty } from '../taxonomy/specialties'
import { pickSocieties, splitTeaser, sumByParent } from '../home-teaser'

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
  it('return the typed payload on success and pass the id', async () => {
    const calls: Array<[string, unknown]> = []
    const client: RpcClient = {
      rpc: async (fn, args) => {
        calls.push([fn, args])
        return { data: fn === 'sitemap_events' ? [{ id: 1, updated_at: null }] : { id: 7 }, error: null }
      },
    }
    expect(await fetchHomePreview(client)).toEqual({ id: 7 })
    expect(await fetchEventPreview(client, 7)).toEqual({ id: 7 })
    expect(await fetchSitemapEvents(client)).toEqual([{ id: 1, updated_at: null }])
    expect(calls[1]).toEqual(['event_preview', { p_id: 7 }])
  })

  it('returns null and warns once per function on PGRST202', async () => {
    const c = fail('PGRST202')
    expect(await fetchHomePreview(c)).toBeNull()
    expect(await fetchHomePreview(c)).toBeNull()
    expect(await fetchEventPreview(c, 1)).toBeNull()
    expect(await fetchSitemapEvents(c)).toBeNull()
    expect(warn).toHaveBeenCalledTimes(3)
    expect(warn.mock.calls[0][0]).toBe('[preview] home_preview missing — falling back to direct reads')
    expect(err).not.toHaveBeenCalled()
  })

  it('returns null (never throws) and console.errors on other codes or a thrown client', async () => {
    expect(await fetchHomePreview(fail('42501'))).toBeNull()
    expect(await fetchSitemapEvents({ rpc: async () => { throw new Error('boom') } })).toBeNull()
    expect(err).toHaveBeenCalledTimes(2)
    expect(warn).not.toHaveBeenCalled()
  })

  it('event_preview distinguishes "no such event" from "function missing"', async () => {
    expect(await fetchEventPreview(ok(null), 9)).toBe(NOT_FOUND)
    expect(await fetchEventPreview(fail('PGRST202'), 9)).toBeNull()
  })

  it('rejects a non-array sitemap payload', async () => {
    expect(await fetchSitemapEvents(ok({ nope: true }))).toBeNull()
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
