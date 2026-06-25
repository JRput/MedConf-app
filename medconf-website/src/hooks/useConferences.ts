// src/hooks/useConferences.ts
'use client'

import { useState, useEffect, useMemo, useCallback } from 'react'
import { useRouter, useSearchParams, usePathname } from 'next/navigation'
import { createSupabaseClient } from '@/lib/supabase'
import { fetchAllPages } from '@/lib/fetch-pages'
import type { Conference, PricingTier, SourceSummary, CourseSession, EventType } from '@/lib/types'

export type SortMode = 'deadline' | 'date' | 'recently_added' | 'alphabetical'
export type TypeFilter = 'all' | 'conference' | 'course' | 'workshop' | 'on_demand'
// Sub-filter under the "Conferences" type. Splits live conferences into the
// flagship/major (Annual Conference / World Congress / etc) bucket and the
// regional/local bucket.
export type ConferenceScope = 'all' | 'major' | 'regional'

export interface Filters {
  specialty: string // '' means all
  region: string // '' means all
  maxPrice: number // 0 means no limit
  searchTerm: string
  // Filter by a single source (legacy) OR by a society (folds multiple
  // sources for the same organisation — e.g. all three RCEM sources —
  // into one chip). Exactly one is non-empty at a time; the chip click
  // handler keeps them mutually exclusive.
  sourceId: number | null
  society: string | null
  sort: SortMode
  eventType: TypeFilter // 'all' is the default
  // Only meaningful when eventType === 'conference'; ignored otherwise.
  conferenceScope: ConferenceScope
}

const DEFAULT_FILTERS: Filters = {
  specialty: '',
  region: '',
  maxPrice: 0,
  searchTerm: '',
  sourceId: null,
  society: null,
  sort: 'deadline',
  eventType: 'all',
  conferenceScope: 'all',
}

function readFiltersFromUrl(params: URLSearchParams): Filters {
  return {
    specialty: params.get('specialty') ?? '',
    region: params.get('region') ?? '',
    searchTerm: params.get('q') ?? '',
    maxPrice: Number(params.get('maxPrice') ?? '0') || 0,
    sourceId: params.get('source') ? Number(params.get('source')) : null,
    society: params.get('society') ?? null,
    sort: (params.get('sort') as SortMode) || 'deadline',
    eventType: (params.get('type') as TypeFilter) || 'all',
    conferenceScope: (params.get('scope') as ConferenceScope) || 'all',
  }
}

function writeFiltersToUrl(f: Filters): URLSearchParams {
  const p = new URLSearchParams()
  if (f.specialty) p.set('specialty', f.specialty)
  if (f.region) p.set('region', f.region)
  if (f.searchTerm) p.set('q', f.searchTerm)
  if (f.maxPrice > 0) p.set('maxPrice', String(f.maxPrice))
  if (f.sourceId !== null) p.set('source', String(f.sourceId))
  if (f.society) p.set('society', f.society)
  if (f.sort !== 'deadline') p.set('sort', f.sort)
  if (f.eventType !== 'all') p.set('type', f.eventType)
  if (f.eventType === 'conference' && f.conferenceScope !== 'all') p.set('scope', f.conferenceScope)
  return p
}

