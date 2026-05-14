// src/components/conferences/PricingTable.tsx
import type { PricingTier } from '@/lib/types'
import { Clock } from 'lucide-react'

interface PricingTableProps { 
  tiers: PricingTier[] 
}

export function PricingTable({ tiers }: PricingTableProps) {
  if (tiers.length === 0) {
    return (
      <p className="text-sm text-slate-500 italic">
        Pricing information not yet available.
      </p>
    )
  }

  return (
    <div className="overflow-hidden rounded-lg border border-slate-700">
      <table className="w-full text-sm">
        <thead className="bg-slate-800">
          <tr>
            <th className="text-left px-4 py-3 font-semibold text-slate-300">Professional Level</th>
            <th className="text-right px-4 py-3 font-semibold text-slate-300">Price</th>
            <th className="text-left px-4 py-3 font-semibold text-slate-300">Notes</th>
          </tr>
        </thead>
        <tbody>
          {tiers.map((t, i) => (
            <tr key={t.id} className={i % 2 === 0 ? 'bg-slate-800/30' : 'bg-slate-800/50'}>
              <td className="px-4 py-3 text-white font-medium">{t.tier_label}</td>
              <td className="px-4 py-3 text-right text-white font-bold">
                £{t.price_gbp.toFixed(2)}
              </td>
              <td className="px-4 py-3">
                {t.is_early_bird && t.early_bird_deadline ? (
                  <span className="inline-flex items-center gap-1.5 bg-amber-500/10 text-amber-400 px-2.5 py-1 rounded-full text-xs font-medium border border-amber-500/20">
                    <Clock className="w-3 h-3" />
                    Early bird – ends {new Date(t.early_bird_deadline).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}
                  </span>
                ) : (
                  <span className="text-slate-500">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}


