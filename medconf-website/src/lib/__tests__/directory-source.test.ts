// Fixture data must be unreachable in production unless explicitly enabled.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../directory-query', async (orig) => {
  const actual = await orig<typeof import('../directory-query')>()
  return { ...actual, queryDirectory: vi.fn(), queryFacets: vi.fn() }
})

import * as dq from '../directory-query'
import { fixtureAllowed, getSocietyNextDates, resolveDirectory, wantsFixture } from '../directory-source'

const sb = {} as never
const q = (s: string) => new URLSearchParams(s)
const livePage = { rows: [], total: 7, page: 1, pageSize: 30 }

beforeEach(() => {
  vi.mocked(dq.queryDirectory).mockReset()
  vi.mocked(dq.queryFacets).mockReset()
})
afterEach(() => {
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
})

describe('production gate', () => {
  it('production + ?fixture=1 is ignored and the live path runs', async () => {
    vi.stubEnv('NODE_ENV', 'production')
    vi.stubEnv('NEXT_PUBLIC_DIRECTORY_FIXTURE', '')
    vi.mocked(dq.queryDirectory).mockResolvedValue(livePage)
    const fixture = wantsFixture(q('fixture=1')) // old code: true -> fails here
    expect(fixture).toBe(false)
    const r = await resolveDirectory(sb, {}, { fixture, wantFacets: false })
    expect(r.usedFixture).toBe(false)
    expect(r.page.total).toBe(7)
  })

  it('production + missing view returns the empty result and logs console.error', async () => {
    vi.stubEnv('NODE_ENV', 'production')
    vi.stubEnv('NEXT_PUBLIC_DIRECTORY_FIXTURE', '')
    vi.mocked(dq.queryDirectory).mockRejectedValue(new Error('relation directory_events not found PGRST205'))
    vi.mocked(dq.queryFacets).mockResolvedValue(null as never)
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})
    const r = await resolveDirectory(sb, { page: 2, pageSize: 10 }, { fixture: false, wantFacets: true })
    // old code: usedFixture true with dummy rows, no console.error -> fails
    expect(r.usedFixture).toBe(false)
    expect(r.page).toEqual({ rows: [], total: 0, page: 2, pageSize: 10 })
    expect(err).toHaveBeenCalledWith('directory_events unavailable', expect.any(String))
  })

  it('production + missing view gives no society dates instead of fixture dates', async () => {
    vi.stubEnv('NODE_ENV', 'production')
    vi.stubEnv('NEXT_PUBLIC_DIRECTORY_FIXTURE', '')
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const failing = { from: () => { throw new Error('directory_events not found') } } as never
    expect(await getSocietyNextDates(failing, { fixture: false })).toEqual({}) // old code: fixture dates
  })

  it('development + ?fixture=1 uses the fixture', async () => {
    vi.stubEnv('NODE_ENV', 'development')
    expect(wantsFixture(q('fixture=1'))).toBe(true)
    const r = await resolveDirectory(sb, {}, { fixture: true, wantFacets: false })
    expect(r.usedFixture).toBe(true)
  })

  it('production with the env flag set allows the fixture', () => {
    vi.stubEnv('NODE_ENV', 'production')
    vi.stubEnv('NEXT_PUBLIC_DIRECTORY_FIXTURE', 'true')
    expect(fixtureAllowed()).toBe(true) // old code: export missing -> fails
    vi.stubEnv('NEXT_PUBLIC_DIRECTORY_FIXTURE', '1')
    expect(wantsFixture(q(''))).toBe(true)
  })
})

import { emptyDirectory, publicDirectoryError } from '../directory-source'
import { ilikeOrFilter } from '../directory-query'

describe('hardening', () => {
  it('production + flag "true" with no ?fixture serves the fixture (flag drift)', () => {
    vi.stubEnv('NODE_ENV', 'production')
    vi.stubEnv('NEXT_PUBLIC_DIRECTORY_FIXTURE', 'true')
    expect(wantsFixture(q(''))).toBe(true) // old: only "1" forced it
    vi.stubEnv('NEXT_PUBLIC_DIRECTORY_FIXTURE', ' TRUE ')
    expect(wantsFixture(q(''))).toBe(true)
  })

  it('api error body is opaque and the real error is logged server-side', () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})
    const r = publicDirectoryError({ message: 'relation "secret_table" does not exist' })
    expect(r).toEqual({ body: { error: 'directory_unavailable' }, status: 500 }) // old route leaked detail
    expect(JSON.stringify(r)).not.toContain('secret_table')
    expect(err).toHaveBeenCalled()
  })

  it('ilike fallback strips PostgREST structural characters from q', () => {
    const out = ilikeOrFilter('a,b(c)"\\d')
    const term = out.split(',')[0].replace('conference_name.ilike.%', '').replace(/%$/, '')
    expect(term).not.toMatch(/[,()"\\]/) // old: raw interpolation
    expect(out.split(',')).toHaveLength(3) // exactly the three intended clauses
  })

  it('emptyDirectory facets have exactly the keys of a live queryFacets result', async () => {
    // Keep in sync: DirectoryFacets in directory-query.ts.
    const { queryFacets } = await vi.importActual<typeof import('../directory-query')>('../directory-query')
    const live = await queryFacets({ rpc: async () => ({ data: {}, error: null }) } as never, {})
    expect(Object.keys(emptyDirectory({}, true).facets!).sort()).toEqual(Object.keys(live).sort())
  })
})
