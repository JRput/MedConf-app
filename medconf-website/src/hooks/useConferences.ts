// src/hooks/useConferences.ts
'use client'

import { useState, useEffect, useMemo } from 'react'
import { createSupabaseClient } from '@/lib/supabase'
import type { Conference, PricingTier, SourceSummary } from '@/lib/types'

export interface Filters {
  specialty: string // '' means all
  region: string // '' means all
  maxPrice: number // 0 means no limit
  searchTerm: string
  sourceId: number | null // null means all sources
}

export function useConferences() {
  const [conferences, setConferences] = useState<Conference[]>([])
  const [pricingMap, setPricingMap] = useState<Record<number, PricingTier[]>>({})
  const [sources, setSources] = useState<SourceSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState<Filters>({
    specialty: '', region: '', maxPrice: 0, searchTerm: '', sourceId: null
  })
  const supabase = createSupabaseClient()

  useEffect(() => {
    async function fetchData() {
      // Fetch in parallel
      const [confResp, tierResp, sourceResp] = await Promise.all([
        supabase.from('conferences').select('*').eq('archived', false).order('start_date', { ascending: true }),
        supabase.from('pricing_tiers').select('*'),
        supabase.from('scraper_sources').select('id, source_name, base_url').eq('active', true).order('source_name'),
      ])

      if (confResp.data) setConferences(confResp.data)

      // Build a map: conference_id -> [tiers]
      if (tierResp.data) {
        const map: Record<number, PricingTier[]> = {}
        tierResp.data.forEach(t => {
          if (!map[t.conference_id]) map[t.conference_id] = []
          map[t.conference_id].push(t)
        })
        setPricingMap(map)
      }

      if (sourceResp.data) setSources(sourceResp.data as SourceSummary[])

      setLoading(false)
    }

    fetchData()
  }, [])

  // Build a quick lookup for cards: source_id -> source_name
  const sourceMap = useMemo(() => {
    const m: Record<number, string> = {}
    sources.forEach(s => { m[s.id] = s.source_name })
    return m
  }, [sources])

  // Filtering logic — runs client-side on the fetched data
  const filtered = useMemo(() => {
    return conferences.filter(c => {
      // Source filter
      if (filters.sourceId !== null && c.source_id !== filters.sourceId) return false

      // Specialty filter
      if (filters.specialty && c.specialty?.toLowerCase() !== filters.specialty.toLowerCase()) return false

      // Region filter
      if (filters.region && c.region?.toLowerCase() !== filters.region.toLowerCase()) return false

      // Price filter — checks if ANY tier is under the max
      if (filters.maxPrice > 0) {
        const tiers = pricingMap[c.id] || []
        const hasAffordableTier = tiers.some(t => t.price_gbp <= filters.maxPrice)
        if (tiers.length > 0 && !hasAffordableTier) return false
      }

      // Search filter — matches name, specialty, city, or description
      if (filters.searchTerm) {
        const term = filters.searchTerm.toLowerCase()
        const searchable = `${c.conference_name} ${c.specialty} ${c.city} ${c.description}`.toLowerCase()
        if (!searchable.includes(term)) return false
      }

      return true
    })
  }, [conferences, pricingMap, filters])

  return { conferences: filtered, pricingMap, sources, sourceMap, loading, filters, setFilters }
}


