// src/components/conferences/CPDBadge.tsx
import { Award, XCircle } from 'lucide-react'

interface CPDBadgeProps { 
  accredited: boolean
  points: number | null 
}

export function CPDBadge({ accredited, points }: CPDBadgeProps) {
  if (accredited) {
    return (
      <span className="inline-flex items-center gap-1.5 bg-emerald-500/10 text-emerald-400 text-xs font-semibold px-2.5 py-1 rounded-full border border-emerald-500/20">
        <Award className="w-3.5 h-3.5" />
        CPD {points ? `${points} pts` : 'Accredited'}
      </span>
    )
  }
  
  return (
    <span className="inline-flex items-center gap-1.5 bg-slate-700/50 text-slate-400 text-xs font-medium px-2.5 py-1 rounded-full border border-slate-600/20">
      <XCircle className="w-3.5 h-3.5" />
      No CPD
    </span>
  )
}