export function useConferences() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const supabase = createSupabaseClient()

  const [conferences, setConferences] = useState<Conference[]>([])
  const [pricingMap, setPricingMap] = useState<Record<number, PricingTier[]>>({})
  const [sessionsMap, setSessionsMap] = useState<Record<number, CourseSession[]>>({})
  const [sources, setSources] = useState<SourceSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [filters, setFiltersState] = useState<Filters>(() => ({
    ...DEFAULT_FILTERS,
    ...readFiltersFromUrl(new URLSearchParams(searchParams?.toString() ?? '')),
  }))

  // Re-sync filter state whenever the URL query string changes.
  // useState's initializer only runs ONCE, so without this effect a
  // notification click that targets /conferences?specialty=X (while the
  // route is already mounted/cached) would update the URL but leave the
  // filter state stuck at its previous value, dropping the user on the
  // unfiltered directory.
  const qs = searchParams?.toString() ?? ''
  useEffect(() => {
    const fromUrl = { ...DEFAULT_FILTERS, ...readFiltersFromUrl(new URLSearchParams(qs)) }
    setFiltersState(prev => {
      // Only replace when something actually differs — prevents an
      // infinite loop with the setFilters → router.replace → effect cycle.
      const keys = Object.keys(fromUrl) as (keyof Filters)[]
      const same = keys.every(k => prev[k] === fromUrl[k])
      return same ? prev : fromUrl
    })
  }, [qs])

  useEffect(() => {
    async function fetchData() {
      // Supabase enforces a server-side cap (db_max_rows = 1000) that
      // .range(0, 9999) silently truncates against. pricing_tiers has
      // already crossed 1000 with per-session course pricing, so we
      // paginate in chunks of 1000 to guarantee a complete fetch.
      const [confs, tiers, sessions, sourceResp] = await Promise.all([
        fetchAllPages<Conference>(() => supabase.from('conferences').select('*').eq('archived', false).order('start_date', { ascending: true })),
        fetchAllPages<PricingTier>(() => supabase.from('pricing_tiers').select('*')),
        fetchAllPages<CourseSession>(() => supabase.from('course_sessions').select('*').order('start_date', { ascending: true })),
        supabase.from('scraper_sources').select('id, source_name, base_url, society').eq('active', true).order('source_name'),
      ])

      setConferences(confs)

      const pMap: Record<number, PricingTier[]> = {}
      tiers.forEach(t => {
        if (!pMap[t.conference_id]) pMap[t.conference_id] = []
        pMap[t.conference_id].push(t)
      })
      setPricingMap(pMap)

      const sMap: Record<number, CourseSession[]> = {}
      sessions.forEach(s => {
        if (!sMap[s.course_id]) sMap[s.course_id] = []
        sMap[s.course_id].push(s)
      })
      setSessionsMap(sMap)

      if (sourceResp.data) setSources(sourceResp.data as SourceSummary[])

      setLoading(false)
    }

    fetchData()
  }, [])

  const setFilters = useCallback((next: Filters) => {
    setFiltersState(next)
    const p = writeFiltersToUrl(next)
    const qs = p.toString()
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
  }, [pathname, router])

  const sourceMap = useMemo(() => {
    const m: Record<number, string> = {}
    sources.forEach(s => { m[s.id] = s.source_name })
    return m
  }, [sources])

  const filtered = useMemo(() => {
    return conferences.filter(c => {
      if (filters.eventType === 'on_demand') {
        if (!c.is_on_demand) return false
      } else if (filters.eventType === 'conference') {
        if (c.event_type !== 'conference' || c.is_on_demand) return false
        if (filters.conferenceScope === 'major' && !c.is_flagship) return false
        if (filters.conferenceScope === 'regional' && c.is_flagship) return false
      } else if (filters.eventType !== 'all') {
        if (c.event_type !== filters.eventType) return false
      }
      if (filters.sourceId !== null && c.source_id !== filters.sourceId) return false
      if (filters.society) {
        const src = sources.find(s => s.id === c.source_id)
        if (!src || src.society !== filters.society) return false
      }
      if (filters.specialty && c.specialty?.toLowerCase() !== filters.specialty.toLowerCase()) return false
      if (filters.region && c.region?.toLowerCase() !== filters.region.toLowerCase()) return false

      if (filters.maxPrice > 0) {
        const tiers = pricingMap[c.id] || []
        const hasAffordableTier = tiers.some(t => t.price_gbp <= filters.maxPrice)
        if (tiers.length > 0 && !hasAffordableTier) return false
      }

      if (filters.searchTerm) {
        const term = filters.searchTerm.toLowerCase()
        const searchable = `${c.conference_name} ${c.specialty} ${c.city} ${c.description}`.toLowerCase()
        if (!searchable.includes(term)) return false
      }
      return true
    })
  }, [conferences, pricingMap, filters])

  const sorted = useMemo(() => {
    const arr = [...filtered]
    const veryHigh = '9999-12-31'
    arr.sort((a, b) => {
      switch (filters.sort) {
        case 'date':
          return (a.start_date ?? veryHigh).localeCompare(b.start_date ?? veryHigh)
        case 'recently_added':
          return (b.created_at ?? '').localeCompare(a.created_at ?? '')
        case 'alphabetical':
          return a.conference_name.localeCompare(b.conference_name)
        case 'deadline':
        default: {
          const aKey = a.abstract_deadline ?? veryHigh
          const bKey = b.abstract_deadline ?? veryHigh
          if (aKey !== bKey) return aKey.localeCompare(bKey)
          return (a.start_date ?? veryHigh).localeCompare(b.start_date ?? veryHigh)
        }
      }
    })
    return arr
  }, [filtered, filters.sort])

  return {
    conferences: sorted,
    allConferences: conferences,
    pricingMap,
    sessionsMap,
    sources,
    sourceMap,
    loading,
    filters,
    setFilters,
  }
}
