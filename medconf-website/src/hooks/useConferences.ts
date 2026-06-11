// src/hooks/useConferences.ts
'use client'

import { useState, useEffect, useMemo, useCallback } from 'react'
import { useRouter, useSearchParams, usePathname } from 'next/navigation'
import { createSupabaseClient } from '@/lib/supabase'
import type { Conference, PricingTier, SourceSummary, CourseSession, EventType } from '@/lib/types'

export type SortMode = 'deadline' | 'date' | 'recently_added' | 'alphabetical'
export type TypeFilter = 'all' | 'conference' | 'course'

export interface Filters {
  specialty: string // '' means all
  region: string // '' means all
  maxPrice: number // 0 means no limit
  searchTerm: string
  sourceId: number | null // null means all sources
  sort: SortMode
  eventType: TypeFilter // 'all' is the default
}

const DEFAULT_FILTERS: Filters = {
  specialty: '',
  region: '',
  maxPrice: 0,
  searchTerm: '',
  sourceId: null,
  sort: 'deadline',
  eventType: 'all',
}

function readFiltersFromUrl(params: URLSearchParams): Filters {
  return {
    specialty: params.get('specialty') ?? '',
    region: params.get('region') ?? '',
    searchTerm: params.get('q') ?? '',
    maxPrice: Number(params.get('maxPrice') ?? '0') || 0,
    sourceId: params.get('source') ? Number(params.get('source')) : null,
    sort: (params.get('sort') as SortMode) || 'deadline',
    eventType: (params.get('type') as TypeFilter) || 'all',
  }
}

function writeFiltersToUrl(f: Filters): URLSearchParams {
  const p = new URLSearchParams()
  if (f.specialty) p.set('specialty', f.specialty)
  if (f.region) p.set('region', f.region)
  if (f.searchTerm) p.set('q', f.searchTerm)
  if (f.maxPrice > 0) p.set('maxPrice', String(f.maxPrice))
  if (f.sourceId !== null) p.set('source', String(f.sourceId))
  if (f.sort !== 'deadline') p.set('sort', f.sort)
  if (f.eventType !== 'all') p.set('type', f.eventType)
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

  useEffect(() => {
    async function fetchData() {
      const [confResp, tierResp, sessionResp, sourceResp] = await Promise.all([
        supabase.from('conferences').select('*').eq('archived', false).order('start_date', { ascending: true }),
        supabase.from('pricing_tiers').select('*'),
        supabase.from('course_sessions').select('*').order('start_date', { ascending: true }),
        supabase.from('scraper_sources').select('id, source_name, base_url').eq('active', true).order('source_name'),
      ])

      if (confResp.data) setConferences(confResp.data)

      if (tierResp.data) {
        const map: Record<number, PricingTier[]> = {}
        tierResp.data.forEach(t => {
          if (!map[t.conference_id]) map[t.conference_id] = []
          map[t.conference_id].push(t)
        })
        setPricingMap(map)
      }

      if (sessionResp.data) {
        const map: Record<number, CourseSession[]> = {}
        sessionResp.data.forEach(s => {
          if (!map[s.course_id]) map[s.course_id] = []
          map[s.course_id].push(s)
        })
        setSessionsMap(map)
      }

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
      if (filters.eventType !== 'all' && c.event_type !== filters.eventType) return false
      if (filters.sourceId !== null && c.source_id !== filters.sourceId) return false
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
