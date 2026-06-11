// src/app/saved/page.tsx
'use client'

import { useState, useEffect, useMemo } from 'react'
import { createSupabaseClient } from '@/lib/supabase'
import { ConferenceCard } from '@/components/conferences/ConferenceCard'
import type { Conference, PricingTier, CourseSession } from '@/lib/types'
import { fetchAllPages } from '@/lib/fetch-pages'
import { useAuth } from '@/hooks/useAuth'
import { Bookmark, Loader2, Calendar, SlidersHorizontal } from 'lucide-react'
import Link from 'next/link'

type FilterMode = 'upcoming' | 'past' | 'sold_out' | 'all'
type SortMode = 'date_asc' | 'date_desc' | 'deadline_asc' | 'specialty' | 'recently_saved'

interface SavedRow {
  conference_id: number
  saved_at: string
}

export default function SavedPage() {
  const [conferences, setConferences] = useState<Conference[]>([])
  const [pricingMap, setPricingMap] = useState<Record<number, PricingTier[]>>({})
  const [sessionsMap, setSessionsMap] = useState<Record<number, CourseSession[]>>({})
  const [sourceMap, setSourceMap] = useState<Record<number, string>>({})
  const [savedAtMap, setSavedAtMap] = useState<Record<number, string>>({})
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<FilterMode>('upcoming')
  const [sort, setSort] = useState<SortMode>('date_asc')
  const { user } = useAuth()
  const supabase = createSupabaseClient()

  useEffect(() => {
    if (!user) return

    async function fetchSaved() {
      const { data: saved } = await supabase
        .from('saved_conferences')
        .select('conference_id, saved_at')
        .eq('user_id', user!.id)

      if (!saved || saved.length === 0) {
        setLoading(false)
        return
      }

      const ids = saved.map((s: SavedRow) => s.conference_id)
      const savedAt: Record<number, string> = {}
      saved.forEach((s: SavedRow) => { savedAt[s.conference_id] = s.saved_at })
      setSavedAtMap(savedAt)

      // Paginate against the Supabase 1000-row cap (see lib/fetch-pages).
      const [confs, tiers, sess, sourceResp] = await Promise.all([
        fetchAllPages<Conference>(() => supabase.from('conferences').select('*').in('id', ids)),
        fetchAllPages<PricingTier>(() => supabase.from('pricing_tiers').select('*').in('conference_id', ids)),
        fetchAllPages<CourseSession>(() => supabase.from('course_sessions').select('*').in('course_id', ids).order('start_date', { ascending: true })),
        supabase.from('scraper_sources').select('id, source_name').eq('active', true),
      ])

      setConferences(confs)

      const pMap: Record<number, PricingTier[]> = {}
      tiers.forEach(t => {
        if (!pMap[t.conference_id]) pMap[t.conference_id] = []
        pMap[t.conference_id].push(t)
      })
      setPricingMap(pMap)

      const sMap: Record<number, CourseSession[]> = {}
      sess.forEach(s => {
        if (!sMap[s.course_id]) sMap[s.course_id] = []
        sMap[s.course_id].push(s)
      })
      setSessionsMap(sMap)

      if (sourceResp.data) {
        const sm: Record<number, string> = {}
        sourceResp.data.forEach(s => { sm[s.id] = s.source_name })
        setSourceMap(sm)
      }

      setLoading(false)
    }

    fetchSaved()
  }, [user, supabase])

  const today = useMemo(() => new Date().toISOString().slice(0, 10), [])

  // Apply filter
  const filtered = useMemo(() => {
    if (filter === 'all') return conferences
    if (filter === 'sold_out') return conferences.filter(c => c.is_sold_out)
    if (filter === 'past') return conferences.filter(c => c.start_date && c.start_date < today)
    // upcoming: start_date >= today OR start_date is null (treat unknown as upcoming)
    return conferences.filter(c => !c.start_date || c.start_date >= today)
  }, [conferences, filter, today])

  // Apply sort
  const sorted = useMemo(() => {
    const arr = [...filtered]
    arr.sort((a, b) => {
      switch (sort) {
        case 'date_asc':
          return (a.start_date ?? '9999').localeCompare(b.start_date ?? '9999')
        case 'date_desc':
          return (b.start_date ?? '0000').localeCompare(a.start_date ?? '0000')
        case 'deadline_asc':
          return (a.abstract_deadline ?? '9999').localeCompare(b.abstract_deadline ?? '9999')
        case 'specialty':
          return (a.specialty ?? '~').localeCompare(b.specialty ?? '~')
        case 'recently_saved':
          return (savedAtMap[b.id] ?? '').localeCompare(savedAtMap[a.id] ?? '')
      }
    })
    return arr
  }, [filtered, sort, savedAtMap])

  // Group by month when sorted by date
  const groups = useMemo(() => {
    const byDate = sort === 'date_asc' || sort === 'date_desc'
    if (!byDate) return [{ label: null, items: sorted }]
    const map = new Map<string, Conference[]>()
    sorted.forEach(c => {
      const key = c.start_date
        ? new Date(c.start_date).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })
        : 'Date TBC'
      const list = map.get(key) ?? []
      list.push(c)
      map.set(key, list)
    })
    return Array.from(map.entries()).map(([label, items]) => ({ label, items }))
  }, [sorted, sort])

  if (loading) {
    return (
      <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="w-8 h-8 text-cyan-400 animate-spin mx-auto mb-4" />
          <p className="text-slate-400 text-sm">Loading saved conferences…</p>
        </div>
      </div>
    )
  }

  const totalSaved = conferences.length
  const counts = {
    upcoming: conferences.filter(c => !c.start_date || c.start_date >= today).length,
    past: conferences.filter(c => c.start_date && c.start_date < today).length,
    sold_out: conferences.filter(c => c.is_sold_out).length,
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-grid-pattern">
      <div className="fixed inset-0 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 -z-10" />

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-rose-500/20 to-pink-500/20 border border-rose-500/30 flex items-center justify-center">
              <Bookmark className="w-5 h-5 text-rose-400" />
            </div>
            <h1 className="text-3xl font-bold text-white font-display">Saved conferences</h1>
          </div>
          <p className="text-slate-400 ml-13">
            {totalSaved === 0
              ? 'Conferences you save will appear here.'
              : `${totalSaved} saved conference${totalSaved === 1 ? '' : 's'}`}
          </p>
        </div>

        {totalSaved === 0 ? (
          <div className="glass-card rounded-xl p-12 text-center max-w-xl mx-auto">
            <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-slate-800/50 flex items-center justify-center">
              <Bookmark className="w-8 h-8 text-slate-500" />
            </div>
            <h2 className="text-lg font-semibold text-white mb-2">No saved conferences yet</h2>
            <p className="text-slate-400 mb-6">
              Browse the directory and click the save button on conferences you&apos;re interested in.
            </p>
            <Link
              href="/conferences"
              className="inline-flex items-center gap-2 bg-gradient-to-r from-cyan-500 to-teal-500 text-white px-6 py-3 rounded-xl font-semibold hover:from-cyan-400 hover:to-teal-400 transition-all shadow-lg shadow-cyan-500/25"
            >
              <Calendar className="w-4 h-4" />
              Browse conferences
            </Link>
          </div>
        ) : (
          <>
            {/* Filter + sort row */}
            <div className="flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between mb-6">
              <div className="flex flex-wrap gap-2">
                <FilterChip label={`Upcoming (${counts.upcoming})`} active={filter === 'upcoming'} onClick={() => setFilter('upcoming')} />
                <FilterChip label={`Past (${counts.past})`} active={filter === 'past'} onClick={() => setFilter('past')} />
                <FilterChip label={`Sold out (${counts.sold_out})`} active={filter === 'sold_out'} onClick={() => setFilter('sold_out')} />
                <FilterChip label={`All (${totalSaved})`} active={filter === 'all'} onClick={() => setFilter('all')} />
              </div>

              <div className="flex items-center gap-2">
                <SlidersHorizontal className="w-4 h-4 text-slate-500" />
                <select
                  value={sort}
                  onChange={e => setSort(e.target.value as SortMode)}
                  className="bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white px-3 py-2 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all appearance-none cursor-pointer"
                >
                  <option value="date_asc" className="bg-slate-800">Date (soonest)</option>
                  <option value="date_desc" className="bg-slate-800">Date (latest)</option>
                  <option value="deadline_asc" className="bg-slate-800">Abstract deadline</option>
                  <option value="specialty" className="bg-slate-800">Specialty</option>
                  <option value="recently_saved" className="bg-slate-800">Recently saved</option>
                </select>
              </div>
            </div>

            {sorted.length === 0 ? (
              <div className="glass-card rounded-xl p-10 text-center">
                <p className="text-slate-400">
                  No saved conferences match this filter.
                </p>
              </div>
            ) : (
              <div className="space-y-8">
                {groups.map(group => (
                  <div key={group.label ?? 'all'}>
                    {group.label && (
                      <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-500 mb-3 border-b border-slate-800 pb-2">
                        {group.label} <span className="text-slate-600">· {group.items.length}</span>
                      </h2>
                    )}
                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                      {group.items.map(c => (
                        <ConferenceCard
                          key={c.id}
                          conference={c}
                          tiers={pricingMap[c.id] || []}
                          sessions={sessionsMap[c.id]}
                          sourceName={c.source_id ? sourceMap[c.source_id] : null}
                        />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function FilterChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`text-sm px-3 py-1.5 rounded-lg border transition-all ${
        active
          ? 'bg-cyan-500/15 border-cyan-500/50 text-cyan-300 font-medium'
          : 'bg-slate-800/50 border-slate-700 text-slate-400 hover:text-white hover:border-slate-600'
      }`}
    >
      {label}
    </button>
  )
}
