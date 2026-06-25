// src/components/conferences/PricingTable.tsx
'use client'

import { useMemo, useState } from 'react'
import type { PricingTier } from '@/lib/types'
import { Clock } from 'lucide-react'
import { currencySymbol } from '@/lib/conference-helpers'

interface PricingTableProps {
  tiers: PricingTier[]
}

// When extractors emit composite labels like
//   "Super early bird · Face-to-face · Member · Consultant · 2 days"
// we split on " · " and use the leading piece as the band (tab), the second
// piece as the in-tab sub-filter (Face-to-face / Virtual), and the rest as
// the row label. Events with short flat labels (the common case) just
// render as a single flat table.
const SEP = ' · '
const GROUP_THRESHOLD = 12 // below this, no point in tabbing — show everything

export function PricingTable({ tiers }: PricingTableProps) {
  const { groups, useTabs } = useMemo(() => {
    const parsed = tiers.map(t => {
      const parts = t.tier_label.includes(SEP)
        ? t.tier_label.split(SEP).map(p => p.trim()).filter(Boolean)
        : [t.tier_label]
      return { tier: t, parts }
    })
    const allHaveBand = parsed.length > 0 && parsed.every(p => p.parts.length >= 2)
    const enable = tiers.length >= GROUP_THRESHOLD && allHaveBand

    // group by leading piece preserving original order
    const seen = new Set<string>()
    const order: string[] = []
    const map: Record<string, typeof parsed> = {}
    for (const p of parsed) {
      const band = enable ? p.parts[0] : 'All'
      if (!seen.has(band)) {
        seen.add(band)
        order.push(band)
        map[band] = []
      }
      map[band].push(p)
    }
    const groupList = order.map(name => ({ name, rows: map[name] }))
    return { groups: groupList, useTabs: enable }
  }, [tiers])

  const [activeBand, setActiveBand] = useState<string>(groups[0]?.name ?? '')
  const active = groups.find(g => g.name === activeBand) ?? groups[0]

  // Optional in-tab sub-filter (second " · " piece — typically Face-to-face / Virtual)
  const subOptions = useMemo(() => {
    if (!useTabs || !active) return [] as string[]
    const set = new Set<string>()
    for (const r of active.rows) {
      if (r.parts.length >= 3) set.add(r.parts[1])
    }
    return [...set]
  }, [useTabs, active])
  const [activeSub, setActiveSub] = useState<string>('All')

  if (tiers.length === 0) {
    return (
      <p className="text-sm text-slate-500 italic">
        Pricing information not yet available.
      </p>
    )
  }

  const rowsForRender = (() => {
    if (!active) return [] as { tier: PricingTier; parts: string[] }[]
    if (!useTabs) return active.rows
    if (activeSub === 'All' || subOptions.length === 0) return active.rows
    return active.rows.filter(r => r.parts[1] === activeSub)
  })()

  return (
    <div className="space-y-3">
      {/* Band tabs — only rendered when grouping kicks in */}
      {useTabs && groups.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          {groups.map(g => (
            <button
              key={g.name}
              onClick={() => { setActiveBand(g.name); setActiveSub('All') }}
              className={`text-xs font-semibold px-3 py-1.5 rounded-full border transition-all ${
                activeBand === g.name
                  ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/50'
                  : 'bg-slate-800/40 text-slate-300 border-slate-700 hover:border-slate-600'
              }`}
            >
              {g.name}
              <span className="ml-1.5 text-slate-500">· {g.rows.length}</span>
            </button>
          ))}
        </div>
      )}

      {/* Optional Face-to-face / Virtual sub-toggle */}
      {useTabs && subOptions.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          {(['All', ...subOptions]).map(opt => (
            <button
              key={opt}
              onClick={() => setActiveSub(opt)}
              className={`text-xs px-2.5 py-1 rounded-full border transition-all ${
                activeSub === opt
                  ? 'bg-slate-700 text-white border-slate-500'
                  : 'bg-transparent text-slate-400 border-slate-700 hover:text-slate-200'
              }`}
            >
              {opt}
            </button>
          ))}
        </div>
      )}

      <div className="overflow-hidden rounded-lg border border-slate-700">
        <table className="w-full text-sm">
          <thead className="bg-slate-800">
            <tr>
              <th className="text-left px-4 py-3 font-semibold text-slate-300">
                {useTabs ? 'Tier' : 'Professional Level'}
              </th>
              <th className="text-right px-4 py-3 font-semibold text-slate-300">Price</th>
              <th className="text-left px-4 py-3 font-semibold text-slate-300">Notes</th>
            </tr>
          </thead>
          <tbody>
            {rowsForRender.map(({ tier, parts }, i) => {
              // For tabbed display, the row label is everything AFTER the
              // band (and the sub-filter when active). For flat display it
              // stays as the original full label.
              const startIdx = useTabs
                ? (activeSub !== 'All' && parts.length >= 3 ? 2 : 1)
                : 0
              const rowLabel = useTabs
                ? parts.slice(startIdx).join(' · ') || parts.join(' · ')
                : tier.tier_label
              return (
                <tr key={tier.id} className={i % 2 === 0 ? 'bg-slate-800/30' : 'bg-slate-800/50'}>
                  <td className="px-4 py-3 text-white font-medium">{rowLabel}</td>
                  <td className="px-4 py-3 text-right text-white font-bold">
                    {currencySymbol(tier.currency)}{tier.price_gbp.toFixed(2)}
                  </td>
                  <td className="px-4 py-3">
                    {tier.is_early_bird && tier.early_bird_deadline ? (
                      <span className="inline-flex items-center gap-1.5 bg-amber-500/10 text-amber-400 px-2.5 py-1 rounded-full text-xs font-medium border border-amber-500/20">
                        <Clock className="w-3 h-3" />
                        Ends {new Date(tier.early_bird_deadline).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}
                      </span>
                    ) : (
                      <span className="text-slate-500">—</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
