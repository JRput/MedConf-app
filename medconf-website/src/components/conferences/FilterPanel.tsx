// src/components/conferences/FilterPanel.tsx
'use client'

import type { Filters } from '@/hooks/useConferences'
import type { SourceSummary } from '@/lib/types'
import { Filter, X, Stethoscope, MapPin, PoundSterling, Building2 } from 'lucide-react'

const SPECIALTIES = [
  'All', 'Cardiology', 'General Practice', 'Orthopaedics', 'General Surgery', 'Emergency Medicine',
  'Neurology', 'Oncology', 'Paediatrics', 'Psychiatry', 'Radiology', 'Anaesthetics', 'Nursing', 'Other'
]

const REGIONS = [
  'All', 'London', 'South East', 'South West', 'East of England', 'East Midlands',
  'West Midlands', 'North East', 'North West', 'Yorkshire & Humber', 'Wales', 'Scotland', 'Northern Ireland'
]

const PRICE_BANDS = [
  { label: 'Any Price', value: 0 },
  { label: 'Free', value: 0.01 },
  { label: 'Under £100', value: 100 },
  { label: 'Under £300', value: 300 },
  { label: 'Under £500', value: 500 },
]

interface FilterPanelProps {
  filters: Filters
  setFilters: (f: Filters) => void
  sources: SourceSummary[]
}

export function FilterPanel({ filters, setFilters, sources }: FilterPanelProps) {
  const update = (key: keyof Filters, value: string | number | null) => setFilters({ ...filters, [key]: value })

  const hasActiveFilters = filters.specialty || filters.region || filters.maxPrice > 0 || filters.sourceId !== null

  return (
    <div className="glass-card rounded-xl p-5 space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="font-bold text-white flex items-center gap-2">
          <Filter className="w-4 h-4 text-cyan-400" />
          Filters
        </h2>
        {hasActiveFilters && (
          <button
            onClick={() => setFilters({ specialty: '', region: '', maxPrice: 0, searchTerm: filters.searchTerm, sourceId: null, sort: filters.sort, eventType: filters.eventType })}
            className="text-xs text-slate-400 hover:text-cyan-400 flex items-center gap-1 transition-colors"
          >
            <X className="w-3 h-3" />
            Clear all
          </button>
        )}
      </div>

      {/* Source */}
      {sources.length > 0 && (
        <div>
          <label className="flex items-center gap-2 text-sm font-medium text-slate-300 mb-3">
            <Building2 className="w-4 h-4 text-slate-500" />
            Source
          </label>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => update('sourceId', null)}
              className={`text-xs px-3 py-1.5 rounded-full border transition-all ${
                filters.sourceId === null
                  ? 'bg-cyan-500/20 text-cyan-400 border-cyan-500/40'
                  : 'bg-slate-800/50 text-slate-400 border-slate-700 hover:border-slate-600 hover:text-slate-300'
              }`}
            >
              All sources
            </button>
            {sources.map(s => (
              <button
                key={s.id}
                onClick={() => update('sourceId', filters.sourceId === s.id ? null : s.id)}
                className={`text-xs px-3 py-1.5 rounded-full border transition-all ${
                  filters.sourceId === s.id
                    ? 'bg-cyan-500/20 text-cyan-400 border-cyan-500/40'
                    : 'bg-slate-800/50 text-slate-400 border-slate-700 hover:border-slate-600 hover:text-slate-300'
                }`}
              >
                {s.source_name}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Specialty */}
      <div>
        <label className="flex items-center gap-2 text-sm font-medium text-slate-300 mb-3">
          <Stethoscope className="w-4 h-4 text-slate-500" />
          Specialty
        </label>
        <div className="flex flex-wrap gap-2">
          {SPECIALTIES.map(s => (
            <button 
              key={s} 
              onClick={() => update('specialty', s === 'All' ? '' : s)}
              className={`text-xs px-3 py-1.5 rounded-full border transition-all ${
                (s === 'All' && !filters.specialty) || filters.specialty === s
                  ? 'bg-cyan-500/20 text-cyan-400 border-cyan-500/40'
                  : 'bg-slate-800/50 text-slate-400 border-slate-700 hover:border-slate-600 hover:text-slate-300'
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Region */}
      <div>
        <label className="flex items-center gap-2 text-sm font-medium text-slate-300 mb-3">
          <MapPin className="w-4 h-4 text-slate-500" />
          Location
        </label>
        <select 
          value={filters.region || 'All'} 
          onChange={e => update('region', e.target.value === 'All' ? '' : e.target.value)}
          className="w-full px-4 py-2.5 bg-slate-800/50 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent transition-all appearance-none cursor-pointer"
        >
          {REGIONS.map(r => (
            <option key={r} value={r === 'All' ? '' : r} className="bg-slate-800">{r}</option>
          ))}
        </select>
      </div>

      {/* Price */}
      <div>
        <label className="flex items-center gap-2 text-sm font-medium text-slate-300 mb-3">
          <PoundSterling className="w-4 h-4 text-slate-500" />
          Price Range
        </label>
        <div className="flex flex-wrap gap-2">
          {PRICE_BANDS.map(p => (
            <button 
              key={p.label} 
              onClick={() => update('maxPrice', p.value)}
              className={`text-xs px-3 py-1.5 rounded-full border transition-all ${
                filters.maxPrice === p.value 
                  ? 'bg-cyan-500/20 text-cyan-400 border-cyan-500/40'
                  : 'bg-slate-800/50 text-slate-400 border-slate-700 hover:border-slate-600 hover:text-slate-300'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}


