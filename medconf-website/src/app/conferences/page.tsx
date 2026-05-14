// src/app/conferences/page.tsx
'use client'

import { useConferences } from '@/hooks/useConferences'
import { FilterPanel } from '@/components/conferences/FilterPanel'
import { SearchBar } from '@/components/conferences/SearchBar'
import { ConferenceCard } from '@/components/conferences/ConferenceCard'
import { Calendar, Loader2 } from 'lucide-react'

export default function ConferencesPage() {
  const { conferences, pricingMap, sources, sourceMap, loading, filters, setFilters } = useConferences()

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
      {/* Background */}
      <div className="fixed inset-0 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 -z-10" />
      
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Page header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-cyan-500/20 to-teal-500/20 border border-cyan-500/30 flex items-center justify-center">
              <Calendar className="w-5 h-5 text-cyan-400" />
            </div>
            <h1 className="text-3xl font-bold text-white font-display">Conference Directory</h1>
          </div>
          <p className="text-slate-400 ml-13">
            Browse upcoming medical conferences and CPD opportunities across the UK
          </p>
        </div>

        {/* Search */}
        <div className="mb-6">
          <SearchBar
            value={filters.searchTerm}
            onChange={v => setFilters({ ...filters, searchTerm: v })}
          />
        </div>

        {/* Source quick-select chip row (Pattern A) — mirrors the sidebar Source filter */}
        {sources.length > 1 && (
          <div className="mb-6 flex flex-wrap gap-2 items-center">
            <span className="text-xs uppercase tracking-wider text-slate-500 font-semibold mr-1">
              Source:
            </span>
            <button
              onClick={() => setFilters({ ...filters, sourceId: null })}
              className={`text-sm px-3.5 py-1.5 rounded-full border transition-all ${
                filters.sourceId === null
                  ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/50'
                  : 'bg-slate-800/40 text-slate-300 border-slate-700 hover:border-slate-600'
              }`}
            >
              All
            </button>
            {sources.map(s => (
              <button
                key={s.id}
                onClick={() => setFilters({ ...filters, sourceId: filters.sourceId === s.id ? null : s.id })}
                className={`text-sm px-3.5 py-1.5 rounded-full border transition-all ${
                  filters.sourceId === s.id
                    ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/50'
                    : 'bg-slate-800/40 text-slate-300 border-slate-700 hover:border-slate-600'
                }`}
              >
                {s.source_name}
              </button>
            ))}
          </div>
        )}

        <div className="flex flex-col lg:flex-row gap-6">
          {/* Sidebar filters */}
          <div className="w-full lg:w-80 shrink-0">
            <FilterPanel filters={filters} setFilters={setFilters} sources={sources} />
          </div>

          {/* Conference grid */}
          <div className="flex-1">
            <p className="text-sm text-slate-400 mb-4">
              <span className="text-white font-semibold">{conferences.length}</span> conference{conferences.length !== 1 ? 's' : ''} found
            </p>

            {conferences.length === 0 ? (
              <div className="glass-card rounded-xl p-12 text-center">
                <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-slate-800/50 flex items-center justify-center">
                  <Calendar className="w-8 h-8 text-slate-500" />
                </div>
                <p className="text-slate-400 mb-2">No conferences match your filters</p>
                <p className="text-slate-500 text-sm">Try adjusting your search or filters</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {conferences.map(c => (
                  <ConferenceCard
                    key={c.id}
                    conference={c}
                    tiers={pricingMap[c.id] || []}
                    sourceName={c.source_id ? sourceMap[c.source_id] : null}
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


