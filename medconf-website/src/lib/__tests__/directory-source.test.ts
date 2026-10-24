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
