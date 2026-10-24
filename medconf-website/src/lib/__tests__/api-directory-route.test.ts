import { beforeEach, describe, expect, it, vi } from 'vitest'

const h = vi.hoisted(() => ({
  getUser: vi.fn(),
  resolveDirectory: vi.fn(),
  setAllCookies: [] as { name: string; value: string; options?: object }[],
}))

vi.mock('next/headers', () => ({ cookies: async () => ({ getAll: () => [] }) }))
vi.mock('@supabase/ssr', () => ({
  createServerClient: (_u: string, _k: string, opts: { cookies: { setAll: (c: unknown[]) => void } }) => ({
    auth: {
      getUser: async () => {
        // Simulate @supabase/ssr refreshing the session during getUser().
        if (h.setAllCookies.length) opts.cookies.setAll(h.setAllCookies)
        return h.getUser()
      },
    },
  }),
}))
vi.mock('@/lib/directory-source', async (orig) => ({
  ...(await orig<typeof import('@/lib/directory-source')>()),
  resolveDirectory: h.resolveDirectory,
}))

import { GET } from '@/app/api/directory/route'

const req = () => new Request('http://localhost/api/directory?pageSize=5')

beforeEach(() => {
  h.getUser.mockReset()
  h.resolveDirectory.mockReset()
  h.setAllCookies.length = 0
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'http://supabase.test'
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'anon'
})

describe('GET /api/directory', () => {
  it('401s with no user and never reads the directory', async () => {
    h.getUser.mockResolvedValue({ data: { user: null }, error: null })
    const res = await GET(req())
    expect(res.status).toBe(401)
    expect(await res.json()).toEqual({ error: 'sign_in_required' })
    expect(res.headers.get('cache-control')).toBe('private, no-store')
    expect(h.resolveDirectory).not.toHaveBeenCalled()
  })

  it('200s for a signed-in user with a private, revalidating cache header', async () => {
    h.getUser.mockResolvedValue({ data: { user: { id: 'u1' } }, error: null })
    h.resolveDirectory.mockResolvedValue({ page: { rows: [], total: 0, page: 1, pageSize: 5 }, facets: null, usedFixture: false })
    const res = await GET(req())
    expect(res.status).toBe(200)
    expect(res.headers.get('cache-control')).toBe('private, max-age=0, must-revalidate')
    expect(h.resolveDirectory).toHaveBeenCalledTimes(1)
  })

  it('writes refreshed session cookies onto both the 200 and the 401', async () => {
    h.setAllCookies.push({ name: 'sb-token', value: 'refreshed', options: { path: '/' } })
    h.getUser.mockResolvedValue({ data: { user: { id: 'u1' } }, error: null })
    h.resolveDirectory.mockResolvedValue({ page: { rows: [], total: 0, page: 1, pageSize: 5 }, facets: null, usedFixture: false })
    const ok = await GET(req())
    expect(ok.cookies.get('sb-token')?.value).toBe('refreshed')

    h.getUser.mockResolvedValue({ data: { user: null }, error: null })
    const denied = await GET(req())
    expect(denied.status).toBe(401)
    expect(denied.cookies.get('sb-token')?.value).toBe('refreshed')
  })
})
