// src/app/conferences/page.tsx
'use client'

import { useMemo } from 'react'
import { useConferences, type SortMode, type TypeFilter } from '@/hooks/useConferences'
import { FilterPanel } from '@/components/conferences/FilterPanel'
import { SearchBar } from '@/components/conferences/SearchBar'
import { ConferenceCard } from '@/components/conferences/ConferenceCard'
import {
  Calendar, Loader2, FileText, Clock, Sparkles, SlidersHorizontal,
} from 'lucide-react'
import Link from 'next/link'
import { isAbstractEffectivelyOpen } from '@/lib/conference-helpers'

export default function ConferencesPage() {
  const {
    conferences,
    allConferences,
    pricingMap,
    sessionsMap,
    sources,
    sourceMap,
    loading,
    filters,
    setFilters,
  } = useConferences()

  // Live stats computed off the UNFILTERED set so the numbers don't
  // shrink when the user narrows the list.
  const stats = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10)
    const in14 = new Date(Date.now() + 14 * 86_400_000).toISOString().slice(0, 10)
    let abstractsOpen = 0
    let closingSoon = 0
    for (const c of allConferences) {
      if (isAbstractEffectivelyOpen(c)) abstractsOpen++
      if (c.abstract_deadline && c.abstract_deadline >= today && c.abstract_deadline <= in14) closingSoon++
    }
    return { total: allConferences.length, abstractsOpen, closingSoon }
  }, [allConferences])

  // "Closing soon" highlight strip: top 5 events with abstract deadline
  // in the next 14 days, sorted by soonest deadline first. Only shown
  // when the user hasn't applied any narrowing filters.
  const closingSoonItems = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10)
    const in14 = new Date(Date.now() + 14 * 86_400_000).toISOString().slice(0, 10)
    return allConferences
      .filter(c => c.abstract_deadline && c.abstract_deadline >= today && c.abstract_deadline <= in14)
      .sort((a, b) => (a.abstract_deadline ?? '').localeCompare(b.abstract_deadline ?? ''))
      .slice(0, 5)
  }, [allConferences])

  const hasActiveFilters = (
    filters.searchTerm.length > 0 ||
    filters.specialty !== '' ||
    filters.region !== '' ||
    filters.sourceId !== null ||
    filters.society !== null ||
    filters.maxPrice > 0
  )

  if (loading) {
    return (
      <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="w-8 h-8 text-cyan-400 animate-spin mx-auto mb-4" />
          <p className="text-slate-400 text-sm">Loading conferences...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-grid-pattern">
      <div className="fixed inset-0 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 -z-10" />

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Page header */}
        <div className="mb-6">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-cyan-500/20 to-teal-500/20 border border-cyan-500/30 flex items-center justify-center">
              <Calendar className="w-5 h-5 text-cyan-400" />
            </div>
            <h1 className="text-3xl font-bold text-white font-display">Conference directory</h1>
          </div>
          <p className="text-slate-400 ml-13">
            Browse upcoming medical conferences and CPD opportunities across the UK
          </p>
        </div>

        {/* Live stats bar */}
        <div className="grid grid-cols-3 gap-3 mb-6">
          <StatTile
            icon={Calendar}
            label="Conferences tracked"
            value={stats.total}
            tint="cyan"
            onClick={() => setFilters({ ...filters, specialty: '', region: '', sourceId: null, society: null, maxPrice: 0, searchTerm: '' })}
          />
          <StatTile
            icon={FileText}
            label="Abstracts open"
            value={stats.abstractsOpen}
            tint="emerald"
          />
          <StatTile
            icon={Clock}
            label="Closing in 14 days"
            value={stats.closingSoon}
            tint="amber"
          />
        </div>

        {/* Search */}
        <div className="mb-6">
          <SearchBar
            value={filters.searchTerm}
            onChange={v => setFilters({ ...filters, searchTerm: v })}
          />
        </div>

        {/* Source quick-select chips — folded by society, so e.g. the three
            RCEM sources (events, on-demand, Annual Conference) appear as a
            single chip rather than three. Sources without a society tag
            fall back to their own chip. */}
        {sources.length > 1 && (() => {
          const seen = new Set<string>()
          const chips: { key: string; label: string; isSociety: boolean; sourceId: number | null; count: number }[] = []
          for (const s of sources) {
            const sourceCount = allConferences.filter(c => c.source_id === s.id).length
            if (s.society) {
              if (seen.has(s.society)) {
                const existing = chips.find(c => c.isSociety && c.label === s.society)
                if (existing) existing.count += sourceCount
                continue
              }
              seen.add(s.society)
              chips.push({ key: `soc:${s.society}`, label: s.society, isSociety: true, sourceId: null, count: sourceCount })
            } else {
              chips.push({ key: `src:${s.id}`, label: s.source_name, isSociety: false, sourceId: s.id, count: sourceCount })
            }
          }
          const allActive = filters.sourceId === null && filters.society === null
          return (
            <div className="mb-6 flex flex-wrap gap-2 items-center">
              <span className="text-xs uppercase tracking-wider text-slate-500 font-semibold mr-1">
                Source:
              </span>
              <button
                onClick={() => setFilters({ ...filters, sourceId: null, society: null })}
                className={`text-sm px-3.5 py-1.5 rounded-full border transition-all ${
                  allActive
                    ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/50'
                    : 'bg-slate-800/40 text-slate-300 border-slate-700 hover:border-slate-600'
                }`}
              >
                All
              </button>
              {chips.map(chip => {
                const active = chip.isSociety
                  ? filters.society === chip.label
                  : filters.sourceId === chip.sourceId
                return (
                  <button
                    key={chip.key}
                    onClick={() => setFilters({
                      ...filters,
                      society: active ? null : (chip.isSociety ? chip.label : null),
                      sourceId: active ? null : (chip.isSociety ? null : chip.sourceId),
                    })}
                    className={`text-sm px-3.5 py-1.5 rounded-full border transition-all ${
                      active
                        ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/50'
                        : 'bg-slate-800/40 text-slate-300 border-slate-700 hover:border-slate-600'
                    }`}
                  >
                    {chip.label}
                    <span className="ml-1.5 text-slate-500">· {chip.count}</span>
                  </button>
                )
              })}
            </div>
          )
        })()}

        {/* Type filter chips — Conference vs Course vs All */}
        <div className="mb-6 flex flex-wrap gap-2 items-center">
          <span className="text-xs uppercase tracking-wider text-slate-500 font-semibold mr-1">
            Type:
          </span>
          {(['all', 'conference', 'course', 'workshop', 'on_demand'] as TypeFilter[]).map(t => {
            const label = t === 'all' ? 'All'
              : t === 'conference' ? 'Conferences'
              : t === 'course' ? 'Courses'
              : t === 'workshop' ? 'Workshops'
              : 'On-Demand'
            const count = t === 'all'
              ? allConferences.length
              : t === 'on_demand'
                ? allConferences.filter(c => c.is_on_demand).length
                : allConferences.filter(c => c.event_type === t && !c.is_on_demand).length
            return (
              <button
                key={t}
                onClick={() => setFilters({ ...filters, eventType: t, conferenceScope: 'all' })}
                className={`text-sm px-3.5 py-1.5 rounded-full border transition-all ${
                  filters.eventType === t
                    ? 'bg-violet-500/20 text-violet-200 border-violet-500/50'
                    : 'bg-slate-800/40 text-slate-300 border-slate-700 hover:border-slate-600'
                }`}
              >
                {label} <span className="text-slate-500">· {count}</span>
              </button>
            )
          })}
        </div>

        {/* Conference sub-filter — only shown when the "Conferences" type
            chip is selected. Splits live conferences into international/
            national flagships and regional/local events. */}
        {filters.eventType === 'conference' && (
          <div className="mb-6 -mt-3 flex flex-wrap gap-2 items-center pl-3 border-l-2 border-violet-500/30">
            <span className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mr-1">
              Scope:
            </span>
            {(['all', 'major', 'regional'] as const).map(s => {
              const label = s === 'all' ? 'All conferences'
                : s === 'major' ? 'International / National'
                : 'Regional / Local'
              const count = s === 'all'
                ? allConferences.filter(c => c.event_type === 'conference' && !c.is_on_demand).length
                : s === 'major'
                  ? allConferences.filter(c => c.event_type === 'conference' && c.is_flagship && !c.is_on_demand).length
                  : allConferences.filter(c => c.event_type === 'conference' && !c.is_flagship && !c.is_on_demand).length
              return (
                <button
                  key={s}
                  onClick={() => setFilters({ ...filters, conferenceScope: s })}
                  className={`text-xs px-3 py-1 rounded-full border transition-all ${
                    filters.conferenceScope === s
                      ? 'bg-yellow-500/15 text-yellow-300 border-yellow-500/40'
                      : 'bg-slate-800/40 text-slate-300 border-slate-700 hover:border-slate-600'
                  }`}
                >
                  {label} <span className="text-slate-500">· {count}</span>
                </button>
              )
            })}
          </div>
        )}

        <div className="flex flex-col lg:flex-row gap-6">
          {/* Sidebar filters */}
          <div className="w-full lg:w-80 shrink-0">
            <FilterPanel filters={filters} setFilters={setFilters} sources={sources} />
          </div>

          {/* Main column */}
          <div className="flex-1">
            {/* Closing-soon highlight strip — only shown when no filter is active */}
            {!hasActiveFilters && closingSoonItems.length > 0 && (
              <section className="mb-8">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-amber-400 flex items-center gap-2">
                    <Clock className="w-4 h-4" />
                    Closing soon
                  </h2>
                  <span className="text-xs text-slate-500">Abstract deadlines in next 14 days</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                  {closingSoonItems.map(c => (
                    <ConferenceCard
                      key={c.id}
                      conference={c}
                      tiers={pricingMap[c.id] || []}
                      sessions={sessionsMap[c.id]}
                      sourceName={c.source_id ? sourceMap[c.source_id] : null}
                    />
                  ))}
                </div>
              </section>
            )}

            {/* Count + sort */}
            <div className="flex items-center justify-between mb-4">
              <p className="text-sm text-slate-400">
                <span className="text-white font-semibold">{conferences.length}</span>{' '}
                conference{conferences.length !== 1 ? 's' : ''} found
                {hasActiveFilters && <span className="text-slate-500 ml-2">— filtered</span>}
              </p>
              <div className="flex items-center gap-2">
                <SlidersHorizontal className="w-4 h-4 text-slate-500" />
                <select
                  value={filters.sort}
                  onChange={e => setFilters({ ...filters, sort: e.target.value as SortMode })}
                  className="bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white px-3 py-2 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all appearance-none cursor-pointer"
                >
                  <option value="deadline" className="bg-slate-800">Deadline soonest</option>
                  <option value="date" className="bg-slate-800">Conference date</option>
                  <option value="recently_added" className="bg-slate-800">Recently added</option>
                  <option value="alphabetical" className="bg-slate-800">Alphabetical</option>
                </select>
              </div>
            </div>

            {conferences.length === 0 ? (
              <div className="glass-card rounded-xl p-12 text-center">
                <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-slate-800/50 flex items-center justify-center">
                  <Sparkles className="w-8 h-8 text-slate-500" />
                </div>
                <p className="text-slate-400 mb-2">No conferences match your filters</p>
                <p className="text-slate-500 text-sm mb-6">Try adjusting your search or filters</p>
                {hasActiveFilters && (
                  <button
                    onClick={() => setFilters({ specialty: '', region: '', maxPrice: 0, searchTerm: '', sourceId: null, society: null, sort: filters.sort, eventType: 'all', conferenceScope: 'all' })}
                    className="inline-flex items-center gap-2 text-sm text-cyan-400 hover:text-cyan-300"
                  >
                    Clear all filters
                  </button>
                )}
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {conferences.map(c => (
                  <ConferenceCard
                    key={c.id}
                    conference={c}
                    tiers={pricingMap[c.id] || []}
                    sessions={sessionsMap[c.id]}
                    sourceName={c.source_id ? sourceMap[c.source_id] : null}
                    showNewBadge={filters.sort === 'recently_added'}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function StatTile({
  icon: Icon, label, value, tint, onClick,
}: {
  icon: typeof Calendar
  label: string
  value: number
  tint: 'cyan' | 'amber' | 'emerald'
  onClick?: () => void
}) {
  const tints = {
    cyan: 'text-cyan-400 hover:border-cyan-500/40',
    amber: 'text-amber-400 hover:border-amber-500/40',
    emerald: 'text-emerald-400 hover:border-emerald-500/40',
  }
  const cls = `glass-card rounded-xl p-4 border border-slate-800 transition-all ${tints[tint]} ${onClick ? 'cursor-pointer' : ''}`
  const Inner = (
    <div className="flex items-center justify-between">
      <div>
        <p className="text-xs text-slate-400">{label}</p>
        <p className="text-2xl font-bold text-white mt-1">{value}</p>
      </div>
      <Icon className={`w-5 h-5 ${tints[tint].split(' ')[0]}`} />
    </div>
  )
  return onClick ? <button className={`${cls} text-left w-full`} onClick={onClick}>{Inner}</button> : <div className={cls}>{Inner}</div>
}
