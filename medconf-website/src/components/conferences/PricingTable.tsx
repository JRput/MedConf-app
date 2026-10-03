// src/components/conferences/PricingTable.tsx
'use client'

import { useMemo, useState } from 'react'
import type { PricingTier } from '@/lib/types'
import { Clock, ChevronDown, ChevronRight } from 'lucide-react'
import { currencySymbol } from '@/lib/conference-helpers'
import { cn } from '@/lib/utils'

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

// Tokens that mean a tier is an optional add-on (lunch, dinner, workshop,
// etc.) rather than a core registration fee. When >=2 tiers match, we
// collapse them into a "Optional add-ons" section below the main table.
const ADD_ON_TOKEN_RE = /\b(?:lunch|dinner|reception|banquet|gala|workshop|masterclass|networking|add[-\s]?on|extras?|social)\b|\(optional\)/i

function isAddOn(label: string): boolean {
  return ADD_ON_TOKEN_RE.test(label)
}

export function PricingTable({ tiers }: PricingTableProps) {
  // Separate optional add-ons (lunch, dinner, workshop) from core
  // registration tiers. Only bucket if there are >=2 add-ons — a single
  // one is noise not worth its own section.
  const { mainTiers, addOnTiers } = useMemo(() => {
    const addOns: PricingTier[] = []
    const main: PricingTier[] = []
    for (const t of tiers) {
      if (isAddOn(t.tier_label)) addOns.push(t)
      else main.push(t)
    }
    if (addOns.length < 2) {
      return { mainTiers: tiers, addOnTiers: [] as PricingTier[] }
    }
    return { mainTiers: main, addOnTiers: addOns }
  }, [tiers])

  const { groups, useTabs } = useMemo(() => {
    const parsed = mainTiers.map(t => {
      const parts = t.tier_label.includes(SEP)
        ? t.tier_label.split(SEP).map(p => p.trim()).filter(Boolean)
        : [t.tier_label]
      return { tier: t, parts }
    })
    const allHaveBand = parsed.length > 0 && parsed.every(p => p.parts.length >= 2)
    const enable = mainTiers.length >= GROUP_THRESHOLD && allHaveBand

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
  }, [mainTiers])

  const [addOnsExpanded, setAddOnsExpanded] = useState(false)

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
      <p className="type-small text-fg-subtle italic">
        No fee published — check the organiser&apos;s site.
      </p>
    )
  }

  const rowsForRender = (() => {
    if (!active) return [] as { tier: PricingTier; parts: string[] }[]
    if (!useTabs) return active.rows
    if (activeSub === 'All' || subOptions.length === 0) return active.rows
    return active.rows.filter(r => r.parts[1] === activeSub)
  })()

  // The Notes column only ever carries an early-bird deadline — when none of
  // the currently visible rows have one, a column of bare "—" dashes is pure
  // noise, so drop the column entirely rather than render it empty.
  const hasNotes = rowsForRender.some(r => r.tier.is_early_bird && r.tier.early_bird_deadline)

  return (
    <div className="space-y-3">
      {/* Band tabs — only rendered when grouping kicks in */}
      {useTabs && groups.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          {groups.map(g => (
            <button
              key={g.name}
              onClick={() => { setActiveBand(g.name); setActiveSub('All') }}
              className={cn(
                'rounded-sm border px-3 py-1.5 type-small font-medium transition-colors duration-150',
                activeBand === g.name
                  ? 'border-brand-border bg-brand-subtle text-brand-text'
                  : 'border-border bg-surface text-fg-muted hover:border-border-strong hover:text-fg'
              )}
            >
              {g.name}
              <span className="ml-1.5 text-fg-subtle">· {g.rows.length}</span>
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
              className={cn(
                'rounded-sm border px-2.5 py-1 type-caption transition-colors duration-150',
                activeSub === opt
                  ? 'border-border-strong bg-surface-active text-fg'
                  : 'border-border bg-transparent text-fg-muted hover:text-fg'
              )}
            >
              {opt}
            </button>
          ))}
        </div>
      )}

      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full type-small">
          <thead className="bg-surface-muted">
            <tr>
              <th className="px-4 py-3 text-left font-semibold text-fg-muted">
                {useTabs ? 'Tier' : 'Professional level'}
              </th>
              <th className="px-4 py-3 text-right font-semibold text-fg-muted">Price</th>
              {hasNotes && <th className="px-4 py-3 text-left font-semibold text-fg-muted">Notes</th>}
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
                <tr key={tier.id} className={cn('border-t border-border-subtle', i % 2 === 1 && 'bg-surface-muted/50')}>
                  <td className="px-4 py-3 font-medium text-fg">{rowLabel}</td>
                  <td className="px-4 py-3 text-right type-numeric font-semibold text-fg-strong">
                    {currencySymbol(tier.currency)}{tier.price_gbp.toFixed(2)}
                  </td>
                  {hasNotes && (
                    <td className="px-4 py-3">
                      {tier.is_early_bird && tier.early_bird_deadline ? (
                        <span className="inline-flex items-center gap-1.5 rounded-sm border border-warn-border bg-warn-subtle px-2 py-0.5 type-caption font-medium text-warn-text">
                          <Clock className="size-3" aria-hidden />
                          Ends {new Date(tier.early_bird_deadline).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}
                        </span>
                      ) : (
                        <span className="text-fg-subtle">—</span>
                      )}
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {addOnTiers.length >= 2 && (
        <div className="rounded-lg border border-border bg-surface-muted">
          <button
            onClick={() => setAddOnsExpanded(v => !v)}
            className="flex w-full items-center justify-between px-4 py-2.5 text-left transition-colors duration-150 hover:bg-surface-hover"
            aria-expanded={addOnsExpanded}
          >
            <span className="type-small text-fg">
              Optional add-ons
              <span className="ml-2 type-caption text-fg-subtle">
                · {addOnTiers.length} option{addOnTiers.length === 1 ? '' : 's'}
              </span>
            </span>
            {addOnsExpanded
              ? <ChevronDown className="size-4 text-fg-muted" aria-hidden />
              : <ChevronRight className="size-4 text-fg-muted" aria-hidden />}
          </button>
          {addOnsExpanded && (
            <table className="w-full type-small border-t border-border-subtle">
              <tbody>
                {addOnTiers.map((tier, i) => (
                  <tr key={tier.id} className={cn(i % 2 === 1 && 'bg-surface-hover')}>
                    <td className="px-4 py-2.5 text-fg">{tier.tier_label}</td>
                    <td className="px-4 py-2.5 text-right type-numeric font-semibold text-fg-strong">
                      {currencySymbol(tier.currency)}{tier.price_gbp.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
